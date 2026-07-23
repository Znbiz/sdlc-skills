"""add conversation project settings

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("product_name", sa.Text(), nullable=True))
    op.add_column(
        "conversations", sa.Column("repositories", sa.JSON(), nullable=False, server_default="[]")
    )


def downgrade() -> None:
    op.drop_column("conversations", "repositories")
    op.drop_column("conversations", "product_name")
