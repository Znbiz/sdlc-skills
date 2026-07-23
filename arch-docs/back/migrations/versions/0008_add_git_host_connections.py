"""add git host connections

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "git_host_connections",
        sa.Column("connection_id", sa.Uuid(), primary_key=True),
        sa.Column("host", sa.Text(), nullable=False, unique=True),
        sa.Column("connection_type", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("git_host_connections")
