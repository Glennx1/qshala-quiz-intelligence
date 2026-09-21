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
from backend.app.routers import documents, questions, quizzes, stats

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Initialize DB tables
Base.metadata.create_all(bind=engine)

from contextlib import asynccontextmanager
from backend.app.database import SessionLocal
from backend.app.models.document import Document
from backend.app.utils.seed_knowledge_base import seed

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        db = SessionLocal()
        doc_count = db.query(Document).count()
        db.close()
        if doc_count == 0:
            logger.info("Knowledge base is empty. Running automatic seeding of sample decks...")
            await seed(force=False)
            logger.info("Auto-seeding completed.")
    except Exception as e:
        logger.warning(f"Lifespan seed check exception: {e}")
    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
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

# Mount static file directory for extracted slide assets
if os.path.exists(settings.STORAGE_DIR):
    app.mount("/static", StaticFiles(directory=str(settings.STORAGE_DIR)), name="static")

# Mount API routers
app.include_router(stats.router, prefix=settings.API_V1_STR)
app.include_router(documents.router, prefix=settings.API_V1_STR)
app.include_router(questions.router, prefix=settings.API_V1_STR)
app.include_router(quizzes.router, prefix=settings.API_V1_STR)

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

