import os
import sys
import shutil
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import field_validator
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

# Clean all empty string environment variables from Vercel / serverless runtime
for _k, _v in list(os.environ.items()):
    if _v == "":
        os.environ.pop(_k, None)

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

    candidate_slide_dirs = [
        BASE_DIR / "storage" / "slides",
        Path.cwd() / "storage" / "slides",
        Path.cwd() / "backend" / "storage" / "slides",
        PROJECT_ROOT / "backend" / "storage" / "slides",
    ]
    bundled_slides = next((p for p in candidate_slide_dirs if p.exists()), None)
    tmp_slides = STORAGE_DIR / "slides"
    if bundled_slides and bundled_slides.exists():
        try:
            tmp_slides.mkdir(parents=True, exist_ok=True)
            for item in bundled_slides.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(bundled_slides)
                    target = tmp_slides / rel
                    if not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, target)
            print(f"[Vercel Init] Seeded slide assets copied to {tmp_slides}", file=sys.stderr)
        except Exception as e:
            print(f"[Vercel Init] Failed to copy bundled slides: {e}", file=sys.stderr)
else:
    STORAGE_DIR = BASE_DIR / "storage"
    default_db_url = f"sqlite:///{(BASE_DIR / 'qshala.db').resolve().as_posix()}"

UPLOAD_DIR = STORAGE_DIR / "uploads"
SLIDES_DIR = STORAGE_DIR / "slides"
EXPORTS_DIR = STORAGE_DIR / "exports"
BLOBS_DIR = STORAGE_DIR / "blobs"

