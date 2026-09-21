import os
import sys
import types
from pathlib import Path

# Ensure the backend directory is in sys.path
_current_dir = Path(__file__).resolve().parent
if str(_current_dir) not in sys.path:
    sys.path.insert(0, str(_current_dir))

# Alias "backend" in sys.modules so that imports like "from backend.app..."
# resolve correctly both locally and in Vercel's serverless environment (/var/task)
if "backend" not in sys.modules:
    backend_pkg = types.ModuleType("backend")
    backend_pkg.__path__ = [str(_current_dir)]
    sys.modules["backend"] = backend_pkg

# Also add the parent directory to sys.path if it exists
_parent_dir = _current_dir.parent
if str(_parent_dir) not in sys.path:
    sys.path.insert(0, str(_parent_dir))

# Import the FastAPI application instance from app.main
from backend.app.main import app

__all__ = ["app"]
