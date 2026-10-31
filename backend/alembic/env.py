"""Alembic environment: wires migrations to this app's own settings.DATABASE_URL and Base,
rather than a separate sqlalchemy.url hardcoded in alembic.ini, so there is exactly one place
the real connection string is read from -- the same normalization app/database.py already does
(postgres:// -> postgresql://) is duplicated here, not imported, to avoid pulling in the whole
app/database.py module just to read a URL and a Base.

Note: importing Base from app.database (needed below, for autogenerate's target_metadata) does
still trigger that module's own top-level side effects -- it opens a connection and runs
ensure_schema_columns() on import, exactly as it does on every app boot today. That's unchanged
by adding Alembic and is harmless (additive, idempotent, already running on every container
start), but it does mean running anything in this directory -- including `alembic stamp head`
-- will also re-run that legacy mechanism as a side effect of the import. Worth untangling if
app/database.py's import-time side effects ever get refactored; out of scope here.
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make `backend.app...` importable when alembic is run from the backend/ directory (the
# repo root is two levels up from this file: backend/alembic/env.py -> backend -> repo root).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.app.config import settings  # noqa: E402
from backend.app.database import Base  # noqa: E402
import backend.app.models  # noqa: E402,F401  -- registers every model's table on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _db_url() -> str:
    url = settings.DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def run_migrations_offline() -> None:
    """Generate SQL without a live DB connection (`alembic upgrade head --sql`)."""
    context.configure(
        url=_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """The normal path: connect and actually run migrations against the configured database."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _db_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
