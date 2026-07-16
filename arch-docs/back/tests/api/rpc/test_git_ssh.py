import unittest.mock

import httpx
from fastapi import status

from app.services.git_ssh import GitAccessStatus


class TestCheckGitSshAccess:
    async def test_returns_accessible_result(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        with unittest.mock.patch(
            "app.api.rpc.git_ssh.check_git_access",
            new=unittest.mock.AsyncMock(
                return_value={"accessible": True, "access_status": GitAccessStatus.OK, "message": "ok"}
            ),
        ):
            response = await async_client.post(
                "/api/rpc/git-ssh/check-access/",
                json={"repository_url": "git@github.com:org/repo.git"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["accessible"] is True
        assert data["access_status"] == "ok"
        assert data["repository_url"] == "git@github.com:org/repo.git"

    async def test_returns_inaccessible_result(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        with unittest.mock.patch(
            "app.api.rpc.git_ssh.check_git_access",
            new=unittest.mock.AsyncMock(
                return_value={
                    "accessible": False,
                    "access_status": GitAccessStatus.AUTH_FAILED,
                    "message": "Permission denied (publickey).",
                }
            ),
        ):
            response = await async_client.post(
                "/api/rpc/git-ssh/check-access/",
                json={"repository_url": "git@github.com:org/private.git"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["accessible"] is False
        assert data["access_status"] == "auth_failed"

    async def test_rejects_empty_repository_url(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        response = await async_client.post(
            "/api/rpc/git-ssh/check-access/",
            json={"repository_url": "  "},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_requires_auth(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.post(
            "/api/rpc/git-ssh/check-access/",
            json={"repository_url": "git@github.com:org/repo.git"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
