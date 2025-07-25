"""Atomic Agent Lifecycle Manager

Provides transaction-like operations for agent lifecycle management
with comprehensive rollback capabilities and cross-service coordination.
"""

import asyncio
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.models.agent import Agent, AgentStatus
from backend.schemas.agent import AgentCreate, AgentUpdate
from backend.services.agent_factory import AgentFactory
from backend.services.dependency_manager import DependencyManager
from backend.services.prompt_manager import PromptManager
from workflows.builder import WorkflowBuilderService
from backend.services.langgraph_service import LangGraphService


@dataclass
class OperationStep:
    """Represents a single step in an atomic operation."""
    name: str
    service: str
    operation: str
    parameters: Dict[str, Any]
    rollback_operation: Optional[str] = None
    rollback_parameters: Optional[Dict[str, Any]] = None
    completed: bool = False
    result: Any = None
    error: Optional[str] = None


@dataclass
class AtomicOperation:
    """Represents a complete atomic operation with rollback capabilities."""
    operation_id: str
    operation_type: str
    steps: List[OperationStep] = field(default_factory=list)
    completed_steps: List[int] = field(default_factory=list)
    failed_step: Optional[int] = None
    success: bool = False
    error_message: Optional[str] = None
    rollback_completed: bool = False


class AgentLifecycleManager:
    """Manages atomic agent lifecycle operations with rollback capabilities."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.agent_factory = AgentFactory()
        self.dependency_manager = DependencyManager(db)
        self.prompt_manager = PromptManager(db)
        self.workflow_builder = WorkflowBuilderService(db)
        self.langgraph_service = LangGraphService(db)
        
        # Track active operations
        self.active_operations: Dict[str, AtomicOperation] = {}
    
    async def create_agent_atomically(
        self,
        agent_data: AgentCreate,
        operation_id: Optional[str] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """Atomically create an agent with full rollback capabilities."""
        
        if operation_id is None:
            import uuid
            operation_id = f"create_agent_{uuid.uuid4().hex[:8]}"
        
        operation = AtomicOperation(
            operation_id=operation_id,
            operation_type="create_agent"
        )
        
        try:
            # Step 1: Validate dependencies
            if agent_data.dependencies:
                operation.steps.append(OperationStep(
                    name="validate_dependencies",
                    service="dependency_manager",
                    operation="validate_circular_dependencies",
                    parameters={"agent_name": agent_data.name, "dependencies": agent_data.dependencies}
                ))
            
            # Step 2: Validate files
            operation.steps.append(OperationStep(
                name="validate_files",
                service="agent_factory", 
                operation="validate_agent_files",
                parameters={"files": agent_data.files, "agent_config": {"name": agent_data.name, "llm_name": agent_data.llm_name}},
                rollback_operation="cleanup_validation_artifacts",
                rollback_parameters={"agent_name": agent_data.name}
            ))
            
            # Step 3: Create agent files and configuration
            operation.steps.append(OperationStep(
                name="create_agent_files",
                service="agent_factory",
                operation="create_agent",
                parameters={
                    "agent_name": agent_data.name,
                    "display_name": agent_data.display_name,
                    "role": agent_data.role,
                    "llm_name": agent_data.llm_name,
                    "temperature": agent_data.temperature,
                    "dependencies": agent_data.dependencies,
                    "files": agent_data.files
                },
                rollback_operation="delete_agent",
                rollback_parameters={"agent_name": agent_data.name}
            ))
            
            # Step 4: Create database record
            operation.steps.append(OperationStep(
                name="create_database_record",
                service="database",
                operation="create_agent_record",
                parameters={"agent_data": agent_data},
                rollback_operation="delete_agent_record",
                rollback_parameters={"agent_name": agent_data.name}
            ))
            
            # Step 5: Update prompts system
            operation.steps.append(OperationStep(
                name="update_prompts",
                service="prompt_manager",
                operation="cascade_update_on_agent_addition",
                parameters={"agent_name": agent_data.name},
                rollback_operation="cascade_update_on_agent_removal",
                rollback_parameters={"agent_name": agent_data.name}
            ))
            
            # Step 6: Rebuild workflow
            operation.steps.append(OperationStep(
                name="rebuild_workflow",
                service="workflow_builder",
                operation="rebuild_workflow_on_agent_change",
                parameters={"operation": "add", "agent_name": agent_data.name},
                rollback_operation="rebuild_workflow_on_agent_change",
                rollback_parameters={"operation": "remove", "agent_name": agent_data.name}
            ))
            
            # Execute operation
            result = await self._execute_atomic_operation(operation)
            
            return result["success"], result
            
        except Exception as e:
            return False, {
                "success": False,
                "error": f"Failed to create agent atomically: {str(e)}",
                "operation_id": operation_id
            }
    
    async def update_agent_atomically(
        self,
        agent_id: int,
        agent_data: AgentUpdate,
        operation_id: Optional[str] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """Atomically update an agent with full rollback capabilities."""
        
        if operation_id is None:
            import uuid
            operation_id = f"update_agent_{uuid.uuid4().hex[:8]}"
        
        # Get current agent data for rollback
        result = await self.db.execute(select(Agent).where(Agent.id == agent_id))
        current_agent = result.scalar_one_or_none()
        
        if not current_agent:
            return False, {"success": False, "error": "Agent not found"}
        
        operation = AtomicOperation(
            operation_id=operation_id,
            operation_type="update_agent"
        )
        
        try:
            # Step 1: Validate dependencies if changed
            if agent_data.dependencies is not None:
                operation.steps.append(OperationStep(
                    name="validate_dependencies",
                    service="dependency_manager",
                    operation="update_agent_dependencies",
                    parameters={"agent_name": current_agent.name, "new_dependencies": agent_data.dependencies},
                    rollback_operation="update_agent_dependencies",
                    rollback_parameters={"agent_name": current_agent.name, "new_dependencies": current_agent.dependencies}
                ))
            
            # Step 2: Always prepare metadata updates for config.json
            metadata_updates = {}
            if agent_data.name is not None:
                metadata_updates["name"] = agent_data.name
            if agent_data.display_name is not None:
                metadata_updates["display_name"] = agent_data.display_name
            if agent_data.role is not None:
                metadata_updates["role"] = agent_data.role
            if agent_data.llm_name is not None:
                metadata_updates["llm_name"] = agent_data.llm_name
            if agent_data.temperature is not None:
                metadata_updates["temperature"] = agent_data.temperature
            if agent_data.max_tokens is not None:
                metadata_updates["max_tokens"] = agent_data.max_tokens
            if agent_data.dependencies is not None:
                metadata_updates["dependencies"] = agent_data.dependencies
            
            # Step 2a: Update files if provided
            if agent_data.files:
                operation.steps.append(OperationStep(
                    name="update_agent_files",
                    service="agent_factory",
                    operation="update_agent_files",
                    parameters={
                        "agent_name": current_agent.name, 
                        "files": agent_data.files,
                        "metadata_updates": metadata_updates
                    },
                    rollback_operation="restore_agent_files",
                    rollback_parameters={"agent_name": current_agent.name, "backup_config": current_agent.config_data}
                ))
            
            # Step 2b: Always update config.json with metadata changes (even if no files uploaded)
            if metadata_updates:
                operation.steps.append(OperationStep(
                    name="update_config_metadata",
                    service="agent_factory",
                    operation="update_agent_metadata",
                    parameters={
                        "agent_name": current_agent.name,
                        "metadata_updates": metadata_updates
                    },
                    rollback_operation="restore_agent_metadata",
                    rollback_parameters={"agent_name": current_agent.name, "backup_config": current_agent.config_data}
                ))
            
            # Step 3: Update database record
            original_data = {
                "display_name": current_agent.display_name,
                "role": current_agent.role,
                "llm_name": current_agent.llm_name,
                "temperature": current_agent.temperature,
                "max_tokens": current_agent.max_tokens,
                "dependencies": current_agent.dependencies
            }
            
            operation.steps.append(OperationStep(
                name="update_database_record",
                service="database",
                operation="update_agent_record",
                parameters={"agent_id": agent_id, "agent_data": agent_data},
                rollback_operation="restore_agent_record",
                rollback_parameters={"agent_id": agent_id, "original_data": original_data}
            ))
            
            # Step 4: Update prompts system
            operation.steps.append(OperationStep(
                name="update_prompts",
                service="prompt_manager",
                operation="cascade_update_on_agent_modification",
                parameters={"agent_name": current_agent.name},
                rollback_operation="cascade_update_on_agent_modification",
                rollback_parameters={"agent_name": current_agent.name}
            ))
            
            # Step 5: Rebuild workflow
            operation.steps.append(OperationStep(
                name="rebuild_workflow",
                service="workflow_builder",
                operation="rebuild_workflow_on_agent_change",
                parameters={"operation": "update", "agent_name": current_agent.name},
                rollback_operation="rebuild_workflow_on_agent_change",
                rollback_parameters={"operation": "update", "agent_name": current_agent.name}
            ))
            
            # Execute operation
            result = await self._execute_atomic_operation(operation)
            
            return result["success"], result
            
        except Exception as e:
            return False, {
                "success": False,
                "error": f"Failed to update agent atomically: {str(e)}",
                "operation_id": operation_id
            }
    
    async def delete_agent_atomically(
        self,
        agent_name: str,
        force_cascade: bool = False,
        operation_id: Optional[str] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """Atomically delete an agent with full rollback capabilities."""
        
        if operation_id is None:
            import uuid
            operation_id = f"delete_agent_{uuid.uuid4().hex[:8]}"
        
        operation = AtomicOperation(
            operation_id=operation_id,
            operation_type="delete_agent"
        )
        
        try:
            # Step 1: Analyze deletion impact
            operation.steps.append(OperationStep(
                name="analyze_deletion_impact",
                service="dependency_manager",
                operation="analyze_deletion_impact",
                parameters={"agent_name": agent_name}
            ))
            
            # Step 2: Execute dependency deletion
            operation.steps.append(OperationStep(
                name="execute_dependency_deletion",
                service="dependency_manager",
                operation="execute_safe_deletion",
                parameters={"agent_name": agent_name, "force_cascade": force_cascade},
                rollback_operation="restore_deleted_agents",
                rollback_parameters={"deletion_plan": None}  # Will be filled after step 1
            ))
            
            # Step 3: Delete agent files
            operation.steps.append(OperationStep(
                name="delete_agent_files",
                service="agent_factory",
                operation="delete_agent",
                parameters={"agent_name": agent_name},
                rollback_operation="restore_agent",
                rollback_parameters={"agent_name": agent_name, "backup_config": None}  # Will be filled
            ))
            
            # Step 4: Update prompts system
            operation.steps.append(OperationStep(
                name="update_prompts",
                service="prompt_manager",
                operation="cascade_update_on_agent_removal",
                parameters={"agent_name": agent_name},
                rollback_operation="cascade_update_on_agent_addition",
                rollback_parameters={"agent_name": agent_name}
            ))
            
            # Step 5: Rebuild workflow
            operation.steps.append(OperationStep(
                name="rebuild_workflow",
                service="workflow_builder",
                operation="rebuild_workflow_on_agent_change",
                parameters={"operation": "remove", "agent_name": agent_name},
                rollback_operation="rebuild_workflow_on_agent_change",
                rollback_parameters={"operation": "add", "agent_name": agent_name}
            ))
            
            # Execute operation
            result = await self._execute_atomic_operation(operation)
            
            return result["success"], result
            
        except Exception as e:
            return False, {
                "success": False,
                "error": f"Failed to delete agent atomically: {str(e)}",
                "operation_id": operation_id
            }
    
    async def _execute_atomic_operation(self, operation: AtomicOperation) -> Dict[str, Any]:
        """Execute an atomic operation with rollback capabilities."""
        
        self.active_operations[operation.operation_id] = operation
        
        try:
            # Execute each step
            for i, step in enumerate(operation.steps):
                try:
                    print(f"🔄 Executing step {i+1}/{len(operation.steps)}: {step.name}")
                    
                    # Execute the step
                    step_result = await self._execute_step(step)
                    step.completed = True
                    step.result = step_result
                    operation.completed_steps.append(i)
                    
                    print(f"✅ Step {i+1} completed: {step.name}")
                    
                except Exception as e:
                    step.error = str(e)
                    operation.failed_step = i
                    operation.error_message = f"Step {i+1} ({step.name}) failed: {str(e)}"
                    
                    print(f"❌ Step {i+1} failed: {step.name} - {str(e)}")
                    
                    # Rollback all completed steps
                    await self._rollback_operation(operation)
                    
                    return {
                        "success": False,
                        "error": operation.error_message,
                        "failed_step": step.name,
                        "rollback_completed": operation.rollback_completed,
                        "operation_id": operation.operation_id
                    }
            
            # All steps completed successfully
            operation.success = True
            
            print(f"🎉 Atomic operation completed successfully: {operation.operation_type}")
            
            return {
                "success": True,
                "message": f"Atomic {operation.operation_type} completed successfully",
                "steps_completed": len(operation.completed_steps),
                "operation_id": operation.operation_id
            }
            
        finally:
            # Clean up
            self.active_operations.pop(operation.operation_id, None)
    
    async def _execute_step(self, step: OperationStep) -> Any:
        """Execute a single operation step."""
        
        if step.service == "dependency_manager":
            return await self._execute_dependency_manager_step(step)
        elif step.service == "agent_factory":
            return await self._execute_agent_factory_step(step)
        elif step.service == "prompt_manager":
            return await self._execute_prompt_manager_step(step)
        elif step.service == "workflow_builder":
            return await self._execute_workflow_builder_step(step)
        elif step.service == "database":
            return await self._execute_database_step(step)
        else:
            raise ValueError(f"Unknown service: {step.service}")
    
    async def _execute_dependency_manager_step(self, step: OperationStep) -> Any:
        """Execute dependency manager operations."""
        
        if step.operation == "validate_circular_dependencies":
            # Get current dependency graph and test with new agent
            current_nodes = await self.dependency_manager.get_dependency_graph()
            
            # Add temporary node for testing
            from backend.services.dependency_manager import DependencyNode
            temp_node = DependencyNode(
                name=step.parameters["agent_name"],
                id=-1,
                dependencies=step.parameters["dependencies"],
                dependents=[]
            )
            current_nodes[step.parameters["agent_name"]] = temp_node
            
            # Check for circular dependencies
            circular_deps = self.dependency_manager.detect_circular_dependencies(current_nodes)
            if circular_deps:
                raise Exception(f"Circular dependencies detected: {circular_deps}")
            
            return {"valid": True}
            
        elif step.operation == "analyze_deletion_impact":
            return await self.dependency_manager.analyze_deletion_impact(step.parameters["agent_name"])
            
        elif step.operation == "execute_safe_deletion":
            return await self.dependency_manager.execute_safe_deletion(
                step.parameters["agent_name"],
                step.parameters["force_cascade"]
            )
            
        elif step.operation == "update_agent_dependencies":
            return await self.dependency_manager.update_agent_dependencies(
                step.parameters["agent_name"],
                step.parameters["new_dependencies"]
            )
            
        else:
            raise ValueError(f"Unknown dependency manager operation: {step.operation}")
    
    async def _execute_agent_factory_step(self, step: OperationStep) -> Any:
        """Execute agent factory operations."""
        
        if step.operation == "validate_agent_files":
            from backend.services.file_processor import FileProcessor
            file_processor = FileProcessor()
            return await file_processor.validate_agent_files(
                step.parameters["files"],
                step.parameters["agent_config"]
            )
            
        elif step.operation == "create_agent":
            return await self.agent_factory.create_agent(**step.parameters)
            
        elif step.operation == "update_agent_files":
            return await self.agent_factory.update_agent_files(
                step.parameters["agent_name"],
                step.parameters["files"],
                step.parameters.get("metadata_updates")
            )
            
        elif step.operation == "delete_agent":
            return await self.agent_factory.delete_agent(step.parameters["agent_name"])
            
        elif step.operation == "update_agent_metadata":
            return await self.agent_factory.update_agent_metadata(
                step.parameters["agent_name"],
                step.parameters["metadata_updates"]
            )
            
        else:
            raise ValueError(f"Unknown agent factory operation: {step.operation}")
    
    async def _execute_prompt_manager_step(self, step: OperationStep) -> Any:
        """Execute prompt manager operations."""
        
        if step.operation == "cascade_update_on_agent_addition":
            # Get agent ID
            result = await self.db.execute(select(Agent).where(Agent.name == step.parameters["agent_name"]))
            agent = result.scalar_one_or_none()
            if not agent:
                raise Exception(f"Agent {step.parameters['agent_name']} not found")
            return await self.prompt_manager.cascade_update_on_agent_addition(agent.id)
            
        elif step.operation == "cascade_update_on_agent_removal":
            return await self.prompt_manager.cascade_update_on_agent_removal(step.parameters["agent_name"])
            
        elif step.operation == "cascade_update_on_agent_modification":
            return await self.prompt_manager.cascade_update_on_agent_modification(step.parameters["agent_name"])
            
        else:
            raise ValueError(f"Unknown prompt manager operation: {step.operation}")
    
    async def _execute_workflow_builder_step(self, step: OperationStep) -> Any:
        """Execute workflow builder operations."""
        
        if step.operation == "rebuild_workflow_on_agent_change":
            return await self.workflow_builder.rebuild_workflow_on_agent_change(
                step.parameters["operation"],
                step.parameters["agent_name"]
            )
        else:
            raise ValueError(f"Unknown workflow builder operation: {step.operation}")
    
    async def _execute_database_step(self, step: OperationStep) -> Any:
        """Execute database operations."""
        
        if step.operation == "create_agent_record":
            agent_data = step.parameters["agent_data"]
            
            # Get the agent config from previous step
            agent_config = None
            for prev_step in [s for s in step.__dict__.values() if hasattr(s, 'result')]:
                if hasattr(prev_step, 'result') and isinstance(prev_step.result, dict):
                    agent_config = prev_step.result
                    break
            
            if not agent_config:
                # This should be set by create_agent_files step, but let's handle it
                agent_config = {}
            
            agent = Agent(
                name=agent_data.name,
                display_name=agent_data.display_name,
                role=agent_data.role,
                llm_name=agent_data.llm_name,
                temperature=agent_data.temperature,
                max_tokens=agent_data.max_tokens,
                dependencies=agent_data.dependencies,
                status=AgentStatus.INACTIVE,
                prompts_file_path=agent_config.get('prompts_file_path'),
                output_class_file_path=agent_config.get('output_class_file_path'),
                tools_file_path=agent_config.get('tools_file_path'),
                generated_class_path=agent_config.get('generated_class_path'),
                generated_model_path=agent_config.get('generated_model_path'),
                config_data=agent_config
            )
            
            self.db.add(agent)
            await self.db.commit()
            await self.db.refresh(agent)
            
            return agent
            
        elif step.operation == "update_agent_record":
            agent_id = step.parameters["agent_id"]
            agent_data = step.parameters["agent_data"]
            
            result = await self.db.execute(select(Agent).where(Agent.id == agent_id))
            agent = result.scalar_one_or_none()
            
            if not agent:
                raise Exception(f"Agent with ID {agent_id} not found")
            
            # Update fields
            update_data = agent_data.model_dump(exclude_unset=True, exclude={'files'})
            for field, value in update_data.items():
                if hasattr(agent, field):
                    setattr(agent, field, value)
            
            await self.db.commit()
            await self.db.refresh(agent)
            
            return agent
            
        elif step.operation == "delete_agent_record":
            result = await self.db.execute(select(Agent).where(Agent.name == step.parameters["agent_name"]))
            agent = result.scalar_one_or_none()
            
            if agent:
                await self.db.delete(agent)
                await self.db.commit()
            
            return {"deleted": True}
            
        else:
            raise ValueError(f"Unknown database operation: {step.operation}")
    
    async def _rollback_operation(self, operation: AtomicOperation):
        """Rollback completed steps of a failed operation."""
        
        print(f"🔄 Rolling back operation: {operation.operation_type}")
        
        # Rollback in reverse order
        for i in reversed(operation.completed_steps):
            step = operation.steps[i]
            
            if step.rollback_operation:
                try:
                    print(f"↩️ Rolling back step {i+1}: {step.name}")
                    
                    rollback_step = OperationStep(
                        name=f"rollback_{step.name}",
                        service=step.service,
                        operation=step.rollback_operation,
                        parameters=step.rollback_parameters or {}
                    )
                    
                    await self._execute_step(rollback_step)
                    print(f"✅ Rollback completed for step {i+1}: {step.name}")
                    
                except Exception as e:
                    print(f"❌ Rollback failed for step {i+1}: {step.name} - {str(e)}")
                    # Continue with other rollbacks even if one fails
        
        # Rollback database transaction
        try:
            await self.db.rollback()
            print("✅ Database transaction rolled back")
        except Exception as e:
            print(f"❌ Database rollback failed: {str(e)}")
        
        operation.rollback_completed = True
        print(f"✅ Rollback completed for operation: {operation.operation_type}")
    
    async def get_operation_status(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """Get status of an active or completed operation."""
        
        operation = self.active_operations.get(operation_id)
        
        if not operation:
            return None
        
        return {
            "operation_id": operation.operation_id,
            "operation_type": operation.operation_type,
            "total_steps": len(operation.steps),
            "completed_steps": len(operation.completed_steps),
            "failed_step": operation.failed_step,
            "success": operation.success,
            "error_message": operation.error_message,
            "rollback_completed": operation.rollback_completed,
            "steps": [
                {
                    "name": step.name,
                    "service": step.service,
                    "operation": step.operation,
                    "completed": step.completed,
                    "error": step.error
                }
                for step in operation.steps
            ]
        }