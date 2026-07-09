import asyncio
import json
import unittest.mock
import uuid

import pytest

from app.services import task_runner as task_runner_module
from app.services.agent_pool import AgentPool
from app.services.task_registry import CliTask, TaskStatus
from app.services.task_runner import (
    LlmCliService,
    _build_cmd,
    _is_auth_error,
    cancel_cli_task,
    run_cli_task,
    set_db_enabled,
)
from app.workflows.init_arch.domain import AuditActor, EventType, LlmTaskKind, LlmTaskRequest, StepId


def _make_task(
    engine_name: str = "claude",
    prompt_text: str = "hello",
    task_status: TaskStatus = TaskStatus.PENDING,
    session_id: str | None = None,
    timeout_seconds: int = 30,
) -> CliTask:
    return CliTask(
        task_id=str(uuid.uuid4()),
        engine_name=engine_name,
        prompt_text=prompt_text,
        workspace_dir="/workspace",
        task_status=task_status,
        session_id=session_id,
        timeout_seconds=timeout_seconds,
    )


def _make_pool() -> AgentPool:
    return AgentPool(pool_size=2)


def _make_stream_reader(data: bytes) -> unittest.mock.MagicMock:
    lines = [*data.splitlines(keepends=True), b""]
    state = {"idx": 0}

    async def readline() -> bytes:
        idx = state["idx"]
        state["idx"] += 1
        return lines[idx] if idx < len(lines) else b""

    mock_reader = unittest.mock.MagicMock()
    mock_reader.readline = readline
    return mock_reader


