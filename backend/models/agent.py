from sqlalchemy import Column, Integer, String, Float, Text, JSON, Boolean, DateTime, Enum
from sqlalchemy.sql import func
import enum

from backend.core.database import Base


class AgentStatus(str, enum.Enum):
    INACTIVE = "inactive"      # Default state - agent created but not running
    RUNNING = "running"        # Agent is participating in active workflow
    ERROR = "error"           # Agent encountered an error
    CONFIGURING = "configuring"  # Agent is being configured (transitional state)


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    display_name = Column(String(200), nullable=False)
    role = Column(Text, nullable=False)
    
    # LLM Configuration
    llm_name = Column(String(100), default="gpt-4", nullable=False)
    temperature = Column(Float, default=0.1, nullable=False)
    max_tokens = Column(Integer, default=4000, nullable=False)
    
    # Agent Status and Dependencies
    status = Column(Enum(AgentStatus), default=AgentStatus.INACTIVE, nullable=False)
    dependencies = Column(JSON, default=[], nullable=False)  # List of agent names
    
    # File Storage References
    prompts_file_path = Column(String(500), nullable=True)
    output_class_file_path = Column(String(500), nullable=True)
    tools_file_path = Column(String(500), nullable=True)
    
    # Generated Code References
    generated_class_path = Column(String(500), nullable=True)
    generated_model_path = Column(String(500), nullable=True)
    
    # Configuration and Metadata
    config_data = Column(JSON, default={}, nullable=False)
    validation_result = Column(JSON, default={}, nullable=False)
    execution_stats = Column(JSON, default={}, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_executed_at = Column(DateTime(timezone=True), nullable=True)