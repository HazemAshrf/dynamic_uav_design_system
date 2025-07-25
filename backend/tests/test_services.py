"""Test service layer functionality."""

import pytest
import tempfile
import os
import base64
from pathlib import Path

from backend.services.file_processor import FileProcessor
from backend.services.agent_factory import AgentFactory
from backend.models.agent import Agent


class TestFileProcessor:
    """Test file processing service."""
    
    def test_validate_file_content_valid(self):
        """Test validation of safe file content."""
        processor = FileProcessor()
        
        safe_content = """
        from pydantic import BaseModel
        
        class TestOutput(BaseModel):
            result: str
        """
        
        issues = processor._validate_file_content(safe_content, "output_class.py")
        assert len(issues) == 0
    
    def test_validate_file_content_dangerous(self):
        """Test detection of dangerous patterns."""
        processor = FileProcessor()
        
        dangerous_content = """
        import os
        os.system('rm -rf /')
        """
        
        issues = processor._validate_file_content(dangerous_content, "tools.py")
        assert len(issues) > 0
        assert any("Dangerous system call" in str(issue) for issue in issues)
    
    def test_validate_file_size(self):
        """Test file size validation."""
        processor = FileProcessor()
        
        # Test valid size
        small_content = "print('hello')"
        assert processor._validate_file_size(small_content, "test.py") == []
        
        # Test oversized content
        large_content = "x" * (processor.MAX_FILE_SIZE + 1)
        issues = processor._validate_file_size(large_content, "test.py")
        assert len(issues) > 0
        assert "exceeds maximum size" in str(issues[0])
    
    def test_validate_python_syntax_valid(self):
        """Test Python syntax validation with valid code."""
        processor = FileProcessor()
        
        valid_python = """
        def hello_world():
            return "Hello, World!"
        """
        
        issues = processor._validate_python_syntax(valid_python, "test.py")
        assert len(issues) == 0
    
    def test_validate_python_syntax_invalid(self):
        """Test Python syntax validation with invalid code."""
        processor = FileProcessor()
        
        invalid_python = """
        def hello_world(
            return "Missing closing parenthesis"
        """
        
        issues = processor._validate_python_syntax(invalid_python, "test.py")
        assert len(issues) > 0
        assert "Syntax error" in str(issues[0])
    
    @pytest.mark.asyncio
    async def test_validate_files_success(self, sample_agent_files):
        """Test successful file validation."""
        processor = FileProcessor()
        
        result = await processor.validate_agent_files(sample_agent_files)
        
        assert result.overall_valid is True
        assert len(result.validation_results) == 4
        
        # Check that validation was successful
        for validation_result in result.validation_results:
            assert validation_result.valid is True
    
    @pytest.mark.asyncio
    async def test_validate_files_validation_failure(self):
        """Test file validation with validation failures."""
        processor = FileProcessor()
        
        # Create files with validation issues
        bad_files = {
            "prompts": base64.b64encode(b"").decode(),  # Empty file
            "output_class": base64.b64encode(b"invalid python syntax (((").decode(),
            "tools": base64.b64encode(b"import os; os.system('rm -rf /')").decode(),
            "dependencies": base64.b64encode(b"not valid json [[[").decode()
        }
        
        result = await processor.validate_agent_files(bad_files)
        
        assert result.overall_valid is False
        invalid_results = [r for r in result.validation_results if not r.valid]
        assert len(invalid_results) > 0


