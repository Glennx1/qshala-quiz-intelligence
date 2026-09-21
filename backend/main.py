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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="QShala Service Root")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_init_error = None
_init_traceback = None

@app.get("/api/ping")
@app.get("/ping")
def ping():
    return {
        "status": "healthy",
        "service": "qshala-backend",
        "has_init_error": _init_error is not None
    }

@app.get("/api/diagnostics")
@app.get("/diagnostics")
def diagnostics():
    return {
        "init_error": _init_error,
        "traceback": _init_traceback.splitlines() if _init_traceback else None,
        "sys_path": sys.path,
        "cwd": os.getcwd(),
        "files": os.listdir("."),
        "python_version": sys.version
    }

try:
    from backend.app.main import app as qshala_app
    for r in qshala_app.routes:
        app.routes.append(r)
except Exception as e:
    import traceback
    _init_error = str(e)
    _init_traceback = traceback.format_exc()

if _init_error is not None:
    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
    def err_handler(path: str):
        return JSONResponse({
            "error": "Backend initialization failed",
            "details": _init_error,
            "traceback": _init_traceback.splitlines() if _init_traceback else []
        }, status_code=500)

__all__ = ["app"]
