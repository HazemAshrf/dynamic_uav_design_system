"""Dynamic workflow builder for multi-agent system using LangGraph."""

import asyncio
import time
from typing import Dict, List, Any, Optional
from langgraph import graph
from langgraph.graph import END
from langchain_openai import ChatOpenAI

from backend.langgraph.state import DynamicGlobalState
from backend.langgraph.memory import DatabaseCheckpointer
from backend.core.config import settings
from backend.services.agent_factory import AgentFactory
from backend.core.database import get_db
from backend.models.agent import Agent, AgentStatus
from sqlalchemy import select


class DynamicWorkflowBuilder:
    """Builds and manages dynamic LangGraph workflows."""
    
    def __init__(self, checkpointer: DatabaseCheckpointer):
        self.checkpointer = checkpointer
        self.workflow = None
        self.compiled_graph = None
        self.agent_factory = AgentFactory()
        self._coordinator_agent = None
        
    def build_workflow(self, agent_configs: List[Dict[str, Any]]):
        """Build workflow with current agent configuration."""
        workflow = graph.StateGraph(DynamicGlobalState)
        
        # Add coordinator node (always present)
        workflow.add_node("coordinator", self._coordinator_node)
        
        # Add dynamic aggregator node
        workflow.add_node("aggregator", self._build_aggregator_node(agent_configs))
        
        # Define workflow edges
        workflow.add_edge("coordinator", "aggregator")
        workflow.add_conditional_edges(
            "aggregator",
            self._should_continue,
            {
                "continue": "coordinator",
                "end": END
            }
        )
        
        workflow.set_entry_point("coordinator")
        self.workflow = workflow
        self.compiled_graph = workflow.compile(checkpointer=self.checkpointer)
        
        return self.compiled_graph
    
    def _build_aggregator_node(self, agent_configs: List[Dict[str, Any]]):
        """Create aggregator node with dynamic agent set."""
        
        async def dynamic_aggregator(state: DynamicGlobalState) -> DynamicGlobalState:
            """Execute all agents concurrently with dependency management."""
            print(f"🔄 Starting aggregator for iteration {state.current_iteration}")
            
            # Load and create dynamic agents
            agents = []
            for config in agent_configs:
                try:
                    agent = await self._create_agent_instance(config)
                    if agent:
                        agents.append(agent)
                except Exception as e:
                    print(f"❌ Failed to create agent {config.get('name', 'unknown')}: {e}")
                    state.agent_execution_status[config.get('name', 'unknown')] = f"error: {str(e)}"
            
            if not agents:
                print("⚠️  No agents available for execution")
                return state
            
            # Execute agents with dependency checking
            executed_agents = []
            max_attempts = 3  # Prevent infinite loops
            
            for attempt in range(max_attempts):
                ready_agents = [
                    agent for agent in agents 
                    if agent not in executed_agents and agent.check_dependencies_ready(state)
                ]
                
                if not ready_agents:
                    break
                
                # Execute ready agents concurrently
                tasks = []
                for agent in ready_agents:
                    task = asyncio.create_task(agent.process(state))
                    tasks.append((agent, task))
                
                # Wait for all tasks to complete
                for agent, task in tasks:
                    try:
                        state = await task
                        executed_agents.append(agent)
                        print(f"✅ {agent.name} completed")
                    except Exception as e:
                        print(f"❌ {agent.name} failed: {e}")
                        state.agent_execution_status[agent.name] = f"error: {str(e)}"
            
            # Log execution summary
            executed_names = [agent.name for agent in executed_agents]
            print(f"📊 Iteration {state.current_iteration} summary: {len(executed_names)}/{len(agents)} agents executed")
            
            return state
        
        return dynamic_aggregator
    
    async def _create_agent_instance(self, config: Dict[str, Any]):
        """Create agent instance from configuration."""
        try:
            # Import the generated agent class
            import importlib.util
            
            agent_file_path = config.get('generated_class_path')
            if not agent_file_path:
                print(f"⚠️  No generated class path for agent {config.get('name')}")
                return None
            
            # Load agent module
            spec = importlib.util.spec_from_file_location(
                f"{config['name']}_agent",
                agent_file_path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Get agent class
            class_name = f"{config['name'].title()}Agent"
            agent_class = getattr(module, class_name)
            
            # Create LLM instance
            llm = ChatOpenAI(
                model=config.get('llm_name', 'gpt-4'),
                temperature=config.get('temperature', 0.1),
                api_key=settings.openai_api_key
            )
            
            # Load tools
            tools = await self._load_agent_tools(config)
            
            # Load output class
            output_class = await self._load_output_class(config)
            
            # Create agent instance
            agent = agent_class(
                llm=llm,
                tools=tools,
                output_class=output_class,
                config=config
            )
            
            return agent
            
        except Exception as e:
            print(f"❌ Error creating agent {config.get('name')}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def _load_agent_tools(self, config: Dict[str, Any]) -> List:
        """Load tools for an agent."""
        try:
            tools_file_path = config.get('tools_file_path')
            if not tools_file_path:
                return []
            
            # Check if tools file exists and has content
            from pathlib import Path
            tools_path = Path(tools_file_path)
            if not tools_path.exists():
                print(f"⚠️  Tools file not found for {config.get('name')}: {tools_file_path}")
                return []
            
            # Read file content to check if it has actual tools
            with open(tools_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            
            # Check if file is empty or only has comments/docstrings
            if not content or self._is_empty_tools_file(content):
                print(f"📄 No tools defined for {config.get('name')} - using empty tools list")
                return []
            
            # Import tools module
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                f"{config['name']}_tools",
                tools_file_path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Extract tools (assume they're defined as functions with @tool decorator)
            tools = []
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if hasattr(attr, 'name') and hasattr(attr, 'description'):
                    # This is likely a LangChain tool
                    tools.append(attr)
            
            if not tools:
                print(f"📄 No valid tools found in {config.get('name')} tools file")
            else:
                print(f"🔧 Loaded {len(tools)} tools for {config.get('name')}: {[t.name for t in tools]}")
            
            return tools
            
        except Exception as e:
            print(f"⚠️  Error loading tools for {config.get('name')}: {e}")
            return []
    
    def _is_empty_tools_file(self, content: str) -> bool:
        """Check if tools file content is effectively empty (only comments/docstrings)."""
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            # Skip empty lines, comments, and docstrings
            if line and not line.startswith('#') and not line.startswith('"""') and not line.startswith("'''"):
                # Check for actual code (imports, function definitions, etc.)
                if any(keyword in line for keyword in ['import', 'from', 'def', '@tool', 'class']):
                    # But exclude common empty patterns
                    if 'intentionally empty' in line.lower() or 'no tools' in line.lower():
                        continue
                    return False
        return True
    
    async def _load_output_class(self, config: Dict[str, Any]):
        """Load output class for an agent."""
        try:
            output_file_path = config.get('generated_model_path')
            if not output_file_path:
                return None
            
            # Import output model module
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                f"{config['name']}_output",
                output_file_path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Get output class (assume it follows naming convention)
            class_name = f"{config['name'].title()}Output"
            output_class = getattr(module, class_name)
            
            return output_class
            
        except Exception as e:
            print(f"⚠️  Error loading output class for {config.get('name')}: {e}")
            return None
    
    async def _coordinator_node(self, state: DynamicGlobalState) -> DynamicGlobalState:
        """Coordinator node that uses dynamic coordinator agent."""
        print(f"🎯 Coordinator processing iteration {state.current_iteration}")
        
        try:
            # Get coordinator agent instance
            coordinator_agent = await self._get_coordinator_agent()
            
            if coordinator_agent:
                # Process with coordinator agent
                result = await coordinator_agent.process(state)
                return result
            else:
                # Fallback to basic coordination
                print("⚠️  No coordinator agent found, using fallback")
                if state.current_iteration == 0:
                    await self._assign_initial_tasks(state)
                else:
                    if await self._check_completion_conditions(state):
                        state.project_complete = True
                        print("🎉 Workflow completed!")
        except Exception as e:
            print(f"❌ Coordinator error: {e}")
            # Fallback coordination
            if state.current_iteration == 0:
                await self._assign_initial_tasks(state)
            else:
                if await self._check_completion_conditions(state):
                    state.project_complete = True
        
        return state
    
    async def _get_coordinator_agent(self):
        """Get the coordinator agent instance."""
        if self._coordinator_agent:
            return self._coordinator_agent
            
        try:
            async for db in get_db():
                # Get coordinator from database 
                result = await db.execute(
                    select(Agent).where(
                        Agent.name == 'coordinator',
                        Agent.status == AgentStatus.ACTIVE
                    )
                )
                coordinator_model = result.scalars().first()
                
                if coordinator_model:
                    # Create coordinator agent instance
                    coordinator_agent = await self.agent_factory.load_agent(coordinator_model)
                    
                    # Adapt coordinator to use available agents
                    coordinator_agent = await self._adapt_coordinator_to_available_agents(
                        coordinator_agent, db
                    )
                    
                    self._coordinator_agent = coordinator_agent
                    return coordinator_agent
                    
                return None
                
        except Exception as e:
            print(f"Error loading coordinator agent: {e}")
            return None
    
    async def _adapt_coordinator_to_available_agents(self, coordinator_agent, db):
        """Adapt coordinator to work with currently available agents."""
        try:
            # Get available agents
            result = await db.execute(
                select(Agent.name).where(
                    Agent.status == AgentStatus.ACTIVE,
                    Agent.name != 'coordinator'
                )
            )
            available_agents = [row[0] for row in result.fetchall()]
            
            # Store available agents in the coordinator for context
            if hasattr(coordinator_agent, 'available_agents'):
                coordinator_agent.available_agents = available_agents
            
            print(f"🎯 Coordinator adapted for agents: {available_agents}")
            return coordinator_agent
            
        except Exception as e:
            print(f"Error adapting coordinator: {e}")
            return coordinator_agent
    
    async def _assign_initial_tasks(self, state: DynamicGlobalState):
        """Assign initial tasks to agents."""
        # Create coordinator output with tasks for each agent
        coordinator_output = {
            "agent_tasks": [],
            "iteration": state.current_iteration,
            "decision": "continue",
            "reasoning": "Initial task assignment based on user requirements"
        }
        
        # Create tasks for each active agent
        for agent_name in state.active_agents:
            task_description = self._generate_task_for_agent(agent_name, state.user_requirements)
            coordinator_output["agent_tasks"].append({
                "agent_name": agent_name,
                "task_description": task_description
            })
        
        # Store coordinator output
        if "coordinator" not in state.agent_outputs:
            state.agent_outputs["coordinator"] = {}
        
        state.agent_outputs["coordinator"][state.current_iteration] = coordinator_output
        print(f"📋 Assigned tasks to {len(coordinator_output['agent_tasks'])} agents")
    
    def _generate_task_for_agent(self, agent_name: str, user_requirements: str) -> str:
        """Generate task description for specific agent."""
        # This could be enhanced with LLM-based task generation
        base_task = f"Work on {agent_name} aspects of the project: {user_requirements}"
        
        # Agent-specific task customization
        task_templates = {
            "mission_planner": f"Analyze the mission requirements and establish baseline parameters: {user_requirements}",
            "aerodynamics": f"Design aerodynamic systems based on mission requirements: {user_requirements}",
            "propulsion": f"Design propulsion systems based on mission requirements: {user_requirements}",
            "structures": f"Design structural systems based on mission and aerodynamic requirements: {user_requirements}",
            "manufacturing": f"Analyze manufacturing requirements and costs based on structural design: {user_requirements}"
        }
        
        return task_templates.get(agent_name, base_task)
    
    async def _check_completion_conditions(self, state: DynamicGlobalState) -> bool:
        """Check if workflow should be completed."""
        # Check maximum iterations
        if state.current_iteration >= state.max_iterations:
            print(f"🔚 Maximum iterations ({state.max_iterations}) reached")
            return True
        
        # Check stability
        if state.check_stability():
            print(f"📊 System has been stable for {state.stability_threshold} iterations")
            return True
        
        # Check for errors
        error_agents = [
            name for name, status in state.agent_execution_status.items()
            if status.startswith("error")
        ]
        
        if len(error_agents) > len(state.active_agents) // 2:
            print(f"❌ Too many agents in error state: {error_agents}")
            return True
        
        return False
    
    def _should_continue(self, state: DynamicGlobalState) -> str:
        """Determine if workflow should continue or end."""
        if state.project_complete:
            return "end"
        
        # Increment iteration for next cycle
        state.current_iteration += 1
        return "continue"
    
    async def execute_workflow(
        self,
        user_requirements: str,
        agent_configs: List[Dict[str, Any]],
        thread_id: str,
        max_iterations: int = 10,
        stability_threshold: int = 3
    ) -> DynamicGlobalState:
        """Execute complete workflow with given configuration."""
        
        # Build workflow with current agents
        compiled_graph = self.build_workflow(agent_configs)
        
        # Create initial state
        initial_state = DynamicGlobalState(
            user_requirements=user_requirements,
            thread_id=thread_id,
            max_iterations=max_iterations,
            stability_threshold=stability_threshold
        )
        
        # Add active agents to state
        for config in agent_configs:
            initial_state.add_agent(config['name'], config)
        
        # Execute workflow
        config = {"configurable": {"thread_id": thread_id}}
        
        try:
            print(f"🚀 Starting workflow execution for thread {thread_id}")
            start_time = time.time()
            
            result = await compiled_graph.ainvoke(initial_state, config)
            
            execution_time = int((time.time() - start_time) * 1000)
            print(f"⏱️  Workflow completed in {execution_time}ms")
            
            return result
            
        except Exception as e:
            print(f"❌ Workflow execution failed: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    async def resume_workflow(
        self,
        thread_id: str,
        agent_configs: List[Dict[str, Any]]
    ) -> DynamicGlobalState:
        """Resume workflow from checkpoint."""
        
        # Load state from checkpoint
        state_data = await self.checkpointer.load_workflow_state(thread_id)
        if not state_data:
            raise ValueError(f"No checkpoint found for thread {thread_id}")
        
        # Build workflow with current agents
        compiled_graph = self.build_workflow(agent_configs)
        
        # Continue execution
        config = {"configurable": {"thread_id": thread_id}}
        
        try:
            print(f"🔄 Resuming workflow for thread {thread_id}")
            result = await compiled_graph.ainvoke(state_data, config)
            return result
            
        except Exception as e:
            print(f"❌ Workflow resume failed: {e}")
            raise