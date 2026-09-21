import sys
from pathlib import Path

# Ensure project root (containing 'backend') is on sys.path
_current_dir = Path(__file__).resolve().parent
_project_root = _current_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
if str(_current_dir) not in sys.path:
    sys.path.insert(0, str(_current_dir))

# Import the FastAPI application instance from app.main
from backend.app.main import app

__all__ = ["app"]
