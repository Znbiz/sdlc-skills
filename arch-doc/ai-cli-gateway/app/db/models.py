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
    created_at: orm.Mapped[datetime.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    started_at: orm.Mapped[datetime.datetime | None] = orm.mapped_column(sa.DateTime(timezone=True), nullable=True)
    finished_at: orm.Mapped[datetime.datetime | None] = orm.mapped_column(sa.DateTime(timezone=True), nullable=True)
