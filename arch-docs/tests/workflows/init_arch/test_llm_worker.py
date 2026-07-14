import unittest.mock

import pytest

from app.services.task_registry import CliTask, TaskStatus
from app.workflows.init_arch.domain import AuditActor, EventType, LlmTaskKind, LlmTaskRequest, StepId
from app.workflows.init_arch.llm_worker import LlmWorkerService, get_llm_worker_service


def _make_request() -> LlmTaskRequest:
    return LlmTaskRequest(
        session_id="wf-1",
        task_kind=LlmTaskKind.STEP_EXECUTION,
        step_id=StepId.DEFINE_SCOPE,
        prompt_text="do work",
        workspace_dir="/workspace",
        timeout_seconds=30,
        expected_schema_name="init_arch_v1",
    )


def _make_cli_task() -> CliTask:
    task = CliTask(
        task_id="task-1",
        engine_name="claude",
        prompt_text="do work",
        workspace_dir="/workspace",
        timeout_seconds=30,
    )
    task.task_status = TaskStatus.SUCCESS
    task.task_result = (
        '{"completed_actions":["updated scope"],"created_artifacts":[],"open_questions_found":[],"notes":"ok"}'
    )
    return task


async def test_llm_worker_service_parses_result_and_emits_audit_events() -> None:
    audit_service = unittest.mock.MagicMock()
    service = LlmWorkerService(audit_service=audit_service)
    request = _make_request()
    cli_task = _make_cli_task()

    with unittest.mock.patch.object(service, "_build_cli_task", return_value=cli_task):
        with unittest.mock.patch.object(service, "_run_cli_task", new=unittest.mock.AsyncMock()) as mock_run:
            result = await service.run_task(request, engine_name="claude")

    mock_run.assert_awaited_once_with(cli_task)
    assert result.completed_actions == ["updated scope"]
    recorded_events = [call.args[0] for call in audit_service.record.call_args_list]
    assert [event.event_type for event in recorded_events] == [
        EventType.LLM_TASK_REQUESTED,
        EventType.LLM_TASK_COMPLETED,
    ]
    assert all(event.actor is AuditActor.LLM_WORKER for event in recorded_events)


async def test_llm_worker_service_emits_failed_event() -> None:
    audit_service = unittest.mock.MagicMock()
    service = LlmWorkerService(audit_service=audit_service)
    request = _make_request()
    cli_task = _make_cli_task()
    cli_task.task_status = TaskStatus.FAILED
    cli_task.task_error = "boom"

    with unittest.mock.patch.object(service, "_build_cli_task", return_value=cli_task):
        with unittest.mock.patch.object(service, "_run_cli_task", new=unittest.mock.AsyncMock()):
            with pytest.raises(RuntimeError, match="boom"):
                await service.run_task(request, engine_name="claude")

    recorded_events = [call.args[0] for call in audit_service.record.call_args_list]
    assert [event.event_type for event in recorded_events] == [
        EventType.LLM_TASK_REQUESTED,
        EventType.LLM_TASK_FAILED,
    ]


async def test_llm_worker_service_fails_over_to_alternative_engine_on_limit_exhaustion() -> None:
    audit_service = unittest.mock.MagicMock()
    service = LlmWorkerService(audit_service=audit_service)
    request = _make_request()
    primary_task = _make_cli_task()
    primary_task.engine_name = "claude"
    primary_task.task_status = TaskStatus.FAILED
    primary_task.task_error = "limit_exhausted: usage limit reached"
    fallback_task = _make_cli_task()
    fallback_task.task_id = "task-2"
    fallback_task.engine_name = "codex"

    build_calls: list[str] = []

    def _build_cli_task(_request, *, engine_name: str):
        build_calls.append(engine_name)
        return primary_task if engine_name == "claude" else fallback_task

    with (
        unittest.mock.patch.object(service, "_build_cli_task", side_effect=_build_cli_task),
        unittest.mock.patch.object(service, "_run_cli_task", new=unittest.mock.AsyncMock()),
    ):
        result = await service.run_task(request, engine_name="claude")

    assert result.completed_actions == ["updated scope"]
    assert build_calls == ["claude", "codex"]
    recorded_events = [call.args[0] for call in audit_service.record.call_args_list]
    assert [event.event_type for event in recorded_events] == [
        EventType.LLM_TASK_REQUESTED,
        EventType.LLM_TASK_FAILED,
        EventType.LLM_TASK_FAILOVER_TRIGGERED,
        EventType.LLM_TASK_REQUESTED,
        EventType.LLM_TASK_COMPLETED,
    ]


async def test_llm_worker_service_stops_after_dual_limit_exhaustion() -> None:
    audit_service = unittest.mock.MagicMock()
    service = LlmWorkerService(audit_service=audit_service)
    request = _make_request()
    primary_task = _make_cli_task()
    primary_task.engine_name = "claude"
    primary_task.task_status = TaskStatus.FAILED
    primary_task.task_error = "limit_exhausted: usage limit reached"
    fallback_task = _make_cli_task()
    fallback_task.task_id = "task-2"
    fallback_task.engine_name = "codex"
    fallback_task.task_status = TaskStatus.FAILED
    fallback_task.task_error = "limit_exhausted: insufficient_quota"

    build_calls: list[str] = []

    def _build_cli_task(_request, *, engine_name: str):
        build_calls.append(engine_name)
        return primary_task if engine_name == "claude" else fallback_task

    with (
        unittest.mock.patch.object(service, "_build_cli_task", side_effect=_build_cli_task),
        unittest.mock.patch.object(service, "_run_cli_task", new=unittest.mock.AsyncMock()),
    ):
        with pytest.raises(RuntimeError, match="limits exhausted"):
            await service.run_task(request, engine_name="claude")

    assert build_calls == ["claude", "codex"]
    recorded_events = [call.args[0] for call in audit_service.record.call_args_list]
    assert [event.event_type for event in recorded_events] == [
        EventType.LLM_TASK_REQUESTED,
        EventType.LLM_TASK_FAILED,
        EventType.LLM_TASK_FAILOVER_TRIGGERED,
        EventType.LLM_TASK_REQUESTED,
        EventType.LLM_TASK_FAILED,
        EventType.LLM_TASK_FAILOVER_EXHAUSTED,
    ]


async def test_llm_worker_service_does_not_failover_on_non_limit_error() -> None:
    audit_service = unittest.mock.MagicMock()
    service = LlmWorkerService(audit_service=audit_service)
    request = _make_request()
    cli_task = _make_cli_task()
    cli_task.task_status = TaskStatus.FAILED
    cli_task.task_error = "auth_expired: login required"

    with unittest.mock.patch.object(service, "_build_cli_task", return_value=cli_task) as mock_build:
        with unittest.mock.patch.object(service, "_run_cli_task", new=unittest.mock.AsyncMock()):
            with pytest.raises(RuntimeError, match="auth_expired"):
                await service.run_task(request, engine_name="claude")

    assert mock_build.call_count == 1


def test_get_llm_worker_service_returns_singleton() -> None:
    service = get_llm_worker_service()

    assert get_llm_worker_service() is service
