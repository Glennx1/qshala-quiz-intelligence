"""Add upload_sessions table, execution_name to ingestion_jobs, and last_seen_at to upload_batches.

Revision ID: 0003_resilience
Revises: 0002_upload_batches
Create Date: 2026-11-03
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0003_resilience"
down_revision: Union[str, None] = "0002_upload_batches"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    tables = insp.get_table_names()

    if "upload_sessions" not in tables:
        op.create_table(
            "upload_sessions",
            sa.Column("upload_id", sa.String(64), primary_key=True),
            sa.Column("doc_id", sa.String(64), nullable=False),
            sa.Column("raw_key", sa.String(512), nullable=False),
            sa.Column("r2_upload_id", sa.String(256), nullable=False),
            sa.Column("parts", sa.JSON(), nullable=True),
            sa.Column("total_bytes", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("filename", sa.String(255), nullable=False),
            sa.Column("title", sa.String(255), nullable=True),
            sa.Column("year", sa.Integer(), nullable=True),
            sa.Column("batch_id", sa.String(64), nullable=True),
            sa.Column("client_item_id", sa.String(64), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="OPEN"),
            sa.Column("document_id", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        try:
            op.create_index("ix_upload_sessions_batch_id", "upload_sessions", ["batch_id"])
            op.create_index("ix_upload_sessions_status", "upload_sessions", ["status"])
        except Exception:
            pass

    if "ingestion_jobs" in tables:
        existing_cols = [c["name"] for c in insp.get_columns("ingestion_jobs")]
        if "execution_name" not in existing_cols:
            op.add_column("ingestion_jobs", sa.Column("execution_name", sa.String(255), nullable=True))

    if "upload_batches" in tables:
        existing_cols = [c["name"] for c in insp.get_columns("upload_batches")]
        if "last_seen_at" not in existing_cols:
            op.add_column("upload_batches", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    tables = insp.get_table_names()

    if "upload_sessions" in tables:
        op.drop_table("upload_sessions")

    if "ingestion_jobs" in tables:
        existing_cols = [c["name"] for c in insp.get_columns("ingestion_jobs")]
        if "execution_name" in existing_cols:
            op.drop_column("ingestion_jobs", "execution_name")

    if "upload_batches" in tables:
        existing_cols = [c["name"] for c in insp.get_columns("upload_batches")]
        if "last_seen_at" in existing_cols:
            op.drop_column("upload_batches", "last_seen_at")
