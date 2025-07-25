from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

from workflows.models import WorkflowStatus


class WorkflowStart(BaseModel):
    user_requirements: str = Field(..., min_length=10)
    max_iterations: int = Field(default=10, ge=1, le=50)
    stability_threshold: int = Field(default=3, ge=1, le=10)
    configuration: Dict[str, Any] = Field(default={})
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_requirements": "Design a cargo drone with 10kg payload capacity for 30km range",
                "max_iterations": 15,
                "stability_threshold": 3,
                "configuration": {
                    "priority_agents": ["mission_planner", "aerodynamics"],
                    "debug_mode": False
                }
            }
        }


class WorkflowResponse(BaseModel):
    workflow_id: str
    thread_id: str
    status: WorkflowStatus
    message: str = "Workflow started successfully"
    
    class Config:
        json_schema_extra = {
            "example": {
                "workflow_id": "wf_20240115_143022",
                "thread_id": "thread_wf_20240115_143022", 
                "status": "running",
                "message": "Workflow started successfully"
            }
        }


class WorkflowStatusResponse(BaseModel):
    id: int
    workflow_id: str
    thread_id: str
    user_requirements: str
    status: WorkflowStatus
    current_iteration: int
    max_iterations: int
    stability_threshold: int
    is_complete: bool
    
    # Agent Status
    active_agents: List[str]
    completed_agents: List[str]
    failed_agents: List[str]
    
    # Performance
    total_execution_time_ms: Optional[int] = None
    average_iteration_time_ms: Optional[int] = None
    
    # Error Info
    error_message: Optional[str] = None
    error_details: Dict[str, Any]
    
    # Timestamps
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class WorkflowListResponse(BaseModel):
    workflows: List[WorkflowStatusResponse]
    total: int


class WorkflowControlRequest(BaseModel):
    action: str = Field(..., pattern=r"^(stop|pause|resume)$")
    reason: Optional[str] = None


class WorkflowIterationSummary(BaseModel):
    iteration: int
    agents_executed: List[str]
    execution_time_ms: int
    messages_generated: int
    errors: List[str] = Field(default=[])
    timestamp: datetime