import unittest.mock
import uuid

import httpx
from fastapi import status

from app.services.git_connections import (
    GitConnectionAlreadyExistsError,
    GitConnectionDetail,
    GitConnectionNotFoundError,
    GitConnectionSummary,
    GitConnectionValidationError,
)


class TestListGitConnections:
    async def test_returns_configured_connections(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        connection_id = uuid.uuid4()
        with unittest.mock.patch(
            "app.api.rest.git_connections.list_git_connections_async",
            new=unittest.mock.AsyncMock(
                return_value=[
                    GitConnectionSummary(connection_id=connection_id, host="github.com", connection_type="token")
                ]
            ),
        ):
            response = await async_client.get("/api/rest/git-connections/", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [
            {"connection_id": str(connection_id), "host": "github.com", "connection_type": "token"}
        ]

    async def test_requires_auth(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.get("/api/rest/git-connections/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestGetGitConnection:
    async def test_returns_detail_for_token_connection(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        connection_id = uuid.uuid4()
        with unittest.mock.patch(
            "app.api.rest.git_connections.get_git_connection_async",
            new=unittest.mock.AsyncMock(
                return_value=GitConnectionDetail(
                    connection_id=connection_id,
                    host="github.com",
                    connection_type="token",
                    token="ghp_abc",
                    username="oauth2",
                )
            ),
        ):
            response = await async_client.get(f"/api/rest/git-connections/{connection_id}/", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "connection_id": str(connection_id),
            "host": "github.com",
            "connection_type": "token",
            "token": "ghp_abc",
            "username": "oauth2",
        }

    async def test_returns_404_for_unknown_id(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        connection_id = uuid.uuid4()
        with unittest.mock.patch(
            "app.api.rest.git_connections.get_git_connection_async",
            new=unittest.mock.AsyncMock(side_effect=GitConnectionNotFoundError(connection_id)),
        ):
            response = await async_client.get(f"/api/rest/git-connections/{connection_id}/", headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_rejects_non_uuid_id(self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
        response = await async_client.get("/api/rest/git-connections/not-a-uuid/", headers=auth_headers)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestCreateGitConnection:
    async def test_creates_token_connection(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        connection_id = uuid.uuid4()
        with unittest.mock.patch(
            "app.api.rest.git_connections.create_git_connection_async",
            new=unittest.mock.AsyncMock(
                return_value=GitConnectionSummary(
                    connection_id=connection_id, host="github.com", connection_type="token"
                )
            ),
        ) as mock_create:
            response = await async_client.post(
                "/api/rest/git-connections/",
                json={"host": "github.com", "connection_type": "token", "token": "ghp_abc", "username": "oauth2"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json() == {
            "connection_id": str(connection_id),
            "host": "github.com",
            "connection_type": "token",
        }
        mock_create.assert_awaited_once_with(
            host="github.com", connection_type="token", token="ghp_abc", username="oauth2"
        )

    async def test_never_echoes_token_back(self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
        with unittest.mock.patch(
            "app.api.rest.git_connections.create_git_connection_async",
            new=unittest.mock.AsyncMock(
                return_value=GitConnectionSummary(
                    connection_id=uuid.uuid4(), host="github.com", connection_type="token"
                )
            ),
        ):
            response = await async_client.post(
                "/api/rest/git-connections/",
                json={"host": "github.com", "connection_type": "token", "token": "super-secret-token"},
                headers=auth_headers,
            )

        assert "super-secret-token" not in response.text

    async def test_rejects_blank_host(self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
        response = await async_client.post(
            "/api/rest/git-connections/",
            json={"host": "  ", "connection_type": "ssh"},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_returns_422_on_validation_error(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with unittest.mock.patch(
            "app.api.rest.git_connections.create_git_connection_async",
            new=unittest.mock.AsyncMock(side_effect=GitConnectionValidationError("token must not be empty")),
        ):
            response = await async_client.post(
                "/api/rest/git-connections/",
                json={"host": "github.com", "connection_type": "token", "token": "   "},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_returns_409_on_duplicate_host(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with unittest.mock.patch(
            "app.api.rest.git_connections.create_git_connection_async",
            new=unittest.mock.AsyncMock(side_effect=GitConnectionAlreadyExistsError("github.com")),
        ):
            response = await async_client.post(
                "/api/rest/git-connections/",
                json={"host": "github.com", "connection_type": "ssh"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_409_CONFLICT


class TestUpdateGitConnection:
    async def test_updates_connection(self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
        connection_id = uuid.uuid4()
        with unittest.mock.patch(
            "app.api.rest.git_connections.update_git_connection_async",
            new=unittest.mock.AsyncMock(
                return_value=GitConnectionSummary(connection_id=connection_id, host="github.com", connection_type="ssh")
            ),
        ) as mock_update:
            response = await async_client.put(
                f"/api/rest/git-connections/{connection_id}/",
                json={"host": "github.com", "connection_type": "ssh"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"connection_id": str(connection_id), "host": "github.com", "connection_type": "ssh"}
        mock_update.assert_awaited_once_with(
            connection_id=connection_id, host="github.com", connection_type="ssh", token=None, username=None
        )

    async def test_returns_404_for_unknown_id(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        connection_id = uuid.uuid4()
        with unittest.mock.patch(
            "app.api.rest.git_connections.update_git_connection_async",
            new=unittest.mock.AsyncMock(side_effect=GitConnectionNotFoundError(connection_id)),
        ):
            response = await async_client.put(
                f"/api/rest/git-connections/{connection_id}/",
                json={"host": "github.com", "connection_type": "ssh"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_returns_409_when_renaming_to_existing_host(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        connection_id = uuid.uuid4()
        with unittest.mock.patch(
            "app.api.rest.git_connections.update_git_connection_async",
            new=unittest.mock.AsyncMock(side_effect=GitConnectionAlreadyExistsError("gitlab.com")),
        ):
            response = await async_client.put(
                f"/api/rest/git-connections/{connection_id}/",
                json={"host": "gitlab.com", "connection_type": "ssh"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_409_CONFLICT


class TestDeleteGitConnection:
    async def test_removes_connection(self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
        connection_id = uuid.uuid4()
        with unittest.mock.patch(
            "app.api.rest.git_connections.delete_git_connection_async",
            new=unittest.mock.AsyncMock(),
        ) as mock_delete:
            response = await async_client.delete(f"/api/rest/git-connections/{connection_id}/", headers=auth_headers)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_delete.assert_awaited_once_with(connection_id)

    async def test_returns_404_for_unknown_id(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        connection_id = uuid.uuid4()
        with unittest.mock.patch(
            "app.api.rest.git_connections.delete_git_connection_async",
            new=unittest.mock.AsyncMock(side_effect=GitConnectionNotFoundError(connection_id)),
        ):
            response = await async_client.delete(f"/api/rest/git-connections/{connection_id}/", headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND
