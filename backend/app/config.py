import os
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
STORAGE_DIR = BASE_DIR / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"
SLIDES_DIR = STORAGE_DIR / "slides"
EXPORTS_DIR = STORAGE_DIR / "exports"

for d in [STORAGE_DIR, UPLOAD_DIR, SLIDES_DIR, EXPORTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

class Settings(BaseSettings):
    PROJECT_NAME: str = "QShala Quiz Intelligence Platform"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = "sqlite:///./backend/qshala.db"  # Fallback to local SQLite if Postgres not set
    POSTGRES_USER: Optional[str] = None
    POSTGRES_PASSWORD: Optional[str] = None
    POSTGRES_DB: Optional[str] = None
    POSTGRES_HOST: Optional[str] = None
    POSTGRES_PORT: Optional[int] = 5432

    # Storage paths
    STORAGE_DIR: Path = STORAGE_DIR
    UPLOAD_DIR: Path = UPLOAD_DIR
    SLIDES_DIR: Path = SLIDES_DIR
    EXPORTS_DIR: Path = EXPORTS_DIR
    
    # AI Provider: 'gemini', 'openai', 'anthropic', or 'local'
    LLM_PROVIDER: str = "local"
    EMBEDDING_PROVIDER: str = "local"
    
    # API Keys
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    
    # Embedding config
    EMBEDDING_DIM: int = 768  # 768 for Gemini / all-mpnet, 1536 for OpenAI
    
    # Validation thresholds
    DUPLICATE_SIMILARITY_THRESHOLD: float = 0.85
    MIN_GROUNDING_SCORE: float = 0.70

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
