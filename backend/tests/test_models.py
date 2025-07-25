"""Test database models."""

import pytest
from datetime import datetime
from sqlalchemy.exc import IntegrityError

from backend.models.agent import Agent, AgentStatus
from backend.models.conversation import AgentConversation, AgentMessage, ConversationStatus
from workflows.models import WorkflowExecution, WorkflowStatus


@pytest.mark.asyncio
async def test_agent_creation(db_session):
    """Test agent creation and validation."""
    agent = Agent(
        name="test_agent",
        display_name="Test Agent",
        role="Test role",
        llm_name="gpt-4",
        temperature=0.1,
        max_tokens=1000,
        dependencies=["mission_planner"],
        prompts_file_path="/test/prompts.py",
        output_class_file_path="/test/output.py",
        tools_file_path="/test/tools.py"
    )
    
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    
    assert agent.id is not None
    assert agent.name == "test_agent"
    assert agent.status == AgentStatus.CONFIGURING
    assert agent.created_at is not None


@pytest.mark.asyncio  
async def test_agent_unique_name(db_session):
    """Test that agent names must be unique."""
    agent1 = Agent(
        name="duplicate_agent",
        display_name="First Agent",
        role="Test role",
        llm_name="gpt-4"
    )
    agent2 = Agent(
        name="duplicate_agent", 
        display_name="Second Agent",
        role="Test role",
        llm_name="gpt-4"
    )
    
    db_session.add(agent1)
    await db_session.commit()
    
    db_session.add(agent2)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_conversation_creation(db_session):
    """Test conversation creation."""
    conversation = AgentConversation(
        conversation_key="agent1_agent2",
        participant_1="agent1",
        participant_2="agent2"
    )
    
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    
    assert conversation.id is not None
    assert conversation.conversation_key == "agent1_agent2"
    assert conversation.participant_1 == "agent1"
    assert conversation.participant_2 == "agent2"
    assert conversation.status == ConversationStatus.ACTIVE
    assert conversation.created_at is not None


@pytest.mark.asyncio
async def test_message_creation(db_session):
    """Test message creation with conversation relationship."""
    # Create conversation first
    conversation = AgentConversation(
        conversation_key="sender_receiver",
        participant_1="sender",
        participant_2="receiver"
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    
    # Create message
    message = AgentMessage(
        conversation_id=conversation.id,
        from_agent="sender",
        to_agent="receiver",
        content="Test message content",
        iteration=1,
        message_metadata={"test": "metadata"}
    )
    
    db_session.add(message)
    await db_session.commit()
    await db_session.refresh(message)
    
    assert message.id is not None
    assert message.conversation_id == conversation.id
    assert message.content == "Test message content"
    assert message.from_agent == "sender"
    assert message.to_agent == "receiver"
    assert message.iteration == 1


@pytest.mark.asyncio
async def test_workflow_creation(db_session):
    """Test workflow creation and status transitions."""
    workflow = WorkflowExecution(
        workflow_id="test_workflow_123",
        thread_id="thread_123",
        user_requirements="Test requirements",
        active_agents=["agent1", "agent2"]
    )
    
    db_session.add(workflow)
    await db_session.commit()
    await db_session.refresh(workflow)
    
    assert workflow.id is not None
    assert workflow.workflow_id == "test_workflow_123"
    assert workflow.status == WorkflowStatus.PENDING
    assert workflow.current_iteration == 0
    
    # Test status transition
    workflow.status = WorkflowStatus.RUNNING
    workflow.current_iteration = 1
    await db_session.commit()
    
    await db_session.refresh(workflow)
    assert workflow.status == WorkflowStatus.RUNNING
    assert workflow.current_iteration == 1


@pytest.mark.asyncio
async def test_agent_dependencies(db_session):
    """Test agent dependency relationships."""
    # Create agents with dependencies
    base_agent = Agent(
        name="base_agent",
        display_name="Base Agent",
        role="Base functionality",
        llm_name="gpt-4"
    )
    
    dependent_agent = Agent(
        name="dependent_agent",
        display_name="Dependent Agent", 
        role="Depends on base",
        llm_name="gpt-4",
        dependencies=["base_agent"]
    )
    
    db_session.add_all([base_agent, dependent_agent])
    await db_session.commit()
    
    await db_session.refresh(base_agent)
    await db_session.refresh(dependent_agent)
    
    assert "base_agent" in dependent_agent.dependencies
    assert len(dependent_agent.dependencies) == 1


@pytest.mark.asyncio
async def test_conversation_message_relationship(db_session):
    """Test relationship between conversations and messages."""
    # Create conversation
    conversation = AgentConversation(
        conversation_key="agent1_agent2",
        participant_1="agent1",
        participant_2="agent2"
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    
    # Create multiple messages
    messages = [
        AgentMessage(
            conversation_id=conversation.id,
            from_agent="agent1",
            to_agent="agent2", 
            content=f"Message {i}",
            iteration=1
        )
        for i in range(3)
    ]
    
    db_session.add_all(messages)
    await db_session.commit()
    
    # Refresh and check relationship
    await db_session.refresh(conversation)
    assert len(conversation.messages) == 3
    
    # Check message ordering
    sorted_messages = sorted(conversation.messages, key=lambda m: m.created_at)
    assert sorted_messages[0].content == "Message 0"
    assert sorted_messages[-1].content == "Message 2"