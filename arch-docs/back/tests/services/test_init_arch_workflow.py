from __future__ import annotations

import asyncio
import datetime
import types
import unittest.mock
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import init_arch_workflow as workflow_module
from app.services.task_registry import CliTask, TaskStatus
from app.services.workflow_event_bus import get_workflow_event_bus, reset_workflow_event_bus
from app.services.workflow_registry import WorkflowRecord, WorkflowStatus, reset_workflow_registry
from app.workflows.init_arch.domain import (
    OpenQuestionRecord,
    RepositoryExecution,
    StepId,
    WorkflowSessionRecord,
)


@pytest.fixture(autouse=True)
def clean_workflow_registry():
    reset_workflow_registry()
    reset_workflow_event_bus()
    yield
    reset_workflow_registry()
    reset_workflow_event_bus()


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


async def test_confirm_init_arch_temporal_window_schedules_resume():
    record = WorkflowRecord(
        workflow_id="wf-window",
        conversation_id="conv-window",
        workflow_status=WorkflowStatus.INTERRUPTED,
        current_step_id="confirm_next_temporal_window",
        pending_interrupt={
            "interrupt_type": "temporal_window_confirmation",
            "next_snapshot_at": "2024-07-10",
        },
    )
    workflow_module.get_workflow_registry()["wf-window"] = record

    with (
        patch("app.services.init_arch_workflow.schedule_resume") as mock_schedule_resume,
        patch("app.services.init_arch_workflow.persist_workflow_record", new=AsyncMock()) as mock_persist,
    ):
        resolved = await workflow_module.confirm_init_arch_temporal_window(
            "wf-window", action="continue_to_next_window"
        )

    assert resolved.workflow_id == "wf-window"
    mock_schedule_resume.assert_called_once_with(record, resume_value={"action": "continue_to_next_window"})
    mock_persist.assert_awaited_once_with(record)


async def test_confirm_init_arch_temporal_window_rejects_wrong_interrupt_type():
    record = WorkflowRecord(
        workflow_id="wf-wrong-interrupt",
        workflow_status=WorkflowStatus.INTERRUPTED,
        pending_interrupt={"interrupt_type": "user_question", "question_id": "Q-1"},
    )
    workflow_module.get_workflow_registry()["wf-wrong-interrupt"] = record

    with pytest.raises(workflow_module.WorkflowConflictError, match="not waiting for a temporal window confirmation"):
        await workflow_module.confirm_init_arch_temporal_window("wf-wrong-interrupt", action="continue_to_next_window")


async def test_confirm_init_arch_temporal_window_rejects_unsupported_action():
    record = WorkflowRecord(
        workflow_id="wf-bad-action",
        workflow_status=WorkflowStatus.INTERRUPTED,
        pending_interrupt={"interrupt_type": "temporal_window_confirmation"},
    )
    workflow_module.get_workflow_registry()["wf-bad-action"] = record

    with pytest.raises(
        workflow_module.WorkflowValidationError, match="Unsupported temporal window confirmation action"
    ):
        await workflow_module.confirm_init_arch_temporal_window("wf-bad-action", action="not_a_real_action")


def test_build_resume_value_supports_temporal_window_confirmation():
    resume_value = workflow_module.build_resume_value(
        interrupt_type="temporal_window_confirmation",
        field=None,
        value="finish_temporal_analysis",
        answer=None,
    )

    assert resume_value == {"action": "finish_temporal_analysis"}


async def test_submit_response_action_async_dispatches_confirm_temporal_window():
    record = WorkflowRecord(
        workflow_id="wf-dispatch",
        workflow_status=WorkflowStatus.INTERRUPTED,
        pending_interrupt={"interrupt_type": "temporal_window_confirmation"},
    )
    workflow_module.get_workflow_registry()["wf-dispatch"] = record

    with (
        patch("app.services.init_arch_workflow.confirm_init_arch_temporal_window", new=AsyncMock()) as mock_confirm,
        patch("app.services.init_arch_workflow.get_response_async", new=AsyncMock(return_value={"ok": True})),
    ):
        result = await workflow_module.submit_response_action_async(
            "wf-dispatch", action_type="confirm_temporal_window", value="continue_to_next_window"
        )

    mock_confirm.assert_awaited_once_with("wf-dispatch", action="continue_to_next_window")
    assert result == {"ok": True}


async def test_submit_response_action_async_requires_value_for_confirm_temporal_window():
    record = WorkflowRecord(workflow_id="wf-no-value", workflow_status=WorkflowStatus.INTERRUPTED)
    workflow_module.get_workflow_registry()["wf-no-value"] = record

    with pytest.raises(workflow_module.WorkflowValidationError, match="confirm_temporal_window requires a value"):
        await workflow_module.submit_response_action_async("wf-no-value", action_type="confirm_temporal_window")


async def test_retry_init_arch_workflow_schedules_resume():
    record = WorkflowRecord(
        workflow_id="wf-retry",
        conversation_id="conv-retry",
        workflow_status=WorkflowStatus.INTERRUPTED,
        current_step_id="clone_repositories",
        pending_interrupt={
            "interrupt_type": "step_failed",
            "step_id": "clone_repositories",
            "error": "boom",
            "retry_count": 3,
        },
    )
    workflow_module.get_workflow_registry()["wf-retry"] = record

    with (
        patch("app.services.init_arch_workflow.schedule_resume") as mock_schedule_resume,
        patch("app.services.init_arch_workflow.persist_workflow_record", new=AsyncMock()) as mock_persist,
    ):
        resolved = await workflow_module.retry_init_arch_workflow("wf-retry", action="retry")

    assert resolved.workflow_id == "wf-retry"
    mock_schedule_resume.assert_called_once_with(record, resume_value={"action": "retry"})
    mock_persist.assert_awaited_once_with(record)


