import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.task_registry import CliTask, TaskStatus, get_registry
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


async def test_create_conversation_returns_201(async_client, auth_headers):
    resp = await async_client.post("/api/rest/conversations/", headers=auth_headers)

    assert resp.status_code == 201
    data = resp.json()
    assert data["conversation_id"]
    assert data["active_response"] is None


async def test_get_conversation_returns_active_response(async_client, auth_headers):
    get_workflow_registry()["wf-conv-1"] = WorkflowRecord(
        workflow_id="wf-conv-1",
        conversation_id="conv-1",
        workflow_status=WorkflowStatus.RUNNING,
        current_step_id="define_scope",
    )

    resp = await async_client.get("/api/rest/conversations/conv-1/", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["conversation_id"] == "conv-1"
    assert data["active_response"]["response_id"] == "wf-conv-1"
    assert data["active_response"]["response_status"] == "running"


async def test_list_conversation_items_returns_workflow_timeline(async_client, auth_headers, monkeypatch):
    get_workflow_registry()["wf-conv-items"] = WorkflowRecord(
        workflow_id="wf-conv-items",
        conversation_id="conv-items",
    )

    async def _fake_events(_workflow_id: str):
        return [
            {
                "item_id": "evt-1",
                "item_kind": "llm_task_requested",
                "actor": "llm_worker",
                "step_id": "define_scope",
                "payload": {"llm_call_id": "call-1"},
                "created_at": "2026-07-09T00:00:00+00:00",
            }
        ]

    monkeypatch.setattr("app.services.init_arch_workflow.list_workflow_events_async", _fake_events)

    resp = await async_client.get("/api/rest/conversations/conv-items/items/", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["conversation_id"] == "conv-items"
    assert data["items"][0]["item_kind"] == "llm_task_requested"


async def test_create_response_init_arch_returns_202(async_client, auth_headers):
    payload = {
        "conversation_id": "conv-start",
        "workflow_type": "init_arch",
        "input": {
            "product_name": "TestProduct",
            "analysis_scope": "full",
            "workspace_dir": "/workspace/test",
            "arch_repo_dir": "/workspace/test/arch-doc",
            "repo_list": ["test-repo"],
            "engine_name": "claude",
            "timeout_seconds": 60,
        },
    }

    resp = await async_client.post("/api/rest/responses/", json=payload, headers=auth_headers)

    assert resp.status_code == 202
    data = resp.json()
    assert data["conversation_id"] == "conv-start"
    assert data["response_id"]
    assert data["response_status"] == "running"
    assert data["workflow_type"] == "init_arch"


async def test_create_response_init_arch_returns_422_when_fields_missing(async_client, auth_headers):
    payload = {
        "conversation_id": "conv-start-incomplete",
        "workflow_type": "init_arch",
        "input": {
            "product_name": "TestProduct",
            "analysis_scope": "full",
        },
    }

    resp = await async_client.post("/api/rest/responses/", json=payload, headers=auth_headers)

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "workspace_dir" in detail
    assert "arch_repo_dir" in detail
    assert "repo_list" in detail
    assert "engine_name" in detail
    assert "timeout_seconds" in detail


async def test_get_response_returns_required_actions(async_client, auth_headers):
    get_workflow_registry()["wf-response-1"] = WorkflowRecord(
        workflow_id="wf-response-1",
        conversation_id="conv-response-1",
        workflow_status=WorkflowStatus.INTERRUPTED,
        current_step_id="interview_user",
        pending_interrupt={
            "interrupt_type": "user_question",
            "question_id": "Q-1",
            "question": "What transport is used?",
        },
    )

    resp = await async_client.get("/api/rest/responses/wf-response-1/", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["response_id"] == "wf-response-1"
    assert data["conversation_id"] == "conv-response-1"
    assert data["response_status"] == "interrupted"
    assert data["required_actions"][0]["question_id"] == "Q-1"


async def test_post_response_action_pause_delegates_to_workflow(async_client, auth_headers):
    # `pause` replaced the old standalone `cancel` action for graph workflows (see
    # arch-docs/docs/spec/2026-07-22-realtime-workflow-observability.md §7) - it's resumable.
    get_workflow_registry()["wf-response-pause"] = WorkflowRecord(
        workflow_id="wf-response-pause",
        conversation_id="conv-response-pause",
        workflow_status=WorkflowStatus.RUNNING,
    )

    resp = await async_client.post(
        "/api/rest/responses/wf-response-pause/actions/",
        json={"action_type": "pause"},
        headers=auth_headers,
    )

    assert resp.status_code == 202
    data = resp.json()
    assert data["response_id"] == "wf-response-pause"
    assert data["response_status"] == "paused"


async def test_post_response_action_continue_delegates_to_workflow(async_client, auth_headers):
    get_workflow_registry()["wf-response-continue"] = WorkflowRecord(
        workflow_id="wf-response-continue",
        conversation_id="conv-response-continue",
        workflow_status=WorkflowStatus.PAUSED,
    )

    with patch("app.services.init_arch_workflow.resume_workflow_task", new=AsyncMock()) as mock_resume:
        resp = await async_client.post(
            "/api/rest/responses/wf-response-continue/actions/",
            json={"action_type": "continue"},
            headers=auth_headers,
        )
        await asyncio.sleep(0)  # let the scheduled background task actually run the mock

    assert resp.status_code == 202
    data = resp.json()
    assert data["response_id"] == "wf-response-continue"
    assert data["response_status"] == "running"
    mock_resume.assert_awaited_once()


async def test_post_response_action_cancel_is_no_longer_supported_for_workflows(async_client, auth_headers):
    # The task-backed (update_arch/query) `cancel` path is a separate, untouched code path in
    # submit_response_action_async() (see tests/services/test_init_arch_workflow.py for its
    # coverage); this covers only the removed graph-workflow branch.
    get_workflow_registry()["wf-response-cancel-removed"] = WorkflowRecord(
        workflow_id="wf-response-cancel-removed",
        conversation_id="conv-response-cancel-removed",
        workflow_status=WorkflowStatus.RUNNING,
    )

    resp = await async_client.post(
        "/api/rest/responses/wf-response-cancel-removed/actions/",
        json={"action_type": "cancel"},
        headers=auth_headers,
    )

    assert resp.status_code == 422


async def test_post_response_action_restart_deletes_workflow_and_returns_conversation_shape(
    async_client, auth_headers, tmp_path
):
    from app.services.init_arch_workflow import persist_workflow_record

    workspace_dir = tmp_path / "workspace"
    (workspace_dir / ".temp").mkdir(parents=True)
    (workspace_dir / "arch-doc").mkdir(parents=True)

    record = WorkflowRecord(
        workflow_id="wf-response-restart",
        conversation_id="conv-response-restart",
        workspace_dir=str(workspace_dir),
        arch_repo_dir=str(workspace_dir / "arch-doc"),
        workflow_status=WorkflowStatus.FAILED,
    )
    get_workflow_registry()["wf-response-restart"] = record
    await persist_workflow_record(record)

    fake_checkpointer = MagicMock()
    fake_checkpointer.adelete_thread = AsyncMock()

    with patch("app.services.init_arch_workflow.get_checkpointer", new=AsyncMock(return_value=fake_checkpointer)):
        resp = await async_client.post(
            "/api/rest/responses/wf-response-restart/actions/",
            json={"action_type": "restart"},
            headers=auth_headers,
        )

    assert resp.status_code == 202
    data = resp.json()
    # conversation-shaped payload, not the usual response-shaped one - the response_id is gone.
    assert data == {
        "conversation_id": "conv-response-restart",
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "active_response": None,
        "previous_init_input": None,
    }
    assert not (workspace_dir / ".temp").exists()
    assert not (workspace_dir / "arch-doc").exists()
    assert "wf-response-restart" not in get_workflow_registry()


async def test_post_response_action_restart_returns_previous_init_input_for_prefill(async_client, auth_headers, tmp_path):
    from app.services.init_arch_workflow import persist_workflow_record
    from app.workflows.init_arch.domain import RepositoryExecution, WorkflowSessionRecord

    workspace_dir = tmp_path / "workspace"
    (workspace_dir / ".temp").mkdir(parents=True)
    (workspace_dir / "arch-doc").mkdir(parents=True)

    session = WorkflowSessionRecord(
        session_id="wf-response-restart-prefill",
        product_name="Arch Docs Gateway",
        analysis_scope="full",
        repositories=[RepositoryExecution(repository_name="repo-a", repository_url="https://github.com/org/repo-a.git")],
    )
    record = WorkflowRecord(
        workflow_id="wf-response-restart-prefill",
        conversation_id="conv-response-restart-prefill",
        workspace_dir=str(workspace_dir),
        arch_repo_dir=str(workspace_dir / "arch-doc"),
        workflow_status=WorkflowStatus.FAILED,
        session=session,
    )
    get_workflow_registry()["wf-response-restart-prefill"] = record
    await persist_workflow_record(record)

    fake_checkpointer = MagicMock()
    fake_checkpointer.adelete_thread = AsyncMock()

    with patch("app.services.init_arch_workflow.get_checkpointer", new=AsyncMock(return_value=fake_checkpointer)):
        resp = await async_client.post(
            "/api/rest/responses/wf-response-restart-prefill/actions/",
            json={"action_type": "restart"},
            headers=auth_headers,
        )

    assert resp.status_code == 202
    data = resp.json()
    assert data["active_response"] is None
    assert data["previous_init_input"] == {
        "product_name": "Arch Docs Gateway",
        "analysis_scope": "full",
        "workspace_dir": str(workspace_dir),
        "arch_repo_dir": str(workspace_dir / "arch-doc"),
        "repo_list": ["https://github.com/org/repo-a.git"],
    }


async def test_post_response_action_retry_delegates_to_workflow(async_client, auth_headers):
    get_workflow_registry()["wf-response-retry"] = WorkflowRecord(
        workflow_id="wf-response-retry",
        conversation_id="conv-response-retry",
        workflow_status=WorkflowStatus.INTERRUPTED,
        pending_interrupt={"interrupt_type": "step_failed", "step_id": "clone_repositories"},
    )

    with patch("app.services.init_arch_workflow.schedule_resume") as mock_schedule_resume:
        resp = await async_client.post(
            "/api/rest/responses/wf-response-retry/actions/",
            json={"action_type": "retry"},
            headers=auth_headers,
        )

    assert resp.status_code == 202
    data = resp.json()
    assert data["response_id"] == "wf-response-retry"
    mock_schedule_resume.assert_called_once_with(
        get_workflow_registry()["wf-response-retry"], resume_value={"action": "retry"}
    )


async def test_create_response_update_arch_returns_202(async_client, auth_headers):
    payload = {
        "conversation_id": "conv-update",
        "workflow_type": "update_arch",
        "input": {
            "repo_path": "/workspace/svc",
            "diff_context": "diff --git a/x b/x",
            "engine_name": "claude",
            "timeout_seconds": 60,
        },
    }

    resp = await async_client.post("/api/rest/responses/", json=payload, headers=auth_headers)

    assert resp.status_code == 202
    data = resp.json()
    assert data["conversation_id"] == "conv-update"
    assert data["workflow_type"] == "update_arch"
    assert data["response_status"] == "pending"
    assert data["response_id"] in get_registry()


async def test_get_response_returns_task_backed_response(async_client, auth_headers):
    cli_task = CliTask(
        task_id="11111111-1111-1111-1111-111111111111",
        engine_name="claude",
        prompt_text="/update-repo-arch-skill",
        workspace_dir="/workspace/svc",
        task_status=TaskStatus.SUCCESS,
        task_result="docs updated",
        conversation_id="conv-task-response",
        response_type="update_arch",
    )
    get_registry()[cli_task.task_id] = cli_task

    resp = await async_client.get(f"/api/rest/responses/{cli_task.task_id}/", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["response_id"] == cli_task.task_id
    assert data["conversation_id"] == "conv-task-response"
    assert data["workflow_type"] == "update_arch"
    assert data["response_status"] == "success"
    assert data["terminal_result"] == {"output_text": "docs updated"}


async def test_stream_conversation_supports_task_backed_response(async_client, auth_headers):
    cli_task = CliTask(
        task_id="22222222-2222-2222-2222-222222222222",
        engine_name="claude",
        prompt_text="Прочитай arch-doc/ и ответь",
        workspace_dir="/workspace/svc",
        task_status=TaskStatus.SUCCESS,
        conversation_id="conv-task-stream",
        response_type="query",
    )
    cli_task.stdout_lines = ["answer line"]
    get_registry()[cli_task.task_id] = cli_task

    resp = await async_client.get("/api/rest/conversations/conv-task-stream/stream/", headers=auth_headers)

    assert resp.status_code == 200
    assert "answer line" in resp.text
    assert "done" in resp.text


async def test_get_conversation_returns_404_when_missing(async_client, auth_headers):
    resp = await async_client.get("/api/rest/conversations/missing/", headers=auth_headers)

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


async def test_list_conversation_items_returns_404_when_missing(async_client, auth_headers):
    resp = await async_client.get("/api/rest/conversations/missing/items/", headers=auth_headers)

    assert resp.status_code == 404


async def test_stream_conversation_returns_empty_stream_without_active_response(
    async_client, auth_headers, monkeypatch
):
    async def _fake_get_conversation_async(_conversation_id: str):
        return {
            "conversation_id": "conv-empty",
            "created_at": "2026-07-09T00:00:00+00:00",
            "updated_at": "2026-07-09T00:00:00+00:00",
            "active_response": None,
        }

    monkeypatch.setattr("app.api.rest.conversations.get_conversation_async", _fake_get_conversation_async)

    resp = await async_client.get("/api/rest/conversations/conv-empty/stream/", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.text == ""


async def test_create_response_returns_422_for_validation_error(async_client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        "app.api.rest.conversations.create_response_async",
        AsyncMock(side_effect=RuntimeError("bad request")),
    )
    monkeypatch.setattr("app.api.rest.conversations.WorkflowValidationError", RuntimeError)

    resp = await async_client.post(
        "/api/rest/responses/",
        json={"conversation_id": "conv", "workflow_type": "query", "input": {}},
        headers=auth_headers,
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "bad request"


async def test_get_response_returns_404_when_missing(async_client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        "app.api.rest.conversations.get_response_async",
        AsyncMock(side_effect=RuntimeError("missing")),
    )
    monkeypatch.setattr("app.api.rest.conversations.WorkflowNotFoundError", RuntimeError)

    resp = await async_client.get("/api/rest/responses/missing/", headers=auth_headers)

    assert resp.status_code == 404


async def test_submit_response_action_returns_422_for_validation_error(async_client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        "app.api.rest.conversations.submit_response_action_async",
        AsyncMock(side_effect=RuntimeError("bad action")),
    )
    monkeypatch.setattr("app.api.rest.conversations.WorkflowValidationError", RuntimeError)

    resp = await async_client.post(
        "/api/rest/responses/wf-1/actions/",
        json={"action_type": "resume"},
        headers=auth_headers,
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "bad action"


async def test_legacy_rest_workflow_endpoints_removed(async_client, auth_headers):
    resp = await async_client.get("/api/rest/workflows/legacy-id/", headers=auth_headers)

    assert resp.status_code == 404


async def test_get_response_includes_path_metadata(async_client, auth_headers, monkeypatch):
    payload = {
        "response_id": "wf-1",
        "conversation_id": "conv-1",
        "workflow_type": "init_arch",
        "response_status": "running",
        "current_step_id": "define_scope",
        "current_repo_name": "",
        "completed_steps": [],
        "required_actions": [],
        "created_at": "2026-07-14T00:00:00+00:00",
        "updated_at": "2026-07-14T00:00:00+00:00",
        "error_message": None,
        "terminal_result": None,
        "workspace_dir": "/workspace",
        "arch_repo_dir": "/workspace/arch",
    }
    monkeypatch.setattr("app.api.rest.conversations.get_response_async", AsyncMock(return_value=payload))

    response = await async_client.get("/api/rest/responses/wf-1/", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["workspace_dir"] == "/workspace"
    assert response.json()["arch_repo_dir"] == "/workspace/arch"


async def test_legacy_rpc_workflow_endpoints_removed(async_client, auth_headers):
    resp = await async_client.post(
        "/api/rpc/workflows/init/",
        json={
            "product_name": "TestProduct",
            "analysis_scope": "full",
            "workspace_dir": "/workspace/test",
            "arch_repo_dir": "/workspace/test/arch-doc",
            "repo_list": ["test-repo"],
            "engine_name": "claude",
            "timeout_seconds": 60,
        },
        headers=auth_headers,
    )

    assert resp.status_code == 404
