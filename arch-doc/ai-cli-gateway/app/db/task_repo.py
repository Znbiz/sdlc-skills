from __future__ import annotations

import uuid

import sqlalchemy as sa
import sqlalchemy.ext.asyncio as async_sa

from app.db.models import CliTaskModel
from app.services.task_registry import CliTask, TaskStatus


async def upsert_cli_task(session: async_sa.AsyncSession, cli_task: CliTask) -> None:
    task_uuid = uuid.UUID(cli_task.task_id)
    existing = await session.get(CliTaskModel, task_uuid)
    stdout_text = "\n".join(cli_task.stdout_lines) if cli_task.stdout_lines else None

    if existing is None:
        record = CliTaskModel(
            task_id=task_uuid,
            engine_name=cli_task.engine_name,
            task_status=str(cli_task.task_status),
            prompt_text=cli_task.prompt_text,
            workspace_dir=cli_task.workspace_dir,
            session_id=cli_task.session_id,
            task_result=cli_task.task_result,
            task_error=cli_task.task_error,
            stdout_output=stdout_text,
            created_at=cli_task.created_at,
            started_at=cli_task.started_at,
            finished_at=cli_task.finished_at,
        )
        session.add(record)
    else:
        existing.task_status = str(cli_task.task_status)
        existing.task_result = cli_task.task_result
        existing.task_error = cli_task.task_error
        existing.stdout_output = stdout_text
        existing.started_at = cli_task.started_at
        existing.finished_at = cli_task.finished_at

    await session.commit()


async def mark_running_tasks_failed(session: async_sa.AsyncSession) -> int:
    result = await session.execute(
        sa.update(CliTaskModel)
        .where(CliTaskModel.task_status.in_(["pending", "running"]))
        .values(task_status=str(TaskStatus.FAILED), task_error="Service restarted")
        .returning(CliTaskModel.task_id)
    )
    await session.commit()
    return len(result.fetchall())
