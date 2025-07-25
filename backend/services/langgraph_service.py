"""LangGraph service for managing workflow execution."""

import asyncio
import time
from typing import Dict, List, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from workflows.langgraph import DynamicWorkflowBuilder
from backend.langgraph.memory import DatabaseCheckpointer
from backend.langgraph.state import DynamicGlobalState
from workflows.models import WorkflowExecution, WorkflowStatus
from backend.models.agent import Agent, AgentStatus
from backend.services.agent_factory import AgentFactory
from workflows.builder import WorkflowBuilderService
from sqlalchemy import update


class LangGraphService:
    """Service for managing LangGraph workflow execution."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.checkpointer = DatabaseCheckpointer()
        self.workflow_builder_service = WorkflowBuilderService(db)
        self.agent_factory = AgentFactory()
        self.active_workflows: Dict[str, DynamicWorkflowBuilder] = {}
    
    async def _set_all_agents_status(self, status: AgentStatus) -> bool:
        """Set status for all agents."""
        try:
            await self.db.execute(
                update(Agent).values(status=status)
            )
            await self.db.commit()
            return True
        except Exception as e:
            await self.db.rollback()
            print(f"Error updating agent statuses: {e}")
            return False
    
    async def _set_agent_status(self, agent_name: str, status: AgentStatus) -> bool:
        """Set status for a specific agent."""
        try:
            await self.db.execute(
                update(Agent)
                .where(Agent.name == agent_name)
                .values(status=status)
            )
            await self.db.commit()
            return True
        except Exception as e:
            await self.db.rollback()
            print(f"Error updating agent {agent_name} status: {e}")
            return False
    
    async def get_agent_execution_status(self) -> Dict[str, str]:
        """Get current execution status of all agents."""
        result = await self.db.execute(
            select(Agent.name, Agent.status)
        )
        return {name: status.value for name, status in result.fetchall()}
    
    async def _check_agents_available_for_workflow(self) -> bool:
        """Check if any agents are available (INACTIVE) for workflow execution."""
        result = await self.db.execute(
            select(Agent).where(Agent.status == AgentStatus.INACTIVE)
        )
        inactive_agents = result.scalars().all()
        return len(inactive_agents) > 0
    
    async def _check_any_agents_running(self) -> bool:
        """Check if any agents are currently running (blocks agent operations)."""
        result = await self.db.execute(
            select(Agent).where(Agent.status == AgentStatus.RUNNING)
        )
        running_agents = result.scalars().all()
        return len(running_agents) > 0
    
    async def are_agents_running(self) -> bool:
        """Public method to check if any agents are currently running (for API endpoints)."""
        return await self._check_any_agents_running()
    
    async def rebuild_workflow_for_agent_change(self, operation: str, agent_name: str = None) -> Dict[str, Any]:
        """Rebuild workflow when agents are added or removed."""
        return await self.workflow_builder_service.rebuild_workflow_on_agent_change(operation, agent_name)
    
    async def get_workflow_compatibility_status(self) -> Dict[str, Any]:
        """Get workflow compatibility status."""
        return await self.workflow_builder_service.validate_workflow_compatibility()
    
    async def clear_workflow_cache(self):
        """Clear workflow cache to force rebuild."""
        await self.workflow_builder_service.clear_workflow_cache()
    
    async def start_workflow(
        self,
        user_requirements: str,
        max_iterations: int = 10,
        stability_threshold: int = 3,
        configuration: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Start a new workflow execution."""
        
        # Generate unique workflow and thread IDs
        timestamp = int(time.time())
        workflow_id = f"wf_{timestamp}"
        thread_id = f"thread_{workflow_id}"
        
        try:
            # Check if any agents are currently running (block if true)
            if await self._check_any_agents_running():
                raise ValueError("Cannot start workflow: agents are currently running in another workflow")
            
            # Check if workflow can be built with current agents
            compatibility = await self.workflow_builder_service.validate_workflow_compatibility()
            
            if not compatibility["compatible"]:
                raise ValueError(f"Workflow cannot be built: {'; '.join(compatibility['issues'])}")
            
            if compatibility["agent_count"] == 0:
                raise ValueError("No agents available for workflow execution")
            
            # Set all agents to RUNNING status
            if not await self._set_all_agents_status(AgentStatus.RUNNING):
                raise ValueError("Failed to update agent statuses to RUNNING")
            
            # Get agent configurations from workflow builder (includes dynamic prompts)
            agent_configs = await self.workflow_builder_service.get_current_agent_configurations()
            
            # Create workflow execution record
            workflow_execution = WorkflowExecution(
                workflow_id=workflow_id,
                thread_id=thread_id,
                user_requirements=user_requirements,
                max_iterations=max_iterations,
                stability_threshold=stability_threshold,
                status=WorkflowStatus.PENDING,
                active_agents=[agent['name'] for agent in agent_configs]
            )
            
            self.db.add(workflow_execution)
            await self.db.commit()
            
            # Start workflow execution in background
            asyncio.create_task(self._execute_workflow_async(
                workflow_id, thread_id, user_requirements, agent_configs, 
                max_iterations, stability_threshold
            ))
            
            return {
                "workflow_id": workflow_id,
                "thread_id": thread_id,
                "status": WorkflowStatus.PENDING,
                "message": "Workflow started successfully"
            }
            
        except Exception as e:
            await self.db.rollback()
            # Rollback agent statuses to INACTIVE if workflow start failed
            await self._set_all_agents_status(AgentStatus.INACTIVE)
            raise Exception(f"Failed to start workflow: {str(e)}")
    
    async def _execute_workflow_async(
        self,
        workflow_id: str,
        thread_id: str,
        user_requirements: str,
        agent_configs: List[Dict[str, Any]],
        max_iterations: int,
        stability_threshold: int
    ):
        """Execute workflow asynchronously."""
        
        try:
            # Update status to running
            await self._update_workflow_status(workflow_id, WorkflowStatus.RUNNING)
            
            # Execute workflow using workflow builder service
            start_time = time.time()
            
            execution_result = await self.workflow_builder_service.execute_workflow(
                user_requirements=user_requirements,
                thread_id=thread_id,
                max_iterations=max_iterations,
                stability_threshold=stability_threshold
            )
            
            if not execution_result["success"]:
                raise Exception(f"Workflow execution failed: {execution_result.get('error', 'Unknown error')}")
            
            final_state = execution_result["final_state"]
            
            # Store workflow builder for this execution
            workflow_builder, _ = await self.workflow_builder_service.build_dynamic_workflow()
            if workflow_builder:
                self.active_workflows[workflow_id] = workflow_builder
            
            execution_time = int((time.time() - start_time) * 1000)
            
            # Update workflow record with results
            await self._update_workflow_completion(
                workflow_id, final_state, execution_time
            )
            
            # Return all agents to INACTIVE status
            await self._set_all_agents_status(AgentStatus.INACTIVE)
            
            # Clean up
            self.active_workflows.pop(workflow_id, None)
            
        except Exception as e:
            # Update workflow with error
            await self._update_workflow_error(workflow_id, str(e))
            # Return all agents to INACTIVE status on error
            await self._set_all_agents_status(AgentStatus.INACTIVE)
            self.active_workflows.pop(workflow_id, None)
    
    async def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get current workflow execution status."""
        
        result = await self.db.execute(
            select(WorkflowExecution).where(WorkflowExecution.workflow_id == workflow_id)
        )
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            return None
        
        # Get current state from checkpoint if running
        current_state = None
        if workflow.status == WorkflowStatus.RUNNING:
            current_state = await self.checkpointer.load_workflow_state(workflow.thread_id)
        
        status_info = {
            "id": workflow.id,
            "workflow_id": workflow.workflow_id,
            "thread_id": workflow.thread_id,
            "user_requirements": workflow.user_requirements,
            "status": workflow.status,
            "current_iteration": workflow.current_iteration,
            "max_iterations": workflow.max_iterations,
            "stability_threshold": workflow.stability_threshold,
            "is_complete": workflow.is_complete,
            "active_agents": workflow.active_agents,
            "completed_agents": workflow.completed_agents,
            "failed_agents": workflow.failed_agents,
            "total_execution_time_ms": workflow.total_execution_time_ms,
            "average_iteration_time_ms": workflow.average_iteration_time_ms,
            "error_message": workflow.error_message,
            "error_details": workflow.error_details,
            "created_at": workflow.created_at,
            "updated_at": workflow.updated_at,
            "started_at": workflow.started_at,
            "completed_at": workflow.completed_at
        }
        
        # Add current state information if available
        if current_state:
            status_info["current_state"] = {
                "current_iteration": current_state.get("current_iteration", 0),
                "agent_execution_status": current_state.get("agent_execution_status", {}),
                "conversations_count": len(current_state.get("conversations", {}))
            }
        
        return status_info
    
    async def stop_workflow(self, workflow_id: str, reason: str = None) -> bool:
        """Stop a running workflow."""
        
        try:
            # Update database status
            result = await self.db.execute(
                select(WorkflowExecution).where(WorkflowExecution.workflow_id == workflow_id)
            )
            workflow = result.scalar_one_or_none()
            
            if not workflow:
                return False
            
            if workflow.status not in [WorkflowStatus.RUNNING, WorkflowStatus.PENDING]:
                return False
            
            # Update status
            workflow.status = WorkflowStatus.STOPPED
            workflow.error_message = reason or "Workflow stopped by user"
            workflow.completed_at = time.time()
            
            await self.db.commit()
            
            # Return all agents to INACTIVE status
            await self._set_all_agents_status(AgentStatus.INACTIVE)
            
            # Remove from active workflows
            self.active_workflows.pop(workflow_id, None)
            
            return True
            
        except Exception as e:
            await self.db.rollback()
            print(f"Error stopping workflow: {e}")
            return False
    
    async def list_workflows(
        self, 
        limit: int = 50, 
        offset: int = 0,
        status_filter: Optional[WorkflowStatus] = None
    ) -> Dict[str, Any]:
        """List workflow executions."""
        
        query = select(WorkflowExecution)
        
        if status_filter:
            query = query.where(WorkflowExecution.status == status_filter)
        
        query = query.order_by(WorkflowExecution.created_at.desc()).offset(offset).limit(limit)
        
        result = await self.db.execute(query)
        workflows = result.scalars().all()
        
        # Get total count
        count_query = select(WorkflowExecution)
        if status_filter:
            count_query = count_query.where(WorkflowExecution.status == status_filter)
        
        count_result = await self.db.execute(count_query)
        total = len(count_result.scalars().all())
        
        return {
            "workflows": [
                {
                    "id": wf.id,
                    "workflow_id": wf.workflow_id,
                    "status": wf.status,
                    "user_requirements": wf.user_requirements[:100] + "..." if len(wf.user_requirements) > 100 else wf.user_requirements,
                    "current_iteration": wf.current_iteration,
                    "max_iterations": wf.max_iterations,
                    "is_complete": wf.is_complete,
                    "created_at": wf.created_at,
                    "completed_at": wf.completed_at,
                    "total_execution_time_ms": wf.total_execution_time_ms
                }
                for wf in workflows
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    
    async def get_workflow_conversations(self, workflow_id: str) -> List[Dict[str, Any]]:
        """Get conversations from a workflow execution."""
        
        # Get workflow
        result = await self.db.execute(
            select(WorkflowExecution).where(WorkflowExecution.workflow_id == workflow_id)
        )
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            return []
        
        # Load state from checkpoint
        state_data = await self.checkpointer.load_workflow_state(workflow.thread_id)
        if not state_data or "conversations" not in state_data:
            return []
        
        conversations = []
        for conversation_key, conversation_data in state_data["conversations"].items():
            participants = conversation_data.get("participants", [])
            messages = conversation_data.get("messages", [])
            
            conversations.append({
                "conversation_key": conversation_key,
                "participants": participants,
                "message_count": len(messages),
                "last_activity": conversation_data.get("last_activity"),
                "messages": messages
            })
        
        return conversations
    
    async def _load_prompts_content(self, agent: Agent) -> str:
        """Load prompts content for an agent."""
        try:
            if agent.prompts_file_path:
                with open(agent.prompts_file_path, 'r', encoding='utf-8') as f:
                    return f.read()
        except:
            pass
        return ""
    
    async def _update_workflow_status(self, workflow_id: str, status: WorkflowStatus):
        """Update workflow status in database."""
        try:
            result = await self.db.execute(
                select(WorkflowExecution).where(WorkflowExecution.workflow_id == workflow_id)
            )
            workflow = result.scalar_one_or_none()
            
            if workflow:
                workflow.status = status
                if status == WorkflowStatus.RUNNING:
                    workflow.started_at = time.time()
                
                await self.db.commit()
        except Exception as e:
            print(f"Error updating workflow status: {e}")
            await self.db.rollback()
    
    async def _update_workflow_completion(
        self,
        workflow_id: str,
        final_state: DynamicGlobalState,
        execution_time_ms: int
    ):
        """Update workflow with completion information."""
        try:
            result = await self.db.execute(
                select(WorkflowExecution).where(WorkflowExecution.workflow_id == workflow_id)
            )
            workflow = result.scalar_one_or_none()
            
            if workflow:
                workflow.status = WorkflowStatus.COMPLETED
                workflow.is_complete = final_state.project_complete
                workflow.current_iteration = final_state.current_iteration
                workflow.total_execution_time_ms = execution_time_ms
                workflow.completed_at = time.time()
                
                # Calculate average iteration time
                if final_state.current_iteration > 0:
                    workflow.average_iteration_time_ms = execution_time_ms // final_state.current_iteration
                
                # Update agent status
                completed_agents = []
                failed_agents = []
                
                for agent_name, status in final_state.agent_execution_status.items():
                    if status == "completed":
                        completed_agents.append(agent_name)
                    elif status.startswith("error"):
                        failed_agents.append(agent_name)
                
                workflow.completed_agents = completed_agents
                workflow.failed_agents = failed_agents
                
                await self.db.commit()
                
        except Exception as e:
            print(f"Error updating workflow completion: {e}")
            await self.db.rollback()
    
    async def _update_workflow_error(self, workflow_id: str, error_message: str):
        """Update workflow with error information."""
        try:
            result = await self.db.execute(
                select(WorkflowExecution).where(WorkflowExecution.workflow_id == workflow_id)
            )
            workflow = result.scalar_one_or_none()
            
            if workflow:
                workflow.status = WorkflowStatus.FAILED
                workflow.error_message = error_message
                workflow.completed_at = time.time()
                
                await self.db.commit()
                
        except Exception as e:
            print(f"Error updating workflow error: {e}")
            await self.db.rollback()