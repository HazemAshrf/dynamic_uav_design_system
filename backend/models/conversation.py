from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, ForeignKey, JSON, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from backend.core.database import Base


class ConversationStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class AgentConversation(Base):
    __tablename__ = "agent_conversations"

    id = Column(Integer, primary_key=True, index=True)
    conversation_key = Column(String(200), nullable=False, unique=True, index=True)  # e.g., "agent1_agent2"
    participant_1 = Column(String(100), nullable=False, index=True)
    participant_2 = Column(String(100), nullable=False, index=True)
    
    status = Column(Enum(ConversationStatus), default=ConversationStatus.ACTIVE, nullable=False)
    message_count = Column(Integer, default=0, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_message_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    messages = relationship("AgentMessage", back_populates="conversation", cascade="all, delete-orphan")


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("agent_conversations.id"), nullable=False)
    
    # Message Details
    from_agent = Column(String(100), nullable=False, index=True)
    to_agent = Column(String(100), nullable=False, index=True)
    content = Column(Text, nullable=False)
    
    # Workflow Context
    iteration = Column(Integer, nullable=False, index=True)
    workflow_id = Column(String(100), nullable=True, index=True)
    
    # Message Metadata
    message_metadata = Column(JSON, default={}, nullable=False)
    confidence_score = Column(Float, nullable=True)
    processing_time_ms = Column(Integer, nullable=True)
    
    # Timestamp
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    conversation = relationship("AgentConversation", back_populates="messages")