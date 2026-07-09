from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import init_arch_workflow as workflow_module
from app.services.task_registry import CliTask, TaskStatus
from app.services.workflow_registry import WorkflowRecord, WorkflowStatus, reset_workflow_registry
from app.workflows.init_arch.domain import OpenQuestionRecord, RepositoryExecution, StepId, WorkflowSessionRecord


@pytest.fixture(autouse=True)
def clean_workflow_registry():
    reset_workflow_registry()
    yield
    reset_workflow_registry()


async def test_get_workflow_record_async_returns_registry_hit():
    record = WorkflowRecord(workflow_id="wf-1")
    workflow_module.get_workflow_registry()["wf-1"] = record

    resolved = await workflow_module.get_workflow_record_async("wf-1")

    assert resolved is record


async def test_get_workflow_record_async_loads_from_db_when_registry_empty():
    record = WorkflowRecord(workflow_id="wf-db", conversation_id="wf-db")
    fake_session = AsyncMock()

    @asynccontextmanager
    async def _fake_get_session():
        yield fake_session

    with (
        patch("app.services.init_arch_workflow.get_session", _fake_get_session),
        patch("app.services.init_arch_workflow.get_workflow_run", new=AsyncMock(return_value=record)),
    ):
        resolved = await workflow_module.get_workflow_record_async("wf-db")

    assert resolved.workflow_id == "wf-db"
    assert workflow_module.get_workflow_registry()["wf-db"] is resolved


async def test_answer_init_arch_question_loads_interrupted_record_from_db():
    record = WorkflowRecord(
        workflow_id="wf-db-question",
        conversation_id="conv-db-question",
        workflow_status=WorkflowStatus.INTERRUPTED,
        current_step_id="interview_user",
        pending_interrupt={
            "interrupt_type": "user_question",
            "question_id": "Q-7",
            "question": "What transport?",
        },
        session=WorkflowSessionRecord(
            session_id="wf-db-question",
            product_name="arch-docs",
            analysis_scope="full",
            current_step=StepId.INTERVIEW_USER,
            open_questions=[OpenQuestionRecord(question_id="Q-7", question_text="What transport?")],
        ),
    )
    fake_session = AsyncMock()

    @asynccontextmanager
    async def _fake_get_session():
        yield fake_session

    with (
        patch("app.services.init_arch_workflow.get_session", _fake_get_session),
        patch("app.services.init_arch_workflow.get_workflow_run", new=AsyncMock(return_value=record)),
        patch("app.services.init_arch_workflow.schedule_resume") as mock_schedule_resume,
        patch("app.services.init_arch_workflow.persist_workflow_record", new=AsyncMock()) as mock_persist,
    ):
        resolved = await workflow_module.answer_init_arch_question("wf-db-question", question_id="Q-7", answer="REST")

    assert resolved.workflow_id == "wf-db-question"
    mock_schedule_resume.assert_called_once_with(record, resume_value={"answer": "REST"})
    mock_persist.assert_awaited_once_with(record)
    assert workflow_module.get_workflow_registry()["wf-db-question"] is record


async def test_list_workflow_events_async_reads_persisted_conversation_items():
    event = MagicMock()
    event.item_id = "evt-1"
    event.item_kind = "artifact_written"
    event.actor = "service"
    event.step_id = "refine_features"
    event.payload_json = {"artifact_path": "wiki/index.md"}
    event.created_at.isoformat.return_value = "2026-07-09T00:00:00+00:00"
    fake_session = AsyncMock()

    @asynccontextmanager
    async def _fake_get_session():
        yield fake_session

    with (
        patch("app.services.init_arch_workflow.get_session", _fake_get_session),
        patch("app.services.init_arch_workflow.list_conversation_items", new=AsyncMock(return_value=[event])),
    ):
        events = await workflow_module.list_workflow_events_async("wf-events")

    assert events == [
        {
            "item_id": "evt-1",
            "item_kind": "artifact_written",
            "actor": "service",
            "step_id": "refine_features",
            "payload": {"artifact_path": "wiki/index.md"},
            "created_at": "2026-07-09T00:00:00+00:00",
        }
    ]


