import unittest.mock

import httpx
from fastapi import status


class TestGetDocsTree:
    async def test_returns_tree_for_response(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with (
            unittest.mock.patch(
                "app.api.rest.docs.get_response_arch_repo_dir_async",
                new=unittest.mock.AsyncMock(return_value="/workspace/arch"),
            ),
            unittest.mock.patch(
                "app.api.rest.docs.build_docs_tree",
                return_value={
                    "path": "",
                    "name": "",
                    "node_type": "directory",
                    "children": [],
                    "size": 0,
                    "modified_at": "2026-07-14T00:00:00+00:00",
                    "media_kind": None,
                },
            ),
        ):
            response = await async_client.get("/api/rest/responses/wf-1/docs/tree/", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["node_type"] == "directory"

    async def test_returns_404_when_response_missing(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        from app.services.init_arch_workflow import WorkflowNotFoundError

        with unittest.mock.patch(
            "app.api.rest.docs.get_response_arch_repo_dir_async",
            new=unittest.mock.AsyncMock(side_effect=WorkflowNotFoundError("missing")),
        ):
            response = await async_client.get("/api/rest/responses/missing/docs/tree/", headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_returns_404_when_arch_repo_not_available(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        from app.services.init_arch_workflow import ArchRepoNotAvailableError

        with unittest.mock.patch(
            "app.api.rest.docs.get_response_arch_repo_dir_async",
            new=unittest.mock.AsyncMock(side_effect=ArchRepoNotAvailableError("no arch repo")),
        ):
            response = await async_client.get("/api/rest/responses/wf-1/docs/tree/", headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"]["reason_code"] == "arch_repo_missing_for_response"


class TestGetDocsFile:
    async def test_returns_file_content(self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
        with (
            unittest.mock.patch(
                "app.api.rest.docs.get_response_arch_repo_dir_async",
                new=unittest.mock.AsyncMock(return_value="/workspace/arch"),
            ),
            unittest.mock.patch(
                "app.api.rest.docs.read_docs_file",
                return_value={
                    "path": "README.md",
                    "name": "README.md",
                    "media_kind": "markdown",
                    "content": "# Title\n",
                    "encoding": "utf-8",
                    "size": 8,
                    "modified_at": "2026-07-14T00:00:00+00:00",
                },
            ),
        ):
            response = await async_client.get(
                "/api/rest/responses/wf-1/docs/file/",
                params={"path": "README.md"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["content"] == "# Title\n"

    async def test_returns_403_for_path_traversal(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        from app.services.docs_browser import DocsPathForbiddenError

        with (
            unittest.mock.patch(
                "app.api.rest.docs.get_response_arch_repo_dir_async",
                new=unittest.mock.AsyncMock(return_value="/workspace/arch"),
            ),
            unittest.mock.patch("app.api.rest.docs.read_docs_file", side_effect=DocsPathForbiddenError("escape")),
        ):
            response = await async_client.get(
                "/api/rest/responses/wf-1/docs/file/",
                params={"path": "../outside.md"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"]["reason_code"] == "path_forbidden"

    async def test_returns_404_for_missing_file(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        from app.services.docs_browser import DocsFileNotFoundError

        with (
            unittest.mock.patch(
                "app.api.rest.docs.get_response_arch_repo_dir_async",
                new=unittest.mock.AsyncMock(return_value="/workspace/arch"),
            ),
            unittest.mock.patch("app.api.rest.docs.read_docs_file", side_effect=DocsFileNotFoundError("missing")),
        ):
            response = await async_client.get(
                "/api/rest/responses/wf-1/docs/file/",
                params={"path": "missing.md"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_requires_auth(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.get("/api/rest/responses/wf-1/docs/file/", params={"path": "README.md"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
