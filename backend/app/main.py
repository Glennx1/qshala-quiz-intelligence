import os
import sys
from pathlib import Path

# Ensure backend directory and project root are on sys.path in all runtimes
import types
_current_file = Path(__file__).resolve()
_backend_dir = _current_file.parent.parent
_project_root = _backend_dir.parent

if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

if "backend" not in sys.modules:
    backend_pkg = types.ModuleType("backend")
    backend_pkg.__path__ = [str(_backend_dir)]
    sys.modules["backend"] = backend_pkg

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from backend.app.config import settings
from backend.app.database import engine, Base
from backend.app.routers import documents, questions, quizzes, stats, jobs, sharepoint, qshala_tagging, question_meta

# Register ALL SQLAlchemy models here so Base.metadata.create_all sees them before
# the first create_all call below. Importing the module is enough; the class
# definitions attach themselves to Base.metadata.
from backend.app.models.question import Question  # noqa: F401
from backend.app.models.qshala_tag import (  # noqa: F401
    QshalaQuestionMetadata, QshalaTag, QshalaTagChange,
)
from backend.app.models.question_meta import (  # noqa: F401
    DeckMetadata, QuestionTopicPath, QuestionRepeat, QuestionEditHistory,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Initialize DB tables
try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    logger.warning(f"DB table creation notice: {e}")

from contextlib import asynccontextmanager
from backend.app.database import SessionLocal
from backend.app.models.document import Document

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        db = SessionLocal()
        doc_count = db.query(Document).count()
        # Nothing can still be processing right after a start: those uploads died with the old process.
        stuck = db.query(Document).filter(Document.processing_status == "PROCESSING").all()
        for d in stuck:
            d.processing_status = "FAILED"
            d.processing_error = ("Processing stopped because the server restarted, most likely because the deck is "
                                  "too large for the server's memory. Compress the pictures and upload it again.")
        if stuck:
            db.commit()
            logger.warning(f"Marked {len(stuck)} interrupted upload(s) as FAILED")
        db.close()
        if doc_count == 0:
            logger.info("Knowledge base is empty. Running automatic seeding of sample decks...")
            from backend.app.utils.seed_knowledge_base import seed
            await seed(force=False)
            logger.info("Auto-seeding completed.")
    except Exception as e:
        logger.warning(f"Lifespan seed check exception: {e}")
    yield

import logging as _logging
_logging.getLogger("httpx").setLevel(_logging.WARNING)   # its INFO lines print the API key in the URL

app = FastAPI(
    title=settings.PROJECT_NAME or "QShala Quiz Intelligence Platform",
    openapi_url=f"{settings.API_V1_STR or '/api/v1'}/openapi.json",
    docs_url=f"{settings.API_V1_STR or '/api/v1'}/docs",
    lifespan=lifespan
)

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class MultiDirStaticFiles(StaticFiles):
    """Static file handler that falls back to bundled repository storage when running in serverless (/tmp)."""
    def __init__(self, *args, fallback_dirs=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fallback_dirs = [Path(d) for d in (fallback_dirs or []) if Path(d).exists()]

    def lookup_path(self, path: str):
        full_path, stat_result = super().lookup_path(path)
        if stat_result is not None:
            return full_path, stat_result
        for fb in self.fallback_dirs:
            fb_path = fb / path
            if fb_path.exists() and fb_path.is_file():
                return str(fb_path.resolve()), fb_path.stat()
        return full_path, stat_result

# Mount static file directory for extracted slide assets with fallback
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
static_fallbacks = [
    _backend_dir / "storage",
    _project_root / "backend" / "storage",
    _project_root / "storage",
    _project_root / "frontend" / "public",
    _project_root / "frontend" / "public" / "static",
    _backend_dir.parent / "frontend" / "public" / "static",
]
slide_fallbacks = [
    _backend_dir / "storage" / "slides",
    _project_root / "backend" / "storage" / "slides",
    _project_root / "storage" / "slides",
    _project_root / "frontend" / "public" / "static" / "slides",
    _backend_dir.parent / "frontend" / "public" / "static" / "slides",
    settings.SLIDES_DIR,
]
app.mount("/static", MultiDirStaticFiles(directory=str(settings.STORAGE_DIR), fallback_dirs=static_fallbacks), name="static")
app.mount(f"{settings.API_V1_STR}/static", MultiDirStaticFiles(directory=str(settings.STORAGE_DIR), fallback_dirs=static_fallbacks), name="api_v1_static")
app.mount("/slides", MultiDirStaticFiles(directory=str(settings.SLIDES_DIR), fallback_dirs=slide_fallbacks), name="slides")

# Mount API routers
app.include_router(stats.router, prefix=settings.API_V1_STR)
app.include_router(documents.router, prefix=settings.API_V1_STR)
app.include_router(questions.router, prefix=settings.API_V1_STR)
app.include_router(question_meta.router, prefix=settings.API_V1_STR)
app.include_router(quizzes.router, prefix=settings.API_V1_STR)
app.include_router(jobs.router, prefix=settings.API_V1_STR)
app.include_router(sharepoint.router, prefix=settings.API_V1_STR)
app.include_router(qshala_tagging.router, prefix=settings.API_V1_STR)
app.include_router(qshala_tagging.router)  # Also mount at /qshala/* directly

@app.get("/")
@app.get("/api")
@app.get(f"{settings.API_V1_STR}")
def root():
    return {
        "service": settings.PROJECT_NAME,
        "status": "online",
        "docs": f"{settings.API_V1_STR}/docs"
    }

@app.get("/health")
@app.get("/api/health")
@app.get(f"{settings.API_V1_STR}/health")
def health():
    return {"status": "healthy"}

