from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

from backend.models.conversation import ConversationStatus


class MessageResponse(BaseModel):
    id: int
    from_agent: str
    to_agent: str
    content: str
    iteration: int
    workflow_id: Optional[str] = None
    message_metadata: Dict[str, Any]
    confidence_score: Optional[float] = None
    processing_time_ms: Optional[int] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class ConversationResponse(BaseModel):
    id: int
    conversation_key: str
    participant_1: str
    participant_2: str
    status: ConversationStatus
    message_count: int
    created_at: datetime
    updated_at: datetime
    last_message_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class ConversationDetailResponse(ConversationResponse):
    messages: List[MessageResponse] = Field(default=[])


class ConversationListResponse(BaseModel):
    conversations: List[ConversationResponse]
    total: int
    
    
class MessageCreateRequest(BaseModel):
    from_agent: str = Field(..., min_length=1, max_length=100)
    to_agent: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1)
    iteration: int = Field(..., ge=0)
    workflow_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default={})
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    
    
class ConversationFilter(BaseModel):
    participant: Optional[str] = None
    status: Optional[ConversationStatus] = None
    workflow_id: Optional[str] = None
    min_messages: Optional[int] = Field(None, ge=0)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None