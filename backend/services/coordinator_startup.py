"""Coordinator startup service to automatically create coordinator agent."""

import os
import base64
from pathlib import Path
from typing import Dict, Any
import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent import Agent, AgentStatus
from backend.services.agent_factory import AgentFactory
from backend.core.database import get_db
from sqlalchemy import select

logger = logging.getLogger(__name__)


class CoordinatorStartupService:
    """Service to automatically create and activate coordinator agent on system startup."""
    
    def __init__(self):
        self.agent_factory = AgentFactory()
        self.templates_path = Path("/home/hazem/Projects/uav_full/agent_templates/coordinator")
    
    async def ensure_coordinator_exists(self) -> bool:
        """Ensure coordinator agent exists and is active."""
        try:
            async for db in get_db():
                # Check if coordinator already exists
                coordinator = await self._get_coordinator(db)
                
                if coordinator:
                    logger.info("Coordinator agent already exists")
                    if coordinator.status != AgentStatus.INACTIVE:
                        # Set coordinator to inactive (ready state)
                        coordinator.status = AgentStatus.INACTIVE
                        await db.commit()
                        logger.info("Set existing coordinator agent to INACTIVE status")
                    return True
                
                # Create new coordinator
                coordinator_data = await self._prepare_coordinator_data()
                
                if not coordinator_data:
                    logger.error("Failed to prepare coordinator data")
                    return False
                
                # Create coordinator agent using factory
                agent_config = await self.agent_factory.create_agent(
                    agent_name=coordinator_data["name"],
                    display_name=coordinator_data["display_name"],
                    role=coordinator_data["role"],
                    llm_name=coordinator_data["llm_name"],
                    temperature=coordinator_data["temperature"],
                    dependencies=coordinator_data["dependencies"],
                    files=coordinator_data["files"]
                )
                
                # Create database record
                new_coordinator = Agent(
                    name=coordinator_data["name"],
                    display_name=coordinator_data["display_name"],
                    role=coordinator_data["role"],
                    llm_name=coordinator_data["llm_name"],
                    temperature=coordinator_data["temperature"],
                    max_tokens=coordinator_data.get("max_tokens", 4000),
                    dependencies=coordinator_data["dependencies"],
                    status=AgentStatus.INACTIVE,  # Will be activated below
                    prompts_file_path=agent_config.get('prompts_file_path'),
                    output_class_file_path=agent_config.get('output_class_file_path'),
                    tools_file_path=agent_config.get('tools_file_path'),
                    generated_class_path=agent_config.get('generated_class_path'),
                    generated_model_path=agent_config.get('generated_model_path'),
                    config_data=agent_config
                )
                
                db.add(new_coordinator)
                await db.commit()
                await db.refresh(new_coordinator)
                
                if new_coordinator:
                    # Coordinator is already INACTIVE (ready state) from creation
                    logger.info(f"Created coordinator agent with INACTIVE status: {new_coordinator.id}")
                    return True
                else:
                    logger.error("Failed to create coordinator agent")
                    return False
                    
        except Exception as e:
            logger.error(f"Error ensuring coordinator exists: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False
    
    async def _get_coordinator(self, db: AsyncSession) -> Agent:
        """Get existing coordinator agent."""
        result = await db.execute(
            select(Agent).where(Agent.name == 'coordinator')
        )
        return result.scalars().first()
    
    async def _prepare_coordinator_data(self) -> Dict[str, Any]:
        """Prepare coordinator agent data from templates."""
        try:
            # Read template files
            files = {}
            
            # Read prompts file
            prompts_file = self.templates_path / "prompts.py"
            if prompts_file.exists():
                with open(prompts_file, 'r') as f:
                    files['prompts'] = base64.b64encode(f.read().encode()).decode()
            
            # Read output class file
            output_class_file = self.templates_path / "output_class.py"
            if output_class_file.exists():
                with open(output_class_file, 'r') as f:
                    files['output_class'] = base64.b64encode(f.read().encode()).decode()
            
            # Read tools file
            tools_file = self.templates_path / "tools.py"
            if tools_file.exists():
                with open(tools_file, 'r') as f:
                    files['tools'] = base64.b64encode(f.read().encode()).decode()
            
            # Read dependencies file
            deps_file = self.templates_path / "dependencies.json"
            if deps_file.exists():
                with open(deps_file, 'r') as f:
                    files['dependencies'] = base64.b64encode(f.read().encode()).decode()
            
            if len(files) < 4:
                logger.error(f"Missing coordinator template files. Found: {list(files.keys())}")
                return None
            
            # Create coordinator data
            coordinator_data = {
                "name": "coordinator",
                "display_name": "Dynamic Coordinator",
                "role": "Manages and coordinates the UAV design workflow, adapting to available agents",
                "llm_name": "gpt-4",
                "temperature": 0.1,
                "max_tokens": 4000,
                "dependencies": [],  # Coordinator has no dependencies
                "files": files
            }
            
            return coordinator_data
            
        except Exception as e:
            logger.error(f"Error preparing coordinator data: {str(e)}")
            return None
    
    async def get_available_agents(self, db: AsyncSession) -> list:
        """Get list of available (inactive/ready) agents excluding coordinator."""
        result = await db.execute(
            select(Agent.name).where(
                Agent.status == AgentStatus.INACTIVE,
                Agent.name != 'coordinator'
            )
        )
        return [row[0] for row in result.fetchall()]


# Global startup service instance
coordinator_startup = CoordinatorStartupService()