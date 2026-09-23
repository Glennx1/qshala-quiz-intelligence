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

def ensure_schema_columns():
    """Safely adds newly introduced columns to existing database tables."""
    if engine is None:
        return
    try:
        # Create all tables that do not exist yet (including sharepoint and job tables)
        import backend.app.models  # noqa: F401
        Base.metadata.create_all(bind=engine)

        with engine.connect() as conn:
            # Check if questions table exists
            table_check = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='questions';").fetchone() if not is_postgres else True
            if table_check:
                new_q_cols = [
                    ("content_hash", "VARCHAR(64)"),
                    ("topics", "TEXT"),
                    ("tags", "TEXT"),
                    ("difficulty_score", "FLOAT DEFAULT 0.50"),
                    ("cognitive_level", "VARCHAR(50) DEFAULT 'Recall / Remember'"),
                    ("audience_suitability", "TEXT"),
                    ("question_hook", "VARCHAR(50) DEFAULT 'DIRECT_TRIVIA'"),
                    ("curiosity_score", "INTEGER DEFAULT 7"),
                    ("temporal_nature", "VARCHAR(20) DEFAULT 'EVERGREEN'"),
                    ("provenance_decks", "TEXT"),
                    ("occurrence_count", "INTEGER DEFAULT 1"),
                    ("round_number", "INTEGER"),
                    ("image_refs", "TEXT DEFAULT '[]'"),
                    ("visual_clues", "TEXT"),
                    ("audio_transcript", "TEXT"),
                    ("video_transcript", "TEXT"),
                    ("raw_media_refs", "TEXT DEFAULT '[]'"),
                    ("source_slide_range", "VARCHAR(50)"),
                    ("duplicate_status", "VARCHAR(50) DEFAULT 'UNIQUE'"),
                    ("duplicate_similarity", "FLOAT"),
                    ("duplicate_of_id", "VARCHAR(36)")
                ]
                for col_name, col_type in new_q_cols:
                    try:
                        if is_postgres:
                            conn.exec_driver_sql(f"ALTER TABLE questions ADD COLUMN IF NOT EXISTS {col_name} {col_type};")
                        else:
                            conn.exec_driver_sql(f"ALTER TABLE questions ADD COLUMN {col_name} {col_type};")
                    except Exception:
                        pass # Column already exists

            # Check if quizzes table exists
            quiz_table_check = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='quizzes';").fetchone() if not is_postgres else True
            if quiz_table_check:
                quiz_cols = [
                    ("tags", "TEXT"),
                    ("personality", "VARCHAR(50) DEFAULT 'CURIOSITY_STORYTELLER'")
                ]
                for col_name, col_type in quiz_cols:
                    try:
                        if is_postgres:
                            conn.exec_driver_sql(f"ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS {col_name} {col_type};")
                        else:
                            conn.exec_driver_sql(f"ALTER TABLE quizzes ADD COLUMN {col_name} {col_type};")
                    except Exception:
                        pass

            # Check if documents table exists
            doc_table_check = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='documents';").fetchone() if not is_postgres else True
            if doc_table_check:
                new_doc_cols = [
                    ("blob_url", "TEXT"),
                    ("source", "VARCHAR(50) DEFAULT 'MANUAL'"),
                    ("sharepoint_file_id", "VARCHAR(255)")
                ]
                for col_name, col_type in new_doc_cols:
                    try:
                        if is_postgres:
                            conn.exec_driver_sql(f"ALTER TABLE documents ADD COLUMN IF NOT EXISTS {col_name} {col_type};")
                        else:
                            conn.exec_driver_sql(f"ALTER TABLE documents ADD COLUMN {col_name} {col_type};")
                    except Exception:
                        pass
            conn.commit()

        # One-time backfill of content_hash and topics for legacy questions
        try:
            from backend.app.services.deduplication.deduplicator import Deduplicator
            from backend.app.services.tagging.auto_tagger import AutoTagger
            from backend.app.services.tagging.difficulty_engine import DifficultyEngine
            from backend.app.models.question import Question

            sess = SessionLocal()
            unhashed = sess.query(Question).filter(Question.content_hash.is_(None)).all()
            if unhashed:
                tagger = AutoTagger()
                diff_eng = DifficultyEngine()
                for q in unhashed:
                    q.content_hash = Deduplicator.compute_hash(q.question_text, q.answer)
                    t_data = tagger.tag_question(q.question_text, q.answer, q.explanation or "")
                    d_data = diff_eng.evaluate(q.question_text, q.answer, q.explanation or "")
                    q.topics = t_data["topics"]
                    q.tags = t_data["tags"]
                    q.question_hook = t_data["question_hook"]
                    q.curiosity_score = t_data["curiosity_score"]
                    q.temporal_nature = t_data["temporal_nature"]
                    q.difficulty = d_data["difficulty"]
                    q.difficulty_score = d_data["difficulty_score"]
                    q.cognitive_level = d_data["cognitive_level"]
                    q.audience_suitability = d_data["audience_suitability"]
                    q.provenance_decks = [{"document_id": q.document_id, "slide_id": q.slide_id}]
                    q.occurrence_count = 1
                sess.commit()
            sess.close()
        except Exception as be:
            logger.debug(f"Legacy backfill notice: {be}")

    except Exception as e:
        logger.debug(f"Schema auto-check notice: {e}")

try:
    ensure_schema_columns()
except Exception:
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

