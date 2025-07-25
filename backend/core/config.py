from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field
import logging


class Settings(BaseSettings):
    # API Configuration
    api_host: str = Field(default="0.0.0.0", env="API_HOST")
    api_port: int = Field(default=8000, env="API_PORT")
    api_prefix: str = Field(default="/api/v1", env="API_PREFIX")
    
    # Database
    database_url: str = Field(default="sqlite+aiosqlite:///./dynamic_agent_dashboard.db", env="DATABASE_URL")
    
    # Security
    secret_key: str = Field(default="your-secret-key-here-change-in-production", env="SECRET_KEY")
    access_token_expire_minutes: int = Field(default=30, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    
    # OpenAI
    openai_api_key: str = Field(default="sk-test-key", env="OPENAI_API_KEY")
    
    # LangSmith (Optional)  
    langsmith_tracing: Optional[str] = Field(default=None, env="LANGSMITH_TRACING")
    langsmith_endpoint: Optional[str] = Field(default=None, env="LANGSMITH_ENDPOINT")
    langsmith_api_key: Optional[str] = Field(default=None, env="LANGSMITH_API_KEY")
    langsmith_project: Optional[str] = Field(default=None, env="LANGSMITH_PROJECT")
    
    # CORS
    cors_origins: List[str] = Field(default=["http://localhost:8501", "http://localhost:8000"], env="CORS_ORIGINS")
    
    # File Upload
    max_upload_size: int = Field(default=10485760, env="MAX_UPLOAD_SIZE")  # 10MB
    allowed_extensions: List[str] = Field(
        default=["py", "md", "txt", "json"], 
        env="ALLOWED_EXTENSIONS"
    )
    
    # Agent Configuration
    max_agents: int = Field(default=20, env="MAX_AGENTS")
    max_workflow_iterations: int = Field(default=20, env="MAX_WORKFLOW_ITERATIONS")
    stability_threshold: int = Field(default=3, env="STABILITY_THRESHOLD")
    
    # Storage Paths - Updated for organized structure
    upload_dir: str = Field(default="agents", env="UPLOAD_DIR")
    generated_dir: str = Field(default="backend/storage/generated", env="GENERATED_DIR")
    
    # Logging Configuration
    log_level: str = Field(default="WARNING", env="LOG_LEVEL")
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


settings = Settings()

# Configure logging to reduce unnecessary database logs
logging.getLogger("sqlalchemy.engine").setLevel(getattr(logging, settings.log_level.upper()))
logging.getLogger("sqlalchemy").setLevel(getattr(logging, settings.log_level.upper()))