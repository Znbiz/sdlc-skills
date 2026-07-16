import unittest.mock

import httpx
from fastapi import status


class TestGetGitCredentialsStatus:
    async def test_returns_configured_true_with_hosts(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with unittest.mock.patch(
            "app.api.rest.git_credentials.list_configured_hosts",
            new=unittest.mock.AsyncMock(return_value=["github.com"]),
        ):
            response = await async_client.get("/api/rest/git-credentials/", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"configured": True, "configured_hosts": ["github.com"]}

    async def test_returns_configured_false_when_empty(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with unittest.mock.patch(
            "app.api.rest.git_credentials.list_configured_hosts",
            new=unittest.mock.AsyncMock(return_value=[]),
        ):
            response = await async_client.get("/api/rest/git-credentials/", headers=auth_headers)

        assert response.json() == {"configured": False, "configured_hosts": []}

    async def test_requires_auth(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.get("/api/rest/git-credentials/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestPutPersonalAccessToken:
    async def test_stores_token_and_returns_masked_status(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with (
            unittest.mock.patch(
                "app.api.rest.git_credentials.set_git_token", new=unittest.mock.AsyncMock()
            ) as mock_set,
            unittest.mock.patch(
                "app.api.rest.git_credentials.list_configured_hosts",
                new=unittest.mock.AsyncMock(return_value=["github.com"]),
            ),
        ):
            response = await async_client.put(
                "/api/rest/git-credentials/personal-access-token/",
                json={"host": "github.com", "token": "ghp_abc123"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"configured": True, "configured_hosts": ["github.com"]}
        mock_set.assert_awaited_once_with(host="github.com", token="ghp_abc123", username=None)

    async def test_rejects_empty_token(self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
        response = await async_client.put(
            "/api/rest/git-credentials/personal-access-token/",
            json={"host": "github.com", "token": "   "},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_never_echoes_token_back(self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
        with (
            unittest.mock.patch("app.api.rest.git_credentials.set_git_token", new=unittest.mock.AsyncMock()),
            unittest.mock.patch(
                "app.api.rest.git_credentials.list_configured_hosts",
                new=unittest.mock.AsyncMock(return_value=["github.com"]),
            ),
        ):
            response = await async_client.put(
                "/api/rest/git-credentials/personal-access-token/",
                json={"host": "github.com", "token": "super-secret-token"},
                headers=auth_headers,
            )

        assert "super-secret-token" not in response.text


class TestDeletePersonalAccessToken:
    async def test_removes_token_for_host(self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
        with (
            unittest.mock.patch(
                "app.api.rest.git_credentials.delete_git_token", new=unittest.mock.AsyncMock(return_value=True)
            ) as mock_delete,
            unittest.mock.patch(
                "app.api.rest.git_credentials.list_configured_hosts", new=unittest.mock.AsyncMock(return_value=[])
            ),
        ):
            response = await async_client.request(
                "DELETE",
                "/api/rest/git-credentials/personal-access-token/",
                params={"host": "github.com"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"configured": False, "configured_hosts": []}
        mock_delete.assert_awaited_once_with("github.com")


class TestCheckGitCredentialsAccess:
    async def test_returns_access_result_with_reason_code(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with unittest.mock.patch(
            "app.api.rest.git_credentials.check_git_access",
            new=unittest.mock.AsyncMock(
                return_value={
                    "accessible": False,
                    "access_status": "auth_failed",
                    "reason_code": "git_pat_missing",
                    "message": "No Git personal access token is configured",
                }
            ),
        ):
            response = await async_client.post(
                "/api/rest/git-credentials/check-access/",
                json={"repository_url": "https://github.com/org/repo.git"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["accessible"] is False
        assert body["reason_code"] == "git_pat_missing"

    async def test_rejects_empty_repository_url(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await async_client.post(
            "/api/rest/git-credentials/check-access/",
            json={"repository_url": "  "},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