async def test_retry_init_arch_workflow_requires_interrupted_status():
    record = WorkflowRecord(workflow_id="wf-not-interrupted", workflow_status=WorkflowStatus.RUNNING)
    workflow_module.get_workflow_registry()["wf-not-interrupted"] = record

    with pytest.raises(workflow_module.WorkflowConflictError, match="not interrupted"):
        await workflow_module.retry_init_arch_workflow("wf-not-interrupted")


async def test_retry_init_arch_workflow_requires_step_failed_interrupt_type():
    record = WorkflowRecord(
        workflow_id="wf-wrong-interrupt-retry",
        workflow_status=WorkflowStatus.INTERRUPTED,
        pending_interrupt={"interrupt_type": "user_question", "question_id": "Q-1"},
    )
    workflow_module.get_workflow_registry()["wf-wrong-interrupt-retry"] = record

    with pytest.raises(workflow_module.WorkflowConflictError, match="not waiting for a step failure recovery"):
        await workflow_module.retry_init_arch_workflow("wf-wrong-interrupt-retry")


async def test_retry_init_arch_workflow_rejects_invalid_action():
    record = WorkflowRecord(
        workflow_id="wf-bad-retry-action",
        workflow_status=WorkflowStatus.INTERRUPTED,
        pending_interrupt={"interrupt_type": "step_failed"},
    )
    workflow_module.get_workflow_registry()["wf-bad-retry-action"] = record

    with pytest.raises(workflow_module.WorkflowValidationError, match="Unsupported step failure recovery action"):
        await workflow_module.retry_init_arch_workflow("wf-bad-retry-action", action="not_a_real_action")


def test_build_resume_value_supports_step_failed():
    resume_value = workflow_module.build_resume_value(
        interrupt_type="step_failed",
        field=None,
        value="abort",
        answer=None,
    )

    assert resume_value == {"action": "abort"}


async def test_submit_response_action_async_dispatches_pause():
    record = WorkflowRecord(workflow_id="wf-pause-dispatch", workflow_status=WorkflowStatus.RUNNING)
    workflow_module.get_workflow_registry()["wf-pause-dispatch"] = record

    with (
        patch("app.services.init_arch_workflow.pause_init_arch_workflow", new=AsyncMock()) as mock_pause,
        patch("app.services.init_arch_workflow.get_response_async", new=AsyncMock(return_value={"ok": True})),
    ):
        result = await workflow_module.submit_response_action_async("wf-pause-dispatch", action_type="pause")

    mock_pause.assert_awaited_once_with("wf-pause-dispatch")
    assert result == {"ok": True}


async def test_submit_response_action_async_dispatches_continue():
    record = WorkflowRecord(workflow_id="wf-continue-dispatch", workflow_status=WorkflowStatus.PAUSED)
    workflow_module.get_workflow_registry()["wf-continue-dispatch"] = record

    with (
        patch("app.services.init_arch_workflow.continue_init_arch_workflow", new=AsyncMock()) as mock_continue,
        patch("app.services.init_arch_workflow.get_response_async", new=AsyncMock(return_value={"ok": True})),
    ):
        result = await workflow_module.submit_response_action_async("wf-continue-dispatch", action_type="continue")

    mock_continue.assert_awaited_once_with("wf-continue-dispatch")
    assert result == {"ok": True}


async def test_submit_response_action_async_dispatches_retry():
    record = WorkflowRecord(
        workflow_id="wf-retry-dispatch",
        workflow_status=WorkflowStatus.INTERRUPTED,
        pending_interrupt={"interrupt_type": "step_failed"},
    )
    workflow_module.get_workflow_registry()["wf-retry-dispatch"] = record

    with (
        patch("app.services.init_arch_workflow.retry_init_arch_workflow", new=AsyncMock()) as mock_retry,
        patch("app.services.init_arch_workflow.get_response_async", new=AsyncMock(return_value={"ok": True})),
    ):
        result = await workflow_module.submit_response_action_async("wf-retry-dispatch", action_type="retry")

    mock_retry.assert_awaited_once_with("wf-retry-dispatch", action="retry")
    assert result == {"ok": True}


async def test_submit_response_action_async_dispatches_retry_with_explicit_abort_value():
    record = WorkflowRecord(
        workflow_id="wf-retry-abort-dispatch",
        workflow_status=WorkflowStatus.INTERRUPTED,
        pending_interrupt={"interrupt_type": "step_failed"},
    )
    workflow_module.get_workflow_registry()["wf-retry-abort-dispatch"] = record

    with (
        patch("app.services.init_arch_workflow.retry_init_arch_workflow", new=AsyncMock()) as mock_retry,
        patch("app.services.init_arch_workflow.get_response_async", new=AsyncMock(return_value={"ok": True})),
    ):
        result = await workflow_module.submit_response_action_async(
            "wf-retry-abort-dispatch", action_type="retry", value="abort"
        )

    mock_retry.assert_awaited_once_with("wf-retry-abort-dispatch", action="abort")
    assert result == {"ok": True}


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


def test_conversation_item_to_sse_payload_maps_actor_and_llm_event_types():
    payload = workflow_module._conversation_item_to_sse_payload(
        {
            "item_kind": "llm_task_requested",
            "actor": "llm_worker",
            "step_id": "analyze_repositories",
            "payload": {"llm_call_id": "call-1", "prompt_text": "do work"},
        }
    )

    assert payload["event_type"] == "llm_call_started"
    assert payload["actor"] == "llm"
    assert payload["prompt_text"] == "do work"


def test_conversation_item_to_sse_payload_step_transition_includes_label():
    payload = workflow_module._conversation_item_to_sse_payload(
        {
            "item_kind": "step_transition",
            "step_id": "analyze_repositories",
            "payload": {"current_step_id": "analyze_repositories", "current_repo_name": "svc-a"},
        }
    )

    assert payload == {
        "event_type": "step_started",
        "actor": "workflow",
        "step_id": "analyze_repositories",
        "step_label": "Анализ репозиториев",
        "repo_name": "svc-a",
    }


