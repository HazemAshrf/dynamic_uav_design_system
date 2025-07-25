"""Configuration Synchronization Service

Handles syncing between config.json files and database records.
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime

from backend.core.config import settings
from backend.models.agent import Agent


class ConfigSynchronizer:
    """Synchronizes config.json files with database records."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.agents_dir = Path(settings.upload_dir)
    
    async def sync_config_to_database(self, agent_name: str) -> Dict[str, Any]:
        """Sync a single agent's config.json to database."""
        try:
            config_path = self.agents_dir / agent_name / "config.json"
            
            if not config_path.exists():
                return {
                    "success": False,
                    "error": f"Config file not found: {config_path}"
                }
            
            # Load config.json
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            # Get agent from database
            result = await self.db.execute(
                select(Agent).where(Agent.name == agent_name)
            )
            agent = result.scalar_one_or_none()
            
            if not agent:
                return {
                    "success": False,
                    "error": f"Agent {agent_name} not found in database"
                }
            
            # Update agent with config values
            updates = {}
            if "display_name" in config_data:
                updates["display_name"] = config_data["display_name"]
            if "role" in config_data:
                updates["role"] = config_data["role"]
            if "llm_name" in config_data:
                updates["llm_name"] = config_data["llm_name"]
            if "temperature" in config_data:
                updates["temperature"] = float(config_data["temperature"])
            if "max_tokens" in config_data:
                updates["max_tokens"] = int(config_data["max_tokens"])
            if "dependencies" in config_data:
                updates["dependencies"] = config_data["dependencies"]
            
            if updates:
                updates["updated_at"] = datetime.utcnow()
                
                await self.db.execute(
                    update(Agent)
                    .where(Agent.name == agent_name)
                    .values(**updates)
                )
                await self.db.commit()
            
            return {
                "success": True,
                "agent_name": agent_name,
                "updates_applied": updates,
                "config_path": str(config_path)
            }
            
        except Exception as e:
            await self.db.rollback()
            return {
                "success": False,
                "error": f"Failed to sync config for {agent_name}: {str(e)}"
            }
    
    async def sync_all_configs_to_database(self) -> Dict[str, Any]:
        """Sync all agent config.json files to database."""
        results = []
        
        if not self.agents_dir.exists():
            return {
                "success": False,
                "error": f"Agents directory not found: {self.agents_dir}"
            }
        
        for agent_dir in self.agents_dir.iterdir():
            if agent_dir.is_dir():
                agent_name = agent_dir.name
                result = await self.sync_config_to_database(agent_name)
                results.append(result)
        
        successful = [r for r in results if r.get("success")]
        failed = [r for r in results if not r.get("success")]
        
        return {
            "success": len(failed) == 0,
            "total_agents": len(results),
            "successful_syncs": len(successful),
            "failed_syncs": len(failed),
            "results": results
        }
    
    async def detect_config_changes(self) -> List[Dict[str, Any]]:
        """Detect differences between config.json files and database."""
        changes = []
        
        if not self.agents_dir.exists():
            return changes
        
        for agent_dir in self.agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
                
            agent_name = agent_dir.name
            config_path = agent_dir / "config.json"
            
            if not config_path.exists():
                continue
            
            try:
                # Load config.json
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                
                # Get agent from database
                result = await self.db.execute(
                    select(Agent).where(Agent.name == agent_name)
                )
                agent = result.scalar_one_or_none()
                
                if not agent:
                    changes.append({
                        "agent_name": agent_name,
                        "type": "agent_not_in_database",
                        "config_path": str(config_path)
                    })
                    continue
                
                # Compare values
                differences = {}
                
                if config_data.get("display_name") != agent.display_name:
                    differences["display_name"] = {
                        "config": config_data.get("display_name"),
                        "database": agent.display_name
                    }
                
                if config_data.get("role") != agent.role:
                    differences["role"] = {
                        "config": config_data.get("role"),
                        "database": agent.role
                    }
                
                if config_data.get("llm_name") != agent.llm_name:
                    differences["llm_name"] = {
                        "config": config_data.get("llm_name"),
                        "database": agent.llm_name
                    }
                
                if config_data.get("temperature") != agent.temperature:
                    differences["temperature"] = {
                        "config": config_data.get("temperature"),
                        "database": agent.temperature
                    }
                
                if config_data.get("max_tokens") != agent.max_tokens:
                    differences["max_tokens"] = {
                        "config": config_data.get("max_tokens"),
                        "database": agent.max_tokens
                    }
                
                if config_data.get("dependencies", []) != (agent.dependencies or []):
                    differences["dependencies"] = {
                        "config": config_data.get("dependencies", []),
                        "database": agent.dependencies or []
                    }
                
                if differences:
                    changes.append({
                        "agent_name": agent_name,
                        "type": "configuration_drift",
                        "differences": differences,
                        "config_path": str(config_path)
                    })
                    
            except Exception as e:
                changes.append({
                    "agent_name": agent_name,
                    "type": "error",
                    "error": str(e),
                    "config_path": str(config_path)
                })
        
        return changes