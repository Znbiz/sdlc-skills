import unittest.mock

import httpx
from fastapi import status


class TestGetGitCredentialsStatus:
    async def test_returns_configured_hosts(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        with unittest.mock.patch(
            "app.api.rest.git_credentials.list_configured_hosts",
            new=unittest.mock.AsyncMock(return_value=["github.com"]),
        ):
            response = await async_client.get("/api/rest/git-credentials/", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"configured_hosts": ["github.com"]}

    async def test_returns_empty_list_when_nothing_configured(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        with unittest.mock.patch(
            "app.api.rest.git_credentials.list_configured_hosts",
            new=unittest.mock.AsyncMock(return_value=[]),
        ):
            response = await async_client.get("/api/rest/git-credentials/", headers=auth_headers)

        assert response.json() == {"configured_hosts": []}

    async def test_requires_auth(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.get("/api/rest/git-credentials/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
