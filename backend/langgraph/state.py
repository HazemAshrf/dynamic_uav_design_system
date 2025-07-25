"""Enhanced global state and conversation system for dynamic agents."""

import time
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field, ConfigDict


class AgentMessage(BaseModel):
    """Individual message between agents."""
    id: str
    from_agent: str
    to_agent: str
    content: str
    timestamp: float
    iteration: int
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentConversation(BaseModel):
    """Conversation thread between two agents."""
    participants: List[str]
    messages: List[AgentMessage] = Field(default_factory=list)
    last_activity: Optional[float] = None
    
    def add_message(self, message: AgentMessage):
        """Add message to conversation."""
        self.messages.append(message)
        self.last_activity = message.timestamp
        
    def get_messages_for_iteration(self, iteration: int) -> List[AgentMessage]:
        """Get messages for specific iteration."""
        return [msg for msg in self.messages if msg.iteration == iteration]
    
    def get_recent_messages(self, limit: int = 10) -> List[AgentMessage]:
        """Get most recent messages."""
        return sorted(self.messages, key=lambda x: x.timestamp)[-limit:]


class DynamicGlobalState(BaseModel):
    """Enhanced global state supporting dynamic agents with checkpointing."""
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    # Dynamic agent outputs (keyed by agent name, then iteration)
    agent_outputs: Dict[str, Dict[int, Any]] = Field(default_factory=dict)
    
    # Agent-to-agent conversations (keyed by sorted participant names)
    conversations: Dict[str, AgentConversation] = Field(default_factory=dict)
    
    # Dynamic agent registry (keyed by agent name)
    active_agents: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    
    # Workflow control
    current_iteration: int = 0
    max_iterations: int = 10
    stability_threshold: int = 3
    project_complete: bool = False
    
    # Execution tracking
    last_update_iteration: Dict[str, int] = Field(default_factory=dict)
    agent_execution_status: Dict[str, str] = Field(default_factory=dict)
    
    # User input and configuration
    user_requirements: str = ""
    workflow_config: Dict[str, Any] = Field(default_factory=dict)
    
    # Checkpointing metadata
    thread_id: str = ""
    checkpoint_id: Optional[str] = None
    
    def add_agent(self, agent_name: str, agent_config: Dict[str, Any]):
        """Add new agent to the state."""
        self.active_agents[agent_name] = agent_config
        if agent_name not in self.agent_outputs:
            self.agent_outputs[agent_name] = {}
        if agent_name not in self.last_update_iteration:
            self.last_update_iteration[agent_name] = -1
        if agent_name not in self.agent_execution_status:
            self.agent_execution_status[agent_name] = "ready"
    
    def remove_agent(self, agent_name: str):
        """Remove agent from the state."""
        self.active_agents.pop(agent_name, None)
        self.agent_outputs.pop(agent_name, None)
        self.last_update_iteration.pop(agent_name, None)
        self.agent_execution_status.pop(agent_name, None)
        
        # Remove conversations involving this agent
        to_remove = []
        for conversation_key, conversation in self.conversations.items():
            if agent_name in conversation.participants:
                to_remove.append(conversation_key)
        
        for key in to_remove:
            self.conversations.pop(key)
    
    def get_conversation(self, agent1: str, agent2: str) -> Optional[AgentConversation]:
        """Get conversation between two agents."""
        conversation_key = "_".join(sorted([agent1, agent2]))
        return self.conversations.get(conversation_key)
    
    def create_conversation(self, agent1: str, agent2: str) -> AgentConversation:
        """Create new conversation between two agents."""
        conversation_key = "_".join(sorted([agent1, agent2]))
        conversation = AgentConversation(participants=sorted([agent1, agent2]))
        self.conversations[conversation_key] = conversation
        return conversation
    
    def send_message(
        self, 
        from_agent: str, 
        to_agent: str, 
        content: str, 
        metadata: Dict[str, Any] = None
    ):
        """Send message between agents."""
        conversation_key = "_".join(sorted([from_agent, to_agent]))
        
        # Ensure conversation exists
        if conversation_key not in self.conversations:
            self.create_conversation(from_agent, to_agent)
        
        # Create message
        message = AgentMessage(
            id=f"{from_agent}_{to_agent}_{time.time()}",
            from_agent=from_agent,
            to_agent=to_agent,
            content=content,
            timestamp=time.time(),
            iteration=self.current_iteration,
            metadata=metadata or {}
        )
        
        # Add to conversation
        self.conversations[conversation_key].add_message(message)
    
    def get_agent_conversations(self, agent_name: str) -> List[AgentConversation]:
        """Get all conversations involving a specific agent."""
        conversations = []
        for conversation in self.conversations.values():
            if agent_name in conversation.participants:
                conversations.append(conversation)
        return conversations
    
    def check_stability(self) -> bool:
        """Check if the system has reached stability."""
        if self.current_iteration < self.stability_threshold:
            return False
        
        # Check if any agent has updated within stability threshold
        for agent_name, last_update in self.last_update_iteration.items():
            if self.current_iteration - last_update < self.stability_threshold:
                return False
        
        return True
    
    def get_active_agent_names(self) -> List[str]:
        """Get list of active agent names."""
        return list(self.active_agents.keys())
    
    def get_iteration_summary(self, iteration: int) -> Dict[str, Any]:
        """Get summary of what happened in a specific iteration."""
        summary = {
            "iteration": iteration,
            "agents_executed": [],
            "messages_sent": 0,
            "errors": []
        }
        
        # Check which agents produced outputs
        for agent_name, outputs in self.agent_outputs.items():
            if iteration in outputs:
                summary["agents_executed"].append(agent_name)
        
        # Count messages sent in this iteration
        for conversation in self.conversations.values():
            iteration_messages = conversation.get_messages_for_iteration(iteration)
            summary["messages_sent"] += len(iteration_messages)
        
        # Check for errors
        for agent_name, status in self.agent_execution_status.items():
            if status.startswith("error"):
                summary["errors"].append(f"{agent_name}: {status}")
        
        return summary
    
    def get_workflow_progress(self) -> Dict[str, Any]:
        """Get overall workflow progress information."""
        total_agents = len(self.active_agents)
        completed_agents = 0
        active_agents = 0
        error_agents = 0
        
        for agent_name in self.active_agents:
            status = self.agent_execution_status.get(agent_name, "ready")
            if status == "completed":
                completed_agents += 1
            elif status == "running":
                active_agents += 1
            elif status.startswith("error"):
                error_agents += 1
        
        progress_percentage = (completed_agents / total_agents * 100) if total_agents > 0 else 0
        
        return {
            "current_iteration": self.current_iteration,
            "max_iterations": self.max_iterations,
            "total_agents": total_agents,
            "completed_agents": completed_agents,
            "active_agents": active_agents,
            "error_agents": error_agents,
            "progress_percentage": progress_percentage,
            "is_stable": self.check_stability(),
            "is_complete": self.project_complete
        }