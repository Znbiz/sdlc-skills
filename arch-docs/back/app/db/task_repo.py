from __future__ import annotations

import datetime
import uuid

import sqlalchemy as sa
import sqlalchemy.ext.asyncio as async_sa

from app.db.models import CliTaskModel
from app.services.task_registry import CliTask, TaskStatus
from app.services.text_sanitization import sanitize_text as _sanitize_text
from app.settings import get_gateway_settings


async def upsert_cli_task(session: async_sa.AsyncSession, cli_task: CliTask) -> None:
    task_uuid = uuid.UUID(cli_task.task_id)
    existing = await session.get(CliTaskModel, task_uuid)
    settings = get_gateway_settings()
    stdout_text = _sanitize_text(
        "\n".join(cli_task.stdout_lines) if cli_task.stdout_lines else None,
        max_chars=settings.audit.max_output_chars,
    )
    stderr_text = _sanitize_text(
        "\n".join(cli_task.stderr_lines) if cli_task.stderr_lines else None,
        max_chars=settings.audit.max_error_chars,
    )
    prompt_text = _sanitize_text(cli_task.prompt_text, max_chars=settings.audit.max_prompt_chars) or ""
    task_result = _sanitize_text(cli_task.task_result, max_chars=settings.audit.max_output_chars)
    task_error = _sanitize_text(cli_task.task_error, max_chars=settings.audit.max_error_chars)

    if existing is None:
        record = CliTaskModel(
            task_id=task_uuid,
            engine_name=cli_task.engine_name,
            task_status=str(cli_task.task_status),
            prompt_text=prompt_text,
            workspace_dir=cli_task.workspace_dir,
            session_id=cli_task.session_id,
            conversation_id=cli_task.conversation_id,
            response_type=cli_task.response_type,
            workflow_id=cli_task.workflow_id,
            step_id=cli_task.step_id,
            repository_name=cli_task.repository_name,
            domain_id=cli_task.domain_id,
            expected_schema_name=cli_task.expected_schema_name,
            task_result=task_result,
            task_error=task_error,
            stdout_output=stdout_text,
            stderr_output=stderr_text,
            exit_code=cli_task.exit_code,
            created_at=cli_task.created_at,
            started_at=cli_task.started_at,
            finished_at=cli_task.finished_at,
        )
        session.add(record)
    else:
        existing.task_status = str(cli_task.task_status)
        existing.conversation_id = cli_task.conversation_id
        existing.response_type = cli_task.response_type
        existing.workflow_id = cli_task.workflow_id
        existing.step_id = cli_task.step_id
        existing.repository_name = cli_task.repository_name
        existing.domain_id = cli_task.domain_id
        existing.expected_schema_name = cli_task.expected_schema_name
        existing.task_result = task_result
        existing.task_error = task_error
        existing.prompt_text = prompt_text
        existing.stdout_output = stdout_text
        existing.stderr_output = stderr_text
        existing.exit_code = cli_task.exit_code
        existing.started_at = cli_task.started_at
        existing.finished_at = cli_task.finished_at

    await session.commit()


def _task_from_model(model: CliTaskModel) -> CliTask:
    return CliTask(
        task_id=str(model.task_id),
        engine_name=model.engine_name,
        prompt_text=model.prompt_text,
        workspace_dir=model.workspace_dir,
        session_id=model.session_id,
        conversation_id=model.conversation_id,
        response_type=model.response_type,
        workflow_id=model.workflow_id,
        step_id=model.step_id,
        repository_name=model.repository_name,
        domain_id=model.domain_id,
        expected_schema_name=model.expected_schema_name,
        task_status=TaskStatus(model.task_status),
        task_result=model.task_result,
        task_error=model.task_error,
        stdout_lines=(model.stdout_output.splitlines() if model.stdout_output else []),
        stderr_lines=(model.stderr_output.splitlines() if model.stderr_output else []),
        exit_code=model.exit_code,
        created_at=model.created_at or datetime.datetime.now(datetime.timezone.utc),
        started_at=model.started_at,
        finished_at=model.finished_at,
    )


async def get_cli_task(session: async_sa.AsyncSession, task_id: str) -> CliTask | None:
    model = await session.get(CliTaskModel, uuid.UUID(task_id))
    if model is None:
        return None
    return _task_from_model(model)


async def list_cli_tasks_for_conversation(
    session: async_sa.AsyncSession,
    *,
    conversation_id: str,
) -> list[CliTask]:
    result = await session.execute(
        sa.select(CliTaskModel)
        .where(CliTaskModel.conversation_id == conversation_id)
        .order_by(CliTaskModel.created_at.desc(), CliTaskModel.task_id.desc())
    )
    return [_task_from_model(model) for model in result.scalars()]


async def mark_running_tasks_failed(session: async_sa.AsyncSession) -> int:
    result = await session.execute(
        sa.update(CliTaskModel)
        .where(CliTaskModel.task_status.in_(["pending", "running"]))
        .values(task_status=str(TaskStatus.FAILED), task_error="Service restarted")
        .returning(CliTaskModel.task_id)
    )
    await session.commit()
    return len(result.fetchall())
