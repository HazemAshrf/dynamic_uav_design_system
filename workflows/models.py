from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, JSON, Boolean
from sqlalchemy.sql import func
import enum

from backend.core.database import Base


class WorkflowStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(String(100), nullable=False, unique=True, index=True)
    thread_id = Column(String(100), nullable=False, unique=True, index=True)
    
    # Workflow Configuration
    user_requirements = Column(Text, nullable=False)
    max_iterations = Column(Integer, default=10, nullable=False)
    stability_threshold = Column(Integer, default=3, nullable=False)
    
    # Execution State
    status = Column(Enum(WorkflowStatus), default=WorkflowStatus.PENDING, nullable=False)
    current_iteration = Column(Integer, default=0, nullable=False)
    is_complete = Column(Boolean, default=False, nullable=False)
    
    # Agent Tracking
    active_agents = Column(JSON, default=[], nullable=False)  # List of agent names
    completed_agents = Column(JSON, default=[], nullable=False)
    failed_agents = Column(JSON, default=[], nullable=False)
    
    # Performance Metrics
    total_execution_time_ms = Column(Integer, nullable=True)
    average_iteration_time_ms = Column(Integer, nullable=True)
    
    # Error Information
    error_message = Column(Text, nullable=True)
    error_details = Column(JSON, default={}, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class WorkflowCheckpoint(Base):
    __tablename__ = "workflow_checkpoints"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(String(100), nullable=False, index=True)
    checkpoint_id = Column(String(100), nullable=False, index=True)
    
    # State Data
    state_data = Column(JSON, nullable=False)
    iteration = Column(Integer, nullable=False, index=True)
    
    # Checkpoint Metadata
    checkpoint_metadata = Column(JSON, default={}, nullable=False)
    size_bytes = Column(Integer, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())