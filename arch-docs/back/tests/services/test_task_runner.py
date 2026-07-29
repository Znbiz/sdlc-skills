import asyncio
import json
import os
import pathlib
import unittest.mock
import uuid

import pytest

from app.services import cli_task_support as cli_task_support_module
from app.services import task_runner as task_runner_module
from app.services.agent_pool import AgentPool
from app.services.llm_provider_credentials import EXTERNAL_LLM_API_KEY_ENV_VAR
from app.services.llm_providers import LlmProviderConnectionDetail, create_llm_provider_connection_async
from app.services.task_registry import CliTask, TaskStatus
from app.services.task_runner import (
    LlmCliService,
    LlmTaskExecutionError,
    _build_cmd,
    _extract_result_text,
    _is_auth_error,
    _is_limit_error,
    cancel_cli_task,
    execute_engine_task,
    run_cli_task,
    set_db_enabled,
)
from app.services.workflow_event_bus import get_workflow_event_bus, reset_workflow_event_bus
from app.workflows.init_arch.domain import AuditActor, EventType, LlmTaskKind, LlmTaskRequest, StepId


@pytest.fixture(autouse=True)
def _isolated_llm_provider_secrets_store(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.llm_provider_credentials._SECRETS_DIR", tmp_path / "llm-provider-secrets")


@pytest.fixture(autouse=True)
def _clean_workflow_event_bus():
    reset_workflow_event_bus()
    yield
    reset_workflow_event_bus()


def _make_task(  # noqa: PLR0913
    engine_name: str = "claude",
    prompt_text: str = "hello",
    task_status: TaskStatus = TaskStatus.PENDING,
    session_id: str | None = None,
    timeout_seconds: int = 30,
    provider_connection_id: str | None = None,
) -> CliTask:
    return CliTask(
        task_id=str(uuid.uuid4()),
        engine_name=engine_name,
        provider_connection_id=provider_connection_id,
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

    def test_claude_cmd_has_verbose_flag(self) -> None:
        # claude CLI rejects --output-format=stream-json without --verbose when --print is used.
        cli_task = _make_task(engine_name="claude", prompt_text="test")
        cmd = _build_cmd(cli_task)
        assert "--verbose" in cmd

    def test_claude_cmd_bypasses_permissions(self) -> None:
        # Non-interactive `-p` runs have nobody to approve tool calls; without this flag every
        # write/Bash action (mkdir, git clone, ...) is silently denied while the CLI still exits 0.
        cli_task = _make_task(engine_name="claude", prompt_text="test")
        cmd = _build_cmd(cli_task)
        assert "--permission-mode" in cmd
        assert cmd[cmd.index("--permission-mode") + 1] == "bypassPermissions"

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

    def test_oversized_prompt_is_written_to_file_instead_of_argv(self, monkeypatch, tmp_path) -> None:
        # Regression: an oversized prompt_text (e.g. analyze_repositories' expanded diff/changed-
        # file context) passed straight through as a CLI argument can exceed the OS's argv size
        # limit - `OSError: [Errno 7] Argument list too long` - and burns all 3 retries identically
        # since the prompt is the same every time. See _resolve_cli_prompt's docstring.
        monkeypatch.setattr("app.services.cli_task_support._MAX_INLINE_PROMPT_CHARS", 10)
        monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
        huge_prompt = "x" * 1000
        cli_task = _make_task(engine_name="codex", prompt_text=huge_prompt)

        cmd = _build_cmd(cli_task)

        assert huge_prompt not in cmd
        prompt_arg = cmd[-1]
        assert cli_task.task_id in prompt_arg
        written_files = list((tmp_path / "arch-docs-prompt-overflow").iterdir())
        assert len(written_files) == 1
        assert written_files[0].read_text(encoding="utf-8") == huge_prompt

    def test_small_prompt_is_passed_through_unchanged(self) -> None:
        cli_task = _make_task(engine_name="codex", prompt_text="short prompt")
        cmd = _build_cmd(cli_task)
        assert "short prompt" in cmd

    def test_codex_cmd_without_provider_connection_has_no_overrides(self) -> None:
        cli_task = _make_task(engine_name="codex")
        cmd = _build_cmd(cli_task, None)
        assert "-c" not in cmd

    def test_codex_cmd_with_provider_connection_adds_overrides(self) -> None:
        cli_task = _make_task(engine_name="codex")
        connection = LlmProviderConnectionDetail(
            connection_id=uuid.uuid4(),
            name="external",
            base_url="https://api.example.com/v1",
            model="my-model",
            wire_api="chat",
            requires_openai_auth=False,
            token="sk-abc",
        )

        cmd = _build_cmd(cli_task, connection)

        assert "-c" in cmd
        overrides = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-c"]
        assert "model_provider=external" in overrides
        assert "model_providers.external.base_url=https://api.example.com/v1" in overrides
        assert f"model_providers.external.env_key={EXTERNAL_LLM_API_KEY_ENV_VAR}" in overrides
        assert "model_providers.external.wire_api=chat" in overrides
        assert "model_providers.external.requires_openai_auth=false" in overrides
        assert "model=my-model" in overrides
        assert any(override.startswith("model_catalog_json=") for override in overrides)
        disabled_features = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--disable"]
        assert disabled_features == ["multi_agent", "apps"]

    def test_codex_cmd_with_provider_connection_writes_model_catalog_file(self) -> None:
        cli_task = _make_task(engine_name="codex")
        connection = LlmProviderConnectionDetail(
            connection_id=uuid.uuid4(),
            name="external",
            base_url="https://api.example.com/v1",
            model="my-model",
            wire_api="responses",
            requires_openai_auth=False,
            token="sk-abc",
        )

        cmd = _build_cmd(cli_task, connection)

        overrides = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-c"]
        catalog_override = next(override for override in overrides if override.startswith("model_catalog_json="))
        catalog_path = pathlib.Path(catalog_override.removeprefix("model_catalog_json="))
        catalog = json.loads(catalog_path.read_text())
        model_entry = catalog["models"][0]
        assert model_entry["slug"] == "my-model"
        assert model_entry["apply_patch_tool_type"] == "freeform"
        assert model_entry["shell_type"] == "shell_command"

    def test_codex_cmd_with_provider_connection_overrides_come_before_prompt(self) -> None:
        cli_task = _make_task(engine_name="codex", prompt_text="do the thing")
        connection = LlmProviderConnectionDetail(
            connection_id=uuid.uuid4(),
            name="external",
            base_url="https://api.example.com/v1",
            model="my-model",
            wire_api="chat",
            requires_openai_auth=True,
            token="sk-abc",
        )

        cmd = _build_cmd(cli_task, connection)

        assert cmd[-1] == "do the thing"
        assert "model_providers.external.requires_openai_auth=true" in cmd


class TestExtractJsonObject:
    def test_parses_plain_json(self) -> None:
        assert task_runner_module._extract_json_object('{"completed_actions": ["a"]}') == {"completed_actions": ["a"]}

    def test_extracts_json_from_fenced_code_block_with_prose_before_it(self) -> None:
        text = (
            "Все данные собраны. Анализ завершён.\n\n"
            "**Итог:** репозиторий небольшой, per_module.\n\n"
            "```json\n"
            '{"completed_actions": ["done"], "domain_assessment": {"volume_class": "small", '
            '"strategy": "per_module", "domains": []}}\n'
            "```\n"
        )
        result = task_runner_module._extract_json_object(text)
        assert result is not None
        assert result["completed_actions"] == ["done"]
        assert result["domain_assessment"]["strategy"] == "per_module"

    def test_extracts_json_from_unfenced_prose(self) -> None:
        text = 'Пояснение перед ответом. {"completed_actions": ["done"]} Пояснение после.'
        assert task_runner_module._extract_json_object(text) == {"completed_actions": ["done"]}

    def test_uses_last_fenced_block_when_multiple_present(self) -> None:
        text = '```json\n{"notes": "first"}\n```\nещё текст\n```json\n{"notes": "second"}\n```'
        assert task_runner_module._extract_json_object(text) == {"notes": "second"}

    def test_returns_none_when_no_json_object_present(self) -> None:
        assert task_runner_module._extract_json_object("просто текст без json") is None


class TestExtractResultText:
    def test_claude_uses_last_result_event(self) -> None:
        lines = [
            '{"type":"system","subtype":"init"}',
            '{"type":"result","result":"first"}',
            '{"type":"result","result":"final"}',
        ]
        assert _extract_result_text("claude", lines) == "final"

    def test_claude_ignores_non_json_and_non_result_lines(self) -> None:
        lines = [
            "not json at all",
            '{"type":"assistant","message":{}}',
            '{"type":"result","result":"final"}',
        ]
        assert _extract_result_text("claude", lines) == "final"

    def test_claude_returns_empty_when_no_result_event(self) -> None:
        lines = ['{"type":"system","subtype":"init"}']
        assert _extract_result_text("claude", lines) == ""

    def test_codex_uses_last_agent_message(self) -> None:
        lines = [
            '{"type":"thread.started"}',
            '{"type":"item.completed","item":{"type":"reasoning","text":"thinking"}}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"final"}}',
        ]
        assert _extract_result_text("codex", lines) == "final"

    def test_unknown_engine_falls_back_to_joined_lines(self) -> None:
        lines = ["line1", "line2"]
        assert _extract_result_text("other", lines) == "line1\nline2"


class TestExtractUsage:
    def test_codex_reads_last_turn_completed_usage(self) -> None:
        lines = [
            '{"type":"thread.started"}',
            '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":40,"output_tokens":10}}',
        ]
        assert task_runner_module._extract_codex_usage(lines) == (100, 10)

    def test_codex_returns_none_without_turn_completed(self) -> None:
        lines = ['{"type":"thread.started"}']
        assert task_runner_module._extract_codex_usage(lines) is None

    def test_codex_defaults_missing_usage_fields_to_zero(self) -> None:
        lines = ['{"type":"turn.completed"}']
        assert task_runner_module._extract_codex_usage(lines) == (0, 0)

    def test_claude_sums_cache_fields_into_input_tokens(self) -> None:
        lines = [
            '{"type":"system","subtype":"init"}',
            (
                '{"type":"result","usage":{"input_tokens":50,"cache_creation_input_tokens":20,'
                '"cache_read_input_tokens":30,"output_tokens":15}}'
            ),
        ]
        assert task_runner_module._extract_claude_usage(lines) == (100, 15)

    def test_claude_returns_none_without_result_event(self) -> None:
        lines = ['{"type":"system","subtype":"init"}']
        assert task_runner_module._extract_claude_usage(lines) is None

    def test_extract_usage_dispatches_by_engine(self) -> None:
        codex_lines = ['{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":2}}']
        claude_lines = ['{"type":"result","usage":{"input_tokens":3,"output_tokens":4}}']
        assert task_runner_module._extract_usage("codex", codex_lines) == (1, 2)
        assert task_runner_module._extract_usage("claude", claude_lines) == (3, 4)
        assert task_runner_module._extract_usage("other", claude_lines) is None


class TestExtractModel:
    def test_claude_reads_model_from_system_init_event(self) -> None:
        lines = [
            '{"type":"system","subtype":"init","model":"claude-sonnet-4-5"}',
            '{"type":"result","result":"ok"}',
        ]
        assert task_runner_module._extract_claude_model(lines) == "claude-sonnet-4-5"

    def test_claude_returns_none_without_init_event(self) -> None:
        assert task_runner_module._extract_claude_model(['{"type":"result","result":"ok"}']) is None

    def test_resolve_model_name_prefers_claude_reported_model(self) -> None:
        lines = ['{"type":"system","subtype":"init","model":"claude-sonnet-4-5"}']
        assert task_runner_module._resolve_model_name("claude", lines, None) == "claude-sonnet-4-5"

    def test_resolve_model_name_uses_provider_connection_for_codex(self) -> None:
        connection = LlmProviderConnectionDetail(
            connection_id=uuid.uuid4(),
            name="gateway",
            base_url="https://example.test",
            model="gpt-4o-mini",
            wire_api="chat",
            requires_openai_auth=False,
            token="secret",
        )
        assert task_runner_module._resolve_model_name("codex", [], connection) == "gpt-4o-mini"

    def test_resolve_model_name_falls_back_to_engine_default(self) -> None:
        assert task_runner_module._resolve_model_name("codex", [], None) == "codex:default"


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


class TestIsLimitError:
    @pytest.mark.parametrize(
        ("engine_name", "exit_code", "stderr_text", "expected"),
        [
            ("claude", 1, "usage limit reached", True),
            ("claude", 1, "rate limit exceeded", True),
            ("claude", 1, "authentication required", False),
            ("codex", 429, "", True),
            ("codex", 1, "insufficient_quota", True),
            ("codex", 1, "quota exceeded for this request", True),
            ("codex", 1, "command not found", False),
            ("codex", 0, "", False),
        ],
    )
    def test_limit_error_detection(self, engine_name: str, exit_code: int, stderr_text: str, expected: bool) -> None:
        assert _is_limit_error(engine_name, exit_code, stderr_text) is expected


class TestRunCliTask:
    async def test_success_sets_status_and_result(self) -> None:
        cli_task = _make_task(engine_name="claude")
        pool = _make_pool()
        # Mirrors real `claude --output-format stream-json --verbose` NDJSON output:
        # a system init event, then the final answer in a `type: result` event.
        stdout = (
            b'{"type":"system","subtype":"init","session_id":"s-1"}\n'
            b'{"type":"result","subtype":"success","is_error":false,"result":"all good","session_id":"s-1"}'
        )
        mock_proc = _make_mock_process(returncode=0, stdout=stdout, stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await run_cli_task(cli_task, pool)

        assert cli_task.task_status == TaskStatus.SUCCESS
        assert cli_task.task_result == "all good"
        assert cli_task.started_at is not None
        assert cli_task.finished_at is not None

    async def test_success_extracts_final_agent_message_for_codex(self) -> None:
        cli_task = _make_task(engine_name="codex")
        pool = _make_pool()
        # Mirrors real `codex exec --json` NDJSON output: lifecycle events plus the final
        # agent answer in an `item.completed` event whose item type is `agent_message`.
        stdout = (
            b'{"type":"thread.started","thread_id":"t-1"}\n'
            b'{"type":"turn.started"}\n'
            b'{"type":"item.completed","item":{"type":"agent_message","text":"all good"}}\n'
            b'{"type":"turn.completed"}'
        )
        mock_proc = _make_mock_process(returncode=0, stdout=stdout, stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await run_cli_task(cli_task, pool)

        assert cli_task.task_status == TaskStatus.SUCCESS
        assert cli_task.task_result == "all good"

    async def test_success_extracts_usage_and_model_for_claude(self) -> None:
        cli_task = _make_task(engine_name="claude")
        pool = _make_pool()
        stdout = (
            b'{"type":"system","subtype":"init","model":"claude-sonnet-4-5"}\n'
            b'{"type":"result","subtype":"success","is_error":false,"result":"all good",'
            b'"usage":{"input_tokens":50,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,'
            b'"output_tokens":12}}'
        )
        mock_proc = _make_mock_process(returncode=0, stdout=stdout, stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await run_cli_task(cli_task, pool)

        assert cli_task.model_name == "claude-sonnet-4-5"
        assert cli_task.input_tokens == 50
        assert cli_task.output_tokens == 12

    async def test_success_extracts_usage_for_codex_and_falls_back_model_name(self) -> None:
        cli_task = _make_task(engine_name="codex")
        pool = _make_pool()
        stdout = (
            b'{"type":"thread.started"}\n'
            b'{"type":"item.completed","item":{"type":"agent_message","text":"all good"}}\n'
            b'{"type":"turn.completed","usage":{"input_tokens":200,"output_tokens":30}}'
        )
        mock_proc = _make_mock_process(returncode=0, stdout=stdout, stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await run_cli_task(cli_task, pool)

        assert cli_task.model_name == "codex:default"
        assert cli_task.input_tokens == 200
        assert cli_task.output_tokens == 30

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

    async def test_limit_error_sets_limit_exhausted_in_error(self) -> None:
        cli_task = _make_task(engine_name="codex")
        pool = _make_pool()
        mock_proc = _make_mock_process(returncode=1, stdout=b"", stderr=b"insufficient_quota")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await run_cli_task(cli_task, pool)

        assert cli_task.task_status == TaskStatus.FAILED
        assert "limit_exhausted" in cli_task.task_error

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

    async def test_cancellation_terminates_orphaned_subprocess(self) -> None:
        # Simulates `pause_init_arch_workflow()` cancelling the graph's asyncio.Task while a CLI
        # subprocess is mid-flight: without an explicit terminate() on CancelledError, the process
        # would keep running orphaned even though the Python task unwound. See test_task_runner.py
        # `run_cli_task`'s `except asyncio.CancelledError` branch.
        cli_task = _make_task(engine_name="claude")
        pool = _make_pool()
        mock_proc = _make_mock_process()
        real_wait_for = asyncio.wait_for
        call_count = 0

        async def _wait_for(awaitable, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                close = getattr(awaitable, "close", None)
                if callable(close):
                    close()
                raise asyncio.CancelledError
            return await real_wait_for(awaitable, **kwargs)

        with (
            unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            unittest.mock.patch("asyncio.wait_for", side_effect=_wait_for),
        ):
            with pytest.raises(asyncio.CancelledError):
                await run_cli_task(cli_task, pool)

        mock_proc.terminate.assert_called_once()

    async def test_os_error_sets_failed_status(self) -> None:
        cli_task = _make_task(engine_name="claude")
        pool = _make_pool()

        with unittest.mock.patch("asyncio.create_subprocess_exec", side_effect=OSError("not found")):
            await run_cli_task(cli_task, pool)

        assert cli_task.task_status == TaskStatus.FAILED
        assert "not found" in cli_task.task_error

    async def test_limit_overrun_error_sets_failed_status(self) -> None:
        # Regression: codex --json can emit a single stdout line past the stream reader's limit
        # (e.g. a tool-output line embedding a whole file's contents), which raises
        # asyncio.LimitOverrunError from reader.readline(). Before this fix that error wasn't
        # caught at all, so it escaped run_cli_task uncaught and left task_status stuck on RUNNING.
        cli_task = _make_task(engine_name="codex")
        pool = _make_pool()
        mock_proc = _make_mock_process()

        async def _raise_readline() -> bytes:
            raise asyncio.LimitOverrunError("Separator is found, but chunk is longer than limit", 65536)

        mock_proc.stdout.readline = _raise_readline

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await run_cli_task(cli_task, pool)

        assert cli_task.task_status == TaskStatus.FAILED
        assert "longer than limit" in cli_task.task_error

    async def test_subprocess_created_with_raised_stream_limit(self) -> None:
        cli_task = _make_task(engine_name="codex")
        pool = _make_pool()
        mock_proc = _make_mock_process()

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            await run_cli_task(cli_task, pool)

        assert mock_exec.call_args.kwargs["limit"] == task_runner_module._STDOUT_STREAM_LIMIT

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

    async def test_publishes_live_llm_tool_call_and_message_for_workflow_bound_task(self) -> None:
        cli_task = _make_task(engine_name="claude")
        cli_task.workflow_id = "wf-live"
        cli_task.step_id = "analyze_repositories"
        cli_task.repository_name = "svc-a"
        pool = _make_pool()
        stdout = (
            b'{"type":"system","subtype":"init"}\n'
            b'{"type":"assistant","message":{"content":[{"type":"text","text":"reading files"}]}}\n'
            b'{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read",'
            b'"input":{"file_path":"a.py"}}]}}\n'
            b'{"type":"result","result":"done"}'
        )
        mock_proc = _make_mock_process(returncode=0, stdout=stdout, stderr=b"")
        subscription = get_workflow_event_bus().subscribe("wf-live")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await run_cli_task(cli_task, pool)

        published = [subscription.get_nowait() for _ in range(subscription.qsize())]
        assert [event["event_type"] for event in published] == ["llm_message", "llm_tool_call"]
        assert published[0]["text"] == "reading files"
        assert published[1]["tool_name"] == "Read"
        assert "a.py" in published[1]["tool_input"]
        assert all(event["actor"] == "llm" for event in published)
        assert all(event["repo_name"] == "svc-a" for event in published)
        assert all(event["step_label"] == "Анализ репозиториев" for event in published)
        # "system" (init) and "result" (already surfaced as llm_call_completed.raw_output) are
        # deliberately not re-published on the per-line live channel.

    async def test_does_not_publish_live_events_for_task_without_workflow_id(self) -> None:
        cli_task = _make_task(engine_name="claude")
        assert cli_task.workflow_id is None
        pool = _make_pool()
        stdout = b'{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}\n{"type":"result","result":"done"}'
        mock_proc = _make_mock_process(returncode=0, stdout=stdout, stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await run_cli_task(cli_task, pool)

        assert get_workflow_event_bus()._subscribers == {}


class TestRunCliTaskWithProviderConnection:
    async def test_fails_task_without_spawning_subprocess_when_connection_missing(self) -> None:
        cli_task = _make_task(engine_name="codex", provider_connection_id=str(uuid.uuid4()))
        pool = _make_pool()

        with unittest.mock.patch("asyncio.create_subprocess_exec") as mock_spawn:
            await run_cli_task(cli_task, pool)

        mock_spawn.assert_not_called()
        assert cli_task.task_status == TaskStatus.FAILED
        assert "LLM provider connection not found" in (cli_task.task_error or "")

    async def test_injects_token_into_subprocess_env_without_mutating_os_environ(self) -> None:
        connection = await create_llm_provider_connection_async(
            name="external-test", base_url="https://api.example.com/v1", model="my-model", token="sk-secret"
        )
        cli_task = _make_task(engine_name="codex", provider_connection_id=str(connection.connection_id))
        pool = _make_pool()
        mock_proc = _make_mock_process(
            returncode=0, stdout=b'{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}', stderr=b""
        )

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_spawn:
            await run_cli_task(cli_task, pool)

        assert cli_task.task_status == TaskStatus.SUCCESS
        passed_env = mock_spawn.call_args.kwargs["env"]
        assert passed_env[EXTERNAL_LLM_API_KEY_ENV_VAR] == "sk-secret"
        # The one subprocess call gets the token in its own env dict - the test process's own
        # os.environ must stay untouched (unlike git_credentials' GIT_CONFIG_GLOBAL mutation).
        assert EXTERNAL_LLM_API_KEY_ENV_VAR not in os.environ

    async def test_passes_provider_overrides_in_built_command(self) -> None:
        connection = await create_llm_provider_connection_async(
            name="external-test-2", base_url="https://api.example.com/v1", model="my-model", token="sk-secret"
        )
        cli_task = _make_task(engine_name="codex", provider_connection_id=str(connection.connection_id))
        pool = _make_pool()
        mock_proc = _make_mock_process(
            returncode=0, stdout=b'{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}', stderr=b""
        )

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_spawn:
            await run_cli_task(cli_task, pool)

        passed_cmd = mock_spawn.call_args.args
        assert "model_provider=external" in passed_cmd


class TestClassifyLiveStreamLine:
    def test_claude_tool_use_block(self) -> None:
        event = task_runner_module._classify_live_stream_line(
            "claude",
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]},
                }
            ),
        )
        assert event == {"event_type": "llm_tool_call", "tool_name": "Bash", "tool_input": '{"command": "ls"}'}

    def test_claude_text_block(self) -> None:
        event = task_runner_module._classify_live_stream_line(
            "claude", json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}})
        )
        assert event == {"event_type": "llm_message", "text": "hi"}

    def test_claude_system_type_is_noise(self) -> None:
        event = task_runner_module._classify_live_stream_line(
            "claude", json.dumps({"type": "system", "subtype": "init"})
        )
        assert event is None

    def test_claude_result_type_is_noise(self) -> None:
        event = task_runner_module._classify_live_stream_line(
            "claude", json.dumps({"type": "result", "result": "done"})
        )
        assert event is None

    def test_codex_command_execution(self) -> None:
        event = task_runner_module._classify_live_stream_line(
            "codex",
            json.dumps({"type": "item.completed", "item": {"type": "command_execution", "command": "ls -la"}}),
        )
        assert event == {"event_type": "llm_tool_call", "tool_name": "shell", "tool_input": "ls -la"}

    def test_codex_agent_message(self) -> None:
        event = task_runner_module._classify_live_stream_line(
            "codex", json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "done"}})
        )
        assert event == {"event_type": "llm_message", "text": "done"}

    def test_codex_thread_started_is_noise(self) -> None:
        event = task_runner_module._classify_live_stream_line("codex", json.dumps({"type": "thread.started"}))
        assert event is None

    def test_unparseable_json_falls_back_to_raw_message(self) -> None:
        event = task_runner_module._classify_live_stream_line("claude", "not json at all")
        assert event == {"event_type": "llm_message", "text": "not json at all"}

    def test_unknown_type_falls_back_to_raw_message_instead_of_swallowing_it(self) -> None:
        event = task_runner_module._classify_live_stream_line("claude", json.dumps({"type": "some_future_event"}))
        assert event == {"event_type": "llm_message", "text": json.dumps({"type": "some_future_event"})}

    def test_unknown_engine_falls_back_to_raw_message(self) -> None:
        event = task_runner_module._classify_live_stream_line("other", json.dumps({"type": "assistant"}))
        assert event == {"event_type": "llm_message", "text": json.dumps({"type": "assistant"})}

    def test_blank_line_is_noise(self) -> None:
        assert task_runner_module._classify_live_stream_line("claude", "   ") is None


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

    async def test_cancels_running_langgraph_task_with_no_subprocess(self) -> None:
        # LangGraph tasks never have a subprocess_handle - cancellation has to go through
        # async_task_handle instead. See
        # arch-docs/docs/spec/2026-07-25-langgraph-api-agent-runner.md, section 7, "Пробел №2".
        cli_task = _make_task(engine_name="langgraph", task_status=TaskStatus.RUNNING)
        cli_task.async_task_handle = asyncio.create_task(asyncio.sleep(10))
        registry = {cli_task.task_id: cli_task}

        await cancel_cli_task(cli_task.task_id, registry)

        assert cli_task.task_status == TaskStatus.CANCELLED
        assert cli_task.async_task_handle.cancelled()
        assert cli_task.finished_at is not None

    async def test_noop_for_already_done_async_task_handle(self) -> None:
        cli_task = _make_task(engine_name="langgraph", task_status=TaskStatus.RUNNING)

        async def _noop() -> None:
            return None

        cli_task.async_task_handle = asyncio.create_task(_noop())
        await cli_task.async_task_handle
        registry = {cli_task.task_id: cli_task}

        await cancel_cli_task(cli_task.task_id, registry)

        assert cli_task.task_status == TaskStatus.RUNNING


