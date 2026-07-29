import unittest.mock
import uuid

import httpx
import pytest

from app.services.llm_provider_connection_check import check_llm_provider_connection_async
from app.services.llm_providers import LlmProviderConnectionNotFoundError, create_llm_provider_connection_async


@pytest.fixture(autouse=True)
def isolated_llm_provider_secrets_store(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.llm_provider_credentials._SECRETS_DIR", tmp_path / "llm-provider-secrets")


def _mock_response(status_code: int, json_body: dict | None = None, text: str = "") -> unittest.mock.MagicMock:
    response = unittest.mock.MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = text
    response.json = unittest.mock.MagicMock(
        side_effect=(lambda: json_body) if json_body is not None else ValueError("not json")
    )
    return response


class TestTestLlmProviderConnection:
    async def test_raises_not_found_for_missing_connection(self):
        with pytest.raises(LlmProviderConnectionNotFoundError):
            await check_llm_provider_connection_async(uuid.uuid4())

    async def test_returns_success_on_2xx_response(self):
        connection = await create_llm_provider_connection_async(
            name="my-provider", base_url="https://api.example.com/v1", model="my-model", token="sk-abc"
        )
        mock_response = _mock_response(200, {"choices": []})

        with unittest.mock.patch(
            "httpx.AsyncClient.post", new=unittest.mock.AsyncMock(return_value=mock_response)
        ) as mock_post:
            result = await check_llm_provider_connection_async(connection.connection_id)

        assert result.success is True
        assert result.status_code == 200
        called_url = mock_post.call_args.args[0]
        called_headers = mock_post.call_args.kwargs["headers"]
        called_payload = mock_post.call_args.kwargs["json"]
        assert called_url == "https://api.example.com/v1/chat/completions"
        assert called_headers["Authorization"] == "Bearer sk-abc"
        assert called_payload["model"] == "my-model"

    async def test_uses_responses_endpoint_for_responses_wire_api(self):
        connection = await create_llm_provider_connection_async(
            name="my-provider",
            base_url="https://api.example.com/v1",
            model="my-model",
            token="sk-abc",
            wire_api="responses",
        )
        mock_response = _mock_response(200, {})

        with unittest.mock.patch(
            "httpx.AsyncClient.post", new=unittest.mock.AsyncMock(return_value=mock_response)
        ) as mock_post:
            result = await check_llm_provider_connection_async(connection.connection_id)

        assert result.success is True
        assert mock_post.call_args.args[0] == "https://api.example.com/v1/responses"

    async def test_returns_failure_with_error_message_on_4xx_response(self):
        connection = await create_llm_provider_connection_async(
            name="my-provider", base_url="https://api.example.com/v1", model="my-model", token="sk-bad"
        )
        mock_response = _mock_response(401, {"error": {"message": "invalid api key"}})

        with unittest.mock.patch("httpx.AsyncClient.post", new=unittest.mock.AsyncMock(return_value=mock_response)):
            result = await check_llm_provider_connection_async(connection.connection_id)

        assert result.success is False
        assert result.status_code == 401
        assert result.message == "invalid api key"

    async def test_returns_failure_with_raw_text_when_response_is_not_json(self):
        connection = await create_llm_provider_connection_async(
            name="my-provider", base_url="https://api.example.com/v1", model="my-model", token="sk-bad"
        )
        mock_response = _mock_response(500, None, text="internal server error")

        with unittest.mock.patch("httpx.AsyncClient.post", new=unittest.mock.AsyncMock(return_value=mock_response)):
            result = await check_llm_provider_connection_async(connection.connection_id)

        assert result.success is False
        assert result.status_code == 500
        assert result.message == "internal server error"

    async def test_returns_failure_on_timeout(self):
        connection = await create_llm_provider_connection_async(
            name="my-provider", base_url="https://api.example.com/v1", model="my-model", token="sk-abc"
        )

        with unittest.mock.patch(
            "httpx.AsyncClient.post", new=unittest.mock.AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        ):
            result = await check_llm_provider_connection_async(connection.connection_id)

        assert result.success is False
        assert result.status_code is None
        assert "Таймаут" in result.message

    async def test_returns_failure_on_connection_error(self):
        connection = await create_llm_provider_connection_async(
            name="my-provider", base_url="https://api.example.com/v1", model="my-model", token="sk-abc"
        )

        with unittest.mock.patch(
            "httpx.AsyncClient.post",
            new=unittest.mock.AsyncMock(side_effect=httpx.ConnectError("connection refused")),
        ):
            result = await check_llm_provider_connection_async(connection.connection_id)

        assert result.success is False
        assert result.status_code is None
        assert "Не удалось подключиться" in result.message
