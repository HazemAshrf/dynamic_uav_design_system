"""Agent management API endpoints."""

from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.api.deps import get_db
from backend.models.agent import Agent, AgentStatus
from backend.schemas.agent import (
    AgentCreate, AgentUpdate, AgentResponse, 
    AgentDetailResponse, AgentValidationResult
)
from backend.schemas.upload import FileValidationRequest, FileValidationResponse
from backend.services.agent_factory import AgentFactory
from backend.services.file_processor import FileProcessor
from backend.services.langgraph_service import LangGraphService
from backend.services.dependency_manager import DependencyManager
from backend.services.agent_lifecycle_manager import AgentLifecycleManager
from backend.services.config_sync import ConfigSynchronizer

router = APIRouter()


async def _check_agents_not_running(db: AsyncSession):
    """Helper function to check if agents are running and block operations if they are."""
    langgraph_service = LangGraphService(db)
    if await langgraph_service.are_agents_running():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot perform agent operations while workflow is running. Please stop the workflow first."
        )


@router.get("/", response_model=List[AgentResponse])
async def get_agents(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    status_filter: AgentStatus = None
) -> Any:
    """Get all agents."""
    
    query = select(Agent)
    
    if status_filter:
        query = query.where(Agent.status == status_filter)
    
    query = query.offset(skip).limit(limit).order_by(Agent.created_at.desc())
    
    result = await db.execute(query)
    agents = result.scalars().all()
    
    return agents


@router.post("/", response_model=AgentResponse)
async def create_agent(
    *,
    db: AsyncSession = Depends(get_db),
    agent_in: AgentCreate
) -> Any:
    """Create a new dynamic agent using atomic operations."""
    
    # Block if agents are currently running
    await _check_agents_not_running(db)
    
    # Check if agent name already exists
    result = await db.execute(
        select(Agent).where(Agent.name == agent_in.name)
    )
    existing_agent = result.scalar_one_or_none()
    
    if existing_agent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Agent with name '{agent_in.name}' already exists"
        )
    
    try:
        # Use atomic agent lifecycle manager
        lifecycle_manager = AgentLifecycleManager(db)
        success, result = await lifecycle_manager.create_agent_atomically(agent_in)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("error", "Failed to create agent")
            )
        
        # Get the created agent from database
        db_result = await db.execute(
            select(Agent).where(Agent.name == agent_in.name)
        )
        agent = db_result.scalar_one_or_none()
        
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Agent was created but could not be retrieved"
            )
        
        return agent
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create agent: {str(e)}"
        )


@router.post("/sync-configs")
async def sync_all_agent_configs(
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Sync all agent config.json files to database."""
    
    try:
        config_sync = ConfigSynchronizer(db)
        result = await config_sync.sync_all_configs_to_database()
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync configs: {str(e)}"
        )


@router.get("/config-drift")
async def detect_config_drift(
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Detect differences between config.json files and database."""
    
    try:
        config_sync = ConfigSynchronizer(db)
        changes = await config_sync.detect_config_changes()
        
        return {
            "drift_detected": len(changes) > 0,
            "total_agents_checked": len([c for c in changes if c.get("type") != "error"]),
            "agents_with_drift": len([c for c in changes if c.get("type") == "configuration_drift"]),
            "changes": changes
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to detect config drift: {str(e)}"
        )


@router.get("/{agent_id}", response_model=AgentDetailResponse)
async def get_agent(
    agent_id: int,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Get agent by ID with detailed information."""
    
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    
    # Load file contents
    file_processor = FileProcessor()
    files = await file_processor.load_agent_files(agent.name)
    
    # Create detailed response
    agent_detail = AgentDetailResponse(
        id=agent.id,
        name=agent.name,
        display_name=agent.display_name,
        role=agent.role,
        llm_name=agent.llm_name,
        temperature=agent.temperature,
        max_tokens=agent.max_tokens,
        dependencies=agent.dependencies,
        status=agent.status,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        last_executed_at=agent.last_executed_at,
        prompts_content=files.get('prompts'),
        output_class_content=files.get('output_class'),
        tools_content=files.get('tools'),
        config_data=agent.config_data,
        validation_result=agent.validation_result,
        execution_stats=agent.execution_stats
    )
    
    return agent_detail


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    *,
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    agent_in: AgentUpdate
) -> Any:
    """Update existing agent using atomic operations."""
    
    # Block if agents are currently running
    await _check_agents_not_running(db)
    
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    
    # COORDINATOR PROTECTION: Ensure coordinator always has empty dependencies
    if agent.name.lower() == "coordinator" and agent_in.dependencies is not None and len(agent_in.dependencies) > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The coordinator agent cannot have dependencies. It must coordinate all other agents independently."
        )
    
    try:
        # Use atomic agent lifecycle manager
        lifecycle_manager = AgentLifecycleManager(db)
        success, result = await lifecycle_manager.update_agent_atomically(agent_id, agent_in)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("error", "Failed to update agent")
            )
        
        # Refresh agent from database
        await db.refresh(agent)
        return agent
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update agent: {str(e)}"
        )


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: int,
    force_cascade: bool = False,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Delete agent using atomic operations with dependency validation."""
    
    # Block if agents are currently running
    await _check_agents_not_running(db)
    
    # Get agent information
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    
    # COORDINATOR PROTECTION: Prevent coordinator deletion
    if agent.name.lower() == "coordinator":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the coordinator agent. The coordinator is required for system operation and cannot be removed."
        )
    
    try:
        # Check deletion feasibility first if not forcing cascade
        if not force_cascade:
            dependency_manager = DependencyManager(db)
            deletion_plan = await dependency_manager.analyze_deletion_impact(agent.name)
            
            if not deletion_plan.can_delete_safely:
                # Return deletion plan for user decision
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": f"Cannot delete agent '{agent.name}': has dependent agents",
                        "dependent_agents": deletion_plan.dependent_agents,
                        "cascade_deletion_required": True,
                        "affected_agents": deletion_plan.deletion_order,
                        "message": "Use force_cascade=true to delete all dependent agents, or remove dependencies first"
                    }
                )
        
        # Use atomic agent lifecycle manager
        lifecycle_manager = AgentLifecycleManager(db)
        success, result = await lifecycle_manager.delete_agent_atomically(agent.name, force_cascade)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("error", "Failed to delete agent")
            )
        
        return {
            "message": "Agent(s) deleted successfully using atomic operations",
            "operation_id": result.get("operation_id"),
            "result": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete agent: {str(e)}"
        )


