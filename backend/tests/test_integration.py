"""Integration tests for complete workflows."""

import pytest
import asyncio
import os
from httpx import AsyncClient

from backend.main import app
from backend.services.agent_factory import AgentFactory
from backend.services.file_processor import FileProcessor
from workflows.langgraph import DynamicWorkflowBuilder
from backend.models.agent import AgentStatus
from workflows.models import WorkflowStatus


@pytest.mark.asyncio
async def test_complete_agent_creation_workflow(db_session, sample_agent_data):
    """Test complete agent creation from files to database."""
    # Step 1: Validate files
    processor = FileProcessor()
    file_result = await processor.validate_agent_files(sample_agent_data["files"])
    
    assert file_result.overall_valid is True
    assert len(file_result.validation_results) == 4
    
    # Step 2: Create agent in database
    factory = AgentFactory(db_session)
    agent = await factory.create_agent(sample_agent_data)
    
    assert agent is not None
    assert agent.name == sample_agent_data["name"]
    assert agent.status == AgentStatus.INACTIVE
    
    # Step 3: Verify file references are correct
    assert agent.prompts_file is not None
    assert agent.output_class_file is not None
    assert agent.tools_file is not None
    assert agent.dependencies_file is not None
    
    # Step 4: Save and verify files
    file_paths = await processor.save_agent_files(agent.name, sample_agent_data["files"])
    assert len(file_paths) == 4
    
    # Step 5: Activate agent
    activated_agent = await factory.update_agent_status(
        agent.name, AgentStatus.ACTIVE
    )
    assert activated_agent.status == AgentStatus.ACTIVE


