"""Usage tracking: qshala_tags.cached_tokens and the ingestion_usage table (per deck and stage).

Additive and nullable. Safe to run on a live database.

Revision ID: 0007_usage_tracking
Revises: 0006_foreign_key_indexes
Create Date: 2026-11-05
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0007_usage_tracking"
down_revision: Union[str, None] = "0006_foreign_key_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    tables = insp.get_table_names()
    if "qshala_tags" in tables and "cached_tokens" not in [c["name"] for c in insp.get_columns("qshala_tags")]:
        op.add_column("qshala_tags", sa.Column("cached_tokens", sa.Integer(), nullable=True))
    if "ingestion_usage" not in tables:
        op.create_table(
            "ingestion_usage",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("document_id", sa.String(36), nullable=False, index=True),
            sa.Column("stage", sa.String(32), nullable=False),
            sa.Column("model", sa.String(64), nullable=True),
            sa.Column("calls", sa.Integer(), server_default="0"),
            sa.Column("tokens_in", sa.Integer(), server_default="0"),
            sa.Column("tokens_out", sa.Integer(), server_default="0"),
            sa.Column("thinking_tokens", sa.Integer(), server_default="0"),
            sa.Column("cached_tokens", sa.Integer(), server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True)),
        )


def downgrade() -> None:
    insp = inspect(op.get_bind())
    if "ingestion_usage" in insp.get_table_names():
        op.drop_table("ingestion_usage")
    if "qshala_tags" in insp.get_table_names() and "cached_tokens" in [c["name"] for c in insp.get_columns("qshala_tags")]:
        op.drop_column("qshala_tags", "cached_tokens")
