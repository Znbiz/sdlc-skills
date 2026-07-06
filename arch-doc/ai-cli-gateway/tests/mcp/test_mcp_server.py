import asyncio
import unittest.mock

import pytest

from app.mcp_server import INIT_ARCH_PROMPT, UPDATE_ARCH_PROMPT_BASE, init_arch, query, run_cli_subprocess, update_arch


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
    async def test_returns_success_with_output(self) -> None:
        mock_proc = _make_mock_process(returncode=0, stdout=b"arch created")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await init_arch(repo_path="/workspace/my-repo")

        assert result["operation_status"] == "success"
        assert result["cli_output"] == "arch created"

    async def test_uses_init_arch_prompt(self) -> None:
        mock_proc = _make_mock_process(returncode=0, stdout=b"ok")
        captured: list[list[str]] = []

        async def fake_exec(*args: str, **_kwargs) -> unittest.mock.MagicMock:
            captured.append(list(args))
            return mock_proc

        with unittest.mock.patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            await init_arch(repo_path="/workspace/my-repo")

        cmd = captured[0]
        assert INIT_ARCH_PROMPT in cmd

    async def test_codex_engine(self) -> None:
        mock_proc = _make_mock_process(returncode=0, stdout=b"codex arch")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await init_arch(repo_path="/ws", engine_name="codex")

        assert result["operation_status"] == "success"
        cmd = mock_exec.call_args.args
        assert cmd[0] == "codex"


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
