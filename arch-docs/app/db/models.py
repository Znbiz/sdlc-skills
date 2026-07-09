from __future__ import annotations

import datetime  # noqa: TC003
import uuid

import sqlalchemy as sa
from sqlalchemy import orm


class Base(orm.DeclarativeBase):
    pass


class CliTaskModel(Base):
    __tablename__ = "cli_tasks"

    task_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        sa.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    engine_name: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    task_status: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False, default="pending")
    prompt_text: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    workspace_dir: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    session_id: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    task_result: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    task_error: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    stdout_output: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    stderr_output: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    exit_code: orm.Mapped[int | None] = orm.mapped_column(sa.Integer, nullable=True)
    created_at: orm.Mapped[datetime.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    started_at: orm.Mapped[datetime.datetime | None] = orm.mapped_column(sa.DateTime(timezone=True), nullable=True)
    finished_at: orm.Mapped[datetime.datetime | None] = orm.mapped_column(sa.DateTime(timezone=True), nullable=True)


class ConversationModel(Base):
    __tablename__ = "conversations"

    conversation_id: orm.Mapped[str] = orm.mapped_column(sa.Text, primary_key=True)
    created_at: orm.Mapped[datetime.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: orm.Mapped[datetime.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


class WorkflowRunModel(Base):
    __tablename__ = "workflow_runs"

    workflow_id: orm.Mapped[str] = orm.mapped_column(sa.Text, primary_key=True)
    conversation_id: orm.Mapped[str] = orm.mapped_column(
        sa.ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_name: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False, default="init_arch")
    workflow_status: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False, index=True)
    current_step_id: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    current_repo_name: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False, default="")
    completed_steps: orm.Mapped[list[str]] = orm.mapped_column(sa.JSON, nullable=False, default=list)
    session_payload: orm.Mapped[dict | None] = orm.mapped_column(sa.JSON, nullable=True)
    pending_interrupt_payload: orm.Mapped[dict | None] = orm.mapped_column(sa.JSON, nullable=True)
    last_cli_output_snippet: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False, default="")
    error_message: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    created_at: orm.Mapped[datetime.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
    )
    updated_at: orm.Mapped[datetime.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
    )


class ConversationItemModel(Base):
    __tablename__ = "conversation_items"

    item_id: orm.Mapped[uuid.UUID] = orm.mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: orm.Mapped[str] = orm.mapped_column(
        sa.ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_id: orm.Mapped[str | None] = orm.mapped_column(
        sa.ForeignKey("workflow_runs.workflow_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    item_kind: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False, index=True)
    actor: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False, default="service")
    step_id: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    payload_json: orm.Mapped[dict] = orm.mapped_column(sa.JSON, nullable=False, default=dict)
    created_at: orm.Mapped[datetime.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        index=True,
    )


class RequiredActionModel(Base):
    __tablename__ = "required_actions"

    action_id: orm.Mapped[uuid.UUID] = orm.mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: orm.Mapped[str] = orm.mapped_column(
        sa.ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_id: orm.Mapped[str] = orm.mapped_column(
        sa.ForeignKey("workflow_runs.workflow_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_type: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    question_id: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    action_status: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False, default="open")
    payload_json: orm.Mapped[dict] = orm.mapped_column(sa.JSON, nullable=False, default=dict)
    created_at: orm.Mapped[datetime.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: orm.Mapped[datetime.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
