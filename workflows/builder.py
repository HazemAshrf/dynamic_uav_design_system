"""Dynamic Workflow Builder Service"""

import asyncio
from typing import Dict, List, Any, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.models.agent import Agent, AgentStatus
from workflows.langgraph import DynamicWorkflowBuilder
from backend.langgraph.memory import DatabaseCheckpointer
from backend.langgraph.state import DynamicGlobalState
from backend.services.prompt_manager import PromptManager
from backend.services.agent_factory import AgentFactory


class WorkflowBuilderService:
    """Service for managing dynamic workflow construction and agent integration."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.prompt_manager = PromptManager(db)
        self.agent_factory = AgentFactory()
        self.checkpointer = DatabaseCheckpointer()
        self._cached_workflow = None
        self._cached_agents_config = None
        
    async def get_current_agent_configurations(self) -> List[Dict[str, Any]]:
        """Get current agent configurations for workflow building."""
        
        result = await self.db.execute(
            select(Agent).where(Agent.status.in_([AgentStatus.INACTIVE, AgentStatus.RUNNING]))
        )
        agents = result.scalars().all()
        
        configs = []
        for agent in agents:
            # Generate dynamic prompt for this agent
            agent_prompt, validation = await self.prompt_manager.generate_agent_prompt(
                agent_name=agent.name,
                agent_role=agent.role,
                dependencies=agent.dependencies or [],
                project_context=None
            )
            
            if not validation.is_valid:
                print(f"⚠️ Warning: Agent {agent.name} prompt validation failed: {validation.errors}")
            
            config = {
                'id': agent.id,
                'name': agent.name,
                'display_name': agent.display_name,
                'role': agent.role,
                'llm_name': agent.llm_name,
                'temperature': agent.temperature,
                'max_tokens': agent.max_tokens,
                'dependencies': agent.dependencies or [],
                'generated_class_path': agent.generated_class_path,
                'generated_model_path': agent.generated_model_path,
                'tools_file_path': agent.tools_file_path,
                'prompts_content': agent_prompt,  # Use dynamically generated prompt
                'status': agent.status,
                **agent.config_data
            }
            configs.append(config)
        
        return configs
    
    async def build_dynamic_workflow(self, force_rebuild: bool = False) -> Tuple[DynamicWorkflowBuilder, Dict[str, Any]]:
        """Build or rebuild the workflow with current agents."""
        
        # Get current agent configurations
        agent_configs = await self.get_current_agent_configurations()
        
        # Check if we need to rebuild
        if not force_rebuild and self._cached_workflow and self._cached_agents_config == agent_configs:
            return self._cached_workflow, {"rebuilt": False, "agent_count": len(agent_configs)}
        
        # Generate coordinator prompt
        coordinator_prompt, coord_validation = await self.prompt_manager.generate_coordinator_prompt()
        
        if not coord_validation.is_valid:
            print(f"⚠️ Warning: Coordinator prompt validation failed: {coord_validation.errors}")
        
        # Create new workflow builder
        workflow_builder = DynamicWorkflowBuilder(self.checkpointer)
        
        # Add coordinator configuration with dynamic prompt
        coordinator_config = {
            'name': 'coordinator',
            'role': 'Project Coordinator',
            'prompts_content': coordinator_prompt,
            'is_coordinator': True
        }
        
        # Build the workflow
        try:
            compiled_graph = workflow_builder.build_workflow(agent_configs)
            
            # Cache the result
            self._cached_workflow = workflow_builder
            self._cached_agents_config = agent_configs
            
            return workflow_builder, {
                "rebuilt": True,
                "agent_count": len(agent_configs),
                "coordinator_prompt_valid": coord_validation.is_valid,
                "agent_prompts_valid": all(
                    config.get('prompt_valid', True) for config in agent_configs
                )
            }
            
        except Exception as e:
            return None, {
                "rebuilt": False,
                "error": f"Failed to build workflow: {str(e)}",
                "agent_count": len(agent_configs)
            }
    
    async def rebuild_workflow_on_agent_change(self, operation: str, agent_name: str = None) -> Dict[str, Any]:
        """Rebuild workflow when agents are added or removed."""
        
        print(f"🔄 Rebuilding workflow due to {operation} operation on agent: {agent_name}")
        
        try:
            # Handle prompt updates based on operation
            if operation == "add" and agent_name:
                # Get the agent ID
                result = await self.db.execute(select(Agent).where(Agent.name == agent_name))
                agent = result.scalar_one_or_none()
                
                if agent:
                    # Cascade update all prompts
                    prompt_results = await self.prompt_manager.cascade_update_on_agent_addition(agent.id)
                else:
                    prompt_results = {"success": False, "error": "Agent not found"}
                    
            elif operation == "remove" and agent_name:
                # Cascade update remaining prompts
                prompt_results = await self.prompt_manager.cascade_update_on_agent_removal(agent_name)
            else:
                # Generic rebuild
                prompt_results = {"success": True, "operation": "generic rebuild"}
            
            # Rebuild workflow
            workflow_builder, build_results = await self.build_dynamic_workflow(force_rebuild=True)
            
            return {
                "success": workflow_builder is not None,
                "operation": operation,
                "agent_name": agent_name,
                "prompt_updates": prompt_results,
                "workflow_build": build_results,
                "total_agents": build_results.get("agent_count", 0)
            }
            
        except Exception as e:
            return {
                "success": False,
                "operation": operation,
                "agent_name": agent_name,
                "error": f"Workflow rebuild failed: {str(e)}"
            }
    
    async def create_initial_state_for_workflow(
        self, 
        user_requirements: str,
        thread_id: str,
        max_iterations: int = 10,
        stability_threshold: int = 3
    ) -> DynamicGlobalState:
        """Create initial state for workflow execution with current agents."""
        
        # Get current agent configurations
        agent_configs = await self.get_current_agent_configurations()
        
        # Create initial state
        state = DynamicGlobalState(
            user_requirements=user_requirements,
            thread_id=thread_id,
            max_iterations=max_iterations,
            stability_threshold=stability_threshold,
            current_iteration=0,
            project_complete=False
        )
        
        # Add agents to state
        for config in agent_configs:
            state.add_agent(config['name'], config)
        
        return state
    
    async def validate_workflow_compatibility(self) -> Dict[str, Any]:
        """Validate that current agents can work together in a workflow."""
        
        agent_configs = await self.get_current_agent_configurations()
        
        if not agent_configs:
            return {
                "compatible": False,
                "issues": ["No agents available for workflow execution"],
                "agent_count": 0
            }
        
        issues = []
        warnings = []
        
        # Check for dependency loops
        agent_dependencies = {}
        for config in agent_configs:
            agent_dependencies[config['name']] = config.get('dependencies', [])
        
        # Simple cycle detection
        for agent_name, deps in agent_dependencies.items():
            visited = set()
            stack = [agent_name]
            
            while stack:
                current = stack.pop()
                if current in visited:
                    issues.append(f"Circular dependency detected involving agent: {agent_name}")
                    break
                visited.add(current)
                
                current_deps = agent_dependencies.get(current, [])
                for dep in current_deps:
                    if dep in agent_dependencies:  # Dependency exists
                        stack.append(dep)
                    else:
                        warnings.append(f"Agent {current} depends on non-existent agent: {dep}")
        
        # Check if coordinator can be generated
        coordinator_prompt, coord_validation = await self.prompt_manager.generate_coordinator_prompt()
        if not coord_validation.is_valid:
            issues.extend([f"Coordinator validation: {error}" for error in coord_validation.errors])
        
        # Check agent prompt validations
        invalid_agents = []
        for config in agent_configs:
            agent_prompt, validation = await self.prompt_manager.generate_agent_prompt(
                config['name'], config['role'], config.get('dependencies', [])
            )
            if not validation.is_valid:
                invalid_agents.append(f"{config['name']}: {validation.errors}")
        
        if invalid_agents:
            issues.extend([f"Agent validation issues: {agent}" for agent in invalid_agents])
        
        return {
            "compatible": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "agent_count": len(agent_configs),
            "coordinator_valid": coord_validation.is_valid,
            "agents_with_issues": len(invalid_agents)
        }
    
    async def get_workflow_status(self) -> Dict[str, Any]:
        """Get current workflow builder status."""
        
        agent_configs = await self.get_current_agent_configurations()
        compatibility = await self.validate_workflow_compatibility()
        
        return {
            "cached_workflow_available": self._cached_workflow is not None,
            "current_agent_count": len(agent_configs),
            "agents": [config['name'] for config in agent_configs],
            "compatibility": compatibility,
            "ready_for_execution": compatibility["compatible"] and len(agent_configs) > 0
        }
    
    async def clear_workflow_cache(self):
        """Clear cached workflow to force rebuild."""
        self._cached_workflow = None
        self._cached_agents_config = None
        print("🗑️ Workflow cache cleared - next build will be from scratch")
    
    async def execute_workflow(
        self,
        user_requirements: str,
        thread_id: str,
        max_iterations: int = 10,
        stability_threshold: int = 3
    ) -> Dict[str, Any]:
        """Execute workflow with current configuration."""
        
        try:
            # Build workflow
            workflow_builder, build_result = await self.build_dynamic_workflow()
            
            if workflow_builder is None:
                return {
                    "success": False,
                    "error": "Failed to build workflow",
                    "build_result": build_result
                }
            
            # Create initial state
            initial_state = await self.create_initial_state_for_workflow(
                user_requirements, thread_id, max_iterations, stability_threshold
            )
            
            # Execute workflow
            final_state = await workflow_builder.execute_workflow(
                user_requirements=user_requirements,
                agent_configs=self._cached_agents_config,
                thread_id=thread_id,
                max_iterations=max_iterations,
                stability_threshold=stability_threshold
            )
            
            return {
                "success": True,
                "final_state": final_state,
                "build_result": build_result,
                "iterations_completed": final_state.current_iteration,
                "project_complete": final_state.project_complete
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Workflow execution failed: {str(e)}"
            }