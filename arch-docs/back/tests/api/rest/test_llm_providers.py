import unittest.mock
import uuid

import httpx
from fastapi import status

from app.services.llm_providers import (
    LlmProviderConnectionAlreadyExistsError,
    LlmProviderConnectionDetail,
    LlmProviderConnectionNotFoundError,
    LlmProviderConnectionSummary,
    LlmProviderConnectionValidationError,
)


class TestListLlmProviderConnections:
    async def test_returns_configured_connections(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        connection_id = uuid.uuid4()
        with unittest.mock.patch(
            "app.api.rest.llm_providers.list_llm_provider_connections_async",
            new=unittest.mock.AsyncMock(
                return_value=[
                    LlmProviderConnectionSummary(
                        connection_id=connection_id,
                        name="my-provider",
                        base_url="https://api.example.com/v1",
                        model="my-model",
                        wire_api="chat",
                        requires_openai_auth=False,
                    )
                ]
            ),
        ):
            response = await async_client.get("/api/rest/llm-providers/", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [
            {
                "connection_id": str(connection_id),
                "name": "my-provider",
                "base_url": "https://api.example.com/v1",
                "model": "my-model",
                "wire_api": "chat",
                "requires_openai_auth": False,
            }
        ]

    async def test_requires_auth(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.get("/api/rest/llm-providers/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestGetLlmProviderConnection:
    async def test_never_echoes_real_token(self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
        connection_id = uuid.uuid4()
        with unittest.mock.patch(
            "app.api.rest.llm_providers.get_llm_provider_connection_async",
            new=unittest.mock.AsyncMock(
                return_value=LlmProviderConnectionDetail(
                    connection_id=connection_id,
                    name="my-provider",
                    base_url="https://api.example.com/v1",
                    model="my-model",
                    wire_api="chat",
                    requires_openai_auth=False,
                    token="sk-super-secret",
                )
            ),
        ):
            response = await async_client.get(f"/api/rest/llm-providers/{connection_id}/", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert "sk-super-secret" not in response.text
        assert response.json()["token"] == "********"

    async def test_returns_404_for_unknown_id(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        connection_id = uuid.uuid4()
        with unittest.mock.patch(
            "app.api.rest.llm_providers.get_llm_provider_connection_async",
            new=unittest.mock.AsyncMock(side_effect=LlmProviderConnectionNotFoundError(connection_id)),
        ):
            response = await async_client.get(f"/api/rest/llm-providers/{connection_id}/", headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestCreateLlmProviderConnection:
    async def test_creates_connection(self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
        connection_id = uuid.uuid4()
        with unittest.mock.patch(
            "app.api.rest.llm_providers.create_llm_provider_connection_async",
            new=unittest.mock.AsyncMock(
                return_value=LlmProviderConnectionSummary(
                    connection_id=connection_id,
                    name="my-provider",
                    base_url="https://api.example.com/v1",
                    model="my-model",
                    wire_api="chat",
                    requires_openai_auth=False,
                )
            ),
        ) as mock_create:
            response = await async_client.post(
                "/api/rest/llm-providers/",
                json={
                    "name": "my-provider",
                    "base_url": "https://api.example.com/v1",
                    "model": "my-model",
                    "token": "sk-abc",
                },
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_201_CREATED
        mock_create.assert_awaited_once_with(
            name="my-provider",
            base_url="https://api.example.com/v1",
            model="my-model",
            token="sk-abc",
            wire_api="chat",
            requires_openai_auth=False,
        )

    async def test_never_echoes_token_back(self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
        with unittest.mock.patch(
            "app.api.rest.llm_providers.create_llm_provider_connection_async",
            new=unittest.mock.AsyncMock(
                return_value=LlmProviderConnectionSummary(
                    connection_id=uuid.uuid4(),
                    name="my-provider",
                    base_url="https://api.example.com/v1",
                    model="my-model",
                    wire_api="chat",
                    requires_openai_auth=False,
                )
            ),
        ):
            response = await async_client.post(
                "/api/rest/llm-providers/",
                json={
                    "name": "my-provider",
                    "base_url": "https://api.example.com/v1",
                    "model": "my-model",
                    "token": "super-secret-token",
                },
                headers=auth_headers,
            )

        assert "super-secret-token" not in response.text

    async def test_returns_422_on_validation_error(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with unittest.mock.patch(
            "app.api.rest.llm_providers.create_llm_provider_connection_async",
            new=unittest.mock.AsyncMock(side_effect=LlmProviderConnectionValidationError("token must not be empty")),
        ):
            response = await async_client.post(
                "/api/rest/llm-providers/",
                json={
                    "name": "my-provider",
                    "base_url": "https://api.example.com/v1",
                    "model": "my-model",
                    "token": "  ",
                },
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_returns_409_on_duplicate_name(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with unittest.mock.patch(
            "app.api.rest.llm_providers.create_llm_provider_connection_async",
            new=unittest.mock.AsyncMock(side_effect=LlmProviderConnectionAlreadyExistsError("my-provider")),
        ):
            response = await async_client.post(
                "/api/rest/llm-providers/",
                json={
                    "name": "my-provider",
                    "base_url": "https://api.example.com/v1",
                    "model": "my-model",
                    "token": "sk-abc",
                },
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_409_CONFLICT


class TestDeleteLlmProviderConnection:
    async def test_removes_connection(self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
        connection_id = uuid.uuid4()
        with unittest.mock.patch(
            "app.api.rest.llm_providers.delete_llm_provider_connection_async",
            new=unittest.mock.AsyncMock(),
        ) as mock_delete:
            response = await async_client.delete(f"/api/rest/llm-providers/{connection_id}/", headers=auth_headers)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_delete.assert_awaited_once_with(connection_id)

    async def test_returns_404_for_unknown_id(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        connection_id = uuid.uuid4()
        with unittest.mock.patch(
            "app.api.rest.llm_providers.delete_llm_provider_connection_async",
            new=unittest.mock.AsyncMock(side_effect=LlmProviderConnectionNotFoundError(connection_id)),
        ):
            response = await async_client.delete(f"/api/rest/llm-providers/{connection_id}/", headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND
