"""Index the foreign keys and sort column that large queries filter on (audit Q9).

questions.document_id / slide_id / duplicate_of_id / created_at and slides.document_id had no index, so per-deck
reads, deck deletes (ON DELETE SET NULL scans) and the default question-list sort used sequential scans.

For a live production database prefer `python -m scripts.add_fk_indexes` (dry-run first, CREATE INDEX
CONCURRENTLY); this migration is the equivalent for environments that run Alembic.

Revision ID: 0006_foreign_key_indexes
Revises: 0005_question_embedding_model
Create Date: 2026-11-04
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import inspect

revision: str = "0006_foreign_key_indexes"
down_revision: Union[str, None] = "0005_question_embedding_model"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEXES = [
    ("ix_questions_document_id", "questions", "document_id"),
    ("ix_questions_slide_id", "questions", "slide_id"),
    ("ix_questions_duplicate_of_id", "questions", "duplicate_of_id"),
    ("ix_questions_created_at", "questions", "created_at"),
    ("ix_slides_document_id", "slides", "document_id"),
]


def upgrade() -> None:
    insp = inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for name, table, column in INDEXES:
        if table in tables and name not in {ix["name"] for ix in insp.get_indexes(table)}:
            op.create_index(name, table, [column])


def downgrade() -> None:
    insp = inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for name, table, _column in INDEXES:
        if table in tables and name in {ix["name"] for ix in insp.get_indexes(table)}:
            op.drop_index(name, table_name=table)
