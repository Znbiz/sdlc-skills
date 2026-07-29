import unittest.mock

from app.services.cli_task_support import _persist_token_usage, set_db_enabled


class TestPersistTokenUsage:
    def setup_method(self) -> None:
        set_db_enabled(False)

    def teardown_method(self) -> None:
        set_db_enabled(False)

    async def test_returns_none_when_db_disabled(self) -> None:
        set_db_enabled(False)
        result = await _persist_token_usage("wf-1", model_name="m", input_tokens=1, output_tokens=1)
        assert result is None

    async def test_returns_none_when_no_workflow_id(self) -> None:
        set_db_enabled(True)
        result = await _persist_token_usage(None, model_name="m", input_tokens=1, output_tokens=1)
        assert result is None

    async def test_returns_none_when_no_tokens(self) -> None:
        set_db_enabled(True)
        result = await _persist_token_usage("wf-1", model_name="m", input_tokens=0, output_tokens=0)
        assert result is None

    async def test_persists_and_returns_cumulative_usage(self) -> None:
        set_db_enabled(True)
        cumulative = {"m": {"input_tokens": 10, "output_tokens": 5}}
        mock_session_ctx = unittest.mock.AsyncMock()
        mock_session_ctx.__aenter__ = unittest.mock.AsyncMock(return_value=mock_session_ctx)
        mock_session_ctx.__aexit__ = unittest.mock.AsyncMock(return_value=False)

        with (
            unittest.mock.patch("app.services.cli_task_support.get_session", return_value=mock_session_ctx),
            unittest.mock.patch(
                "app.services.cli_task_support.increment_workflow_token_usage",
                new=unittest.mock.AsyncMock(return_value=cumulative),
            ),
        ):
            result = await _persist_token_usage("wf-1", model_name="m", input_tokens=10, output_tokens=5)

        assert result == cumulative

    async def test_survives_db_error_and_returns_none(self) -> None:
        set_db_enabled(True)
        mock_session_ctx = unittest.mock.AsyncMock()
        mock_session_ctx.__aenter__ = unittest.mock.AsyncMock(side_effect=Exception("db down"))
        mock_session_ctx.__aexit__ = unittest.mock.AsyncMock(return_value=False)

        with unittest.mock.patch("app.services.cli_task_support.get_session", return_value=mock_session_ctx):
            result = await _persist_token_usage("wf-1", model_name="m", input_tokens=10, output_tokens=5)

        assert result is None
