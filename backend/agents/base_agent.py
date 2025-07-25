"""Enhanced base agent class for dynamic multi-agent system using LangGraph."""

import asyncio
import time
from typing import Dict, List, Any, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

from backend.langgraph.state import DynamicGlobalState, AgentMessage


class BaseAgent:
    """Enhanced base class for all dynamic agents using LangGraph's create_react_agent."""
    
    def __init__(
        self, 
        name: str, 
        llm: ChatOpenAI, 
        tools: List, 
        output_class, 
        system_prompt: str,
        dependencies: List[str] = None,
        config: Dict[str, Any] = None
    ):
        self.name = name
        self.llm = llm
        self.tools = tools
        self.output_class = output_class
        self.system_prompt = system_prompt
        self.dependencies = dependencies or []
        self.config = config or {}
        self.communication_allowed = self._get_communication_rules()
    
    def _get_communication_rules(self) -> List[str]:
        """Get list of agents this agent can communicate with."""
        # By default, agents can communicate with their dependencies and dependents
        rules = self.dependencies.copy()
        
        # Add any additional communication rules from config
        if "communication_rules" in self.config:
            rules.extend(self.config["communication_rules"])
        
        return list(set(rules))  # Remove duplicates
    
    def can_communicate_with(self, other_agent: str) -> bool:
        """Check if this agent can communicate with another agent."""
        return other_agent in self.communication_allowed
    
    def get_task_for_current_iteration(self, state: DynamicGlobalState) -> Optional[str]:
        """Get task from coordinator for current iteration."""
        if "coordinator" not in state.agent_outputs:
            return None
        
        coordinator_outputs = state.agent_outputs["coordinator"]
        if state.current_iteration not in coordinator_outputs:
            # Look for most recent coordinator output
            available_iterations = sorted(coordinator_outputs.keys(), reverse=True)
            if not available_iterations:
                return None
            latest_iteration = available_iterations[0]
            coord_output = coordinator_outputs[latest_iteration]
        else:
            coord_output = coordinator_outputs[state.current_iteration]
        
        # Extract task for this agent from coordinator output
        if hasattr(coord_output, 'agent_tasks'):
            for task in coord_output.agent_tasks:
                if task.agent_name == self.name:
                    return task.task_description
        
        return None
    
    def get_conversation_history(self, state: DynamicGlobalState, with_agent: str = None) -> List[Dict[str, Any]]:
        """Get conversation history with specific agent or all agents."""
        history = []
        
        for conversation_key, conversation in state.conversations.items():
            if with_agent:
                if with_agent not in conversation.participants:
                    continue
            
            if self.name in conversation.participants:
                for message in conversation.messages:
                    if message.from_agent == self.name or message.to_agent == self.name:
                        history.append({
                            "iteration": message.iteration,
                            "from_agent": message.from_agent,
                            "to_agent": message.to_agent,
                            "content": message.content,
                            "timestamp": message.timestamp,
                            "metadata": message.metadata
                        })
        
        # Sort by timestamp
        history.sort(key=lambda x: x["timestamp"])
        return history
    
    def get_own_previous_output(self, state: DynamicGlobalState) -> Optional[Any]:
        """Get this agent's most recent previous output."""
        if self.name not in state.agent_outputs:
            return None
        
        agent_outputs = state.agent_outputs[self.name]
        if not agent_outputs:
            return None
        
        latest_iteration = max(agent_outputs.keys())
        return agent_outputs[latest_iteration]
    
    def check_dependencies_ready(self, state: DynamicGlobalState) -> bool:
        """Check if required agent dependencies have produced outputs."""
        if not self.dependencies:
            return True
        
        current_iteration = state.current_iteration
        
        for dependency in self.dependencies:
            if dependency not in state.agent_outputs:
                return False
            
            # Check if dependency has output for current or previous iteration
            dep_outputs = state.agent_outputs[dependency]
            if not dep_outputs:
                return False
            
            # Dependencies should have output from current or previous iteration
            has_recent_output = any(
                iteration <= current_iteration 
                for iteration in dep_outputs.keys()
            )
            if not has_recent_output:
                return False
        
        return True
    
    def get_dependency_outputs(self, state: DynamicGlobalState) -> Dict[str, Any]:
        """Get outputs from dependent agents."""
        dependency_outputs = {}
        
        for dependency in self.dependencies:
            if dependency in state.agent_outputs:
                dep_outputs = state.agent_outputs[dependency]
                if dep_outputs:
                    # Get most recent output
                    latest_iteration = max(dep_outputs.keys())
                    dependency_outputs[dependency] = dep_outputs[latest_iteration]
        
        return dependency_outputs
    
    def send_message(
        self, 
        state: DynamicGlobalState, 
        to_agent: str, 
        content: str, 
        metadata: Dict[str, Any] = None
    ) -> DynamicGlobalState:
        """Send message to another agent."""
        if not self.can_communicate_with(to_agent):
            print(f"⚠️  Warning: {self.name} cannot send message to '{to_agent}'")
            return state
        
        # Create conversation key (sorted participants)
        conversation_key = "_".join(sorted([self.name, to_agent]))
        
        # Ensure conversation exists
        if conversation_key not in state.conversations:
            from backend.langgraph.state import AgentConversation
            state.conversations[conversation_key] = AgentConversation(
                participants=sorted([self.name, to_agent])
            )
        
        # Create and add message
        message = AgentMessage(
            id=f"{self.name}_{to_agent}_{time.time()}",
            from_agent=self.name,
            to_agent=to_agent,
            content=content,
            timestamp=time.time(),
            iteration=state.current_iteration,
            metadata=metadata or {}
        )
        
        state.conversations[conversation_key].add_message(message)
        
        return state
    
    def format_system_message(self, current_iteration: int) -> str:
        """Format system message with agent role and current context."""
        tools_info = ""
        if self.tools:
            tools_info = f"\nAvailable tools: {', '.join([tool.name for tool in self.tools])}"
        
        return f"""You are {self.name}, a specialized agent in a multi-agent UAV design system.

{self.system_prompt}

Current iteration: {current_iteration}
Your dependencies: {', '.join(self.dependencies) if self.dependencies else 'None'}
{tools_info}

Always provide structured output according to your output schema and include relevant messages for other agents when appropriate."""
    
    def format_human_message(
        self, 
        task: Optional[str],
        dependency_outputs: Dict[str, Any],
        conversation_history: List[Dict[str, Any]],
        own_previous_output: Optional[Any]
    ) -> str:
        """Format human message with complete context."""
        message_parts = []
        
        # Current task
        if task:
            message_parts.append(f"Current Task: {task}")
        else:
            message_parts.append("No specific task assigned for this iteration.")
        
        # Dependency outputs
        if dependency_outputs:
            message_parts.append("\nDependency Outputs:")
            for dep_name, output in dependency_outputs.items():
                message_parts.append(f"- {dep_name}: {output}")
        
        # Conversation history
        if conversation_history:
            message_parts.append(f"\nRecent Conversation History ({len(conversation_history)} messages):")
            for msg in conversation_history[-5:]:  # Last 5 messages
                direction = "→" if msg["from_agent"] == self.name else "←"
                other_agent = msg["to_agent"] if msg["from_agent"] == self.name else msg["from_agent"]
                message_parts.append(f"  {direction} {other_agent}: {msg['content']}")
        
        # Previous output
        if own_previous_output:
            message_parts.append(f"\nYour Previous Output: {own_previous_output}")
        
        return "\n".join(message_parts)
    
    def create_react_agent_instance(self, state: DynamicGlobalState):
        """Create LangGraph react agent with current state context."""
        # Get context
        task = self.get_task_for_current_iteration(state)
        dependency_outputs = self.get_dependency_outputs(state)
        conversation_history = self.get_conversation_history(state)
        own_previous_output = self.get_own_previous_output(state)
        
        # Create messages
        system_message = SystemMessage(content=self.format_system_message(state.current_iteration))
        human_message = HumanMessage(content=self.format_human_message(
            task, dependency_outputs, conversation_history, own_previous_output
        ))
        
        def pre_model_hook(agent_state, config):
            return {"messages": [system_message, human_message]}
        
        return create_react_agent(
            model=self.llm,
            tools=self.tools,
            pre_model_hook=pre_model_hook,
            response_format=self.output_class,
            checkpointer=MemorySaver()
        )
    
    def should_update_last_iteration(self, state: DynamicGlobalState, new_output) -> bool:
        """Determine if this output represents an update vs maintaining current values."""
        if self.name not in state.agent_outputs:
            return True
        
        agent_outputs = state.agent_outputs[self.name]
        if not agent_outputs:
            return True
        
        # Get previous outputs (excluding current iteration)
        previous_outputs = {
            k: v for k, v in agent_outputs.items() 
            if k < state.current_iteration
        }
        
        if not previous_outputs:
            return True
        
        # Get most recent previous output
        latest_previous_iteration = max(previous_outputs.keys())
        previous_output = previous_outputs[latest_previous_iteration]
        
        # Compare outputs (implementation depends on output structure)
        if hasattr(new_output, 'model_dump') and hasattr(previous_output, 'model_dump'):
            new_dict = new_output.model_dump()
            prev_dict = previous_output.model_dump()
            
            # Remove metadata fields for comparison
            for field in ['iteration', 'timestamp', 'messages']:
                new_dict.pop(field, None)
                prev_dict.pop(field, None)
            
            return new_dict != prev_dict
        
        return True
    
    async def process(self, state: DynamicGlobalState) -> DynamicGlobalState:
        """Process the agent's task using LangGraph's create_react_agent."""
        current_iter = state.current_iteration
        
        # Check if already processed this iteration
        if (self.name in state.last_update_iteration and 
            state.last_update_iteration[self.name] == current_iter):
            return state
        
        # Check dependencies
        if not self.check_dependencies_ready(state):
            print(f"⚠️  {self.name}: Dependencies not ready for iteration {current_iter}")
            return state
        
        # Get task
        task = self.get_task_for_current_iteration(state)
        if not task:
            print(f"⚠️  {self.name}: No task assigned for iteration {current_iter}")
            return state
        
        try:
            # Update execution status
            state.agent_execution_status[self.name] = "running"
            
            # Create and run agent
            agent = self.create_react_agent_instance(state)
            config = {"configurable": {"thread_id": f"{self.name}_{current_iter}"}}
            
            start_time = time.time()
            result = await agent.ainvoke({"messages": []}, config)
            execution_time = int((time.time() - start_time) * 1000)
            
            # Extract structured output
            structured_output = result.get("structured_response")
            if structured_output:
                # Add iteration info
                if hasattr(structured_output, 'iteration'):
                    structured_output.iteration = current_iter
                
                # Store output
                if self.name not in state.agent_outputs:
                    state.agent_outputs[self.name] = {}
                
                state.agent_outputs[self.name][current_iter] = structured_output
                
                # Update last execution tracking
                if self.should_update_last_iteration(state, structured_output):
                    state.last_update_iteration[self.name] = current_iter
                
                # Send messages if any
                if hasattr(structured_output, 'messages') and structured_output.messages:
                    for message in structured_output.messages:
                        self.send_message(
                            state, 
                            message.to_agent, 
                            message.content,
                            {"confidence": getattr(message, 'confidence', None)}
                        )
                
                # Update execution status
                state.agent_execution_status[self.name] = "completed"
                print(f"✅ {self.name} completed iteration {current_iter} in {execution_time}ms")
            
        except Exception as e:
            state.agent_execution_status[self.name] = f"error: {str(e)}"
            print(f"❌ {self.name} ERROR in iteration {current_iter}: {e}")
            import traceback
            traceback.print_exc()
        
        return state