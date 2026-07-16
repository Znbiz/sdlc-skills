"""add conversation fields to cli_tasks

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cli_tasks", sa.Column("conversation_id", sa.Text(), nullable=True))
    op.add_column("cli_tasks", sa.Column("response_type", sa.Text(), nullable=True))
    op.create_index("ix_cli_tasks_conversation_id", "cli_tasks", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_cli_tasks_conversation_id", table_name="cli_tasks")
    op.drop_column("cli_tasks", "response_type")
    op.drop_column("cli_tasks", "conversation_id")