class TestDbPersistence:
    def setup_method(self) -> None:
        set_db_enabled(False)

    def teardown_method(self) -> None:
        set_db_enabled(False)

    def test_set_db_enabled_toggles(self) -> None:
        set_db_enabled(True)
        assert cli_task_support_module._db_enabled is True  # type: ignore[attr-defined]
        set_db_enabled(False)
        assert cli_task_support_module._db_enabled is False  # type: ignore[attr-defined]

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
            unittest.mock.patch("app.services.cli_task_support.get_session", return_value=mock_session_ctx),
            unittest.mock.patch(
                "app.services.cli_task_support.upsert_cli_task", new_callable=unittest.mock.AsyncMock
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
                "app.services.cli_task_support.upsert_cli_task", new_callable=unittest.mock.AsyncMock
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
            unittest.mock.patch("app.services.cli_task_support.get_session", return_value=mock_session_ctx),
        ):
            await run_cli_task(cli_task, pool)  # не должно бросить


class TestLlmCliService:
    def test_build_cli_task_caps_timeout_to_workflow_limit(self, monkeypatch) -> None:
        from app.settings import GatewaySettings

        monkeypatch.setattr(
            "app.services.task_runner.get_gateway_settings",
            lambda: GatewaySettings(
                auth_secret="secret",
                workflows={"init": {"max_step_timeout_seconds": 45}},
            ),
        )
        service = LlmCliService()
        request = LlmTaskRequest(
            task_kind=LlmTaskKind.STEP_EXECUTION,
            step_id=StepId.ANALYZE_REPOSITORIES,
            prompt_text="analyze",
            workspace_dir="/workspace",
            timeout_seconds=120,
            expected_schema_name="init_arch_v1",
            session_id="wf-1",
        )

        cli_task = service._build_cli_task(request, engine_name="claude")

        assert cli_task.timeout_seconds == 45

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
                "diff_based_findings": ["новый endpoint появился в diff"],
                "snapshot_based_findings": ["текущая структура каталогов"],
                "notes": "ok",
            }
        )

        with unittest.mock.patch.object(service, "_build_cli_task", return_value=cli_task):
            with unittest.mock.patch.object(service, "_run_cli_task", new=unittest.mock.AsyncMock()) as mock_run:
                result = await service.run_task(request, engine_name="claude")

        mock_run.assert_awaited_once_with(cli_task)
        assert result.task_kind == LlmTaskKind.STEP_EXECUTION
        assert result.completed_actions == ["updated scope"]
        assert result.diff_based_findings == ["новый endpoint появился в diff"]
        assert result.snapshot_based_findings == ["текущая структура каталогов"]
        assert cli_task.workflow_id == "wf-1"
        assert cli_task.step_id == "define_scope"
        assert cli_task.expected_schema_name == "init_arch_v1"
        recorded_events = [call.args[0] for call in audit_service.record.call_args_list]
        assert [event.event_type for event in recorded_events] == [
            EventType.LLM_TASK_REQUESTED,
            EventType.LLM_TASK_COMPLETED,
        ]
        assert all(event.actor is AuditActor.LLM_WORKER for event in recorded_events)
        assert all(event.payload["llm_call_id"] == cli_task.task_id for event in recorded_events)

    async def test_run_task_parses_structured_result_wrapped_in_prose_and_json_fence(self) -> None:
        # Regression: codex's final agent_message sometimes wraps the required JSON report in
        # explanatory prose plus a ```json fence instead of returning raw JSON. A naive
        # json.loads() on the whole text used to throw and silently fall back to an empty result,
        # dropping fields like `domain_assessment` even though the LLM produced them (observed on
        # a real `assess_scope_and_domains` run - see _extract_json_object's docstring).
        audit_service = unittest.mock.MagicMock()
        service = LlmCliService(audit_service=audit_service)
        request = LlmTaskRequest(
            task_kind=LlmTaskKind.STEP_EXECUTION,
            step_id=StepId.ASSESS_SCOPE_AND_DOMAINS,
            prompt_text="assess",
            workspace_dir="/workspace",
            timeout_seconds=30,
            expected_schema_name="init_arch_v1",
            session_id="wf-1",
        )
        cli_task = _make_task(engine_name="codex")
        cli_task.task_status = TaskStatus.SUCCESS
        cli_task.task_result = (
            "Все данные собраны. Анализ завершён.\n\n"
            "**Итог оценки:** репозиторий небольшой, per_module.\n\n"
            "```json\n"
            '{"completed_actions": ["assessed"], "domain_assessment": '
            '{"volume_class": "small", "strategy": "per_module", "domains": []}}\n'
            "```\n"
        )

        with unittest.mock.patch.object(service, "_build_cli_task", return_value=cli_task):
            with unittest.mock.patch.object(service, "_run_cli_task", new=unittest.mock.AsyncMock()):
                result = await service.run_task(request, engine_name="codex")

        assert result.completed_actions == ["assessed"]
        assert result.domain_assessment is not None
        assert result.domain_assessment.strategy.value == "per_module"

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
        assert all(event.payload["llm_call_id"] == cli_task.task_id for event in recorded_events)

    async def test_run_task_publishes_live_bus_events_on_success(self) -> None:
        service = LlmCliService(audit_service=unittest.mock.MagicMock())
        request = LlmTaskRequest(
            task_kind=LlmTaskKind.STEP_EXECUTION,
            step_id=StepId.ANALYZE_REPOSITORIES,
            prompt_text="do work",
            workspace_dir="/workspace",
            timeout_seconds=30,
            expected_schema_name="init_arch_v1",
            session_id="wf-live",
            repository_name="svc-a",
        )
        cli_task = _make_task(engine_name="claude")
        cli_task.task_status = TaskStatus.SUCCESS
        cli_task.task_result = json.dumps({"completed_actions": ["done"], "notes": "ok"})

        subscription = get_workflow_event_bus().subscribe("wf-live")
        with unittest.mock.patch.object(service, "_build_cli_task", return_value=cli_task):
            with unittest.mock.patch.object(service, "_run_cli_task", new=unittest.mock.AsyncMock()):
                await service.run_task(request, engine_name="claude")

        published = [subscription.get_nowait() for _ in range(subscription.qsize())]
        assert [event["event_type"] for event in published] == ["llm_call_started", "llm_call_completed"]
        assert all(event["actor"] == "llm" for event in published)
        assert all(event["repo_name"] == "svc-a" for event in published)
        assert all(event["step_label"] == "Анализ репозиториев" for event in published)
        assert published[0]["prompt_text"] == "do work"
        assert published[1]["completed_actions"] == ["done"]
        assert "ok" in published[1]["raw_output"]

    async def test_run_task_publishes_live_bus_event_on_failure(self) -> None:
        service = LlmCliService(audit_service=unittest.mock.MagicMock())
        request = LlmTaskRequest(
            task_kind=LlmTaskKind.STEP_EXECUTION,
            step_id=StepId.DEFINE_SCOPE,
            prompt_text="do work",
            workspace_dir="/workspace",
            timeout_seconds=30,
            expected_schema_name="init_arch_v1",
            session_id="wf-live",
        )
        cli_task = _make_task(engine_name="claude")
        cli_task.task_status = TaskStatus.FAILED
        cli_task.task_error = "boom"

        subscription = get_workflow_event_bus().subscribe("wf-live")
        with unittest.mock.patch.object(service, "_build_cli_task", return_value=cli_task):
            with unittest.mock.patch.object(service, "_run_cli_task", new=unittest.mock.AsyncMock()):
                with pytest.raises(RuntimeError):
                    await service.run_task(request, engine_name="claude")

        published = [subscription.get_nowait() for _ in range(subscription.qsize())]
        assert [event["event_type"] for event in published] == ["llm_call_started", "llm_call_failed"]
        assert published[1]["error"] == "boom"
        assert published[1]["error_reason"] == "task_failed"

    async def test_run_task_skips_bus_publish_without_session_id(self) -> None:
        service = LlmCliService(audit_service=unittest.mock.MagicMock())
        request = LlmTaskRequest(
            task_kind=LlmTaskKind.STEP_EXECUTION,
            step_id=StepId.DEFINE_SCOPE,
            prompt_text="do work",
            workspace_dir="/workspace",
            timeout_seconds=30,
            expected_schema_name="init_arch_v1",
            session_id="",
        )
        cli_task = _make_task(engine_name="claude")
        cli_task.task_status = TaskStatus.SUCCESS
        cli_task.task_result = json.dumps({"notes": "ok"})

        with unittest.mock.patch.object(service, "_build_cli_task", return_value=cli_task):
            with unittest.mock.patch.object(service, "_run_cli_task", new=unittest.mock.AsyncMock()):
                await service.run_task(request, engine_name="claude")

        assert get_workflow_event_bus()._subscribers == {}

    async def test_run_task_raises_typed_error_for_limit_exhaustion(self) -> None:
        service = LlmCliService(audit_service=unittest.mock.MagicMock())
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
        cli_task.task_error = "limit_exhausted: usage limit reached"

        with unittest.mock.patch.object(service, "_build_cli_task", return_value=cli_task):
            with unittest.mock.patch.object(service, "_run_cli_task", new=unittest.mock.AsyncMock()):
                with pytest.raises(LlmTaskExecutionError, match="limit_exhausted"):
                    await service.run_task(request, engine_name="claude")