@router.post("/validate", response_model=FileValidationResponse)
async def validate_agent_files(
    *,
    validation_request: FileValidationRequest
) -> Any:
    """Validate agent files before creation."""
    
    try:
        file_processor = FileProcessor()
        validation_result = await file_processor.validate_agent_files(
            validation_request.files,
            validation_request.agent_config
        )
        
        return validation_result
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File validation failed: {str(e)}"
        )


@router.post("/preview")
async def preview_agent_code(
    *,
    agent_name: str,
    files: dict
) -> Any:
    """Preview generated agent code without saving."""
    
    try:
        agent_factory = AgentFactory()
        preview = await agent_factory.get_agent_preview(agent_name, files)
        
        return preview
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Code preview failed: {str(e)}"
        )


@router.post("/{agent_id}/activate")
async def activate_agent(
    agent_id: int,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Activate an agent."""
    
    # Block if agents are currently running
    await _check_agents_not_running(db)
    
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    
    try:
        agent.status = AgentStatus.ACTIVE
        await db.commit()
        
        return {"message": f"Agent '{agent.name}' activated successfully"}
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to activate agent: {str(e)}"
        )


@router.post("/{agent_id}/deactivate")
async def deactivate_agent(
    agent_id: int,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Deactivate an agent."""
    
    # Block if agents are currently running
    await _check_agents_not_running(db)
    
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    
    try:
        agent.status = AgentStatus.INACTIVE
        await db.commit()
        
        return {"message": f"Agent '{agent.name}' deactivated successfully"}
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to deactivate agent: {str(e)}"
        )


@router.get("/dependencies/report")
async def get_dependency_report(
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Get comprehensive dependency report for all agents."""
    
    try:
        dependency_manager = DependencyManager(db)
        report = await dependency_manager.get_dependency_report()
        
        return report
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate dependency report: {str(e)}"
        )


@router.post("/dependencies/validate")
async def validate_dependencies(
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Validate the entire dependency system for issues."""
    
    try:
        dependency_manager = DependencyManager(db)
        validation_result = await dependency_manager.validate_dependencies()
        
        return validation_result
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Dependency validation failed: {str(e)}"
        )


@router.get("/{agent_name}/deletion-impact")
async def analyze_deletion_impact(
    agent_name: str,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Analyze the impact of deleting a specific agent."""
    
    try:
        dependency_manager = DependencyManager(db)
        deletion_plan = await dependency_manager.analyze_deletion_impact(agent_name)
        
        return deletion_plan
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze deletion impact: {str(e)}"
        )


@router.put("/{agent_name}/dependencies")
async def update_agent_dependencies(
    agent_name: str,
    dependencies: List[str],
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Update an agent's dependencies with validation."""
    
    # Block if agents are currently running
    await _check_agents_not_running(db)
    
    try:
        dependency_manager = DependencyManager(db)
        result = await dependency_manager.update_agent_dependencies(agent_name, dependencies)
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )
        
        # Trigger workflow rebuild
        langgraph_service = LangGraphService(db)
        rebuild_result = await langgraph_service.rebuild_workflow_for_agent_change("update", agent_name)
        
        return {
            "message": f"Dependencies updated for agent '{agent_name}'",
            "dependency_update": result,
            "workflow_rebuild": rebuild_result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update dependencies: {str(e)}"
        )


@router.get("/operations/{operation_id}")
async def get_operation_status(
    operation_id: str,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Get status of an atomic agent operation."""
    
    try:
        lifecycle_manager = AgentLifecycleManager(db)
        operation_status = await lifecycle_manager.get_operation_status(operation_id)
        
        if not operation_status:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Operation {operation_id} not found"
            )
        
        return operation_status
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get operation status: {str(e)}"
        )