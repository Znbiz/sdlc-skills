import unittest.mock

from app.services.cli_auth_checker import (
    _CODEX_AUTH_FILE,
    CliAuthStatus,
    _run_smoke,
    check_claude_auth,
    check_codex_auth,
)


class TestCheckCodexAuth:
    async def test_not_initialized_when_auth_file_missing(self) -> None:
        with unittest.mock.patch.object(type(_CODEX_AUTH_FILE), "exists", return_value=False):
            result = await check_codex_auth()

        assert result["auth_status"] == CliAuthStatus.NOT_INITIALIZED
        assert result["authenticated"] is False
        assert result["auth_file_exists"] is False

    async def test_ok_when_smoke_succeeds(self) -> None:
        with (
            unittest.mock.patch.object(type(_CODEX_AUTH_FILE), "exists", return_value=True),
            unittest.mock.patch(
                "app.services.cli_auth_checker._run_smoke",
                return_value=(0, ""),
            ),
        ):
            result = await check_codex_auth()

        assert result["auth_status"] == CliAuthStatus.OK
        assert result["authenticated"] is True
        assert result["auth_file_exists"] is True

    async def test_auth_expired_on_401(self) -> None:
        with (
            unittest.mock.patch.object(type(_CODEX_AUTH_FILE), "exists", return_value=True),
            unittest.mock.patch(
                "app.services.cli_auth_checker._run_smoke",
                return_value=(401, ""),
            ),
        ):
            result = await check_codex_auth()

        assert result["auth_status"] == CliAuthStatus.AUTH_EXPIRED
        assert result["authenticated"] is False

    async def test_auth_expired_on_auth_in_stderr(self) -> None:
        with (
            unittest.mock.patch.object(type(_CODEX_AUTH_FILE), "exists", return_value=True),
            unittest.mock.patch(
                "app.services.cli_auth_checker._run_smoke",
                return_value=(1, "auth token expired"),
            ),
        ):
            result = await check_codex_auth()

        assert result["auth_status"] == CliAuthStatus.AUTH_EXPIRED


class TestCheckClaudeAuth:
    def _mock_auth_dir_exists(self, *, exists: bool, has_files: bool = True) -> unittest.mock.MagicMock:
        mock_path = unittest.mock.MagicMock()
        mock_path.exists.return_value = exists
        mock_path.iterdir.return_value = iter(["somefile"]) if has_files else iter([])
        return mock_path

    async def test_not_initialized_when_dir_missing(self) -> None:
        with unittest.mock.patch(
            "app.services.cli_auth_checker._CLAUDE_AUTH_DIR",
            self._mock_auth_dir_exists(exists=False),
        ):
            result = await check_claude_auth()

        assert result["auth_status"] == CliAuthStatus.NOT_INITIALIZED
        assert result["authenticated"] is False

    async def test_not_initialized_when_dir_empty(self) -> None:
        with unittest.mock.patch(
            "app.services.cli_auth_checker._CLAUDE_AUTH_DIR",
            self._mock_auth_dir_exists(exists=True, has_files=False),
        ):
            result = await check_claude_auth()

        assert result["auth_status"] == CliAuthStatus.NOT_INITIALIZED

    async def test_ok_when_smoke_succeeds(self) -> None:
        with (
            unittest.mock.patch(
                "app.services.cli_auth_checker._CLAUDE_AUTH_DIR",
                self._mock_auth_dir_exists(exists=True),
            ),
            unittest.mock.patch(
                "app.services.cli_auth_checker._run_smoke",
                return_value=(0, ""),
            ),
        ):
            result = await check_claude_auth()

        assert result["auth_status"] == CliAuthStatus.OK
        assert result["authenticated"] is True

    async def test_auth_expired_on_not_logged_in(self) -> None:
        with (
            unittest.mock.patch(
                "app.services.cli_auth_checker._CLAUDE_AUTH_DIR",
                self._mock_auth_dir_exists(exists=True),
            ),
            unittest.mock.patch(
                "app.services.cli_auth_checker._run_smoke",
                return_value=(1, "not logged in, please run claude auth login"),
            ),
        ):
            result = await check_claude_auth()

        assert result["auth_status"] == CliAuthStatus.AUTH_EXPIRED
        assert result["authenticated"] is False

    async def test_auth_expired_on_unknown_error_phrase(self) -> None:
        with (
            unittest.mock.patch(
                "app.services.cli_auth_checker._CLAUDE_AUTH_DIR",
                self._mock_auth_dir_exists(exists=True),
            ),
            unittest.mock.patch(
                "app.services.cli_auth_checker._run_smoke",
                return_value=(1, "some unexpected failure"),
            ),
        ):
            result = await check_claude_auth()

        assert result["auth_status"] == CliAuthStatus.AUTH_EXPIRED
        assert result["authenticated"] is False


class TestCheckCodexAuthFallback:
    async def test_auth_expired_on_nonzero_non_auth_exit(self) -> None:
        with (
            unittest.mock.patch.object(type(_CODEX_AUTH_FILE), "exists", return_value=True),
            unittest.mock.patch(
                "app.services.cli_auth_checker._run_smoke",
                return_value=(1, "some unrelated failure"),
            ),
        ):
            result = await check_codex_auth()

        assert result["auth_status"] == CliAuthStatus.AUTH_EXPIRED
        assert result["authenticated"] is False


class TestRunSmoke:
    async def test_smoke_success(self) -> None:
        mock_proc = unittest.mock.AsyncMock()
        mock_proc.communicate = unittest.mock.AsyncMock(return_value=(b"", b"stderr output"))
        mock_proc.returncode = 0

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            exit_code, stderr = await _run_smoke(["echo", "ok"])

        assert exit_code == 0
        assert stderr == "stderr output"

    async def test_smoke_nonzero_exit(self) -> None:
        mock_proc = unittest.mock.AsyncMock()
        mock_proc.communicate = unittest.mock.AsyncMock(return_value=(b"", b"auth error"))
        mock_proc.returncode = 1

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            exit_code, stderr = await _run_smoke(["false"])

        assert exit_code == 1
        assert "auth error" in stderr

    async def test_smoke_os_error_returns_minus_one(self) -> None:
        with unittest.mock.patch("asyncio.create_subprocess_exec", side_effect=OSError("not found")):
            exit_code, stderr = await _run_smoke(["nonexistent_binary"])

        assert exit_code == -1
        assert stderr == ""

    async def test_smoke_timeout_returns_minus_one(self) -> None:
        mock_proc = unittest.mock.AsyncMock()
        mock_proc.communicate = unittest.mock.AsyncMock(side_effect=TimeoutError)

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            exit_code, stderr = await _run_smoke(["sleep", "100"])

        assert exit_code == -1
        assert stderr == ""
