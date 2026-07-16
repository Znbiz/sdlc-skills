"""add workflow path metadata

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workflow_runs", sa.Column("workspace_dir", sa.Text(), nullable=False, server_default=""))
    op.add_column("workflow_runs", sa.Column("arch_repo_dir", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("workflow_runs", "arch_repo_dir")
    op.drop_column("workflow_runs", "workspace_dir")
