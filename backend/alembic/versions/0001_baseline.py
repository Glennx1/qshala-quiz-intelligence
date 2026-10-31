"""baseline: schema as created by Base.metadata.create_all() + the legacy ad-hoc column adds
in app/database.py's ensure_schema_columns(), at the point Alembic was adopted.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-31

This migration is deliberately a no-op. Every table and column it would otherwise describe
already exists on every environment that has run this app -- ensure_schema_columns() built
them, and still does, unchanged by this change. Its only purpose is to give Alembic a
revision 0 that an existing database can be stamped onto (`alembic stamp head`), so that
FUTURE schema changes have something to layer real, reviewable migrations on top of, without
this one commit trying to re-describe years of incrementally-added columns and risk getting
some type, default, or nullability detail subtly wrong against a live production database that
couldn't safely be verified against from the environment this was written in.

See backend/alembic/README.md for the one-time `alembic stamp head` step this needs before
`alembic upgrade head` is used for anything real.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
