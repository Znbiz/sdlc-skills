import asyncio
import json
import typing

import fastapi
import pydantic
import structlog
from fastapi import status
from fastapi.responses import StreamingResponse

from app.services.task_registry import CliTask, TaskStatus, get_registry
from app.services.task_runner import cancel_cli_task

router = fastapi.APIRouter()
logger = structlog.get_logger()

_POLL_INTERVAL: typing.Final[float] = 0.05
_TERMINAL_STATUSES: typing.Final[frozenset[TaskStatus]] = frozenset(
    {
        TaskStatus.SUCCESS,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }
)


class TaskResponse(pydantic.BaseModel, frozen=True):
    task_id: str
    task_status: str
    engine_name: str
    session_id: str | None = None
    created_at: str
    started_at: str | None
    finished_at: str | None
    task_result: str | None
    task_error: str | None
    stdout_output: str | None = None


def _to_response(cli_task: CliTask, *, include_output: bool = False) -> TaskResponse:
    return TaskResponse(
        task_id=cli_task.task_id,
        task_status=cli_task.task_status,
        engine_name=cli_task.engine_name,
        session_id=cli_task.session_id,
        created_at=cli_task.created_at.isoformat(),
        started_at=cli_task.started_at.isoformat() if cli_task.started_at else None,
        finished_at=cli_task.finished_at.isoformat() if cli_task.finished_at else None,
        task_result=cli_task.task_result,
        task_error=cli_task.task_error,
        stdout_output="\n".join(cli_task.stdout_lines) if include_output else None,
    )


@router.get("/tasks/")
async def list_tasks(
    task_status: str | None = None,
    engine_name: str | None = None,
    limit: int = 20,
) -> list[TaskResponse]:
    registry = get_registry()
    tasks = list(registry.values())

    if task_status is not None:
        tasks = [t for t in tasks if t.task_status == task_status]
    if engine_name is not None:
        tasks = [t for t in tasks if t.engine_name == engine_name]

    return [_to_response(t) for t in tasks[-limit:]]


@router.get("/tasks/{task_id}/")
async def get_task(task_id: str, include_output: bool = False) -> TaskResponse:
    registry = get_registry()
    cli_task = registry.get(task_id)
    if cli_task is None:
        raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return _to_response(cli_task, include_output=include_output)


@router.delete("/tasks/{task_id}/", status_code=status.HTTP_200_OK)
async def cancel_task(task_id: str) -> TaskResponse:
    registry = get_registry()
    cli_task = registry.get(task_id)
    if cli_task is None:
        raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if cli_task.task_status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
        raise fastapi.HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task is not cancellable in status '{cli_task.task_status}'",
        )
    await cancel_cli_task(task_id, registry)
    return _to_response(cli_task)


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _stream_task_events(cli_task: CliTask) -> typing.AsyncGenerator[str, None]:
    last_stdout_idx = 0
    last_stderr_idx = 0

    while cli_task.task_status not in _TERMINAL_STATUSES:
        for line in cli_task.stderr_lines[last_stderr_idx:]:
            yield _sse_event({"event_type": "progress", "event_data": line, "stream_source": "stderr"})
        last_stderr_idx = len(cli_task.stderr_lines)

        for line in cli_task.stdout_lines[last_stdout_idx:]:
            yield _sse_event({"event_type": "output", "event_data": line, "stream_source": "stdout"})
        last_stdout_idx = len(cli_task.stdout_lines)

        await asyncio.sleep(_POLL_INTERVAL)

    for line in cli_task.stderr_lines[last_stderr_idx:]:
        yield _sse_event({"event_type": "progress", "event_data": line, "stream_source": "stderr"})
    for line in cli_task.stdout_lines[last_stdout_idx:]:
        yield _sse_event({"event_type": "output", "event_data": line, "stream_source": "stdout"})

    exit_code = cli_task.subprocess_handle.returncode if cli_task.subprocess_handle else None
    yield _sse_event({"event_type": "done", "exit_code": exit_code, "task_id": cli_task.task_id})


@router.get("/tasks/{task_id}/stream/")
async def stream_task(task_id: str) -> StreamingResponse:
    registry = get_registry()
    cli_task = registry.get(task_id)
    if cli_task is None:
        raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    logger.info("sse.task_stream.connected", task_id=task_id)
    return StreamingResponse(
        _stream_task_events(cli_task),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