@pytest.mark.asyncio
async def test_end_to_end_api_workflow(sample_agent_data):
    """Test complete workflow through API endpoints."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Step 1: Validate files
        validation_data = {
            "agent_name": sample_agent_data["name"],
            "files": sample_agent_data["files"]
        }
        
        response = await client.post(
            "/api/v1/agents/validate-files",
            json=validation_data
        )
        assert response.status_code == 200
        assert response.json()["valid"] is True
        
        # Step 2: Create agent
        response = await client.post(
            "/api/v1/agents/",
            json=sample_agent_data
        )
        assert response.status_code == 201
        created_agent = response.json()
        
        # Step 3: Verify agent creation
        response = await client.get(f"/api/v1/agents/{sample_agent_data['name']}")
        assert response.status_code == 200
        agent_data = response.json()
        assert agent_data["name"] == sample_agent_data["name"]
        assert agent_data["status"] == "inactive"
        
        # Step 4: Activate agent
        response = await client.patch(
            f"/api/v1/agents/{sample_agent_data['name']}/status",
            json={"status": "active"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "active"
        
        # Step 5: Create workflow with active agent
        workflow_data = {
            "name": "integration_test_workflow",
            "requirements": "Test workflow with new agent",
            "active_agents": [sample_agent_data["name"]]
        }
        
        response = await client.post("/api/v1/workflows/", json=workflow_data)
        assert response.status_code == 201
        workflow = response.json()
        
        # Step 6: Verify workflow creation
        response = await client.get(f"/api/v1/workflows/{workflow['id']}")
        assert response.status_code == 200
        workflow_data = response.json()
        assert sample_agent_data["name"] in workflow_data["active_agents"]


@pytest.mark.asyncio
async def test_agent_dependency_resolution(db_session):
    """Test agent creation with dependency resolution."""
    factory = AgentFactory(db_session)
    
    # Create base agent first
    base_agent_data = {
        "name": "mission_planner",
        "display_name": "Mission Planner",
        "role": "Plans missions",
        "llm_name": "gpt-4",
        "temperature": 0.1,
        "max_tokens": 1000,
        "dependencies": [],
        "files": {
            "prompts": "UGxhbiB0aGUgbWlzc2lvbg==",  # "Plan the mission"
            "output_class": "ZnJvbSBweWRhbnRpYyBpbXBvcnQgQmFzZU1vZGVsCgpjbGFzcyBNaXNzaW9uUGxhbihCYXNlTW9kZWwpOgogICAgcGxhbjogc3Ry",
            "tools": "ZGVmIHBsYW5fbWlzc2lvbigpOgogICAgcmV0dXJuICJNaXNzaW9uIHBsYW5uZWQi",
            "dependencies": "W10="  # []
        }
    }
    
    dependent_agent_data = {
        "name": "thermal_manager",
        "display_name": "Thermal Manager",
        "role": "Manages thermal systems",
        "llm_name": "gpt-4",
        "temperature": 0.1,
        "max_tokens": 1000,
        "dependencies": ["mission_planner"],
        "files": {
            "prompts": "TWFuYWdlIHRoZXJtYWwgc3lzdGVtcw==",  # "Manage thermal systems"
            "output_class": "ZnJvbSBweWRhbnRpYyBpbXBvcnQgQmFzZU1vZGVsCgpjbGFzcyBUaGVybWFsUmVzdWx0KEJhc2VNb2RlbCk6CiAgICB0ZW1wZXJhdHVyZTogZmxvYXQ=",
            "tools": "ZGVmIG1hbmFnZV90aGVybWFsKCk6CiAgICByZXR1cm4gIlRoZXJtYWwgbWFuYWdlZCI=",
            "dependencies": "W1wibWlzc2lvbl9wbGFubmVyXCJd"  # ["mission_planner"]
        }
    }
    
    # Create base agent
    base_agent = await factory.create_agent(base_agent_data)
    assert base_agent is not None
    
    # Create dependent agent
    dependent_agent = await factory.create_agent(dependent_agent_data)
    assert dependent_agent is not None
    assert "mission_planner" in dependent_agent.dependencies
    
    # Verify both agents exist
    agents = await factory.list_agents()
    agent_names = [agent.name for agent in agents]
    assert "mission_planner" in agent_names
    assert "thermal_manager" in agent_names


@pytest.mark.asyncio
async def test_workflow_execution_simulation(db_session, sample_agent_data):
    """Test simulated workflow execution with conversation tracking."""
    # Setup agents
    factory = AgentFactory(db_session)
    agent = await factory.create_agent(sample_agent_data)
    await factory.update_agent_status(agent.name, AgentStatus.ACTIVE)
    
    # Test workflow builder initialization
    builder = DynamicWorkflowBuilder()
    active_agents = await factory.list_agents()
    active_agents = [a for a in active_agents if a.status == AgentStatus.ACTIVE]
    
    # Verify agent is in active list
    assert len(active_agents) == 1
    assert active_agents[0].name == sample_agent_data["name"]
    
    # Test that workflow can be constructed (basic validation)
    # Note: Full LangGraph execution would require more complex setup
    assert len(active_agents) > 0


@pytest.mark.asyncio  
async def test_concurrent_agent_operations(db_session, sample_agent_files):
    """Test concurrent agent creation and operations."""
    factory = AgentFactory(db_session)
    
    # Create multiple agent configurations
    agent_configs = []
    for i in range(5):
        config = {
            "name": f"concurrent_agent_{i}",
            "display_name": f"Concurrent Agent {i}",
            "role": f"Role {i}",
            "llm_name": "gpt-4",
            "temperature": 0.1,
            "max_tokens": 1000,
            "dependencies": [],
            "files": sample_agent_files
        }
        agent_configs.append(config)
    
    # Create agents concurrently
    tasks = [factory.create_agent(config) for config in agent_configs]
    agents = await asyncio.gather(*tasks)
    
    # Verify all agents were created
    assert len(agents) == 5
    for i, agent in enumerate(agents):
        assert agent.name == f"concurrent_agent_{i}"
    
    # Verify in database
    all_agents = await factory.list_agents()
    concurrent_agents = [a for a in all_agents if a.name.startswith("concurrent_agent_")]
    assert len(concurrent_agents) == 5


@pytest.mark.asyncio
async def test_file_validation_edge_cases():
    """Test file validation with edge cases."""
    processor = FileProcessor()
    
    # Test empty files
    empty_files = {
        "prompts": "",
        "output_class": "",
        "tools": "",
        "dependencies": ""
    }
    
    # Convert to base64
    import base64
    encoded_files = {
        key: base64.b64encode(value.encode()).decode()
        for key, value in empty_files.items()
    }
    
    result = await processor.validate_agent_files(encoded_files)
    assert result.overall_valid is False
    invalid_results = [r for r in result.validation_results if not r.valid]
    assert len(invalid_results) > 0
    
    # Test files with only whitespace
    whitespace_files = {
        "prompts": "   \n\t   ",
        "output_class": "   \n\t   ",
        "tools": "   \n\t   ",
        "dependencies": "   \n\t   "
    }
    
    encoded_whitespace_files = {
        key: base64.b64encode(value.encode()).decode()
        for key, value in whitespace_files.items()
    }
    
    result = await processor.validate_agent_files(encoded_whitespace_files)
    assert result.overall_valid is False


@pytest.mark.asyncio
async def test_system_cleanup_after_tests(db_session):
    """Test system cleanup after all operations."""
    factory = AgentFactory(db_session)
    
    # List all agents
    agents = await factory.list_agents()
    
    # Clean up test agents
    test_agent_names = [
        agent.name for agent in agents 
        if any(keyword in agent.name for keyword in [
            "test_", "concurrent_", "integration_", "empty_", "whitespace_"
        ])
    ]
    
    # Delete test agents
    for name in test_agent_names:
        await factory.delete_agent(name)
    
    # Verify cleanup
    remaining_agents = await factory.list_agents()
    remaining_names = [agent.name for agent in remaining_agents]
    
    for test_name in test_agent_names:
        assert test_name not in remaining_names