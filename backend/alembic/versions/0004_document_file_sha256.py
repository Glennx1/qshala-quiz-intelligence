"""Add documents.file_sha256 (fingerprint of the uploaded deck, used to spot identical re-uploads).

Nullable and additive: existing rows stay NULL. Safe to run on a live database.

Revision ID: 0004_document_file_sha256
Revises: 0003_resilience
Create Date: 2026-11-04
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0004_document_file_sha256"
down_revision: Union[str, None] = "0003_resilience"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if "documents" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("documents")]
        if "file_sha256" not in cols:
            op.add_column("documents", sa.Column("file_sha256", sa.String(64), nullable=True))


def downgrade() -> None:
    insp = inspect(op.get_bind())
    if "documents" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("documents")]
        if "file_sha256" in cols:
            op.drop_column("documents", "file_sha256")
