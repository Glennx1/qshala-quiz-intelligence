import sys
from pathlib import Path

# Ensure project root is in sys.path
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import pytest

@pytest.fixture(scope="session", autouse=True)
def setup_test_schema():
    from backend.app.database import ensure_schema_columns
    ensure_schema_columns()

@pytest.fixture
def anyio_backend():
    return "asyncio"