def test_conversation_item_to_sse_payload_defaults_unknown_actor_to_workflow():
    payload = workflow_module._conversation_item_to_sse_payload(
        {"item_kind": "artifact_written", "payload": {"artifact_path": "features/x.md"}}
    )

    assert payload["actor"] == "workflow"
    assert payload["event_type"] == "artifact_written"


def test_terminal_event_for_status_reports_paused_with_step_meta():
    record = WorkflowRecord(
        workflow_id="wf-paused",
        workflow_status=WorkflowStatus.PAUSED,
        current_step_id="analyze_repositories",
        current_repo_name="svc-a",
    )

    event = workflow_module._terminal_event_for_status(record)

    assert event == {
        "event_type": "workflow_paused",
        "actor": "workflow",
        "step_id": "analyze_repositories",
        "step_label": "Анализ репозиториев",
        "repo_name": "svc-a",
    }


async def test_stream_persisted_workflow_events_reports_paused_status():
    record = WorkflowRecord(
        workflow_id="wf-paused-replay",
        workflow_status=WorkflowStatus.PAUSED,
        current_step_id="interview_user",
    )

    with (
        patch("app.services.init_arch_workflow.get_workflow_record_async", new=AsyncMock(return_value=record)),
        patch("app.services.init_arch_workflow.list_workflow_events_async", new=AsyncMock(return_value=[])),
    ):
        chunks = [chunk async for chunk in workflow_module._stream_persisted_workflow_events("wf-paused-replay")]

    assert any("workflow_paused" in chunk for chunk in chunks)


async def test_stream_live_workflow_events_forwards_bus_events_before_terminal():
    record = WorkflowRecord(
        workflow_id="wf-live",
        conversation_id="wf-live",
        workflow_status=WorkflowStatus.RUNNING,
        current_step_id="define_scope",
    )
    workflow_module.get_workflow_registry()["wf-live"] = record
    bus = get_workflow_event_bus()

    gen = workflow_module._stream_live_workflow_events("wf-live")
    try:
        first_chunk = await gen.__anext__()
        assert '"event_type": "step_started"' in first_chunk
        assert "define_scope" in first_chunk

        bus.publish("wf-live", {"event_type": "llm_call_started", "actor": "llm", "prompt_text": "hi"})
        second_chunk = await gen.__anext__()
        assert '"event_type": "llm_call_started"' in second_chunk
        assert '"prompt_text": "hi"' in second_chunk

        record.workflow_status = WorkflowStatus.SUCCESS
        remaining = [chunk async for chunk in gen]
        assert any("workflow_done" in chunk for chunk in remaining)
    finally:
        await gen.aclose()

    # generator's `finally: bus.unsubscribe(...)` must have run by now (loop `break` on
    # workflow_done, or the `aclose()` above as a safety net) - no dangling queue left behind.
    assert "wf-live" not in bus._subscribers


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


async def test_start_init_arch_workflow_parses_urls_into_repository_name_and_url(monkeypatch):
    created_tasks = []
    real_create_task = asyncio.create_task

    def _fake_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", AsyncMock())
    monkeypatch.setattr("app.services.init_arch_workflow.asyncio.create_task", _fake_create_task)
    monkeypatch.setattr("app.services.init_arch_workflow.run_workflow", AsyncMock())
    # no host has a PAT configured here, so SSH-form URLs must be left untouched
    monkeypatch.setattr("app.services.init_arch_workflow.list_configured_hosts", AsyncMock(return_value=[]))

    record = await workflow_module.start_init_arch_workflow(
        product_name="svc",
        analysis_scope="full",
        workspace_dir="/workspace",
        arch_repo_dir="/workspace/arch",
        repo_list=[
            "https://github.com/org/svc-a.git",
            "git@github.com:org/svc-b.git",
            "svc-c",
        ],
        engine_name="claude",
        timeout_seconds=30,
        conversation_id="conv-start-urls",
    )

    repos = {repo.repository_name: repo.repository_url for repo in record.session.repositories}
    assert repos == {
        "svc-a": "https://github.com/org/svc-a.git",
        "svc-b": "git@github.com:org/svc-b.git",
        "svc-c": "",
    }
    for task in created_tasks:
        task.cancel()


async def test_start_init_arch_workflow_rewrites_ssh_url_to_https_when_pat_configured(monkeypatch):
    # A PAT only ever authenticates the HTTPS transport, so an SSH-form URL for a host that
    # has a PAT (and no deploy key) must be rewritten, or cloning will always fail.
    created_tasks = []
    real_create_task = asyncio.create_task

    def _fake_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", AsyncMock())
    monkeypatch.setattr("app.services.init_arch_workflow.asyncio.create_task", _fake_create_task)
    monkeypatch.setattr("app.services.init_arch_workflow.run_workflow", AsyncMock())
    monkeypatch.setattr(
        "app.services.init_arch_workflow.list_configured_hosts", AsyncMock(return_value=["gt.tropass.me"])
    )

    record = await workflow_module.start_init_arch_workflow(
        product_name="svc",
        analysis_scope="full",
        workspace_dir="/workspace",
        arch_repo_dir="/workspace/arch",
        repo_list=[
            "git@gt.tropass.me:futureproject/frontend/admin.git",
            "https://gt.tropass.me/futureproject/backend/billing",
            "https://gt.tropass.me/futureproject/backend/cupol.git/",
        ],
        engine_name="claude",
        timeout_seconds=30,
        conversation_id="conv-start-pat",
    )

    repos = {repo.repository_name: repo.repository_url for repo in record.session.repositories}
    assert repos == {
        "admin": "https://gt.tropass.me/futureproject/frontend/admin.git",
        "billing": "https://gt.tropass.me/futureproject/backend/billing.git",
        "cupol": "https://gt.tropass.me/futureproject/backend/cupol.git",
    }
    for task in created_tasks:
        task.cancel()


