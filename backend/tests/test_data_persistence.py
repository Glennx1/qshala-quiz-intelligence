"""Guards against the silent-SQLite data-loss trap.

The /health endpoint must report which database is live and whether it persists, and REQUIRE_POSTGRES
must make a missing/unreachable Postgres fail loudly at startup instead of falling back to SQLite.
"""
import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.main import app

client = TestClient(app)


def test_health_reports_database_backend_and_persistence():
    r = client.get("/api/v1/health").json()
    assert r["status"] == "healthy"
    assert r["database"] in ("postgres", "sqlite")
    assert isinstance(r["persistent"], bool)
    # on sqlite the endpoint must warn; on postgres it must not
    assert (r["warning"] is None) == (r["database"] == "postgres")


def test_require_postgres_refuses_to_boot_on_sqlite():
    """With REQUIRE_POSTGRES=1 and no DATABASE_URL, importing the DB layer must raise rather than
    silently use an ephemeral SQLite file."""
    repo_root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, REQUIRE_POSTGRES="1", DATABASE_URL="")
    proc = subprocess.run(
        [sys.executable, "-c", "import backend.app.database"],
        cwd=str(repo_root),
        env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 0
    assert "REQUIRE_POSTGRES" in (proc.stderr + proc.stdout)
