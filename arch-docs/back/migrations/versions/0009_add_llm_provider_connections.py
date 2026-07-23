"""add llm provider connections

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_provider_connections",
        sa.Column("connection_id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("wire_api", sa.Text(), nullable=False, server_default="chat"),
        sa.Column("requires_openai_auth", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("cli_tasks", sa.Column("provider_connection_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cli_tasks", "provider_connection_id")
    op.drop_table("llm_provider_connections")
