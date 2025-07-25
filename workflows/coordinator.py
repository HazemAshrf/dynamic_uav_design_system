"""Dynamic Coordinator Agent for the multi-agent dashboard system."""

import asyncio
import json
from typing import Dict, List, Any, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from backend.langgraph.state import DynamicGlobalState
from backend.core.config import settings


class DynamicCoordinator:
    """Dynamic coordinator that adapts to available agents in the system."""
    
    def __init__(self, llm_config: Dict[str, Any], prompts: str, output_class):
        """Initialize dynamic coordinator."""
        self.llm = ChatOpenAI(
            model=llm_config.get('model', 'gpt-4'),
            temperature=llm_config.get('temperature', 0.1),
            max_tokens=llm_config.get('max_tokens', 4000),
            api_key=settings.openai_api_key
        )
        
        # Set up structured output
        self.structured_llm = self.llm.with_structured_output(output_class)
        
        self.prompts = prompts
        self.output_class = output_class
        self.available_agents = []
        self.stability_threshold = 3
    
    def check_stability(self, state: DynamicGlobalState) -> bool:
        """Check if results are stable (no updates for stability_threshold iterations)."""
        current_iter = state.current_iteration
        
        if current_iter < self.stability_threshold:
            return False
        
        # Check if any agent has updated recently
        for agent_name in state.active_agents:
            agent_outputs = state.agent_outputs.get(agent_name, {})
            if agent_outputs:
                last_iter = max(agent_outputs.keys())
                if current_iter - last_iter < self.stability_threshold:
                    return False
        
        return True
    
    async def process(self, state: DynamicGlobalState) -> DynamicGlobalState:
        """Process coordinator logic with dynamic agent adaptation."""
        current_iter = state.current_iteration
        
        if current_iter == 0:
            # Initial task assignment
            output = await self._create_initial_tasks(state)
            print(f"🎯 Dynamic Coordinator created initial tasks for {len(output.agent_tasks)} agents")
        else:
            # Check stability first
            is_stable = self.check_stability(state)
            
            if not is_stable:
                # System is not stable, continue without LLM evaluation
                print(f"🔄 System NOT STABLE - continuing to iteration {current_iter + 1}")
                output = self.output_class(
                    project_complete=False,
                    completion_reason=f"System not stable - agents still updating. Continuing to iteration {current_iter + 1}.",
                    available_agents=self.available_agents,
                    agent_tasks=[],
                    messages=[],
                    iteration=current_iter
                )
            else:
                # System is stable, evaluate with LLM
                print(f"✅ System STABLE - evaluating completion...")
                output = await self._evaluate_and_decide(state)
                
                if not output.project_complete:
                    print(f"🔄 Coordinator decided to CONTINUE: {output.completion_reason}")
                else:
                    print(f"🎉 Coordinator decided to COMPLETE: {output.completion_reason}")
        
        # Update state
        output.iteration = current_iter
        
        # Store coordinator output
        if "coordinator" not in state.agent_outputs:
            state.agent_outputs["coordinator"] = {}
        state.agent_outputs["coordinator"][current_iter] = output
        
        state.project_complete = output.project_complete
        
        # Process messages (send to agent mailboxes if available)
        for msg in output.messages:
            if hasattr(state, 'agent_conversations') and msg.to_agent in state.agent_conversations:
                # Add message to conversation system
                await self._send_message_to_agent(state, msg, current_iter)
        
        # Increment iteration if continuing
        if not output.project_complete:
            state.current_iteration += 1
        
        return state
    
    async def _create_initial_tasks(self, state: DynamicGlobalState):
        """Create initial tasks for available agents."""
        # Prepare context with available agents
        available_agents_context = f"Available agents in the system: {', '.join(self.available_agents)}"
        
        human_message = f"""
User Requirements: {state.user_requirements}

{available_agents_context}

Create specific tasks for each available agent. This is iteration 0 - initial task assignment. 
Make each task specific and actionable, adapted to the agents currently available in the system.

If critical agents are missing, note this in your completion_reason but still assign tasks to available agents.
"""
        
        try:
            response = await self.structured_llm.ainvoke([
                SystemMessage(content=self.prompts),
                HumanMessage(content=human_message)
            ])
            
            # Ensure available_agents is populated
            response.available_agents = self.available_agents
            
            return response
        except Exception as e:
            print(f"Error in coordinator task creation: {e}")
            # Return fallback response
            return self.output_class(
                project_complete=False,
                completion_reason=f"Initial task assignment (fallback due to error: {str(e)})",
                available_agents=self.available_agents,
                agent_tasks=[
                    {"agent_name": agent, "task_description": f"Work on {agent} aspects of: {state.user_requirements}"}
                    for agent in self.available_agents
                ],
                messages=[],
                iteration=0
            )
    
    async def _evaluate_and_decide(self, state: DynamicGlobalState):
        """Evaluate current outputs and decide on project completion."""
        # Get latest outputs from available agents
        latest_outputs = {}
        for agent_name in self.available_agents:
            agent_outputs = state.agent_outputs.get(agent_name, {})
            if agent_outputs:
                latest_iter = max(agent_outputs.keys())
                latest_outputs[agent_name] = agent_outputs[latest_iter]
        
        is_stable = self.check_stability(state)
        
        # Create evaluation context
        available_agents_context = f"Available agents: {', '.join(self.available_agents)}"
        outputs_summary = json.dumps({k: str(v)[:200] + "..." if len(str(v)) > 200 else str(v) 
                                     for k, v in latest_outputs.items()}, indent=2)
        
        human_message = f"""
User Requirements: {state.user_requirements}
Current Iteration: {state.current_iteration}
System Stable: {is_stable}
{available_agents_context}

Latest Agent Outputs:
{outputs_summary}

Evaluate if the project is complete or if specific agents need to continue work.
STRONG BIAS TOWARD COMPLETION - only continue for CRITICAL safety or fundamental feasibility issues.

If continuing, provide specific tasks for MAJOR issues only.
Adapt your evaluation to the agents currently available in the system.
"""
        
        try:
            response = await self.structured_llm.ainvoke([
                SystemMessage(content=self.prompts),
                HumanMessage(content=human_message)
            ])
            
            # Ensure available_agents is populated
            response.available_agents = self.available_agents
            
            return response
        except Exception as e:
            print(f"Error in coordinator evaluation: {e}")
            # Return completion fallback
            return self.output_class(
                project_complete=True,
                completion_reason=f"Completed due to evaluation error: {str(e)}",
                available_agents=self.available_agents,
                agent_tasks=[],
                messages=[],
                iteration=state.current_iteration
            )
    
    async def _send_message_to_agent(self, state: DynamicGlobalState, message, iteration: int):
        """Send message to agent (placeholder for future message system)."""
        # This would integrate with the conversation system when available
        print(f"📨 Coordinator → {message.to_agent}: {message.content}")