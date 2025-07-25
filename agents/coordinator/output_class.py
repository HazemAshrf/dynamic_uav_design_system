"""Coordinator agent output class."""

from typing import List
from pydantic import BaseModel, Field


class AgentMessage(BaseModel):
    """Message from coordinator to another agent."""
    to_agent: str = Field(description="Target agent to send message to")
    content: str = Field(description="Message content")


class AgentTask(BaseModel):
    """Task assignment for an agent."""
    agent_name: str = Field(description="Name of the agent")
    task_description: str = Field(description="Specific task for this agent")


class CoordinatorOutput(BaseModel):
    """Coordinator output for dynamic agent management."""
    project_complete: bool = Field(description="Whether project is complete")
    completion_reason: str = Field(description="Detailed reason for completion/continuation")
    available_agents: List[str] = Field(default=[], description="List of available agents detected")
    agent_tasks: List[AgentTask] = Field(default=[], description="Tasks for specific agents if continuing")
    messages: List[AgentMessage] = Field(default=[], description="Messages to send to specific agents")
    iteration: int = Field(description="Current iteration number")