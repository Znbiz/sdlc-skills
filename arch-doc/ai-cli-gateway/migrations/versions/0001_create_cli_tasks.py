"""create cli_tasks table

Revision ID: 0001
Revises:
Create Date: 2026-07-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cli_tasks",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("engine_name", sa.Text(), nullable=False),
        sa.Column("task_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("workspace_dir", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column("task_result", sa.Text(), nullable=True),
        sa.Column("task_error", sa.Text(), nullable=True),
        sa.Column("stdout_output", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_index("ix_cli_tasks_task_status", "cli_tasks", ["task_status"])
    op.create_index("ix_cli_tasks_engine_name", "cli_tasks", ["engine_name"])
    op.create_index("ix_cli_tasks_created_at", "cli_tasks", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_cli_tasks_created_at", table_name="cli_tasks")
    op.drop_index("ix_cli_tasks_engine_name", table_name="cli_tasks")
    op.drop_index("ix_cli_tasks_task_status", table_name="cli_tasks")
    op.drop_table("cli_tasks")
