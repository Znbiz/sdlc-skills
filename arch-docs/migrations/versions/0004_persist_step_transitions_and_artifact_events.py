"""persist step transitions and artifact events

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_step_transitions",
        sa.Column("transition_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("previous_step_id", sa.Text(), nullable=True),
        sa.Column("current_step_id", sa.Text(), nullable=False),
        sa.Column("completed_steps", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.conversation_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_runs.workflow_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("transition_id"),
    )
    op.create_index("ix_workflow_step_transitions_conversation_id", "workflow_step_transitions", ["conversation_id"])
    op.create_index("ix_workflow_step_transitions_workflow_id", "workflow_step_transitions", ["workflow_id"])
    op.create_index("ix_workflow_step_transitions_created_at", "workflow_step_transitions", ["created_at"])

    op.create_table(
        "artifact_events",
        sa.Column("artifact_event_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("step_id", sa.Text(), nullable=True),
        sa.Column("artifact_path", sa.Text(), nullable=False),
        sa.Column("artifact_kind", sa.Text(), nullable=False),
        sa.Column("repository_name", sa.Text(), nullable=True),
        sa.Column("domain_id", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.conversation_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_runs.workflow_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("artifact_event_id"),
    )
    op.create_index("ix_artifact_events_conversation_id", "artifact_events", ["conversation_id"])
    op.create_index("ix_artifact_events_workflow_id", "artifact_events", ["workflow_id"])
    op.create_index("ix_artifact_events_created_at", "artifact_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_artifact_events_created_at", table_name="artifact_events")
    op.drop_index("ix_artifact_events_workflow_id", table_name="artifact_events")
    op.drop_index("ix_artifact_events_conversation_id", table_name="artifact_events")
    op.drop_table("artifact_events")

    op.drop_index("ix_workflow_step_transitions_created_at", table_name="workflow_step_transitions")
    op.drop_index("ix_workflow_step_transitions_workflow_id", table_name="workflow_step_transitions")
    op.drop_index("ix_workflow_step_transitions_conversation_id", table_name="workflow_step_transitions")
    op.drop_table("workflow_step_transitions")
