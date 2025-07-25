"""Dynamically generated agent: coordinator"""

import asyncio
from typing import Dict, List, Any, Optional
from langchain_openai import ChatOpenAI

from backend.agents.base_agent import BaseAgent
from backend.langgraph.state import DynamicGlobalState

# Import generated output model
try:
    from backend.storage.generated.models.coordinator_output import CoordinatorOutput
except ImportError:
    # Fallback to local output class if generated one doesn't exist
    from agents.coordinator.output_class import CoordinatorOutput

# Import tools (empty for coordinator)
# No tools detected - using empty tools list


class CoordinatorAgent(BaseAgent):
    """
    Manages and coordinates the UAV design workflow, adapting to available agents
    
    Generated agent for: coordinator
    Dependencies: None
    """
    
    def __init__(self, llm: ChatOpenAI, tools: List, output_class, config: Dict[str, Any]):
        # Read prompts from prompts.py file
        try:
            from agents.coordinator.prompts import SYSTEM_PROMPT
            prompts = SYSTEM_PROMPT
        except ImportError:
            prompts = """You are the UAV Design Project Coordinator managing a team of specialized engineering agents. Your role is to coordinate tasks and evaluate project completion."""
        
        super().__init__(
            name="coordinator",
            llm=llm,
            tools=tools,
            output_class=output_class or CoordinatorOutput,
            system_prompt=prompts,
            dependencies=[],
            config=config
        )
    
    def check_dependencies_ready(self, state: DynamicGlobalState) -> bool:
        """Check if required dependencies have produced outputs."""
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
    
    def _debug_dependency_status(self, state: DynamicGlobalState):
        """Debug dependency status for troubleshooting."""
        print(f"🔍 {self.name} dependency debug:")
        for dep in self.dependencies:
            if dep in state.agent_outputs:
                iterations = list(state.agent_outputs[dep].keys())
                print(f"  - {dep}: has outputs for iterations {iterations}")
            else:
                print(f"  - {dep}: no outputs found")