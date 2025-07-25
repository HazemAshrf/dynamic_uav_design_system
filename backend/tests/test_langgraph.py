"""Test LangGraph integration components."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.langgraph.state import DynamicGlobalState
from backend.langgraph.workflow import DynamicWorkflowBuilder
from backend.models.agent import Agent, AgentStatus


class TestDynamicGlobalState:
    """Test dynamic global state management."""
    
    def test_global_state_initialization(self):
        """Test DynamicGlobalState initialization."""
        state = DynamicGlobalState(
            user_requirements="Design a cargo drone",
            current_iteration=1
        )
        
        assert state.user_requirements == "Design a cargo drone"
        assert state.current_iteration == 1
        assert len(state.agent_outputs) == 0
        assert len(state.conversations) == 0
        assert len(state.active_agents) == 0
    
    def test_global_state_send_message(self):
        """Test sending messages between agents."""
        state = DynamicGlobalState(
            user_requirements="Test requirements",
            current_iteration=1
        )
        
        # Send message
        state.send_message("agent1", "agent2", "Test message", {"test": "metadata"})
        
        assert len(state.conversations) == 1
        conversation_key = "agent1_agent2"
        assert conversation_key in state.conversations
        conversation = state.conversations[conversation_key]
        assert len(conversation.messages) == 1
        message = conversation.messages[0]
        assert message.from_agent == "agent1"
        assert message.to_agent == "agent2"
        assert message.content == "Test message"
        assert message.metadata["test"] == "metadata"
    
    def test_global_state_add_agent(self):
        """Test adding agent to state."""
        state = DynamicGlobalState(
            user_requirements="Test requirements",
            current_iteration=1
        )
        
        agent_config = {
            "name": "test_agent",
            "role": "Test agent",
            "llm_name": "gpt-4"
        }
        
        state.add_agent("test_agent", agent_config)
        
        assert "test_agent" in state.active_agents
        assert state.active_agents["test_agent"] == agent_config
        assert "test_agent" in state.agent_outputs
        assert "test_agent" in state.last_update_iteration
    
    def test_global_state_remove_agent(self):
        """Test removing agent from state."""
        state = DynamicGlobalState(
            user_requirements="Test requirements",
            current_iteration=1
        )
        
        # Add agent first
        agent_config = {"name": "test_agent"}
        state.add_agent("test_agent", agent_config)
        
        # Add a conversation
        state.send_message("test_agent", "other_agent", "test message")
        
        # Remove agent
        state.remove_agent("test_agent")
        
        assert "test_agent" not in state.active_agents
        assert "test_agent" not in state.agent_outputs
        assert len(state.conversations) == 0  # Conversations involving agent should be removed
    
    def test_global_state_get_conversation(self):
        """Test getting conversation between agents."""
        state = DynamicGlobalState(
            user_requirements="Test requirements",
            current_iteration=1
        )
        
        # No conversation initially
        conversation = state.get_conversation("agent1", "agent2")
        assert conversation is None
        
        # Send message to create conversation
        state.send_message("agent1", "agent2", "test message")
        
        # Get conversation
        conversation = state.get_conversation("agent1", "agent2")
        assert conversation is not None
        assert len(conversation.messages) == 1
    
    def test_global_state_check_stability(self):
        """Test stability checking."""
        state = DynamicGlobalState(
            user_requirements="Test requirements",
            current_iteration=1
        )
        
        # Should not be stable initially (iteration < threshold)
        assert not state.check_stability()
        
        # Set iteration above threshold
        state.current_iteration = 5
        
        # Should be stable if no recent agent updates
        assert state.check_stability()
    
    def test_global_state_get_workflow_progress(self):
        """Test workflow progress tracking."""
        state = DynamicGlobalState(
            user_requirements="Test requirements",
            current_iteration=1
        )
        
        # Add some agents
        state.add_agent("agent1", {"name": "agent1"})
        state.add_agent("agent2", {"name": "agent2"})
        
        # Set some statuses
        state.agent_execution_status["agent1"] = "completed"
        state.agent_execution_status["agent2"] = "running"
        
        progress = state.get_workflow_progress()
        
        assert progress["total_agents"] == 2
        assert progress["completed_agents"] == 1
        assert progress["active_agents"] == 1
        assert progress["current_iteration"] == 1


class TestDynamicWorkflowBuilder:
    """Test dynamic workflow builder."""
    
    def test_workflow_builder_initialization(self):
        """Test workflow builder initialization."""
        builder = DynamicWorkflowBuilder()
        assert builder is not None
    
    def test_create_agent_node_basic(self):
        """Test basic agent node creation."""
        builder = DynamicWorkflowBuilder()
        
        # Mock agent
        agent = MagicMock()
        agent.name = "test_agent"
        agent.display_name = "Test Agent"
        agent.role = "Test role"
        agent.llm_name = "gpt-4"
        agent.temperature = 0.1
        agent.max_tokens = 1000
        agent.prompts_file = "/path/to/prompts.py"
        agent.output_class_file = "/path/to/output_class.py"
        agent.tools_file = "/path/to/tools.py"
        
        # Create node function
        node_func = builder._create_agent_node(agent)
        
        assert callable(node_func)
        assert node_func.__name__ == "test_agent"
    
    @pytest.mark.asyncio
    async def test_agent_node_execution_mock(self):
        """Test agent node execution with mocking."""
        builder = DynamicWorkflowBuilder()
        
        # Create mock agent
        agent = MagicMock()
        agent.name = "test_agent"
        agent.display_name = "Test Agent"
        agent.role = "Test role"
        agent.llm_name = "gpt-4"
        agent.temperature = 0.1
        agent.max_tokens = 1000
        agent.prompts_file = "/path/to/prompts.py"
        agent.output_class_file = "/path/to/output_class.py"
        agent.tools_file = "/path/to/tools.py"
        
        # Create node function
        node_func = builder._create_agent_node(agent)
        
        # Create mock state
        state = GlobalState(
            user_requirements="Test requirements",
            current_agent="test_agent",
            iteration=1
        )
        
        # Mock the actual agent execution
        with patch('backend.langgraph.workflow.DynamicWorkflowBuilder._execute_agent') as mock_execute:
            mock_execute.return_value = {
                "result": "Mock result",
                "confidence": 0.9,
                "errors": [],
                "metadata": {},
                "iteration": 1
            }
            
            # Execute node
            result = await node_func(state)
            
            # Verify execution
            assert result is not None
            assert isinstance(result, GlobalState)
            mock_execute.assert_called_once()
    
    def test_resolve_dependencies_no_deps(self):
        """Test dependency resolution with no dependencies."""
        builder = DynamicWorkflowBuilder()
        
        # Create agents with no dependencies
        agent1 = MagicMock()
        agent1.name = "agent1"
        agent1.dependencies = []
        
        agent2 = MagicMock()
        agent2.name = "agent2"
        agent2.dependencies = []
        
        agents = [agent1, agent2]
        resolved = builder._resolve_dependencies(agents)
        
        # All agents should be in the first level
        assert len(resolved) >= 1
        first_level = resolved[0]
        agent_names = [agent.name for agent in first_level]
        assert "agent1" in agent_names
        assert "agent2" in agent_names
    
    def test_resolve_dependencies_with_deps(self):
        """Test dependency resolution with dependencies."""
        builder = DynamicWorkflowBuilder()
        
        # Create agents with dependencies
        base_agent = MagicMock()
        base_agent.name = "base_agent"
        base_agent.dependencies = []
        
        dependent_agent = MagicMock()
        dependent_agent.name = "dependent_agent"
        dependent_agent.dependencies = ["base_agent"]
        
        agents = [dependent_agent, base_agent]  # Intentionally out of order
        resolved = builder._resolve_dependencies(agents)
        
        # Should have at least 2 levels
        assert len(resolved) >= 2
        
        # Base agent should be in first level
        first_level_names = [agent.name for agent in resolved[0]]
        assert "base_agent" in first_level_names
        
        # Dependent agent should be in later level
        all_later_names = []
        for level in resolved[1:]:
            all_later_names.extend([agent.name for agent in level])
        assert "dependent_agent" in all_later_names
    
    def test_resolve_dependencies_circular(self):
        """Test handling of circular dependencies."""
        builder = DynamicWorkflowBuilder()
        
        # Create agents with circular dependencies
        agent1 = MagicMock()
        agent1.name = "agent1"
        agent1.dependencies = ["agent2"]
        
        agent2 = MagicMock()
        agent2.name = "agent2"
        agent2.dependencies = ["agent1"]
        
        agents = [agent1, agent2]
        
        # Should handle gracefully (may raise exception or return partial resolution)
        try:
            resolved = builder._resolve_dependencies(agents)
            # If it succeeds, ensure it's not empty
            assert len(resolved) > 0
        except ValueError as e:
            # Should detect circular dependency
            assert "circular" in str(e).lower() or "cycle" in str(e).lower()
    
    def test_create_coordinator_node(self):
        """Test coordinator node creation."""
        builder = DynamicWorkflowBuilder()
        
        coordinator_func = builder._create_coordinator_node()
        
        assert callable(coordinator_func)
        assert coordinator_func.__name__ == "coordinator"
    
    def test_create_aggregator_node(self):
        """Test aggregator node creation."""
        builder = DynamicWorkflowBuilder()
        
        aggregator_func = builder._create_aggregator_node()
        
        assert callable(aggregator_func)
        assert aggregator_func.__name__ == "aggregator"
    
    def test_determine_next_agent(self):
        """Test next agent determination logic."""
        builder = DynamicWorkflowBuilder()
        
        # Mock state
        state = GlobalState(
            user_requirements="Test requirements",
            current_agent="agent1",
            iteration=1
        )
        
        # Test with empty agent levels
        next_agent = builder._determine_next_agent(state, [])
        assert next_agent == "aggregator"
        
        # Test with agent levels
        mock_agent = MagicMock()
        mock_agent.name = "agent2"
        agent_levels = [[mock_agent]]
        
        next_agent = builder._determine_next_agent(state, agent_levels)
        # Should return either next agent or coordinator/aggregator
        assert next_agent in ["agent2", "coordinator", "aggregator"]
    
    @pytest.mark.asyncio
    async def test_build_workflow_empty_agents(self):
        """Test workflow building with empty agent list."""
        builder = DynamicWorkflowBuilder()
        
        # Should handle empty agent list gracefully
        try:
            workflow = await builder.build_workflow([])
            # If successful, should return something
            assert workflow is not None
        except ValueError:
            # Or should raise appropriate error
            pass
    
    @pytest.mark.asyncio
    async def test_build_workflow_single_agent(self):
        """Test workflow building with single agent."""
        builder = DynamicWorkflowBuilder()
        
        # Create mock agent
        agent = MagicMock()
        agent.name = "single_agent"
        agent.display_name = "Single Agent"
        agent.role = "Single role"
        agent.llm_name = "gpt-4"
        agent.temperature = 0.1
        agent.max_tokens = 1000
        agent.dependencies = []
        agent.prompts_file = "/path/to/prompts.py"
        agent.output_class_file = "/path/to/output_class.py"
        agent.tools_file = "/path/to/tools.py"
        
        # Build workflow
        workflow = await builder.build_workflow([agent])
        
        # Should create workflow successfully
        assert workflow is not None