async def test_start_init_arch_workflow_rejects_arch_repo_inside_raw_workspace(monkeypatch):
    monkeypatch.setattr(
        "app.services.init_arch_workflow.get_gateway_settings",
        lambda: workflow_module.GatewaySettings(
            auth_secret="secret",
            workflows={"init": {"raw_workspace_subdir": ".raw"}},
        ),
    )

    with pytest.raises(workflow_module.WorkflowValidationError, match="must not live inside raw workspace"):
        await workflow_module.start_init_arch_workflow(
            product_name="svc",
            analysis_scope="full",
            workspace_dir="/workspace",
            arch_repo_dir="/workspace/.raw/arch-doc",
            repo_list=["repo-a"],
            engine_name="claude",
            timeout_seconds=30,
            conversation_id="conv-start",
        )


async def test_run_workflow_writes_progress_snapshot_after_each_step(monkeypatch, tmp_path):
    progress_file = tmp_path / "arch-doc" / "repo-initialization-progress.yaml"
    initial_session = WorkflowSessionRecord(
        session_id="wf-snapshot",
        product_name="Prod",
        analysis_scope="full",
    )
    advanced_session = initial_session.model_copy(
        update={"current_step": StepId.REQUEST_REPOSITORY_LIST, "completed_steps": [StepId.DEFINE_SCOPE]}
    )
    final_session = advanced_session.model_copy(update={"current_step": StepId.DONE})
    record = WorkflowRecord(workflow_id="wf-snapshot", conversation_id="conv-snapshot", session=initial_session)

    state_after_define_scope = {
        "session_id": "wf-snapshot",
        "session": advanced_session,
        "workspace_dir": str(tmp_path),
        "arch_repo_dir": str(tmp_path / "arch-doc"),
        "engine_name": "claude",
        "timeout_seconds": 600,
        "progress_file_path": str(progress_file),
    }
    state_after_finalize = {**state_after_define_scope, "session": final_session}

    class _Graph:
        def __init__(self) -> None:
            self._states = iter([state_after_define_scope, state_after_finalize])

        async def astream(self, _state, *, config):
            assert config == {"configurable": {"thread_id": "wf-snapshot"}}
            yield {"define_scope": {"session": advanced_session, "current_step_id": "request_repository_list"}}
            yield {"finalize_progress": {"session": final_session, "current_step_id": "done"}}

        async def aget_state(self, config):
            del config
            return types.SimpleNamespace(values=next(self._states))

    async def _fake_persist(current: WorkflowRecord) -> None:
        del current

    def _compile_graph(checkpointer):
        del checkpointer
        return _Graph()

    monkeypatch.setattr("app.services.init_arch_workflow.get_checkpointer", AsyncMock(return_value="checkpoint"))
    monkeypatch.setattr("app.services.init_arch_workflow.compile_graph", _compile_graph)
    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", _fake_persist)

    await workflow_module.run_workflow(
        record,
        workflow_module.InitArchState(
            session_id=initial_session.session_id,
            session=initial_session,
            workspace_dir=str(tmp_path),
            arch_repo_dir=str(tmp_path / "arch-doc"),
            engine_name="claude",
            timeout_seconds=600,
            progress_file_path=str(progress_file),
            last_llm_result=None,
            last_guard_output="",
            step_error=None,
            retry_count=0,
        ),
    )

    assert progress_file.exists()
    from app.workflows.init_arch.snapshot import parse_snapshot_yaml

    restored = parse_snapshot_yaml(progress_file.read_text(encoding="utf-8"))
    assert restored.session.current_step is StepId.DONE


async def test_run_workflow_happy_path_persists_node_progress_and_terminal_success(monkeypatch):
    initial_session = WorkflowSessionRecord(
        session_id="wf-happy",
        product_name="arch-docs",
        analysis_scope="full",
    )
    advanced_session = initial_session.model_copy(
        update={
            "current_step": StepId.REQUEST_REPOSITORY_LIST,
            "completed_steps": [StepId.DEFINE_SCOPE],
        }
    )
    final_session = advanced_session.model_copy(
        update={
            "current_step": StepId.DONE,
            "completed_steps": [StepId.DEFINE_SCOPE, StepId.REQUEST_REPOSITORY_LIST],
        }
    )
    record = WorkflowRecord(workflow_id="wf-happy", conversation_id="conv-happy", session=initial_session)
    persisted_states: list[tuple[str, WorkflowStatus]] = []

    class _Graph:
        async def astream(self, _state, *, config):
            assert config == {"configurable": {"thread_id": "wf-happy"}}
            yield {
                "define_scope": {
                    "session": advanced_session,
                    "current_step_id": "request_repository_list",
                    "last_cli_output": "scope done",
                }
            }
            yield {
                "finalize_progress": {
                    "session": final_session,
                    "current_step_id": "done",
                }
            }

        async def aget_state(self, config):
            del config
            return types.SimpleNamespace(values={})

    async def _fake_persist(current: WorkflowRecord) -> None:
        persisted_states.append((current.current_step_id, current.workflow_status))

    def _compile_graph(checkpointer):
        del checkpointer
        return _Graph()

    monkeypatch.setattr("app.services.init_arch_workflow.get_checkpointer", AsyncMock(return_value="checkpoint"))
    monkeypatch.setattr("app.services.init_arch_workflow.compile_graph", _compile_graph)
    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", _fake_persist)

    await workflow_module.run_workflow(
        record,
        workflow_module.InitArchState(
            session_id=initial_session.session_id,
            session=initial_session,
            workspace_dir="/workspace",
            arch_repo_dir="/workspace/arch-doc",
            engine_name="claude",
            timeout_seconds=60,
            progress_file_path="/workspace/arch-doc/progress.yaml",
            last_llm_result=None,
            last_guard_output="",
            step_error=None,
            retry_count=0,
        ),
    )

    assert record.workflow_status is WorkflowStatus.SUCCESS
    assert record.current_step_id == "done"
    assert record.completed_steps == ["define_scope", "request_repository_list"]
    assert record.last_cli_output_snippet == "scope done"
    assert persisted_states == [
        ("request_repository_list", WorkflowStatus.RUNNING),
        ("done", WorkflowStatus.RUNNING),
        ("done", WorkflowStatus.SUCCESS),
    ]