class TestAgentFactory:
    """Test agent factory service."""
    
    @pytest.mark.asyncio
    async def test_create_agent_success(self, db_session, sample_agent_data):
        """Test successful agent creation."""
        factory = AgentFactory(db_session)
        
        agent = await factory.create_agent(sample_agent_data)
        
        assert agent is not None
        assert agent.name == "test_agent"
        assert agent.display_name == "Test Agent"
        assert agent.llm_name == "gpt-4"
        assert agent.dependencies == ["mission_planner"]
    
    @pytest.mark.asyncio
    async def test_create_agent_duplicate_name(self, db_session, sample_agent_data):
        """Test agent creation with duplicate name."""
        factory = AgentFactory(db_session)
        
        # Create first agent
        await factory.create_agent(sample_agent_data)
        
        # Try to create second agent with same name
        with pytest.raises(ValueError, match="Agent with name .* already exists"):
            await factory.create_agent(sample_agent_data)
    
    @pytest.mark.asyncio
    async def test_create_agent_missing_files(self, db_session):
        """Test agent creation with missing files."""
        factory = AgentFactory(db_session)
        
        incomplete_data = {
            "name": "incomplete_agent",
            "display_name": "Incomplete Agent",
            "role": "Test",
            "llm_name": "gpt-4",
            "files": {
                "prompts": "dGVzdA==",  # Only prompts file
                # Missing other required files
            }
        }
        
        with pytest.raises(ValueError, match="Missing required files"):
            await factory.create_agent(incomplete_data)
    
    @pytest.mark.asyncio
    async def test_get_agent_by_name(self, db_session, sample_agent_data):
        """Test retrieving agent by name."""
        factory = AgentFactory(db_session)
        
        # Create agent
        created_agent = await factory.create_agent(sample_agent_data)
        
        # Retrieve agent
        retrieved_agent = await factory.get_agent_by_name("test_agent")
        
        assert retrieved_agent is not None
        assert retrieved_agent.id == created_agent.id
        assert retrieved_agent.name == "test_agent"
    
    @pytest.mark.asyncio
    async def test_get_agent_by_name_not_found(self, db_session):
        """Test retrieving non-existent agent."""
        factory = AgentFactory(db_session)
        
        agent = await factory.get_agent_by_name("nonexistent_agent")
        assert agent is None
    
    @pytest.mark.asyncio
    async def test_list_agents(self, db_session, sample_agent_data):
        """Test listing all agents."""
        factory = AgentFactory(db_session)
        
        # Create multiple agents
        agent_data_1 = sample_agent_data.copy()
        agent_data_1["name"] = "agent_1"
        
        agent_data_2 = sample_agent_data.copy()  
        agent_data_2["name"] = "agent_2"
        agent_data_2["files"] = sample_agent_data["files"].copy()
        
        await factory.create_agent(agent_data_1)
        await factory.create_agent(agent_data_2)
        
        # List agents
        agents = await factory.list_agents()
        
        assert len(agents) == 2
        agent_names = [agent.name for agent in agents]
        assert "agent_1" in agent_names
        assert "agent_2" in agent_names
    
    @pytest.mark.asyncio
    async def test_delete_agent(self, db_session, sample_agent_data):
        """Test agent deletion."""
        factory = AgentFactory(db_session)
        
        # Create agent
        agent = await factory.create_agent(sample_agent_data)
        agent_id = agent.id
        
        # Delete agent
        success = await factory.delete_agent("test_agent")
        assert success is True
        
        # Verify deletion
        deleted_agent = await factory.get_agent_by_name("test_agent")
        assert deleted_agent is None
    
    @pytest.mark.asyncio
    async def test_delete_nonexistent_agent(self, db_session):
        """Test deletion of non-existent agent."""
        factory = AgentFactory(db_session)
        
        success = await factory.delete_agent("nonexistent_agent")
        assert success is False
    
    @pytest.mark.asyncio
    async def test_update_agent_status(self, db_session, sample_agent_data):
        """Test updating agent status."""
        from backend.models.agent import AgentStatus
        
        factory = AgentFactory(db_session)
        
        # Create agent
        agent = await factory.create_agent(sample_agent_data)
        assert agent.status == AgentStatus.INACTIVE
        
        # Update status
        updated_agent = await factory.update_agent_status("test_agent", AgentStatus.ACTIVE)
        assert updated_agent is not None
        assert updated_agent.status == AgentStatus.ACTIVE
        
        # Verify persistence
        retrieved_agent = await factory.get_agent_by_name("test_agent")
        assert retrieved_agent.status == AgentStatus.ACTIVE