async def test_get_conversation_async_uses_task_when_it_is_newer():
    task = CliTask(
        task_id="task-1",
        engine_name="claude",
        prompt_text="q",
        workspace_dir="/workspace/repo",
        conversation_id="conv-1",
        response_type="query",
    )
    task.task_status = TaskStatus.SUCCESS
    task.task_result = "answer"
    workflow_module.get_task_registry()[task.task_id] = task
    workflow_module.get_workflow_registry()["wf-1"] = WorkflowRecord(
        workflow_id="wf-1",
        conversation_id="conv-1",
        workflow_status=WorkflowStatus.RUNNING,
        updated_at=task.created_at.replace(year=2025),
    )

    payload = await workflow_module.get_conversation_async("conv-1")

    assert payload["active_response"]["response_id"] == "task-1"
    assert payload["active_response"]["response_status"] == "success"


async def test_get_conversation_async_raises_when_conversation_missing():
    with pytest.raises(workflow_module.WorkflowNotFoundError, match="Conversation 'missing' not found"):
        await workflow_module.get_conversation_async("missing")


async def test_list_conversation_items_async_builds_task_timeline():
    task = CliTask(
        task_id="task-2",
        engine_name="claude",
        prompt_text="q",
        workspace_dir="/workspace/repo",
        conversation_id="conv-items",
        response_type="query",
    )
    task.stdout_lines = ["answer"]
    task.stderr_lines = ["progress"]
    task.task_status = TaskStatus.SUCCESS
    workflow_module.get_task_registry()[task.task_id] = task

    items = await workflow_module.list_conversation_items_async("conv-items")

    assert [item["item_kind"] for item in items] == ["response_started", "progress", "output", "done"]


async def test_create_response_async_update_arch_enqueues_cli_task(monkeypatch):
    monkeypatch.setattr("app.services.init_arch_workflow.create_conversation_async", AsyncMock())
    captured = {}

    def _fake_enqueue(cli_task: CliTask):
        captured["task"] = cli_task
        return cli_task

    monkeypatch.setattr("app.services.init_arch_workflow._enqueue_cli_task", _fake_enqueue)

    payload = await workflow_module.create_response_async(
        conversation_id="conv-update",
        workflow_type="update_arch",
        input_payload={"repo_path": "/repo", "diff_context": "diff", "engine_name": "codex", "timeout_seconds": 12},
    )

    assert payload["workflow_type"] == "update_arch"
    assert captured["task"].prompt_text.startswith("/update-repo-arch-skill")
    assert captured["task"].engine_name == "codex"


async def test_create_response_async_query_validates_required_fields():
    with pytest.raises(workflow_module.WorkflowValidationError, match="query requires repo_path and question"):
        await workflow_module.create_response_async(
            conversation_id="conv-query",
            workflow_type="query",
            input_payload={"repo_path": "/repo"},
        )


async def test_create_response_async_rejects_unsupported_engine(monkeypatch):
    monkeypatch.setattr("app.services.init_arch_workflow.create_conversation_async", AsyncMock())

    with pytest.raises(workflow_module.WorkflowValidationError, match="engine_name must be 'claude' or 'codex'"):
        await workflow_module.create_response_async(
            conversation_id="conv-query",
            workflow_type="query",
            input_payload={"repo_path": "/repo", "question": "what", "engine_name": "gpt"},
        )


async def test_submit_response_action_async_cancels_task_backed_response(monkeypatch):
    task = CliTask(
        task_id="task-cancel",
        engine_name="claude",
        prompt_text="q",
        workspace_dir="/workspace/repo",
        conversation_id="conv-cancel",
        response_type="query",
    )

    monkeypatch.setattr(
        "app.services.init_arch_workflow.get_workflow_record_async",
        AsyncMock(side_effect=workflow_module.WorkflowNotFoundError("missing")),
    )
    monkeypatch.setattr("app.services.init_arch_workflow.get_cli_task_async", AsyncMock(return_value=task))
    monkeypatch.setattr("app.services.init_arch_workflow.cancel_cli_task", AsyncMock())

    payload = await workflow_module.submit_response_action_async("task-cancel", action_type="cancel")

    assert payload["response_id"] == "task-cancel"


