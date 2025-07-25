from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class FileValidationRequest(BaseModel):
    files: Dict[str, str] = Field(...)  # filename -> base64 content
    agent_config: Optional[Dict[str, str]] = Field(default={})
    
    class Config:
        json_schema_extra = {
            "example": {
                "files": {
                    "prompts.py": "base64_encoded_content",
                    "output_class.py": "base64_encoded_content",
                    "tools.py": "base64_encoded_content", 
                    "dependencies.json": "base64_encoded_content"
                },
                "agent_config": {
                    "name": "thermal_management",
                    "llm_name": "gpt-4"
                }
            }
        }


class FileValidationResult(BaseModel):
    filename: str
    valid: bool
    file_type: str
    size_bytes: int
    errors: List[str] = Field(default=[])
    warnings: List[str] = Field(default=[])
    metadata: Dict[str, Any] = Field(default={})


class FileValidationResponse(BaseModel):
    overall_valid: bool
    validation_results: List[FileValidationResult]
    summary: Dict[str, int] = Field(default={})  # valid_count, invalid_count, etc.
    
    class Config:
        json_schema_extra = {
            "example": {
                "overall_valid": True,
                "validation_results": [
                    {
                        "filename": "prompts.py",
                        "valid": True,
                        "file_type": "python",
                        "size_bytes": 1024,
                        "errors": [],
                        "warnings": [],
                        "metadata": {"format": "python", "prompts_found": ["SYSTEM_PROMPT"]}
                    }
                ],
                "summary": {
                    "valid_count": 4,
                    "invalid_count": 0,
                    "total_size_bytes": 8192
                }
            }
        }


class AgentCodePreview(BaseModel):
    agent_class_code: str
    output_model_code: str
    import_statements: List[str]
    tools_detected: List[str]
    dependencies_resolved: List[str]