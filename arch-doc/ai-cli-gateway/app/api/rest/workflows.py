from __future__ import annotations

import asyncio
import json
import typing

import fastapi
import pydantic
import structlog
from fastapi import status
from fastapi.responses import StreamingResponse

from app.services.workflow_registry import WorkflowStatus, get_workflow_registry

router = fastapi.APIRouter()
logger = structlog.get_logger()

_POLL_INTERVAL: typing.Final[float] = 0.2
_TERMINAL_STATUSES: typing.Final[frozenset[WorkflowStatus]] = frozenset({
    WorkflowStatus.SUCCESS,
    WorkflowStatus.FAILED,
    WorkflowStatus.INTERRUPTED,
})


class PendingInterruptResponse(pydantic.BaseModel, frozen=True):
    interrupt_type: str
    question: str | None = None
    field: str | None = None
    remaining_count: int | None = None


class WorkflowStatusResponse(pydantic.BaseModel, frozen=True):
    workflow_id: str
    workflow_status: str
    current_step_id: str
    current_repo_name: str
    completed_steps: list[str]
    pending_interrupt: PendingInterruptResponse | None
    created_at: str
    updated_at: str
    last_cli_output_snippet: str
    error_message: str | None = None


@router.get("/workflows/{workflow_id}/")
async def get_workflow(workflow_id: str) -> WorkflowStatusResponse:
    registry = get_workflow_registry()
    record = registry.get(workflow_id)
    if record is None:
        raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    pending: PendingInterruptResponse | None = None
    if record.pending_interrupt:
        pending = PendingInterruptResponse(**{
            k: v for k, v in record.pending_interrupt.items()
            if k in PendingInterruptResponse.model_fields
        })

    return WorkflowStatusResponse(
        workflow_id=record.workflow_id,
        workflow_status=record.workflow_status,
        current_step_id=record.current_step_id,
        current_repo_name=record.current_repo_name,
        completed_steps=record.completed_steps,
        pending_interrupt=pending,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
        last_cli_output_snippet=record.last_cli_output_snippet,
        error_message=record.error_message,
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _stream_workflow_events(workflow_id: str) -> typing.AsyncGenerator[str, None]:
    registry = get_workflow_registry()
    record = registry.get(workflow_id)
    if record is None:
        yield _sse({"event_type": "error", "error_message": f"Workflow {workflow_id!r} not found"})
        return

    logger.info("sse.workflow_stream.connected", workflow_id=workflow_id)
    last_step = ""
    last_snippet = ""

    while True:
        current = registry.get(workflow_id)
        if current is None:
            break

        if current.current_step_id != last_step:
            last_step = current.current_step_id
            yield _sse({
                "event_type": "step_started",
                "step_id": last_step,
                "repo_name": current.current_repo_name,
            })

        if current.last_cli_output_snippet != last_snippet:
            last_snippet = current.last_cli_output_snippet
            yield _sse({
                "event_type": "cli_output",
                "event_data": last_snippet,
                "stream_source": "stdout",
            })

        if current.workflow_status == WorkflowStatus.INTERRUPTED:
            yield _sse({"event_type": "interrupted", **(current.pending_interrupt or {})})
            break

        if current.workflow_status == WorkflowStatus.SUCCESS:
            yield _sse({"event_type": "workflow_done", "workflow_status": "success"})
            break

        if current.workflow_status == WorkflowStatus.FAILED:
            yield _sse({"event_type": "workflow_failed", "error_message": current.error_message or "unknown error"})
            break

        await asyncio.sleep(_POLL_INTERVAL)


@router.get("/workflows/{workflow_id}/stream/")
async def stream_workflow(workflow_id: str) -> StreamingResponse:
    registry = get_workflow_registry()
    if workflow_id not in registry:
        raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    logger.info("sse.workflow_stream.requested", workflow_id=workflow_id)
    return StreamingResponse(
        _stream_workflow_events(workflow_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
