import asyncio
import types
import unittest.mock

import pytest

from app.mcp_server import UPDATE_ARCH_PROMPT_BASE, init_arch, query, run_cli_subprocess, update_arch


def _make_mock_process(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> unittest.mock.MagicMock:
    mock_proc = unittest.mock.MagicMock()
    mock_proc.returncode = returncode

    async def communicate() -> tuple[bytes, bytes]:
        return stdout, stderr

    mock_proc.communicate = communicate
    return mock_proc


class TestRunCliSubprocess:
    async def test_claude_builds_correct_cmd(self) -> None:
        mock_proc = _make_mock_process(returncode=0, stdout=b"result")

        captured: list[list[str]] = []

        async def fake_exec(*args: str, **_kwargs) -> unittest.mock.MagicMock:
            captured.append(list(args))
            return mock_proc

        with unittest.mock.patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await run_cli_subprocess("claude", "my prompt", "/workspace", 30)

        assert result == "result"
        cmd = captured[0]
        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "my prompt" in cmd
        assert "--output-format" in cmd
        assert "stream-json" in cmd

    async def test_codex_builds_correct_cmd(self) -> None:
        mock_proc = _make_mock_process(returncode=0, stdout=b"codex result")

        captured: list[list[str]] = []

        async def fake_exec(*args: str, **_kwargs) -> unittest.mock.MagicMock:
            captured.append(list(args))
            return mock_proc

        with unittest.mock.patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await run_cli_subprocess("codex", "codex prompt", "/ws", 30)

        assert result == "codex result"
        cmd = captured[0]
        assert cmd[0] == "codex"
        assert "exec" in cmd
        assert "--skip-git-repo-check" in cmd
        assert "codex prompt" in cmd

    async def test_raises_on_nonzero_exit(self) -> None:
        mock_proc = _make_mock_process(returncode=1, stdout=b"", stderr=b"auth error")

        with (
            unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            pytest.raises(RuntimeError, match="auth error"),
        ):
            await run_cli_subprocess("claude", "prompt", "/ws", 30)

    async def test_raises_on_timeout(self) -> None:
        mock_proc = _make_mock_process()

        with (
            unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            unittest.mock.patch("asyncio.wait_for", side_effect=asyncio.TimeoutError),
            pytest.raises(asyncio.TimeoutError),
        ):
            await run_cli_subprocess("claude", "prompt", "/ws", 1)


class TestInitArch:
    async def test_delegates_to_backend_workflow_runtime(self) -> None:
        with unittest.mock.patch(
            "app.mcp_server.start_init_arch_workflow", new_callable=unittest.mock.AsyncMock
        ) as mock_start:
            mock_start.return_value = types.SimpleNamespace(
                workflow_id="wf-mcp",
                workflow_status="running",
                current_step_id="define_scope",
                created_at=types.SimpleNamespace(isoformat=lambda: "2026-07-08T00:00:00+00:00"),
            )

            result = await init_arch(
                repo_path="/workspace/my-repo",
                product_name="My Repo",
                arch_repo_dir="/workspace/my-repo/arch-doc",
            )

        assert result["workflow_id"] == "wf-mcp"
        assert result["workflow_status"] == "running"
        mock_start.assert_awaited_once()

    async def test_builds_default_dirs_from_repo_path(self) -> None:
        with unittest.mock.patch(
            "app.mcp_server.start_init_arch_workflow", new_callable=unittest.mock.AsyncMock
        ) as mock_start:
            mock_start.return_value = types.SimpleNamespace(
                workflow_id="wf-mcp",
                workflow_status="running",
                current_step_id="define_scope",
                created_at=types.SimpleNamespace(isoformat=lambda: "2026-07-08T00:00:00+00:00"),
            )

            await init_arch(repo_path="/workspace/my-repo")

        kwargs = mock_start.await_args.kwargs
        assert kwargs["product_name"] == "my-repo"
        assert kwargs["workspace_dir"] == "/workspace/my-repo"
        assert kwargs["arch_repo_dir"] == "/workspace/my-repo/arch-doc"


class TestUpdateArch:
    async def test_returns_success_with_output(self) -> None:
        mock_proc = _make_mock_process(returncode=0, stdout=b"updated")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await update_arch(repo_path="/workspace/my-repo")

        assert result["operation_status"] == "success"
        assert result["cli_output"] == "updated"

    async def test_uses_base_prompt_without_diff_context(self) -> None:
        mock_proc = _make_mock_process(returncode=0, stdout=b"ok")
        captured: list[list[str]] = []

        async def fake_exec(*args: str, **_kwargs) -> unittest.mock.MagicMock:
            captured.append(list(args))
            return mock_proc

        with unittest.mock.patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            await update_arch(repo_path="/ws")

        cmd = captured[0]
        assert UPDATE_ARCH_PROMPT_BASE in cmd

    async def test_appends_diff_context_to_prompt(self) -> None:
        mock_proc = _make_mock_process(returncode=0, stdout=b"ok")
        captured: list[list[str]] = []

        async def fake_exec(*args: str, **_kwargs) -> unittest.mock.MagicMock:
            captured.append(list(args))
            return mock_proc

        with unittest.mock.patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            await update_arch(repo_path="/ws", diff_context="some diff")

        cmd = captured[0]
        prompt_arg = next(arg for arg in cmd if UPDATE_ARCH_PROMPT_BASE in arg)
        assert "some diff" in prompt_arg


class TestQuery:
    async def test_returns_answer_text(self) -> None:
        mock_proc = _make_mock_process(returncode=0, stdout=b"service uses PostgreSQL")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await query(question="What database is used?", repo_path="/ws")

        assert result["answer_text"] == "service uses PostgreSQL"

    async def test_includes_question_in_prompt(self) -> None:
        mock_proc = _make_mock_process(returncode=0, stdout=b"answer")
        captured: list[list[str]] = []

        async def fake_exec(*args: str, **_kwargs) -> unittest.mock.MagicMock:
            captured.append(list(args))
            return mock_proc

        with unittest.mock.patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            await query(question="How does auth work?", repo_path="/ws")

        cmd = captured[0]
        prompt_arg = next(arg for arg in cmd if "arch-doc/" in arg)
        assert "How does auth work?" in prompt_arg
