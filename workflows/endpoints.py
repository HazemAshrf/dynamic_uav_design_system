"""Workflow management API endpoints."""

from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_db
from workflows.schemas import (
    WorkflowStart, WorkflowResponse, WorkflowStatusResponse,
    WorkflowListResponse, WorkflowControlRequest
)
from backend.services.langgraph_service import LangGraphService
from workflows.models import WorkflowStatus

router = APIRouter()


@router.post("/start", response_model=WorkflowResponse)
async def start_workflow(
    *,
    db: AsyncSession = Depends(get_db),
    workflow_request: WorkflowStart
) -> Any:
    """Start a new workflow execution."""
    
    try:
        langgraph_service = LangGraphService(db)
        
        result = await langgraph_service.start_workflow(
            user_requirements=workflow_request.user_requirements,
            max_iterations=workflow_request.max_iterations,
            stability_threshold=workflow_request.stability_threshold,
            configuration=workflow_request.configuration
        )
        
        return WorkflowResponse(**result)
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start workflow: {str(e)}"
        )


@router.get("/{workflow_id}/status", response_model=WorkflowStatusResponse)
async def get_workflow_status(
    workflow_id: str,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Get workflow execution status."""
    
    try:
        langgraph_service = LangGraphService(db)
        status_info = await langgraph_service.get_workflow_status(workflow_id)
        
        if not status_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found"
            )
        
        return WorkflowStatusResponse(**status_info)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get workflow status: {str(e)}"
        )


@router.post("/{workflow_id}/stop")
async def stop_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
    control_request: WorkflowControlRequest = None
) -> Any:
    """Stop a running workflow."""
    
    try:
        langgraph_service = LangGraphService(db)
        
        reason = None
        if control_request and control_request.action == "stop":
            reason = control_request.reason
        
        success = await langgraph_service.stop_workflow(workflow_id, reason)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to stop workflow. It may not be running or may not exist."
            )
        
        return {"message": f"Workflow '{workflow_id}' stopped successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop workflow: {str(e)}"
        )


@router.get("/", response_model=WorkflowListResponse)
async def list_workflows(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 50,
    status_filter: Optional[WorkflowStatus] = None
) -> Any:
    """List workflow executions."""
    
    try:
        langgraph_service = LangGraphService(db)
        
        result = await langgraph_service.list_workflows(
            limit=limit,
            offset=skip,
            status_filter=status_filter
        )
        
        return WorkflowListResponse(
            workflows=[
                WorkflowStatusResponse(
                    id=wf["id"],
                    workflow_id=wf["workflow_id"],
                    status=wf["status"],
                    user_requirements=wf["user_requirements"],
                    current_iteration=wf["current_iteration"],
                    max_iterations=wf["max_iterations"],
                    is_complete=wf["is_complete"],
                    created_at=wf["created_at"],
                    completed_at=wf["completed_at"],
                    total_execution_time_ms=wf["total_execution_time_ms"],
                    # Set required fields with defaults
                    thread_id="",
                    stability_threshold=3,
                    active_agents=[],
                    completed_agents=[],
                    failed_agents=[],
                    average_iteration_time_ms=0,
                    error_message=None,
                    error_details={},
                    updated_at=wf["created_at"],
                    started_at=None
                )
                for wf in result["workflows"]
            ],
            total=result["total"]
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list workflows: {str(e)}"
        )


@router.get("/{workflow_id}/conversations")
async def get_workflow_conversations(
    workflow_id: str,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Get conversations from a workflow execution."""
    
    try:
        langgraph_service = LangGraphService(db)
        conversations = await langgraph_service.get_workflow_conversations(workflow_id)
        
        return {
            "workflow_id": workflow_id,
            "conversations": conversations,
            "total": len(conversations)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get workflow conversations: {str(e)}"
        )


@router.get("/{workflow_id}/progress")
async def get_workflow_progress(
    workflow_id: str,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Get detailed workflow progress information."""
    
    try:
        langgraph_service = LangGraphService(db)
        status_info = await langgraph_service.get_workflow_status(workflow_id)
        
        if not status_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found"
            )
        
        # Calculate progress metrics
        total_agents = len(status_info.get("active_agents", []))
        completed_agents = len(status_info.get("completed_agents", []))
        failed_agents = len(status_info.get("failed_agents", []))
        
        progress_percentage = 0
        if total_agents > 0:
            progress_percentage = (completed_agents / total_agents) * 100
        
        current_iteration = status_info.get("current_iteration", 0)
        max_iterations = status_info.get("max_iterations", 10)
        iteration_progress = (current_iteration / max_iterations) * 100
        
        return {
            "workflow_id": workflow_id,
            "status": status_info.get("status"),
            "progress": {
                "agents": {
                    "total": total_agents,
                    "completed": completed_agents,
                    "failed": failed_agents,
                    "active": total_agents - completed_agents - failed_agents,
                    "completion_percentage": progress_percentage
                },
                "iterations": {
                    "current": current_iteration,
                    "maximum": max_iterations,
                    "progress_percentage": min(iteration_progress, 100)
                },
                "timing": {
                    "total_execution_time_ms": status_info.get("total_execution_time_ms"),
                    "average_iteration_time_ms": status_info.get("average_iteration_time_ms"),
                    "started_at": status_info.get("started_at"),
                    "estimated_completion": None  # Could calculate based on average times
                }
            },
            "current_state": status_info.get("current_state", {}),
            "is_complete": status_info.get("is_complete", False)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get workflow progress: {str(e)}"
        )


@router.get("/agents-running")
async def check_agents_running(
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Check if any agents are currently running."""
    
    try:
        langgraph_service = LangGraphService(db)
        agents_running = await langgraph_service.are_agents_running()
        
        return {
            "agents_running": agents_running,
            "message": "Agents are running in workflow" if agents_running else "No agents running"
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check agent status: {str(e)}"
        )


@router.get("/agents-status")
async def get_agent_execution_status(
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Get individual execution status of all agents."""
    
    try:
        langgraph_service = LangGraphService(db)
        agent_status = await langgraph_service.get_agent_execution_status()
        
        return {
            "agent_status": agent_status,
            "total_agents": len(agent_status),
            "running_agents": [name for name, status in agent_status.items() if status == "running"],
            "inactive_agents": [name for name, status in agent_status.items() if status == "inactive"]
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get agent execution status: {str(e)}"
        )