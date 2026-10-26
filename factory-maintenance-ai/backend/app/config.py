from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///./factory_maintenance.db"
    
    # File Upload
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE: int = 10485760  # 10MB
    ALLOWED_EXTENSIONS: str = "jpg,jpeg,png"
    
    # AI/LLM (Optional)
    LLM_API_KEY: Optional[str] = None
    LLM_API_URL: Optional[str] = None
    LLM_MODEL: Optional[str] = None
    
    # Application
    APP_ENV: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = "your-secret-key-change-in-production"
    
    # API
    API_V1_PREFIX: str = "/api"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()