async def test_run_workflow_interrupt_persists_pending_question(monkeypatch):
    session = WorkflowSessionRecord(
        session_id="wf-interrupt",
        product_name="arch-docs",
        analysis_scope="full",
        current_step=StepId.INTERVIEW_USER,
    )
    record = WorkflowRecord(workflow_id="wf-interrupt", conversation_id="conv-interrupt", session=session)
    persisted_statuses: list[WorkflowStatus] = []

    class _Graph:
        async def astream(self, _state, *, config):
            assert config == {"configurable": {"thread_id": "wf-interrupt"}}
            yield {
                "__interrupt__": [
                    types.SimpleNamespace(
                        value={
                            "interrupt_type": "user_question",
                            "question_id": "Q-1",
                            "question": "What transport?",
                        }
                    )
                ]
            }

        async def aget_state(self, config):
            del config
            return types.SimpleNamespace(values={})

    async def _fake_persist(current: WorkflowRecord) -> None:
        persisted_statuses.append(current.workflow_status)

    def _compile_graph(checkpointer):
        del checkpointer
        return _Graph()

    monkeypatch.setattr("app.services.init_arch_workflow.get_checkpointer", AsyncMock(return_value="checkpoint"))
    monkeypatch.setattr("app.services.init_arch_workflow.compile_graph", _compile_graph)
    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", _fake_persist)

    await workflow_module.run_workflow(
        record,
        workflow_module.InitArchState(
            session_id=session.session_id,
            session=session,
            workspace_dir="/workspace",
            arch_repo_dir="/workspace/arch-doc",
            engine_name="claude",
            timeout_seconds=60,
            progress_file_path="/workspace/arch-doc/progress.yaml",
            last_llm_result=None,
            last_guard_output="",
            step_error=None,
            retry_count=0,
        ),
    )

    assert record.workflow_status is WorkflowStatus.INTERRUPTED
    assert record.pending_interrupt == {
        "interrupt_type": "user_question",
        "question_id": "Q-1",
        "question": "What transport?",
    }
    assert persisted_statuses == [WorkflowStatus.INTERRUPTED]


async def test_run_workflow_failure_marks_record_failed(monkeypatch):
    session = WorkflowSessionRecord(session_id="wf-failed", product_name="arch-docs", analysis_scope="full")
    record = WorkflowRecord(workflow_id="wf-failed", conversation_id="conv-failed", session=session)
    persisted_statuses: list[WorkflowStatus] = []

    class _Graph:
        async def astream(self, _state, *, config):
            assert config == {"configurable": {"thread_id": "wf-failed"}}
            if False:
                yield {}
            raise ValueError("graph boom")

        async def aget_state(self, config):
            del config
            return types.SimpleNamespace(values={})

    async def _fake_persist(current: WorkflowRecord) -> None:
        persisted_statuses.append(current.workflow_status)

    def _compile_graph(checkpointer):
        del checkpointer
        return _Graph()

    monkeypatch.setattr("app.services.init_arch_workflow.get_checkpointer", AsyncMock(return_value="checkpoint"))
    monkeypatch.setattr("app.services.init_arch_workflow.compile_graph", _compile_graph)
    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", _fake_persist)

    await workflow_module.run_workflow(
        record,
        workflow_module.InitArchState(
            session_id=session.session_id,
            session=session,
            workspace_dir="/workspace",
            arch_repo_dir="/workspace/arch-doc",
            engine_name="claude",
            timeout_seconds=60,
            progress_file_path="/workspace/arch-doc/progress.yaml",
            last_llm_result=None,
            last_guard_output="",
            step_error=None,
            retry_count=0,
        ),
    )

    assert record.workflow_status is WorkflowStatus.FAILED
    assert record.error_message == "graph boom"
    assert persisted_statuses == [WorkflowStatus.FAILED]


async def test_run_workflow_marks_failed_when_graph_exhausts_retries_via_handle_error(monkeypatch):
    # The graph's own routing (see graph.py `_route_after_node`) can exhaust step retries and
    # route through the `handle_error` node straight to a clean END, with no Python exception
    # raised. Before this fix `run_workflow` treated any clean `astream` completion as success.
    session = WorkflowSessionRecord(session_id="wf-exhausted", product_name="arch-docs", analysis_scope="full")
    record = WorkflowRecord(workflow_id="wf-exhausted", conversation_id="conv-exhausted", session=session)
    persisted_statuses: list[WorkflowStatus] = []

    class _Graph:
        async def astream(self, _state, *, config):
            assert config == {"configurable": {"thread_id": "wf-exhausted"}}
            yield {
                "define_scope": {
                    "step_error": "Error: When using --print, --output-format=stream-json requires --verbose",
                    "retry_count": 3,
                }
            }
            # real LangGraph reports a node that returned `{}` as `None`, not `{}` (verified
            # against langgraph 1.2.7) - mock the actual shape, not the intuitive one
            yield {"handle_error": None}

        async def aget_state(self, config):
            del config
            return types.SimpleNamespace(values={})

    async def _fake_persist(current: WorkflowRecord) -> None:
        persisted_statuses.append(current.workflow_status)

    def _compile_graph(checkpointer):
        del checkpointer
        return _Graph()

    monkeypatch.setattr("app.services.init_arch_workflow.get_checkpointer", AsyncMock(return_value="checkpoint"))
    monkeypatch.setattr("app.services.init_arch_workflow.compile_graph", _compile_graph)
    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", _fake_persist)

    await workflow_module.run_workflow(
        record,
        workflow_module.InitArchState(
            session_id=session.session_id,
            session=session,
            workspace_dir="/workspace",
            arch_repo_dir="/workspace/arch-doc",
            engine_name="claude",
            timeout_seconds=60,
            progress_file_path="/workspace/arch-doc/progress.yaml",
            last_llm_result=None,
            last_guard_output="",
            step_error=None,
            retry_count=0,
        ),
    )

    assert record.workflow_status is WorkflowStatus.FAILED
    assert record.error_message == "Error: When using --print, --output-format=stream-json requires --verbose"
    assert persisted_statuses[-1] == WorkflowStatus.FAILED


