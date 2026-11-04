"""Add questions.embedding_model (which model produced each stored vector).

Nullable and additive: existing rows stay NULL. Safe to run on a live database.

Revision ID: 0005_question_embedding_model
Revises: 0004_document_file_sha256
Create Date: 2026-11-04
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0005_question_embedding_model"
down_revision: Union[str, None] = "0004_document_file_sha256"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if "questions" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("questions")]
        if "embedding_model" not in cols:
            op.add_column("questions", sa.Column("embedding_model", sa.String(64), nullable=True))


def downgrade() -> None:
    insp = inspect(op.get_bind())
    if "questions" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("questions")]
        if "embedding_model" in cols:
            op.drop_column("questions", "embedding_model")
