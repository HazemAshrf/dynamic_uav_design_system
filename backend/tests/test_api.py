"""Test API endpoints."""

import pytest
import json
from httpx import AsyncClient
from fastapi.testclient import TestClient

from backend.main import app
from backend.core.database import get_db
from backend.models.agent import AgentStatus


@pytest.mark.asyncio
async def test_api_health_check():
    """Test API health check endpoint."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/v1/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data


@pytest.mark.asyncio
async def test_create_agent_success(sample_agent_data):
    """Test successful agent creation via API."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/agents/",
            json=sample_agent_data
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == sample_agent_data["name"]
        assert data["display_name"] == sample_agent_data["display_name"]
        assert data["status"] == "inactive"


@pytest.mark.asyncio  
async def test_create_agent_invalid_data():
    """Test agent creation with invalid data."""
    invalid_data = {
        "name": "",  # Empty name
        "display_name": "Test Agent",
        "role": "Test role"
        # Missing required fields
    }
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/agents/",
            json=invalid_data
        )
        
        assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_list_agents():
    """Test listing agents via API."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/v1/agents/")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_agent_by_name(sample_agent_data):
    """Test retrieving specific agent by name."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Create agent first
        create_response = await client.post(
            "/api/v1/agents/",
            json=sample_agent_data
        )
        assert create_response.status_code == 201
        
        # Get agent by name
        response = await client.get(f"/api/v1/agents/{sample_agent_data['name']}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == sample_agent_data["name"]


@pytest.mark.asyncio
async def test_get_nonexistent_agent():
    """Test retrieving non-existent agent."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/v1/agents/nonexistent_agent")
        
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_agent_status(sample_agent_data):
    """Test updating agent status via API."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Create agent first
        create_response = await client.post(
            "/api/v1/agents/",
            json=sample_agent_data
        )
        assert create_response.status_code == 201
        
        # Update status
        update_data = {"status": "active"}
        response = await client.patch(
            f"/api/v1/agents/{sample_agent_data['name']}/status",
            json=update_data
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "active"


@pytest.mark.asyncio
async def test_delete_agent(sample_agent_data):
    """Test deleting agent via API."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Create agent first
        create_response = await client.post(
            "/api/v1/agents/",
            json=sample_agent_data
        )
        assert create_response.status_code == 201
        
        # Delete agent
        response = await client.delete(f"/api/v1/agents/{sample_agent_data['name']}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Agent deleted successfully"
        
        # Verify deletion
        get_response = await client.get(f"/api/v1/agents/{sample_agent_data['name']}")
        assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_validate_files_success(sample_agent_files):
    """Test file validation endpoint with valid files."""
    validation_data = {
        "agent_name": "test_validation",
        "files": sample_agent_files
    }
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/agents/validate-files",
            json=validation_data
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert len(data["validation_errors"]) == 0


@pytest.mark.asyncio
async def test_validate_files_failure():
    """Test file validation endpoint with invalid files."""
    import base64
    
    invalid_files = {
        "prompts": base64.b64encode(b"").decode(),  # Empty
        "output_class": base64.b64encode(b"invalid syntax (((").decode(),
        "tools": base64.b64encode(b"import os; os.system('rm -rf')").decode(),
        "dependencies": base64.b64encode(b"invalid json [[[").decode()
    }
    
    validation_data = {
        "agent_name": "invalid_test",
        "files": invalid_files
    }
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/agents/validate-files",
            json=validation_data
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert len(data["validation_errors"]) > 0


@pytest.mark.asyncio
async def test_workflow_endpoints():
    """Test workflow management endpoints."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Test workflow creation
        workflow_data = {
            "name": "test_workflow",
            "requirements": "Test workflow requirements",
            "active_agents": ["agent1", "agent2"]
        }
        
        response = await client.post("/api/v1/workflows/", json=workflow_data)
        assert response.status_code == 201
        
        workflow = response.json()
        workflow_id = workflow["id"]
        
        # Test workflow retrieval
        response = await client.get(f"/api/v1/workflows/{workflow_id}")
        assert response.status_code == 200
        
        # Test workflow status update
        status_data = {"status": "running"}
        response = await client.patch(
            f"/api/v1/workflows/{workflow_id}/status",
            json=status_data
        )
        assert response.status_code == 200
        
        # Test workflow list
        response = await client.get("/api/v1/workflows/")
        assert response.status_code == 200
        assert len(response.json()) >= 1


@pytest.mark.asyncio
async def test_conversation_endpoints():
    """Test conversation management endpoints."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Create conversation
        conversation_data = {
            "title": "Test Conversation",
            "participants": ["agent1", "agent2"]
        }
        
        response = await client.post("/api/v1/conversations/", json=conversation_data)
        assert response.status_code == 201
        
        conversation = response.json()
        conversation_id = conversation["id"]
        
        # Add message to conversation
        message_data = {
            "sender": "agent1",
            "receiver": "agent2",
            "content": "Test message",
            "message_type": "agent_to_agent"
        }
        
        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json=message_data
        )
        assert response.status_code == 201
        
        # Get conversation with messages
        response = await client.get(f"/api/v1/conversations/{conversation_id}")
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["messages"]) == 1
        assert data["messages"][0]["content"] == "Test message"


@pytest.mark.asyncio
async def test_cors_headers():
    """Test that CORS headers are properly set."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.options("/api/v1/agents/")
        
        assert "access-control-allow-origin" in response.headers
        assert "access-control-allow-methods" in response.headers


@pytest.mark.asyncio
async def test_error_handling():
    """Test API error handling."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Test 404 error
        response = await client.get("/api/v1/nonexistent-endpoint")
        assert response.status_code == 404
        
        # Test validation error
        response = await client.post("/api/v1/agents/", json={})
        assert response.status_code == 422
        
        data = response.json()
        assert "detail" in data