async def test_run_workflow_seeds_checkpoint_via_aupdate_state_when_as_node_given(monkeypatch):
    session = WorkflowSessionRecord(
        session_id="wf-seed",
        product_name="Prod",
        analysis_scope="full",
        current_step=StepId.CLONE_REPOSITORIES,
        completed_steps=[StepId.DEFINE_SCOPE, StepId.REQUEST_REPOSITORY_LIST, StepId.PREPARE_TEMP_WORKSPACE],
    )
    record = WorkflowRecord(workflow_id="wf-seed", conversation_id="conv-seed", session=session)
    final_session = session.model_copy(update={"current_step": StepId.DONE})
    aupdate_state_calls = []

    class _Graph:
        async def aupdate_state(self, config, values, *, as_node):
            aupdate_state_calls.append((config, values, as_node))

        async def astream(self, state_input, *, config):
            del config
            assert state_input is None
            yield {"finalize_progress": {"session": final_session, "current_step_id": "done"}}

        async def aget_state(self, config):
            del config
            return types.SimpleNamespace(values={})

    def _compile_graph(checkpointer):
        del checkpointer
        return _Graph()

    monkeypatch.setattr("app.services.init_arch_workflow.get_checkpointer", AsyncMock(return_value="checkpoint"))
    monkeypatch.setattr("app.services.init_arch_workflow.compile_graph", _compile_graph)
    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", AsyncMock())

    initial_state = workflow_module.InitArchState(
        session_id=session.session_id,
        session=session,
        workspace_dir="/workspace",
        arch_repo_dir="/workspace/arch-doc",
        engine_name="claude",
        timeout_seconds=60,
        progress_file_path="/workspace/arch-doc/progress.yaml",
        last_llm_result=None,
        last_guard_output="",
        step_error=None,
        retry_count=0,
    )

    await workflow_module.run_workflow(record, initial_state, as_node="prepare_temp_workspace")

    assert len(aupdate_state_calls) == 1
    seeded_config, seeded_values, seeded_as_node = aupdate_state_calls[0]
    assert seeded_config == {"configurable": {"thread_id": "wf-seed"}}
    assert seeded_values["session"] == session
    assert seeded_as_node == "prepare_temp_workspace"
    assert record.workflow_status is WorkflowStatus.SUCCESS


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


async def test_pause_init_arch_workflow_rejects_non_running_status():
    record = WorkflowRecord(workflow_id="wf-not-running", workflow_status=WorkflowStatus.INTERRUPTED)
    workflow_module.get_workflow_registry()["wf-not-running"] = record

    with pytest.raises(workflow_module.WorkflowConflictError, match="not pausable"):
        await workflow_module.pause_init_arch_workflow("wf-not-running")


async def test_pause_init_arch_workflow_cancels_task_and_sets_paused_immediately():
    record = WorkflowRecord(workflow_id="wf-pause", workflow_status=WorkflowStatus.RUNNING)
    fake_task = MagicMock()
    fake_task.done.return_value = False
    record.asyncio_task = fake_task
    workflow_module.get_workflow_registry()["wf-pause"] = record

    with patch("app.services.init_arch_workflow.persist_workflow_record", new=AsyncMock()) as mock_persist:
        resolved = await workflow_module.pause_init_arch_workflow("wf-pause")

    assert resolved.workflow_status == WorkflowStatus.PAUSED
    assert resolved.pause_requested is True
    fake_task.cancel.assert_called_once()
    mock_persist.assert_awaited_once_with(record)


async def test_pause_init_arch_workflow_without_live_task_still_sets_paused():
    # e.g. a record rehydrated from the DB in a process that isn't the one running it - there's
    # no asyncio.Task to cancel, but the caller must still see PAUSED, not a stale RUNNING.
    record = WorkflowRecord(workflow_id="wf-pause-no-task", workflow_status=WorkflowStatus.RUNNING)
    workflow_module.get_workflow_registry()["wf-pause-no-task"] = record

    with patch("app.services.init_arch_workflow.persist_workflow_record", new=AsyncMock()):
        resolved = await workflow_module.pause_init_arch_workflow("wf-pause-no-task")

    assert resolved.workflow_status == WorkflowStatus.PAUSED


async def test_continue_init_arch_workflow_rejects_non_paused_status():
    record = WorkflowRecord(workflow_id="wf-not-paused", workflow_status=WorkflowStatus.RUNNING)
    workflow_module.get_workflow_registry()["wf-not-paused"] = record

    with pytest.raises(workflow_module.WorkflowConflictError, match="not paused"):
        await workflow_module.continue_init_arch_workflow("wf-not-paused")


