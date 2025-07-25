"""Test configuration and fixtures."""

import pytest
import asyncio
import tempfile
import os
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from backend.core.database import Base
from backend.core.config import settings


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def test_db():
    """Create a temporary test database."""
    # Create temporary database file
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(db_fd)
    
    # Create test database URL
    test_db_url = f"sqlite+aiosqlite:///{db_path}"
    
    # Create engine and tables
    engine = create_async_engine(test_db_url)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Create session factory
    TestSessionLocal = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    yield TestSessionLocal
    
    # Cleanup
    await engine.dispose()
    os.unlink(db_path)


@pytest.fixture
async def db_session(test_db):
    """Create a database session for testing."""
    session_factory = test_db
    async with session_factory() as session:
        yield session


@pytest.fixture
def sample_agent_files():
    """Sample agent files for testing."""
    import base64
    
    prompts_content = """You are a test agent for system validation.
    
Your role is to process test inputs and provide structured outputs.
You have access to test tools and should use them appropriately.
Always provide clear, accurate responses based on the given context."""

    output_class_content = """from pydantic import BaseModel, Field
from typing import List, Optional

class TestAgentOutput(BaseModel):
    \"\"\"Test agent output model.\"\"\"
    result: str = Field(description="Processing result")
    confidence: float = Field(description="Confidence score", ge=0.0, le=1.0)
    errors: List[str] = Field(default=[], description="Any errors encountered")
    metadata: Optional[dict] = Field(default=None, description="Additional metadata")
    iteration: int = Field(description="Current iteration number")"""

    tools_content = """from langchain_core.tools import tool
from typing import Dict, Any

@tool
def test_calculation_tool(input_value: float) -> Dict[str, Any]:
    \"\"\"A simple calculation tool for testing.\"\"\"
    result = input_value * 2 + 10
    return {
        "input": input_value,
        "output": result,
        "operation": "multiply by 2 and add 10"
    }

@tool  
def test_validation_tool(data: str) -> Dict[str, Any]:
    \"\"\"A validation tool for testing.\"\"\"
    is_valid = len(data) > 0 and data.isalnum()
    return {
        "data": data,
        "is_valid": is_valid,
        "length": len(data)
    }"""

    dependencies_content = '["mission_planner"]'
    
    return {
        "prompts": base64.b64encode(prompts_content.encode()).decode(),
        "output_class": base64.b64encode(output_class_content.encode()).decode(),
        "tools": base64.b64encode(tools_content.encode()).decode(),
        "dependencies": base64.b64encode(dependencies_content.encode()).decode()
    }


@pytest.fixture
def sample_agent_data(sample_agent_files):
    """Complete agent data for testing."""
    return {
        "name": "test_agent",
        "display_name": "Test Agent",
        "role": "A test agent for system validation",
        "llm_name": "gpt-4",
        "temperature": 0.1,
        "max_tokens": 1000,
        "dependencies": ["mission_planner"],
        "files": sample_agent_files
    }