"""persist workflow runtime and conversation timeline

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cli_tasks", sa.Column("stderr_output", sa.Text(), nullable=True))
    op.add_column("cli_tasks", sa.Column("exit_code", sa.Integer(), nullable=True))

    op.create_table(
        "conversations",
        sa.Column("conversation_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("conversation_id"),
    )

    op.create_table(
        "workflow_runs",
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.Text(), nullable=False),
        sa.Column("workflow_name", sa.Text(), nullable=False),
        sa.Column("workflow_status", sa.Text(), nullable=False),
        sa.Column("current_step_id", sa.Text(), nullable=False),
        sa.Column("current_repo_name", sa.Text(), nullable=False),
        sa.Column("completed_steps", sa.JSON(), nullable=False),
        sa.Column("session_payload", sa.JSON(), nullable=True),
        sa.Column("pending_interrupt_payload", sa.JSON(), nullable=True),
        sa.Column("last_cli_output_snippet", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.conversation_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workflow_id"),
    )
    op.create_index("ix_workflow_runs_conversation_id", "workflow_runs", ["conversation_id"])
    op.create_index("ix_workflow_runs_workflow_status", "workflow_runs", ["workflow_status"])

    op.create_table(
        "conversation_items",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=True),
        sa.Column("item_kind", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("step_id", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.conversation_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_runs.workflow_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id"),
    )
    op.create_index("ix_conversation_items_conversation_id", "conversation_items", ["conversation_id"])
    op.create_index("ix_conversation_items_workflow_id", "conversation_items", ["workflow_id"])
    op.create_index("ix_conversation_items_item_kind", "conversation_items", ["item_kind"])
    op.create_index("ix_conversation_items_created_at", "conversation_items", ["created_at"])

    op.create_table(
        "required_actions",
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("question_id", sa.Text(), nullable=True),
        sa.Column("action_status", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.conversation_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_runs.workflow_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("action_id"),
    )
    op.create_index("ix_required_actions_conversation_id", "required_actions", ["conversation_id"])
    op.create_index("ix_required_actions_workflow_id", "required_actions", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_required_actions_workflow_id", table_name="required_actions")
    op.drop_index("ix_required_actions_conversation_id", table_name="required_actions")
    op.drop_table("required_actions")

    op.drop_index("ix_conversation_items_created_at", table_name="conversation_items")
    op.drop_index("ix_conversation_items_item_kind", table_name="conversation_items")
    op.drop_index("ix_conversation_items_workflow_id", table_name="conversation_items")
    op.drop_index("ix_conversation_items_conversation_id", table_name="conversation_items")
    op.drop_table("conversation_items")

    op.drop_index("ix_workflow_runs_workflow_status", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_conversation_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")

    op.drop_table("conversations")

    op.drop_column("cli_tasks", "exit_code")
    op.drop_column("cli_tasks", "stderr_output")
