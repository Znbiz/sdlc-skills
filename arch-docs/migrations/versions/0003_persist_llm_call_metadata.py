"""persist llm call metadata for workflow audit links

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cli_tasks", sa.Column("workflow_id", sa.Text(), nullable=True))
    op.add_column("cli_tasks", sa.Column("step_id", sa.Text(), nullable=True))
    op.add_column("cli_tasks", sa.Column("repository_name", sa.Text(), nullable=True))
    op.add_column("cli_tasks", sa.Column("domain_id", sa.Text(), nullable=True))
    op.add_column("cli_tasks", sa.Column("expected_schema_name", sa.Text(), nullable=True))
    op.create_index("ix_cli_tasks_workflow_id", "cli_tasks", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_cli_tasks_workflow_id", table_name="cli_tasks")
    op.drop_column("cli_tasks", "expected_schema_name")
    op.drop_column("cli_tasks", "domain_id")
    op.drop_column("cli_tasks", "repository_name")
    op.drop_column("cli_tasks", "step_id")
    op.drop_column("cli_tasks", "workflow_id")
