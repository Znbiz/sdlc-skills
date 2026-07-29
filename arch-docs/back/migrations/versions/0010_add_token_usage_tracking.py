"""add token usage tracking to cli_tasks and workflow_runs

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cli_tasks", sa.Column("model_name", sa.Text(), nullable=True))
    op.add_column("cli_tasks", sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("cli_tasks", sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(
        "workflow_runs",
        sa.Column("token_usage_by_model", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "token_usage_by_model")
    op.drop_column("cli_tasks", "output_tokens")
    op.drop_column("cli_tasks", "input_tokens")
    op.drop_column("cli_tasks", "model_name")