class TestLlmCliServiceTokenUsage:
    def _make_request(self, **overrides: object) -> LlmTaskRequest:
        defaults: dict[str, object] = dict(
            task_kind=LlmTaskKind.STEP_EXECUTION,
            step_id=StepId.DEFINE_SCOPE,
            prompt_text="do work",
            workspace_dir="/workspace",
            timeout_seconds=30,
            expected_schema_name="init_arch_v1",
            session_id="wf-usage",
        )
        defaults.update(overrides)
        return LlmTaskRequest(**defaults)  # type: ignore[arg-type]

    async def test_persists_and_publishes_usage_on_success(self) -> None:
        service = LlmCliService(audit_service=unittest.mock.MagicMock())
        request = self._make_request()
        cli_task = _make_task(engine_name="claude")
        cli_task.task_status = TaskStatus.SUCCESS
        cli_task.task_result = json.dumps({"notes": "ok"})
        cli_task.model_name = "claude-sonnet-4-5"
        cli_task.input_tokens = 50
        cli_task.output_tokens = 12
        cumulative = {"claude-sonnet-4-5": {"input_tokens": 150, "output_tokens": 40}}

        subscription = get_workflow_event_bus().subscribe("wf-usage")
        with (
            unittest.mock.patch.object(service, "_build_cli_task", return_value=cli_task),
            unittest.mock.patch.object(service, "_run_cli_task", new=unittest.mock.AsyncMock()),
            unittest.mock.patch(
                "app.services.task_runner._persist_token_usage",
                new=unittest.mock.AsyncMock(return_value=cumulative),
            ) as mock_persist,
        ):
            await service.run_task(request, engine_name="claude")

        mock_persist.assert_awaited_once_with(
            "wf-usage", model_name="claude-sonnet-4-5", input_tokens=50, output_tokens=12
        )
        published = [subscription.get_nowait() for _ in range(subscription.qsize())]
        completed_event = next(event for event in published if event["event_type"] == "llm_call_completed")
        assert completed_event["model_name"] == "claude-sonnet-4-5"
        assert completed_event["input_tokens"] == 50
        assert completed_event["output_tokens"] == 12
        assert completed_event["token_usage_by_model"] == cumulative

    async def test_persists_and_publishes_usage_on_failure(self) -> None:
        service = LlmCliService(audit_service=unittest.mock.MagicMock())
        request = self._make_request()
        cli_task = _make_task(engine_name="codex")
        cli_task.task_status = TaskStatus.FAILED
        cli_task.task_error = "boom"
        cli_task.model_name = "codex:default"
        cli_task.input_tokens = 20
        cli_task.output_tokens = 5

        subscription = get_workflow_event_bus().subscribe("wf-usage")
        with (
            unittest.mock.patch.object(service, "_build_cli_task", return_value=cli_task),
            unittest.mock.patch.object(service, "_run_cli_task", new=unittest.mock.AsyncMock()),
            unittest.mock.patch(
                "app.services.task_runner._persist_token_usage",
                new=unittest.mock.AsyncMock(return_value=None),
            ) as mock_persist,
        ):
            with pytest.raises(RuntimeError):
                await service.run_task(request, engine_name="codex")

        mock_persist.assert_awaited_once_with("wf-usage", model_name="codex:default", input_tokens=20, output_tokens=5)
        published = [subscription.get_nowait() for _ in range(subscription.qsize())]
        failed_event = next(event for event in published if event["event_type"] == "llm_call_failed")
        assert failed_event["model_name"] == "codex:default"
        assert failed_event["input_tokens"] == 20
        assert failed_event["output_tokens"] == 5

    async def test_records_audit_events_with_usage_scalars(self) -> None:
        audit_service = unittest.mock.MagicMock()
        service = LlmCliService(audit_service=audit_service)
        request = self._make_request()
        cli_task = _make_task(engine_name="claude")
        cli_task.task_status = TaskStatus.SUCCESS
        cli_task.task_result = json.dumps({"notes": "ok"})
        cli_task.model_name = "claude-sonnet-4-5"
        cli_task.input_tokens = 7
        cli_task.output_tokens = 3

        with (
            unittest.mock.patch.object(service, "_build_cli_task", return_value=cli_task),
            unittest.mock.patch.object(service, "_run_cli_task", new=unittest.mock.AsyncMock()),
            unittest.mock.patch(
                "app.services.task_runner._persist_token_usage",
                new=unittest.mock.AsyncMock(return_value=None),
            ),
        ):
            await service.run_task(request, engine_name="claude")

        completed_event = next(
            call.args[0]
            for call in audit_service.record.call_args_list
            if call.args[0].event_type == EventType.LLM_TASK_COMPLETED
        )
        assert completed_event.payload["model_name"] == "claude-sonnet-4-5"
        assert completed_event.payload["input_tokens"] == 7
        assert completed_event.payload["output_tokens"] == 3


