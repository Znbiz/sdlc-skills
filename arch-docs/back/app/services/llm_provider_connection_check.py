from __future__ import annotations

import dataclasses
import typing

import httpx

from app.services.llm_providers import get_llm_provider_connection_async

if typing.TYPE_CHECKING:
    import uuid

    from app.services.llm_providers import LlmProviderConnectionDetail

_TEST_TIMEOUT_SECONDS: typing.Final[float] = 10.0
_TEST_PROMPT: typing.Final[str] = "ping"
_MESSAGE_TRUNCATE_CHARS: typing.Final[int] = 300


@dataclasses.dataclass(frozen=True, slots=True)
class LlmProviderConnectionTestResult:
    success: bool
    status_code: int | None
    message: str


def _build_test_request(connection: LlmProviderConnectionDetail) -> tuple[str, dict[str, typing.Any]]:
    base_url = connection.base_url.rstrip("/")
    if connection.wire_api == "responses":
        return f"{base_url}/responses", {
            "model": connection.model,
            "input": _TEST_PROMPT,
            "max_output_tokens": 1,
        }
    return f"{base_url}/chat/completions", {
        "model": connection.model,
        "messages": [{"role": "user", "content": _TEST_PROMPT}],
        "max_tokens": 1,
    }


def _extract_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return (response.text or f"HTTP {response.status_code}")[:_MESSAGE_TRUNCATE_CHARS]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:_MESSAGE_TRUNCATE_CHARS]
        if isinstance(error, str) and error:
            return error[:_MESSAGE_TRUNCATE_CHARS]
    return f"HTTP {response.status_code}"


async def check_llm_provider_connection_async(connection_id: uuid.UUID) -> LlmProviderConnectionTestResult:
    """Send one minimal real request to the connection's endpoint to verify it actually works.

    Raises `LlmProviderConnectionNotFoundError` (propagated from `get_llm_provider_connection_async`)
    if `connection_id` does not exist - the REST layer turns that into a 404, same as other
    llm-providers endpoints.
    """
    connection = await get_llm_provider_connection_async(connection_id)
    if not connection.token:
        return LlmProviderConnectionTestResult(success=False, status_code=None, message="Токен не настроен")

    url, payload = _build_test_request(connection)
    headers = {"Authorization": f"Bearer {connection.token}"}

    try:
        async with httpx.AsyncClient(timeout=_TEST_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException:
        return LlmProviderConnectionTestResult(success=False, status_code=None, message="Таймаут запроса к провайдеру")
    except httpx.RequestError as exc:
        return LlmProviderConnectionTestResult(
            success=False, status_code=None, message=f"Не удалось подключиться: {exc}"
        )

    if response.status_code < httpx.codes.BAD_REQUEST:
        return LlmProviderConnectionTestResult(
            success=True, status_code=response.status_code, message="Подключение работает"
        )
    return LlmProviderConnectionTestResult(
        success=False, status_code=response.status_code, message=_extract_error_message(response)
    )
