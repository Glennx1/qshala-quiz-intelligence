import json
import logging
from typing import List, Optional
from sqlalchemy import create_engine, TypeDecorator, Text
from sqlalchemy.orm import sessionmaker, declarative_base
from backend.app.config import settings

logger = logging.getLogger(__name__)

# Check if using PostgreSQL and normalize URL scheme
raw_db_url = settings.DATABASE_URL
if raw_db_url.startswith("postgres://"):
    raw_db_url = raw_db_url.replace("postgres://", "postgresql://", 1)

is_postgres = raw_db_url.startswith("postgresql")

# Custom JSON-backed Vector type for SQLite and fallback
class VectorType(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, (list, tuple)):
            return json.dumps([float(x) for x in value])
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return []
        return value

# Try importing pgvector if postgres
PG_VECTOR_AVAILABLE = False
if is_postgres:
    try:
        from pgvector.sqlalchemy import Vector
        PG_VECTOR_AVAILABLE = True
    except (ImportError, Exception):
        logger.warning("pgvector package not loaded, using custom VectorType fallback")

def get_vector_column_type(dim: int = 768):
    if is_postgres and PG_VECTOR_AVAILABLE:
        try:
            from pgvector.sqlalchemy import Vector
            return Vector(dim)
        except Exception:
            return VectorType()
    return VectorType()

# Database engine with automatic fallback
engine = None
if is_postgres:
    try:
        engine = create_engine(raw_db_url, echo=False)
        with engine.connect() as conn:
            pass
    except Exception as exc:
        logger.warning(f"PostgreSQL connection failed ({exc}), falling back to SQLite")
        is_postgres = False
        engine = None

if engine is None:
    import os
    from backend.app.config import default_db_url
    connect_args = {"check_same_thread": False}
    engine = create_engine(default_db_url, connect_args=connect_args, echo=False)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