def _make_mock_process(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> unittest.mock.MagicMock:
    mock_proc = unittest.mock.MagicMock()
    mock_proc.returncode = returncode
    mock_proc.stdout = _make_stream_reader(stdout)
    mock_proc.stderr = _make_stream_reader(stderr)
    mock_proc.terminate = unittest.mock.MagicMock()
    mock_proc.kill = unittest.mock.MagicMock()
    mock_proc.wait = unittest.mock.AsyncMock(return_value=returncode)
    return mock_proc


class TestBuildCmd:
    def test_claude_cmd_has_print_flag(self) -> None:
        cli_task = _make_task(engine_name="claude", prompt_text="test")
        cmd = _build_cmd(cli_task)
        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "test" in cmd

    def test_claude_cmd_includes_resume_when_session_id(self) -> None:
        cli_task = _make_task(engine_name="claude", session_id="sess-123")
        cmd = _build_cmd(cli_task)
        assert "--resume" in cmd
        assert "sess-123" in cmd

    def test_claude_cmd_no_resume_without_session_id(self) -> None:
        cli_task = _make_task(engine_name="claude")
        cmd = _build_cmd(cli_task)
        assert "--resume" not in cmd

    def test_codex_cmd_structure(self) -> None:
        cli_task = _make_task(engine_name="codex", prompt_text="fix it")
        cmd = _build_cmd(cli_task)
        assert cmd[0] == "codex"
        assert "exec" in cmd
        assert "--skip-git-repo-check" in cmd
        assert "fix it" in cmd

    def test_codex_cmd_includes_resume_when_session_id(self) -> None:
        cli_task = _make_task(engine_name="codex", prompt_text="continue", session_id="codex-sess-456")
        cmd = _build_cmd(cli_task)
        assert cmd[:3] == ["codex", "exec", "resume"]
        assert "codex-sess-456" in cmd
        assert "continue" in cmd

    def test_codex_cmd_no_resume_without_session_id(self) -> None:
        cli_task = _make_task(engine_name="codex")
        cmd = _build_cmd(cli_task)
        assert "resume" not in cmd
        assert "--skip-git-repo-check" in cmd


class TestIsAuthError:
    @pytest.mark.parametrize(
        ("engine_name", "exit_code", "stderr_text", "expected"),
        [
            ("claude", 1, "not logged in", True),
            ("claude", 1, "authentication required", True),
            ("claude", 0, "not logged in", False),
            ("claude", 1, "some other error", False),
            ("codex", 401, "", True),
            ("codex", 403, "", True),
            ("codex", 1, "auth error encountered", True),
            ("codex", 1, "command not found", False),
            ("codex", 0, "", False),
        ],
    )
    def test_auth_error_detection(self, engine_name: str, exit_code: int, stderr_text: str, expected: bool) -> None:
        assert _is_auth_error(engine_name, exit_code, stderr_text) is expected


class TestRunCliTask:
    async def test_success_sets_status_and_result(self) -> None:
        cli_task = _make_task(engine_name="claude")
        pool = _make_pool()
        mock_proc = _make_mock_process(returncode=0, stdout=b"all good", stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await run_cli_task(cli_task, pool)

        assert cli_task.task_status == TaskStatus.SUCCESS
        assert cli_task.task_result == "all good"
        assert cli_task.started_at is not None
        assert cli_task.finished_at is not None

    async def test_nonzero_exit_sets_failed_status(self) -> None:
        cli_task = _make_task(engine_name="codex")
        pool = _make_pool()
        mock_proc = _make_mock_process(returncode=1, stdout=b"", stderr=b"codex crashed")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await run_cli_task(cli_task, pool)

        assert cli_task.task_status == TaskStatus.FAILED
        assert cli_task.task_error == "codex crashed"

    async def test_auth_error_sets_auth_expired_in_error(self) -> None:
        cli_task = _make_task(engine_name="claude")
        pool = _make_pool()
        mock_proc = _make_mock_process(returncode=1, stdout=b"", stderr=b"not logged in")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await run_cli_task(cli_task, pool)

        assert cli_task.task_status == TaskStatus.FAILED
        assert "auth_expired" in cli_task.task_error

    async def test_timeout_sets_failed_status(self) -> None:
        cli_task = _make_task(engine_name="claude", timeout_seconds=1)
        pool = _make_pool()
        mock_proc = _make_mock_process()

        async def _timeout_wait_for(awaitable, **_kwargs):
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            raise TimeoutError

        with (
            unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            unittest.mock.patch("asyncio.wait_for", side_effect=_timeout_wait_for),
        ):
            await run_cli_task(cli_task, pool)

        assert cli_task.task_status == TaskStatus.FAILED
        assert "Timeout" in cli_task.task_error

    async def test_os_error_sets_failed_status(self) -> None:
        cli_task = _make_task(engine_name="claude")
        pool = _make_pool()

        with unittest.mock.patch("asyncio.create_subprocess_exec", side_effect=OSError("not found")):
            await run_cli_task(cli_task, pool)

        assert cli_task.task_status == TaskStatus.FAILED
        assert "not found" in cli_task.task_error

    async def test_cancelled_task_skips_execution(self) -> None:
        cli_task = _make_task(task_status=TaskStatus.CANCELLED)
        pool = _make_pool()

        with unittest.mock.patch("asyncio.create_subprocess_exec") as mock_exec:
            await run_cli_task(cli_task, pool)

        mock_exec.assert_not_called()
        assert cli_task.task_status == TaskStatus.CANCELLED

    async def test_stdout_lines_populated_on_success(self) -> None:
        cli_task = _make_task(engine_name="claude")
        pool = _make_pool()
        mock_proc = _make_mock_process(returncode=0, stdout=b"line1\nline2\nline3", stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await run_cli_task(cli_task, pool)

        assert cli_task.stdout_lines == ["line1", "line2", "line3"]

    async def test_stderr_lines_populated_on_failure(self) -> None:
        cli_task = _make_task(engine_name="codex")
        pool = _make_pool()
        mock_proc = _make_mock_process(returncode=1, stdout=b"", stderr=b"error line1\nerror line2")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await run_cli_task(cli_task, pool)

        assert cli_task.task_status == TaskStatus.FAILED
        assert cli_task.stderr_lines == ["error line1", "error line2"]


class TestCancelCliTask:
    async def test_cancels_pending_task(self) -> None:
        cli_task = _make_task(task_status=TaskStatus.PENDING)
        registry = {cli_task.task_id: cli_task}

        await cancel_cli_task(cli_task.task_id, registry)

        assert cli_task.task_status == TaskStatus.CANCELLED

    async def test_cancels_running_task_with_sigterm(self) -> None:
        cli_task = _make_task(task_status=TaskStatus.RUNNING)
        mock_proc = _make_mock_process(returncode=None)
        cli_task.subprocess_handle = mock_proc
        registry = {cli_task.task_id: cli_task}

        await cancel_cli_task(cli_task.task_id, registry)

        assert cli_task.task_status == TaskStatus.CANCELLED
        mock_proc.terminate.assert_called_once()

    async def test_noop_for_missing_task(self) -> None:
        registry: dict = {}
        await cancel_cli_task("nonexistent", registry)

    async def test_noop_for_finished_process(self) -> None:
        cli_task = _make_task(task_status=TaskStatus.RUNNING)
        mock_proc = _make_mock_process(returncode=0)
        cli_task.subprocess_handle = mock_proc
        original_status = cli_task.task_status
        registry = {cli_task.task_id: cli_task}

        await cancel_cli_task(cli_task.task_id, registry)

        assert cli_task.task_status == original_status
        mock_proc.terminate.assert_not_called()

    async def test_kills_process_on_timeout(self) -> None:
        cli_task = _make_task(task_status=TaskStatus.RUNNING)
        mock_proc = _make_mock_process(returncode=None)
        mock_proc.wait = unittest.mock.AsyncMock(side_effect=asyncio.TimeoutError)
        cli_task.subprocess_handle = mock_proc
        registry = {cli_task.task_id: cli_task}

        await cancel_cli_task(cli_task.task_id, registry)

        assert cli_task.task_status == TaskStatus.CANCELLED
        mock_proc.kill.assert_called_once()


class TestDbPersistence:
    def setup_method(self) -> None:
        set_db_enabled(False)

    def teardown_method(self) -> None:
        set_db_enabled(False)

    def test_set_db_enabled_toggles(self) -> None:
        set_db_enabled(True)
        assert task_runner_module._db_enabled is True  # type: ignore[attr-defined]
        set_db_enabled(False)
        assert task_runner_module._db_enabled is False  # type: ignore[attr-defined]

    async def test_run_cli_task_calls_upsert_when_db_enabled(self) -> None:
        set_db_enabled(True)
        cli_task = _make_task(engine_name="claude")
        pool = _make_pool()
        mock_proc = _make_mock_process(returncode=0, stdout=b"ok", stderr=b"")

        mock_session_ctx = unittest.mock.AsyncMock()
        mock_session_ctx.__aenter__ = unittest.mock.AsyncMock(return_value=mock_session_ctx)
        mock_session_ctx.__aexit__ = unittest.mock.AsyncMock(return_value=False)

        with (
            unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            unittest.mock.patch("app.services.task_runner.get_session", return_value=mock_session_ctx),
            unittest.mock.patch(
                "app.services.task_runner.upsert_cli_task", new_callable=unittest.mock.AsyncMock
            ) as mock_upsert,
        ):
            await run_cli_task(cli_task, pool)

        assert mock_upsert.call_count >= 2  # при старте + при завершении

    async def test_run_cli_task_skips_upsert_when_db_disabled(self) -> None:
        set_db_enabled(False)
        cli_task = _make_task(engine_name="claude")
        pool = _make_pool()
        mock_proc = _make_mock_process(returncode=0, stdout=b"ok", stderr=b"")

        with (
            unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            unittest.mock.patch(
                "app.services.task_runner.upsert_cli_task", new_callable=unittest.mock.AsyncMock
            ) as mock_upsert,
        ):
            await run_cli_task(cli_task, pool)

        mock_upsert.assert_not_called()

    async def test_run_cli_task_survives_db_error(self) -> None:
        set_db_enabled(True)
        cli_task = _make_task(engine_name="claude")
        pool = _make_pool()
        mock_proc = _make_mock_process(returncode=0, stdout=b"ok", stderr=b"")

        mock_session_ctx = unittest.mock.AsyncMock()
        mock_session_ctx.__aenter__ = unittest.mock.AsyncMock(side_effect=Exception("db down"))
        mock_session_ctx.__aexit__ = unittest.mock.AsyncMock(return_value=False)

        with (
            unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            unittest.mock.patch("app.services.task_runner.get_session", return_value=mock_session_ctx),
        ):
            await run_cli_task(cli_task, pool)  # не должно бросить


class TestLlmCliService:
    async def test_run_task_parses_structured_result(self) -> None:
        audit_service = unittest.mock.MagicMock()
        service = LlmCliService(audit_service=audit_service)
        request = LlmTaskRequest(
            task_kind=LlmTaskKind.STEP_EXECUTION,
            step_id=StepId.DEFINE_SCOPE,
            prompt_text="do work",
            workspace_dir="/workspace",
            timeout_seconds=30,
            expected_schema_name="init_arch_v1",
            session_id="wf-1",
        )
        cli_task = _make_task(engine_name="claude")
        cli_task.task_status = TaskStatus.SUCCESS
        cli_task.task_result = json.dumps(
            {
                "completed_actions": ["updated scope"],
                "created_artifacts": ["arch-doc/notes.md"],
                "open_questions_found": [],
                "notes": "ok",
            }
        )

        with unittest.mock.patch.object(service, "_build_cli_task", return_value=cli_task):
            with unittest.mock.patch.object(service, "_run_cli_task", new=unittest.mock.AsyncMock()) as mock_run:
                result = await service.run_task(request, engine_name="claude")

        mock_run.assert_awaited_once_with(cli_task)
        assert result.task_kind == LlmTaskKind.STEP_EXECUTION
        assert result.completed_actions == ["updated scope"]
        recorded_events = [call.args[0] for call in audit_service.record.call_args_list]
        assert [event.event_type for event in recorded_events] == [
            EventType.LLM_TASK_REQUESTED,
            EventType.LLM_TASK_COMPLETED,
        ]
        assert all(event.actor is AuditActor.LLM_WORKER for event in recorded_events)

    async def test_run_task_raises_when_cli_task_fails(self) -> None:
        audit_service = unittest.mock.MagicMock()
        service = LlmCliService(audit_service=audit_service)
        request = LlmTaskRequest(
            task_kind=LlmTaskKind.STEP_EXECUTION,
            step_id=StepId.DEFINE_SCOPE,
            prompt_text="do work",
            workspace_dir="/workspace",
            timeout_seconds=30,
            expected_schema_name="init_arch_v1",
            session_id="wf-1",
        )
        cli_task = _make_task(engine_name="claude")
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
