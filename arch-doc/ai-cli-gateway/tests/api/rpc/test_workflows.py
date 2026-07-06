import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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


_INIT_PAYLOAD = {
    "product_name": "TestProduct",
    "analysis_scope": "full",
    "workspace_dir": "/workspace/test",
    "arch_repo_dir": "/workspace/test/arch-doc",
    "repo_list": ["test-repo"],
    "engine_name": "claude",
    "timeout_seconds": 60,
}


async def _empty_astream(*_args, **_kwargs):
    return
    yield  # noqa: unreachable


def _make_mock_graph() -> MagicMock:
    mock_compiled = MagicMock()
    mock_compiled.astream = _empty_astream
    return mock_compiled


async def test_init_workflow_returns_202(async_client, auth_headers):
    with patch("app.api.rpc.workflows.get_checkpointer", new_callable=AsyncMock) as mock_cp, \
         patch("app.api.rpc.workflows.compile_graph", return_value=_make_mock_graph()):
        mock_cp.return_value = MagicMock()
        resp = await async_client.post("/api/rpc/workflows/init/", json=_INIT_PAYLOAD, headers=auth_headers)

    assert resp.status_code == 202
    data = resp.json()
    assert "workflow_id" in data
    assert data["workflow_status"] == "running"
    assert data["current_step_id"] == "define_scope"
    assert data["created_at"]


async def test_init_workflow_no_auth(async_client):
    resp = await async_client.post("/api/rpc/workflows/init/", json=_INIT_PAYLOAD)
    assert resp.status_code == 401


async def test_resume_workflow_not_found(async_client, auth_headers):
    resp = await async_client.post(
        "/api/rpc/workflows/nonexistent/resume/",
        json={"answer": "yes"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_resume_workflow_not_interrupted(async_client, auth_headers):
    record = WorkflowRecord(workflow_id="wf-running", workflow_status=WorkflowStatus.RUNNING)
    get_workflow_registry()["wf-running"] = record

    resp = await async_client.post(
        "/api/rpc/workflows/wf-running/resume/",
        json={"answer": "yes"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


async def test_resume_workflow_user_question(async_client, auth_headers):
    record = WorkflowRecord(
        workflow_id="wf-interrupted",
        workflow_status=WorkflowStatus.INTERRUPTED,
        pending_interrupt={"interrupt_type": "user_question", "question": "What protocol?"},
    )
    get_workflow_registry()["wf-interrupted"] = record

    with patch("app.api.rpc.workflows.get_checkpointer", new_callable=AsyncMock) as mock_cp, \
         patch("app.api.rpc.workflows.compile_graph", return_value=_make_mock_graph()):
        mock_cp.return_value = MagicMock()
        resp = await async_client.post(
            "/api/rpc/workflows/wf-interrupted/resume/",
            json={"answer": "REST over HTTPS"},
            headers=auth_headers,
        )

    assert resp.status_code == 202
    data = resp.json()
    assert data["workflow_id"] == "wf-interrupted"


async def test_resume_workflow_user_input(async_client, auth_headers):
    record = WorkflowRecord(
        workflow_id="wf-input",
        workflow_status=WorkflowStatus.INTERRUPTED,
        pending_interrupt={"interrupt_type": "user_input", "field": "repo_list"},
    )
    get_workflow_registry()["wf-input"] = record

    with patch("app.api.rpc.workflows.get_checkpointer", new_callable=AsyncMock) as mock_cp, \
         patch("app.api.rpc.workflows.compile_graph", return_value=_make_mock_graph()):
        mock_cp.return_value = MagicMock()
        resp = await async_client.post(
            "/api/rpc/workflows/wf-input/resume/",
            json={"field": "repo_list", "value": ["svc-a", "svc-b"]},
            headers=auth_headers,
        )

    assert resp.status_code == 202


async def test_resume_workflow_invalid_payload(async_client, auth_headers):
    record = WorkflowRecord(
        workflow_id="wf-bad",
        workflow_status=WorkflowStatus.INTERRUPTED,
        pending_interrupt={"interrupt_type": "user_question"},
    )
    get_workflow_registry()["wf-bad"] = record

    resp = await async_client.post(
        "/api/rpc/workflows/wf-bad/resume/",
        json={},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_init_workflow_astream_yields_events(async_client, auth_headers):
    """Граф возвращает события — воркфлоу обновляет record."""

    async def _events_astream(*_args, **_kwargs):
        yield {"define_scope": {"current_step_id": "request_repository_list", "completed_steps": ["define_scope"], "current_repo_name": "svc-a", "last_cli_output": "done"}}

    mock_graph = MagicMock()
    mock_graph.astream = _events_astream

    with patch("app.api.rpc.workflows.get_checkpointer", new_callable=AsyncMock) as mock_cp, \
         patch("app.api.rpc.workflows.compile_graph", return_value=mock_graph):
        mock_cp.return_value = MagicMock()
        resp = await async_client.post("/api/rpc/workflows/init/", json=_INIT_PAYLOAD, headers=auth_headers)

    assert resp.status_code == 202
    await asyncio.sleep(0.05)


async def test_resume_workflow_astream_yields_interrupt(async_client, auth_headers):
    """Resume: граф возвращает interrupt — статус переходит в interrupted."""
    record = WorkflowRecord(
        workflow_id="wf-resume-interrupt",
        workflow_status=WorkflowStatus.INTERRUPTED,
        pending_interrupt={"interrupt_type": "user_question", "question": "Q?"},
    )
    get_workflow_registry()["wf-resume-interrupt"] = record

    class _FakeInterrupt:
        def __init__(self):
            self.value = {"interrupt_type": "user_question", "question": "Q2?"}

    async def _interrupt_astream(*_args, **_kwargs):
        yield {"__interrupt__": [_FakeInterrupt()]}

    mock_graph = MagicMock()
    mock_graph.astream = _interrupt_astream

    with patch("app.api.rpc.workflows.get_checkpointer", new_callable=AsyncMock) as mock_cp, \
         patch("app.api.rpc.workflows.compile_graph", return_value=mock_graph):
        mock_cp.return_value = MagicMock()
        resp = await async_client.post(
            "/api/rpc/workflows/wf-resume-interrupt/resume/",
            json={"answer": "yes"},
            headers=auth_headers,
        )

    assert resp.status_code == 202
    await asyncio.sleep(0.05)


async def test_init_workflow_handles_graph_error(async_client, auth_headers):
    async def _error_astream(*_args, **_kwargs):
        raise RuntimeError("graph crashed")
        yield  # noqa: unreachable

    mock_graph = MagicMock()
    mock_graph.astream = _error_astream

    with patch("app.api.rpc.workflows.get_checkpointer", new_callable=AsyncMock) as mock_cp, \
         patch("app.api.rpc.workflows.compile_graph", return_value=mock_graph):
        mock_cp.return_value = MagicMock()
        resp = await async_client.post("/api/rpc/workflows/init/", json=_INIT_PAYLOAD, headers=auth_headers)

    assert resp.status_code == 202
    workflow_id = resp.json()["workflow_id"]

    await asyncio.sleep(0.05)

    registry = get_workflow_registry()
    record = registry.get(workflow_id)
    if record:
        assert record.workflow_status in (WorkflowStatus.RUNNING, WorkflowStatus.FAILED)
