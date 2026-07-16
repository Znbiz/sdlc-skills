import unittest.mock

import httpx
from fastapi import status


class TestGetGitSshPublicKey:
    async def test_returns_public_key(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        with unittest.mock.patch(
            "app.api.rest.git_ssh.get_public_key",
            new=unittest.mock.AsyncMock(return_value="ssh-ed25519 AAAA... arch-docs-service"),
        ):
            response = await async_client.get("/api/rest/git-ssh/public-key/", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"public_key": "ssh-ed25519 AAAA... arch-docs-service"}

    async def test_requires_auth(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.get("/api/rest/git-ssh/public-key/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
