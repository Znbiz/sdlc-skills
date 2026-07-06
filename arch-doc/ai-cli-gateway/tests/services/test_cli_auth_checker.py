import unittest.mock

from app.services.cli_auth_checker import (
    _CODEX_AUTH_FILE,
    CliAuthStatus,
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
