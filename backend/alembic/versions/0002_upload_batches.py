"""Add upload_batches table and batch columns to ingestion_jobs.

Revision ID: 0002_upload_batches
Revises: 0001_baseline
Create Date: 2026-11-02
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0002_upload_batches"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    tables = insp.get_table_names()

    if "upload_batches" not in tables:
        op.create_table(
            "upload_batches",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("total_expected", sa.Integer(), nullable=False),
            sa.Column("items", sa.JSON(), nullable=True),
        )

    if "ingestion_jobs" in tables:
        existing_cols = [c["name"] for c in insp.get_columns("ingestion_jobs")]
        if "batch_id" not in existing_cols:
            op.add_column("ingestion_jobs", sa.Column("batch_id", sa.String(36), nullable=True))
            try:
                op.create_index("ix_ingestion_jobs_batch_id", "ingestion_jobs", ["batch_id"])
            except Exception:
                pass
        if "client_item_id" not in existing_cols:
            op.add_column("ingestion_jobs", sa.Column("client_item_id", sa.String(64), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    tables = insp.get_table_names()

    if "upload_batches" in tables:
        op.drop_table("upload_batches")

    if "ingestion_jobs" in tables:
        existing_cols = [c["name"] for c in insp.get_columns("ingestion_jobs")]
        if "batch_id" in existing_cols:
            try:
                op.drop_index("ix_ingestion_jobs_batch_id", table_name="ingestion_jobs")
            except Exception:
                pass
            op.drop_column("ingestion_jobs", "batch_id")
        if "client_item_id" in existing_cols:
            op.drop_column("ingestion_jobs", "client_item_id")
