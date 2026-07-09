import json

import pytest

from app.services.workflow_registry import (
    WorkflowRecord,
    WorkflowStatus,
    get_workflow_registry,
    reset_workflow_registry,
)


@pytest.fixture(autouse=True)
def clean_workflow_registry():
    reset_workflow_registry()
    yield
    reset_workflow_registry()


async def test_stream_workflow_not_found(async_client, auth_headers):
    resp = await async_client.get("/api/rest/workflows/nonexistent/stream/", headers=auth_headers)
    assert resp.status_code == 404


async def test_stream_workflow_no_auth(async_client):
    resp = await async_client.get("/api/rest/workflows/some-id/stream/")
    assert resp.status_code == 401


async def test_stream_workflow_success(async_client, auth_headers):
    record = WorkflowRecord(
        workflow_id="wf-sse-success",
        workflow_status=WorkflowStatus.SUCCESS,
        current_step_id="finalize_progress",
        last_cli_output_snippet="all done",
    )
    get_workflow_registry()["wf-sse-success"] = record

    resp = await async_client.get(
        "/api/rest/workflows/wf-sse-success/stream/",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    events = _parse_sse(resp.text)
    event_types = [e.get("event_type") for e in events]
    assert "step_started" in event_types
    assert "cli_output" in event_types
    assert "workflow_done" in event_types


async def test_stream_workflow_failed(async_client, auth_headers):
    record = WorkflowRecord(
        workflow_id="wf-sse-failed",
        workflow_status=WorkflowStatus.FAILED,
        error_message="cli crashed",
    )
    get_workflow_registry()["wf-sse-failed"] = record

    resp = await async_client.get("/api/rest/workflows/wf-sse-failed/stream/", headers=auth_headers)
    assert resp.status_code == 200

    events = _parse_sse(resp.text)
    event_types = [e.get("event_type") for e in events]
    assert "workflow_failed" in event_types
    failed = next(e for e in events if e.get("event_type") == "workflow_failed")
    assert failed["error_message"] == "cli crashed"


async def test_stream_workflow_interrupted(async_client, auth_headers):
    record = WorkflowRecord(
        workflow_id="wf-sse-interrupted",
        workflow_status=WorkflowStatus.INTERRUPTED,
        pending_interrupt={"interrupt_type": "user_question", "question": "What is X?"},
    )
    get_workflow_registry()["wf-sse-interrupted"] = record

    resp = await async_client.get("/api/rest/workflows/wf-sse-interrupted/stream/", headers=auth_headers)
    assert resp.status_code == 200

    events = _parse_sse(resp.text)
    event_types = [e.get("event_type") for e in events]
    assert "interrupted" in event_types


async def test_stream_workflow_removes_from_registry_mid_stream(async_client, auth_headers):
    """Воркфлоу исчезает из реестра в момент стриминга — цикл должен завершиться."""
    import asyncio

    from app.services.workflow_registry import WorkflowRecord, WorkflowStatus, get_workflow_registry

    record = WorkflowRecord(
        workflow_id="wf-disappears",
        workflow_status=WorkflowStatus.RUNNING,
        current_step_id="define_scope",
    )
    get_workflow_registry()["wf-disappears"] = record

    async def _finalize():
        await asyncio.sleep(0.05)
        del get_workflow_registry()["wf-disappears"]

    asyncio.create_task(_finalize())

    resp = await async_client.get("/api/rest/workflows/wf-disappears/stream/", headers=auth_headers)
    assert resp.status_code == 200


def _parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events