class TestExecuteEngineTask:
    async def test_langgraph_engine_dispatches_to_run_langgraph_task(self) -> None:
        cli_task = _make_task(engine_name="langgraph")
        pool = _make_pool()

        with (
            unittest.mock.patch(
                "app.services.task_runner.run_langgraph_task", new=unittest.mock.AsyncMock()
            ) as mock_run_langgraph_task,
            unittest.mock.patch(
                "app.services.task_runner.run_cli_task", new=unittest.mock.AsyncMock()
            ) as mock_run_cli_task,
        ):
            await execute_engine_task(cli_task, pool)

        mock_run_langgraph_task.assert_awaited_once_with(cli_task, pool)
        mock_run_cli_task.assert_not_called()

    @pytest.mark.parametrize("engine_name", ["claude", "codex"])
    async def test_cli_engines_dispatch_to_run_cli_task(self, engine_name: str) -> None:
        cli_task = _make_task(engine_name=engine_name)
        pool = _make_pool()

        with (
            unittest.mock.patch(
                "app.services.task_runner.run_langgraph_task", new=unittest.mock.AsyncMock()
            ) as mock_run_langgraph_task,
            unittest.mock.patch(
                "app.services.task_runner.run_cli_task", new=unittest.mock.AsyncMock()
            ) as mock_run_cli_task,
        ):
            await execute_engine_task(cli_task, pool)

        mock_run_cli_task.assert_awaited_once_with(cli_task, pool)
        mock_run_langgraph_task.assert_not_called()
