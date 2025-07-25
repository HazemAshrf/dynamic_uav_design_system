from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

from backend.models.agent import AgentStatus


class AgentBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    display_name: str = Field(..., min_length=1, max_length=200)
    role: str = Field(..., min_length=1)
    llm_name: str = Field(default="gpt-4", max_length=100)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4000, gt=0, le=32000)
    dependencies: List[str] = Field(default=[])


class AgentCreate(AgentBase):
    files: Dict[str, str] = Field(...)  # Base64 encoded files
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "thermal_management",
                "display_name": "Thermal Management Agent",
                "role": "Heat dissipation and thermal analysis specialist",
                "llm_name": "gpt-4",
                "temperature": 0.2,
                "max_tokens": 4000,
                "dependencies": ["propulsion", "structures"],
                "files": {
                    "prompts": "base64_encoded_content",
                    "output_class": "base64_encoded_content", 
                    "tools": "base64_encoded_content",
                    "dependencies": "base64_encoded_content"
                }
            }
        }


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    display_name: Optional[str] = Field(None, min_length=1, max_length=200)
    role: Optional[str] = Field(None, min_length=1)
    llm_name: Optional[str] = Field(None, max_length=100)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, gt=0, le=32000)
    dependencies: Optional[List[str]] = None
    status: Optional[AgentStatus] = None
    files: Optional[Dict[str, str]] = None  # Base64 encoded files for update


class AgentResponse(AgentBase):
    id: int
    status: AgentStatus
    created_at: datetime
    updated_at: datetime
    last_executed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class AgentDetailResponse(AgentResponse):
    prompts_content: Optional[str] = None
    output_class_content: Optional[str] = None
    tools_content: Optional[str] = None
    config_data: Dict[str, Any]
    validation_result: Dict[str, Any]
    execution_stats: Dict[str, Any]


class AgentValidationResult(BaseModel):
    prompts_valid: bool
    output_class_valid: bool 
    tools_valid: bool
    dependencies_valid: bool
    errors: List[str] = Field(default=[])
    warnings: List[str] = Field(default=[])
    
    class Config:
        json_schema_extra = {
            "example": {
                "prompts_valid": True,
                "output_class_valid": True,
                "tools_valid": True,
                "dependencies_valid": True,
                "errors": [],
                "warnings": ["Temperature value is high (1.5), consider lowering for more deterministic outputs"]
            }
        }


class AgentFileContent(BaseModel):
    prompts: str
    output_class: str
    tools: str
    dependencies: str