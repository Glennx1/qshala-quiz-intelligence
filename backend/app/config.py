import os
import sys
import shutil
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional

import types

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure "backend" module is registered in sys.modules
if "backend" not in sys.modules:
    backend_pkg = types.ModuleType("backend")
    backend_pkg.__path__ = [str(BASE_DIR)]
    sys.modules["backend"] = backend_pkg

# Handle Vercel serverless environment (/tmp is the only writable directory)
is_vercel = bool(os.environ.get("VERCEL"))
if is_vercel:
    STORAGE_DIR = Path("/tmp/storage")
    default_db_url = "sqlite:////tmp/qshala.db"
    tmp_db = Path("/tmp/qshala.db")

    # Locate pre-seeded SQLite database across multiple potential runtime roots
    candidate_dbs = [
        BASE_DIR / "qshala.db",
        Path.cwd() / "qshala.db",
        Path.cwd() / "backend" / "qshala.db",
        Path(__file__).resolve().parent.parent / "qshala.db",
    ]
    bundled_db = next((p for p in candidate_dbs if p.exists() and p.stat().st_size > 0), None)

    if bundled_db and (not tmp_db.exists() or tmp_db.stat().st_size == 0):
        try:
            shutil.copy2(bundled_db, tmp_db)
            print(f"[Vercel Init] Seeded DB copied from {bundled_db} ({bundled_db.stat().st_size} bytes) to {tmp_db}", file=sys.stderr)
        except Exception as e:
            print(f"[Vercel Init] Failed to copy bundled DB: {e}", file=sys.stderr)

    candidate_deck_dirs = [
        BASE_DIR / "sample_decks",
        Path.cwd() / "sample_decks",
        Path.cwd() / "backend" / "sample_decks",
    ]
    bundled_decks = next((p for p in candidate_deck_dirs if p.exists()), None)
    tmp_uploads = STORAGE_DIR / "uploads"
    try:
        tmp_uploads.mkdir(parents=True, exist_ok=True)
        if bundled_decks and bundled_decks.exists():
            for f in bundled_decks.glob("*.pptx"):
                dest_f = tmp_uploads / f.name
                if not dest_f.exists():
                    shutil.copy2(f, dest_f)
    except Exception as e:
        print(f"[Vercel Init] Failed to copy sample decks: {e}", file=sys.stderr)
else:
    STORAGE_DIR = BASE_DIR / "storage"
    default_db_url = f"sqlite:///{(BASE_DIR / 'qshala.db').resolve().as_posix()}"

UPLOAD_DIR = STORAGE_DIR / "uploads"
SLIDES_DIR = STORAGE_DIR / "slides"
EXPORTS_DIR = STORAGE_DIR / "exports"

for d in [STORAGE_DIR, UPLOAD_DIR, SLIDES_DIR, EXPORTS_DIR]:
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

class Settings(BaseSettings):
    PROJECT_NAME: str = "QShala Quiz Intelligence Platform"
    API_V1_STR: str = "/api/v1"
    
    # Database (uses PostgreSQL if DATABASE_URL is set, otherwise SQLite)
    DATABASE_URL: str = default_db_url
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