async def test_continue_init_arch_workflow_resumes_from_checkpoint_with_no_resume_value():
    record = WorkflowRecord(workflow_id="wf-continue", workflow_status=WorkflowStatus.PAUSED)
    workflow_module.get_workflow_registry()["wf-continue"] = record
    resume_calls: list[tuple[WorkflowRecord, object]] = []
    created_tasks = []
    real_create_task = asyncio.create_task

    async def _fake_resume_workflow_task(current_record: WorkflowRecord, resume_value: object) -> None:
        resume_calls.append((current_record, resume_value))

    def _fake_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    with (
        patch("app.services.init_arch_workflow.persist_workflow_record", new=AsyncMock()),
        patch("app.services.init_arch_workflow.resume_workflow_task", new=_fake_resume_workflow_task),
        patch("app.services.init_arch_workflow.asyncio.create_task", side_effect=_fake_create_task),
    ):
        resolved = await workflow_module.continue_init_arch_workflow("wf-continue")
        await asyncio.gather(*created_tasks)

    assert resolved.workflow_status == WorkflowStatus.RUNNING
    assert resume_calls == [(record, None)]


async def test_handle_workflow_cancellation_sets_paused_when_pause_was_requested():
    record = WorkflowRecord(
        workflow_id="wf-cancel-branch-paused", workflow_status=WorkflowStatus.RUNNING, pause_requested=True
    )

    with patch("app.services.init_arch_workflow.persist_workflow_record", new=AsyncMock()) as mock_persist:
        await workflow_module._handle_workflow_cancellation(record)

    assert record.workflow_status == WorkflowStatus.PAUSED
    assert record.pause_requested is False
    assert record.error_message is None
    mock_persist.assert_awaited_once_with(record)


async def test_handle_workflow_cancellation_sets_cancelled_when_pause_was_not_requested():
    record = WorkflowRecord(
        workflow_id="wf-cancel-branch-cancelled", workflow_status=WorkflowStatus.RUNNING, pause_requested=False
    )

    with patch("app.services.init_arch_workflow.persist_workflow_record", new=AsyncMock()):
        await workflow_module._handle_workflow_cancellation(record)

    assert record.workflow_status == WorkflowStatus.CANCELLED
    assert record.error_message == "Workflow cancelled"


async def test_run_workflow_cancellation_sets_paused_status_end_to_end(monkeypatch):
    # Mirrors test_run_workflow_failure_marks_record_failed's _Graph fixture, but the graph
    # raises CancelledError (as it would when pause_init_arch_workflow() cancels the task
    # mid-`astream`) instead of a plain exception.
    session = WorkflowSessionRecord(session_id="wf-paused-e2e", product_name="arch-docs", analysis_scope="full")
    record = WorkflowRecord(
        workflow_id="wf-paused-e2e",
        conversation_id="conv-paused-e2e",
        session=session,
        pause_requested=True,
    )

    class _Graph:
        async def astream(self, _state, *, config):
            del config
            if False:
                yield {}
            raise asyncio.CancelledError

        async def aget_state(self, config):
            del config
            return types.SimpleNamespace(values={})

    monkeypatch.setattr("app.services.init_arch_workflow.get_checkpointer", AsyncMock(return_value="checkpoint"))
    monkeypatch.setattr("app.services.init_arch_workflow.compile_graph", lambda **_kwargs: _Graph())
    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", AsyncMock())

    with pytest.raises(asyncio.CancelledError):
        await workflow_module.run_workflow(
            record,
            workflow_module.InitArchState(
                session_id=session.session_id,
                session=session,
                workspace_dir="/workspace",
                arch_repo_dir="/workspace/arch-doc",
                engine_name="claude",
                timeout_seconds=60,
                progress_file_path="/workspace/arch-doc/progress.yaml",
                last_llm_result=None,
                last_guard_output="",
                step_error=None,
                retry_count=0,
            ),
        )

    assert record.workflow_status is WorkflowStatus.PAUSED
    assert record.pause_requested is False


async def test_start_init_arch_workflow_persists_resolved_paths(monkeypatch):
    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", AsyncMock())
    monkeypatch.setattr("app.services.init_arch_workflow.asyncio.create_task", asyncio.create_task)
    monkeypatch.setattr("app.services.init_arch_workflow.run_workflow", AsyncMock())

    record = await workflow_module.start_init_arch_workflow(
        product_name="svc",
        analysis_scope="full",
        workspace_dir="/workspace",
        arch_repo_dir="/workspace/arch",
        repo_list=["repo-a"],
        engine_name="claude",
        timeout_seconds=30,
        conversation_id="conv-paths",
    )

    assert record.workspace_dir == "/workspace"
    assert record.arch_repo_dir == "/workspace/arch"
    record.asyncio_task.cancel()


async def test_workflow_response_payload_includes_path_metadata():
    record = workflow_module.WorkflowRecord(
        workflow_id="wf-1",
        conversation_id="conv-1",
        workspace_dir="/workspace",
        arch_repo_dir="/workspace/arch",
    )
    payload = workflow_module._workflow_response_payload(record, [])
    assert payload["workspace_dir"] == "/workspace"
    assert payload["arch_repo_dir"] == "/workspace/arch"


async def test_get_response_arch_repo_dir_async_returns_path(monkeypatch):
    record = workflow_module.WorkflowRecord(workflow_id="wf-2", arch_repo_dir="/workspace/arch")
    monkeypatch.setattr("app.services.init_arch_workflow.get_workflow_record_async", AsyncMock(return_value=record))

    result = await workflow_module.get_response_arch_repo_dir_async("wf-2")

    assert result == "/workspace/arch"


async def test_get_response_arch_repo_dir_async_raises_when_missing(monkeypatch):
    record = workflow_module.WorkflowRecord(workflow_id="wf-3", arch_repo_dir="")
    monkeypatch.setattr("app.services.init_arch_workflow.get_workflow_record_async", AsyncMock(return_value=record))

    with pytest.raises(workflow_module.ArchRepoNotAvailableError):
        await workflow_module.get_response_arch_repo_dir_async("wf-3")