for d in [STORAGE_DIR, UPLOAD_DIR, SLIDES_DIR, EXPORTS_DIR, BLOBS_DIR]:
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
    BLOBS_DIR: Path = BLOBS_DIR

    # Vercel Blob Object Storage
    BLOB_READ_WRITE_TOKEN: Optional[str] = None

    # Cloudflare R2 Object Storage (S3-compatible). Preferred media store when configured;
    # falls back to Vercel Blob, then local disk, when any of these are missing.
    R2_ACCOUNT_ID: Optional[str] = None
    R2_ACCESS_KEY_ID: Optional[str] = None
    R2_SECRET_ACCESS_KEY: Optional[str] = None
    R2_BUCKET_NAME: Optional[str] = None
    # Public base URL for the bucket (R2.dev dev URL or a custom domain). Required to
    # construct a servable https URL for uploaded media.
    R2_PUBLIC_BASE_URL: Optional[str] = None

    # Azure AD / Microsoft Graph / SharePoint Integration
    AZURE_TENANT_ID: Optional[str] = None
    AZURE_CLIENT_ID: Optional[str] = None
    AZURE_CLIENT_SECRET: Optional[str] = None
    SHAREPOINT_SITE_ID: Optional[str] = None
    SHAREPOINT_DRIVE_ID: Optional[str] = None
    
    # AI Provider: 'gemini', 'openai', 'anthropic', or 'local'
    LLM_PROVIDER: str = "local"
    EMBEDDING_PROVIDER: str = "local"
    
    # API Keys
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None

    # Which Gemini model to call for tagging/generation/image-description. Overridable
    # without a code change in case Google renames/retires the default.
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"

    # QShala-domain tagger (business/finance/culture) runs on a cheaper, faster model
    # so bulk tagging stays affordable while the heavier generator stays on GEMINI_MODEL.
    # Overridable via env; blank/None falls back to Flash-Lite.
    QSHALA_TAGGER_MODEL: str = "gemini-3.5-flash-lite"

    # Embedding config
    EMBEDDING_DIM: int = 768  # 768 for Gemini / all-mpnet, 1536 for OpenAI

    # Validation thresholds
    DUPLICATE_SIMILARITY_THRESHOLD: float = 0.92
    MIN_GROUNDING_SCORE: float = 0.70

    # Hybrid tagging thresholds: the free rule-based tagger runs first on every question.
    # If its top-scoring topic clears CONFIDENCE_THRESHOLD and isn't too close to the
    # runner-up (AMBIGUITY_RATIO), we skip the Gemini call entirely for that question.
    # Only ambiguous/low-confidence questions are escalated to the AI, which keeps
    # per-question AI cost down at high ingestion volume (e.g. SharePoint bulk sync).
    TAGGING_CONFIDENCE_THRESHOLD: float = 4.0
    TAGGING_AMBIGUITY_RATIO: float = 0.65

    # Early-volume override: when True, every question is sent to Gemini regardless of
    # how confident the rule-based pass is -- the confidence gate above is skipped
    # entirely. Use this while ingestion volume is still low (first few hundred
    # questions) and accuracy matters more than API cost. Once you've accumulated
    # enough Gemini-tagged questions to train your own local classifier on them, flip
    # this back to False to re-enable the cost-saving hybrid gate.
    FORCE_AI_TAGGING: bool = True

    # Upload queue: when True, uploads enqueue a job and a single serial worker processes one deck
    # at a time (memory-safe on a 512 MB host). When False, falls back to immediate per-upload
    # background processing (the old behaviour). Flip off with UPLOAD_QUEUE_ENABLED=0 to revert.
    UPLOAD_QUEUE_ENABLED: bool = True
    UPLOAD_QUEUE_POLL_SECONDS: int = 5          # how often the worker looks for the next deck
    UPLOAD_QUEUE_MAX_RETRIES: int = 2           # manual-retry cap per deck

    # Data safety: when True, the app refuses to start on a non-persistent SQLite database. Set
    # REQUIRE_POSTGRES=1 in any deployed environment (Render, Railway) so a missing or unreachable
    # DATABASE_URL fails loudly at boot instead of silently writing to a disk that gets wiped on
    # restart. Leave False for local development, where SQLite is intentional.
    REQUIRE_POSTGRES: bool = False

    @field_validator("UPLOAD_QUEUE_ENABLED", "REQUIRE_POSTGRES", mode="before")
    @classmethod
    def _parse_safety_bools(cls, v, info):
        if v == "" or v is None:
            return True if info.field_name == "UPLOAD_QUEUE_ENABLED" else False
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in {"1", "true", "yes", "on"}

    @field_validator("FORCE_AI_TAGGING", mode="before")
    @classmethod
    def parse_force_ai_tagging(cls, v):
        if v == "" or v is None:
            return True
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in {"1", "true", "yes", "on"}

    @field_validator("GEMINI_MODEL", mode="before")
    @classmethod
    def parse_gemini_model(cls, v):
        if v == "" or v is None:
            return "gemini-3.5-flash-lite"
        return str(v)

    @field_validator("QSHALA_TAGGER_MODEL", mode="before")
    @classmethod
    def parse_qshala_tagger_model(cls, v):
        if v == "" or v is None:
            return "gemini-3.5-flash-lite"
        return str(v)

    @field_validator("TAGGING_CONFIDENCE_THRESHOLD", mode="before")
    @classmethod
    def parse_tagging_confidence(cls, v):
        if v == "" or v is None:
            return 4.0
        return float(v)

    @field_validator("TAGGING_AMBIGUITY_RATIO", mode="before")
    @classmethod
    def parse_tagging_ambiguity(cls, v):
        if v == "" or v is None:
            return 0.65
        return float(v)

    @field_validator("EMBEDDING_DIM", mode="before")
    @classmethod
    def parse_embedding_dim(cls, v):
        if v == "" or v is None:
            return 768
        return int(v)

    @field_validator("DUPLICATE_SIMILARITY_THRESHOLD", mode="before")
    @classmethod
    def parse_dup_thresh(cls, v):
        if v == "" or v is None:
            return 0.92
        return float(v)

    @field_validator("MIN_GROUNDING_SCORE", mode="before")
    @classmethod
    def parse_min_ground(cls, v):
        if v == "" or v is None:
            return 0.70
        return float(v)

    @field_validator("POSTGRES_PORT", mode="before")
    @classmethod
    def parse_postgres_port(cls, v):
        if v == "" or v is None:
            return 5432
        return int(v)

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def parse_db_url(cls, v):
        if v == "" or v is None:
            return default_db_url
        return str(v)

    @field_validator("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                     "BLOB_READ_WRITE_TOKEN", "AZURE_TENANT_ID", "AZURE_CLIENT_ID",
                     "AZURE_CLIENT_SECRET", "SHAREPOINT_SITE_ID", "SHAREPOINT_DRIVE_ID",
                     "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                     "R2_BUCKET_NAME", "R2_PUBLIC_BASE_URL",
                     mode="before")
    @classmethod
    def parse_empty_keys(cls, v):
        if v == "" or v is None:
            return None
        return str(v)

    @field_validator("PROJECT_NAME", mode="before")
    @classmethod
    def parse_project_name(cls, v):
        if not v:
            return "QShala Quiz Intelligence Platform"
        return str(v)

    class Config:
        env_file = ".env"
        extra = "ignore"

# Ensure no empty strings slip into settings
for _k, _v in list(os.environ.items()):
    if _v == "":
        os.environ.pop(_k, None)

settings = Settings()