async def test_submit_response_action_async_rejects_non_cancel_for_task(monkeypatch):
    task = CliTask(
        task_id="task-action",
        engine_name="claude",
        prompt_text="q",
        workspace_dir="/workspace/repo",
    )

    monkeypatch.setattr(
        "app.services.init_arch_workflow.get_workflow_record_async",
        AsyncMock(side_effect=workflow_module.WorkflowNotFoundError("missing")),
    )
    monkeypatch.setattr("app.services.init_arch_workflow.get_cli_task_async", AsyncMock(return_value=task))

    with pytest.raises(workflow_module.WorkflowValidationError, match="Unsupported action_type"):
        await workflow_module.submit_response_action_async("task-action", action_type="resume")


async def test_stream_persisted_workflow_events_emits_cli_output_and_terminal_status(monkeypatch):
    record = WorkflowRecord(
        workflow_id="wf-stream",
        conversation_id="conv-stream",
        workflow_status=WorkflowStatus.SUCCESS,
        last_cli_output_snippet="last line",
    )

    monkeypatch.setattr("app.services.init_arch_workflow.get_workflow_record_async", AsyncMock(return_value=record))
    monkeypatch.setattr(
        "app.services.init_arch_workflow.list_workflow_events_async",
        AsyncMock(return_value=[{"item_kind": "step_transition", "step_id": "define_scope", "payload": {}}]),
    )

    chunks = [chunk async for chunk in workflow_module._stream_persisted_workflow_events("wf-stream")]

    assert any("step_started" in chunk for chunk in chunks)
    assert any("last line" in chunk for chunk in chunks)
    assert any("workflow_done" in chunk for chunk in chunks)


async def test_stream_task_events_replays_persisted_task(monkeypatch):
    task = CliTask(
        task_id="task-persisted",
        engine_name="claude",
        prompt_text="q",
        workspace_dir="/workspace/repo",
    )
    task.stdout_lines = ["out"]
    task.stderr_lines = ["err"]
    task.task_status = TaskStatus.SUCCESS

    monkeypatch.setattr("app.services.init_arch_workflow.get_cli_task_async", AsyncMock(return_value=task))

    chunks = [chunk async for chunk in workflow_module._stream_task_events("task-persisted")]

    assert any("progress" in chunk for chunk in chunks)
    assert any("output" in chunk for chunk in chunks)
    assert any('"event_type": "done"' in chunk for chunk in chunks)


async def test_start_init_arch_workflow_registers_record_and_schedules_task(monkeypatch):
    created_tasks = []
    real_create_task = asyncio.create_task

    def _fake_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", AsyncMock())
    monkeypatch.setattr("app.services.init_arch_workflow.asyncio.create_task", _fake_create_task)
    monkeypatch.setattr("app.services.init_arch_workflow.run_workflow", AsyncMock())

    record = await workflow_module.start_init_arch_workflow(
        product_name="svc",
        analysis_scope="full",
        workspace_dir="/workspace",
        arch_repo_dir="/workspace/arch",
        repo_list=["repo-a", "repo-b"],
        engine_name="claude",
        timeout_seconds=30,
        conversation_id="conv-start",
    )

    assert record.conversation_id == "conv-start"
    assert [repo.repository_name for repo in record.session.repositories] == ["repo-a", "repo-b"]
    assert created_tasks
    for task in created_tasks:
        task.cancel()


async def test_resume_and_answer_require_interrupted_workflow():
    record = WorkflowRecord(workflow_id="wf-status", workflow_status=WorkflowStatus.RUNNING)
    workflow_module.get_workflow_registry()["wf-status"] = record

    with pytest.raises(workflow_module.WorkflowConflictError, match="not interrupted"):
        await workflow_module.resume_init_arch_workflow("wf-status", field="repo_path", value="/repo", answer=None)

    with pytest.raises(workflow_module.WorkflowConflictError, match="not interrupted"):
        await workflow_module.answer_init_arch_question("wf-status", question_id="Q-1", answer="REST")


async def test_cancel_init_arch_workflow_rejects_terminal_status():
    record = WorkflowRecord(workflow_id="wf-terminal", workflow_status=WorkflowStatus.SUCCESS)
    workflow_module.get_workflow_registry()["wf-terminal"] = record

    with pytest.raises(workflow_module.WorkflowConflictError, match="not cancellable"):
        await workflow_module.cancel_init_arch_workflow("wf-terminal")
