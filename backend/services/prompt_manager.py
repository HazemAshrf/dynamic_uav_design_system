"""Dynamic Prompt Management Service"""

import asyncio
from typing import Dict, List, Any, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from backend.models.agent import Agent, AgentStatus
from backend.templates.coordinator_templates import (
    get_coordinator_no_agents_prompt,
    get_coordinator_with_agents_prompt
)
from backend.templates.agent_templates import generate_complete_agent_prompt
from backend.services.template_validator import TemplateValidator, ValidationResult


class PromptManager:
    """Manages dynamic prompt generation for agents and coordinator."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.validator = TemplateValidator()
        
    async def get_current_agents(self, exclude_agent: str = None) -> List[Dict[str, Any]]:
        """Get current agents in the system."""
        query = select(Agent).where(Agent.status.in_([AgentStatus.INACTIVE, AgentStatus.RUNNING]))
        
        if exclude_agent:
            query = query.where(Agent.name != exclude_agent)
            
        result = await self.db.execute(query)
        agents = result.scalars().all()
        
        return [
            {
                "name": agent.name,
                "role": agent.role,
                "dependencies": agent.dependencies or [],
                "id": agent.id
            }
            for agent in agents
        ]
    
    async def generate_coordinator_prompt(self) -> Tuple[str, ValidationResult]:
        """Generate dynamic coordinator prompt based on available agents."""
        
        current_agents = await self.get_current_agents()
        
        if not current_agents:
            # No agents available - use planning mode
            prompt = get_coordinator_no_agents_prompt()
            validation = self.validator.validate_prompt(prompt, "coordinator")
        else:
            # Agents available - use coordination mode
            prompt = get_coordinator_with_agents_prompt(current_agents)
            validation = self.validator.validate_prompt(prompt, "coordinator")
            
            # Additional validation for agent references
            agent_names = [agent["name"] for agent in current_agents]
            agent_validation = self.validator.validate_agent_references(prompt, agent_names)
            
            # Merge validation results
            validation.errors.extend(agent_validation.errors)
            validation.warnings.extend(agent_validation.warnings)
            validation.is_valid = validation.is_valid and agent_validation.is_valid
            
            # Validate coordinator output schema
            schema_validation = self.validator.validate_coordinator_output_schema(prompt)
            validation.errors.extend(schema_validation.errors)
            validation.warnings.extend(schema_validation.warnings)
            validation.is_valid = validation.is_valid and schema_validation.is_valid
        
        return prompt, validation
    
    async def generate_agent_prompt(
        self, 
        agent_name: str, 
        agent_role: str, 
        dependencies: List[str] = None,
        project_context: str = None
    ) -> Tuple[str, ValidationResult]:
        """Generate dynamic agent prompt with awareness of other agents."""
        
        # Get other agents in the system (excluding this one)
        other_agents = await self.get_current_agents(exclude_agent=agent_name)
        
        # Generate the prompt
        prompt = generate_complete_agent_prompt(
            agent_name=agent_name,
            agent_role=agent_role,
            other_agents=other_agents,
            dependencies=dependencies or [],
            project_context=project_context
        )
        
        # Validate the prompt
        validation = self.validator.validate_prompt(prompt, "agent")
        
        # Additional validation for agent references
        other_agent_names = [agent["name"] for agent in other_agents]
        agent_validation = self.validator.validate_agent_references(prompt, other_agent_names)
        
        # Merge validation results
        validation.errors.extend(agent_validation.errors)
        validation.warnings.extend(agent_validation.warnings)
        validation.is_valid = validation.is_valid and agent_validation.is_valid
        
        return prompt, validation
    
    async def update_agent_prompt(
        self, 
        agent_id: int, 
        new_prompt: str = None
    ) -> Tuple[bool, ValidationResult]:
        """Update an agent's prompt (regenerate if new_prompt is None)."""
        
        # Get the agent
        result = await self.db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        
        if not agent:
            validation = ValidationResult(
                is_valid=False,
                errors=["Agent not found"],
                warnings=[],
                word_count=0,
                line_count=0
            )
            return False, validation
        
        if new_prompt is None:
            # Regenerate prompt dynamically
            new_prompt, validation = await self.generate_agent_prompt(
                agent_name=agent.name,
                agent_role=agent.role,
                dependencies=agent.dependencies,
                project_context=None  # Could be enhanced with project context
            )
        else:
            # Validate provided prompt
            validation = self.validator.validate_prompt(new_prompt, "agent")
        
        if validation.is_valid:
            # Update the agent's prompt file
            # Note: This would need to write to the agent's prompts file
            # For now, we'll update the database record
            try:
                # In a real implementation, you'd write to the prompts file
                # Here we could store in config_data as a fallback
                config_data = agent.config_data or {}
                config_data["generated_prompt"] = new_prompt
                config_data["prompt_generated_at"] = asyncio.get_event_loop().time()
                
                await self.db.execute(
                    update(Agent)
                    .where(Agent.id == agent_id)
                    .values(config_data=config_data)
                )
                await self.db.commit()
                
                return True, validation
                
            except Exception as e:
                validation.errors.append(f"Failed to update agent prompt: {str(e)}")
                validation.is_valid = False
                return False, validation
        
        return False, validation
    
    async def update_all_agent_prompts(self) -> Dict[str, Tuple[bool, ValidationResult]]:
        """Update prompts for all agents to reflect current system state."""
        
        agents = await self.get_current_agents()
        results = {}
        
        for agent_data in agents:
            agent_name = agent_data["name"]
            try:
                success, validation = await self.update_agent_prompt(agent_data["id"])
                results[agent_name] = (success, validation)
            except Exception as e:
                validation = ValidationResult(
                    is_valid=False,
                    errors=[f"Error updating {agent_name}: {str(e)}"],
                    warnings=[],
                    word_count=0,
                    line_count=0
                )
                results[agent_name] = (False, validation)
        
        return results
    
    async def cascade_update_on_agent_addition(self, new_agent_id: int) -> Dict[str, Any]:
        """Handle prompt updates when a new agent is added."""
        
        # Get the new agent
        result = await self.db.execute(select(Agent).where(Agent.id == new_agent_id))
        new_agent = result.scalar_one_or_none()
        
        if not new_agent:
            return {"success": False, "error": "New agent not found"}
        
        # Update the new agent's prompt
        new_agent_success, new_agent_validation = await self.update_agent_prompt(new_agent_id)
        
        # Update all existing agents' prompts to include the new agent
        existing_updates = await self.update_all_agent_prompts()
        
        # Generate new coordinator prompt
        coordinator_prompt, coordinator_validation = await self.generate_coordinator_prompt()
        
        return {
            "success": new_agent_success and all(result[0] for result in existing_updates.values()),
            "new_agent": {
                "success": new_agent_success,
                "validation": new_agent_validation
            },
            "existing_agents": existing_updates,
            "coordinator": {
                "prompt": coordinator_prompt,
                "validation": coordinator_validation
            },
            "summary": {
                "total_agents_updated": len(existing_updates) + 1,
                "successful_updates": sum(1 for result in existing_updates.values() if result[0]) + (1 if new_agent_success else 0),
                "coordinator_valid": coordinator_validation.is_valid
            }
        }
    
    async def cascade_update_on_agent_removal(self, removed_agent_name: str) -> Dict[str, Any]:
        """Handle prompt updates when an agent is removed."""
        
        # Update all remaining agents' prompts
        remaining_updates = await self.update_all_agent_prompts()
        
        # Generate new coordinator prompt
        coordinator_prompt, coordinator_validation = await self.generate_coordinator_prompt()
        
        return {
            "success": all(result[0] for result in remaining_updates.values()),
            "removed_agent": removed_agent_name,
            "remaining_agents": remaining_updates,
            "coordinator": {
                "prompt": coordinator_prompt,
                "validation": coordinator_validation
            },
            "summary": {
                "total_agents_updated": len(remaining_updates),
                "successful_updates": sum(1 for result in remaining_updates.values() if result[0]),
                "coordinator_valid": coordinator_validation.is_valid
            }
        }
    
    async def cascade_update_on_agent_modification(self, modified_agent_name: str) -> Dict[str, Any]:
        """Handle prompt updates when an agent is modified."""
        
        # Update all agents' prompts (including the modified one)
        all_updates = await self.update_all_agent_prompts()
        
        # Generate new coordinator prompt
        coordinator_prompt, coordinator_validation = await self.generate_coordinator_prompt()
        
        return {
            "success": all(result[0] for result in all_updates.values()),
            "modified_agent": modified_agent_name,
            "updated_agents": all_updates,
            "coordinator": {
                "prompt": coordinator_prompt,
                "validation": coordinator_validation
            },
            "summary": {
                "total_agents_updated": len(all_updates),
                "successful_updates": sum(1 for result in all_updates.values() if result[0]),
                "coordinator_valid": coordinator_validation.is_valid
            }
        }
    
    async def get_validation_report(self) -> Dict[str, Any]:
        """Get comprehensive validation report for all prompts."""
        
        # Get coordinator prompt
        coordinator_prompt, coordinator_validation = await self.generate_coordinator_prompt()
        
        # Get all agent prompts
        agents = await self.get_current_agents()
        agent_validations = {}
        
        for agent_data in agents:
            agent_prompt, agent_validation = await self.generate_agent_prompt(
                agent_name=agent_data["name"],
                agent_role=agent_data["role"],
                dependencies=agent_data["dependencies"]
            )
            agent_validations[agent_data["name"]] = agent_validation
        
        # Compile report
        all_validations = {"coordinator": coordinator_validation, **agent_validations}
        summary = self.validator.get_validation_summary(all_validations)
        
        return {
            "coordinator_validation": coordinator_validation,
            "agent_validations": agent_validations,
            "summary": summary,
            "total_prompts": len(all_validations),
            "valid_prompts": sum(1 for v in all_validations.values() if v.is_valid),
            "total_errors": sum(len(v.errors) for v in all_validations.values()),
            "total_warnings": sum(len(v.warnings) for v in all_validations.values())
        }