def _make_snapshot_yaml(*, current_step: StepId, completed_steps: list[StepId]) -> str:
    from app.workflows.init_arch.snapshot import WorkflowSnapshot, dump_snapshot_yaml

    session = WorkflowSessionRecord(
        session_id="wf-original",
        product_name="Prod",
        analysis_scope="full",
        current_step=current_step,
        completed_steps=completed_steps,
        repositories=[RepositoryExecution(repository_name="svc-a")],
    )
    snapshot = WorkflowSnapshot(
        workflow_id="wf-original",
        workspace_dir="/old/workspace",
        arch_repo_dir="/old/workspace/arch-doc",
        engine_name="claude",
        timeout_seconds=600,
        updated_at=datetime.datetime.now(datetime.timezone.utc),
        session=session,
    )
    return dump_snapshot_yaml(snapshot)


async def test_resume_init_arch_workflow_from_snapshot_schedules_task_with_as_node(monkeypatch):
    yaml_text = _make_snapshot_yaml(
        current_step=StepId.CLONE_REPOSITORIES,
        completed_steps=[StepId.DEFINE_SCOPE, StepId.REQUEST_REPOSITORY_LIST, StepId.PREPARE_TEMP_WORKSPACE],
    )
    created_tasks = []
    real_create_task = asyncio.create_task

    def _fake_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", AsyncMock())
    monkeypatch.setattr("app.services.init_arch_workflow.asyncio.create_task", _fake_create_task)
    run_workflow_mock = AsyncMock()
    monkeypatch.setattr("app.services.init_arch_workflow.run_workflow", run_workflow_mock)

    record = await workflow_module.resume_init_arch_workflow_from_snapshot(
        yaml_text,
        workspace_dir="/new/workspace",
        arch_repo_dir="/new/workspace/arch-doc",
    )

    assert record.workflow_id != "wf-original"
    assert record.session.session_id == record.workflow_id
    assert record.session.current_step is StepId.CLONE_REPOSITORIES
    assert [repo.repository_name for repo in record.session.repositories] == ["svc-a"]
    assert created_tasks
    # `asyncio.create_task` only schedules the task; give the event loop one tick so the
    # (fully-mocked) `run_workflow` coroutine actually runs and records the await before assertions.
    await asyncio.sleep(0)
    run_workflow_mock.assert_awaited_once()
    _, kwargs = run_workflow_mock.await_args
    assert kwargs["as_node"] == "prepare_temp_workspace"
    for task in created_tasks:
        task.cancel()


async def test_resume_init_arch_workflow_from_snapshot_raises_when_active_workflow_shares_arch_repo_dir(
    monkeypatch,
):
    yaml_text = _make_snapshot_yaml(
        current_step=StepId.CLONE_REPOSITORIES,
        completed_steps=[StepId.DEFINE_SCOPE, StepId.REQUEST_REPOSITORY_LIST, StepId.PREPARE_TEMP_WORKSPACE],
    )
    _, resolved_arch_repo_dir, _ = workflow_module._resolve_init_arch_paths(
        workspace_dir="/new/workspace", arch_repo_dir="/new/workspace/arch-doc"
    )
    workflow_module.get_workflow_registry()["wf-active"] = WorkflowRecord(
        workflow_id="wf-active",
        arch_repo_dir=resolved_arch_repo_dir,
        workflow_status=WorkflowStatus.RUNNING,
    )

    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", AsyncMock())
    create_task_mock = unittest.mock.MagicMock()
    monkeypatch.setattr("app.services.init_arch_workflow.asyncio.create_task", create_task_mock)

    with pytest.raises(workflow_module.WorkflowConflictError, match="wf-active"):
        await workflow_module.resume_init_arch_workflow_from_snapshot(
            yaml_text,
            workspace_dir="/new/workspace",
            arch_repo_dir="/new/workspace/arch-doc",
        )

    create_task_mock.assert_not_called()


async def test_resume_init_arch_workflow_from_snapshot_allows_when_active_workflow_has_different_arch_repo_dir(
    monkeypatch,
):
    yaml_text = _make_snapshot_yaml(
        current_step=StepId.CLONE_REPOSITORIES,
        completed_steps=[StepId.DEFINE_SCOPE, StepId.REQUEST_REPOSITORY_LIST, StepId.PREPARE_TEMP_WORKSPACE],
    )
    workflow_module.get_workflow_registry()["wf-other"] = WorkflowRecord(
        workflow_id="wf-other",
        arch_repo_dir="/some/other/arch-doc",
        workflow_status=WorkflowStatus.RUNNING,
    )

    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", AsyncMock())
    real_create_task = asyncio.create_task
    created_tasks: list[asyncio.Task[None]] = []

    def _fake_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr("app.services.init_arch_workflow.asyncio.create_task", _fake_create_task)
    run_workflow_mock = AsyncMock()
    monkeypatch.setattr("app.services.init_arch_workflow.run_workflow", run_workflow_mock)

    record = await workflow_module.resume_init_arch_workflow_from_snapshot(
        yaml_text,
        workspace_dir="/new/workspace",
        arch_repo_dir="/new/workspace/arch-doc",
    )

    assert record.workflow_id != "wf-other"
    await asyncio.sleep(0)
    run_workflow_mock.assert_awaited_once()
    for task in created_tasks:
        task.cancel()


async def test_resume_init_arch_workflow_from_snapshot_already_done_marks_success_without_task(monkeypatch):
    yaml_text = _make_snapshot_yaml(
        current_step=StepId.DONE,
        completed_steps=[StepId.FINALIZE_PROGRESS],
    )

    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", AsyncMock())
    create_task_mock = unittest.mock.MagicMock()
    monkeypatch.setattr("app.services.init_arch_workflow.asyncio.create_task", create_task_mock)

    record = await workflow_module.resume_init_arch_workflow_from_snapshot(
        yaml_text,
        workspace_dir="/new/workspace",
        arch_repo_dir="/new/workspace/arch-doc",
    )

    assert record.workflow_status == WorkflowStatus.SUCCESS
    create_task_mock.assert_not_called()
