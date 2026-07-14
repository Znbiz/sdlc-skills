import unittest.mock

import httpx
from fastapi import status

from app.services.git_credentials import GitAccessStatus


class TestSetGitCredentials:
    async def test_stores_token_and_returns_configured_hosts(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        with (
            unittest.mock.patch("app.api.rpc.git_credentials.set_git_token", new=unittest.mock.AsyncMock()) as mock_set,
            unittest.mock.patch(
                "app.api.rpc.git_credentials.list_configured_hosts",
                new=unittest.mock.AsyncMock(return_value=["github.com"]),
            ),
        ):
            response = await async_client.post(
                "/api/rpc/git-credentials/set/",
                json={"host": "github.com", "token": "ghp_abc123"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json() == {"configured_hosts": ["github.com"]}
        mock_set.assert_awaited_once_with(host="github.com", token="ghp_abc123", username=None)

    async def test_rejects_host_with_scheme(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        response = await async_client.post(
            "/api/rpc/git-credentials/set/",
            json={"host": "https://github.com", "token": "ghp_abc123"},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_rejects_empty_token(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        response = await async_client.post(
            "/api/rpc/git-credentials/set/",
            json={"host": "github.com", "token": "  "},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_requires_auth(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.post(
            "/api/rpc/git-credentials/set/",
            json={"host": "github.com", "token": "ghp_abc123"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestCheckGitCredentialsAccess:
    async def test_returns_accessible_result(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        with unittest.mock.patch(
            "app.api.rpc.git_credentials.check_git_access",
            new=unittest.mock.AsyncMock(
                return_value={"accessible": True, "access_status": GitAccessStatus.OK, "message": "ok"}
            ),
        ):
            response = await async_client.post(
                "/api/rpc/git-credentials/check-access/",
                json={"repository_url": "https://github.com/org/repo.git"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["accessible"] is True
        assert data["access_status"] == "ok"

    async def test_returns_inaccessible_result(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        with unittest.mock.patch(
            "app.api.rpc.git_credentials.check_git_access",
            new=unittest.mock.AsyncMock(
                return_value={
                    "accessible": False,
                    "access_status": GitAccessStatus.AUTH_FAILED,
                    "message": "Authentication failed",
                }
            ),
        ):
            response = await async_client.post(
                "/api/rpc/git-credentials/check-access/",
                json={"repository_url": "https://github.com/org/private.git"},
                headers=auth_headers,
            )

        data = response.json()
        assert data["accessible"] is False
        assert data["access_status"] == "auth_failed"

    async def test_rejects_empty_repository_url(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        response = await async_client.post(
            "/api/rpc/git-credentials/check-access/",
            json={"repository_url": "  "},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_requires_auth(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.post(
            "/api/rpc/git-credentials/check-access/",
            json={"repository_url": "https://github.com/org/repo.git"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
