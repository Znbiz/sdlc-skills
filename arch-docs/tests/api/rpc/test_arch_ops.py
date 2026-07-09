import asyncio
import unittest.mock

import httpx
from fastapi import status

from app.services.task_registry import TaskStatus, get_registry


def _make_stream_reader(data: bytes) -> unittest.mock.MagicMock:
    lines = [*data.splitlines(keepends=True), b""]
    state = {"idx": 0}

    async def readline() -> bytes:
        idx = state["idx"]
        state["idx"] += 1
        return lines[idx] if idx < len(lines) else b""

    mock_reader = unittest.mock.MagicMock()
    mock_reader.readline = readline
    return mock_reader


def _make_mock_process(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> unittest.mock.MagicMock:
    mock_proc = unittest.mock.MagicMock()
    mock_proc.returncode = returncode
    mock_proc.stdout = _make_stream_reader(stdout)
    mock_proc.stderr = _make_stream_reader(stderr)
    mock_proc.terminate = unittest.mock.MagicMock()
    mock_proc.kill = unittest.mock.MagicMock()
    mock_proc.wait = unittest.mock.AsyncMock(return_value=returncode)
    return mock_proc


class TestUpdateArch:
    async def test_no_auth_returns_401(self, async_client: httpx.AsyncClient) -> None:
        # Arrange / Act
        response = await async_client.post(
            "/api/rpc/update-arch/",
            json={"repo_path": "/workspace/my-service"},
        )
        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_returns_202_with_pending_status(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Arrange
        mock_proc = _make_mock_process(returncode=0, stdout=b"docs updated", stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            # Act
            response = await async_client.post(
                "/api/rpc/update-arch/",
                json={"repo_path": "/workspace/my-service"},
                headers=auth_headers,
            )

        # Assert
        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert data["task_status"] == TaskStatus.PENDING
        assert "task_id" in data
        assert "created_at" in data

    async def test_task_added_to_registry_with_update_prompt(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Arrange
        mock_proc = _make_mock_process(returncode=0, stdout=b"ok", stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            # Act
            response = await async_client.post(
                "/api/rpc/update-arch/",
                json={"repo_path": "/workspace/svc"},
                headers=auth_headers,
            )

        # Assert
        task_id = response.json()["task_id"]
        registry = get_registry()
        assert task_id in registry
        cli_task = registry[task_id]
        assert cli_task.engine_name == "claude"
        assert "/update-repo-arch-skill" in cli_task.prompt_text

    async def test_with_diff_context_appends_to_prompt(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Arrange
        mock_proc = _make_mock_process(returncode=0, stdout=b"ok", stderr=b"")
        diff_text = "diff --git a/service.py b/service.py\n+++ new code"

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            # Act
            response = await async_client.post(
                "/api/rpc/update-arch/",
                json={"repo_path": "/workspace/svc", "diff_context": diff_text},
                headers=auth_headers,
            )

        # Assert
        task_id = response.json()["task_id"]
        registry = get_registry()
        cli_task = registry[task_id]
        assert diff_text in cli_task.prompt_text
        assert "/update-repo-arch-skill" in cli_task.prompt_text

    async def test_without_diff_context_uses_base_prompt(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Arrange
        mock_proc = _make_mock_process(returncode=0, stdout=b"ok", stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            # Act
            response = await async_client.post(
                "/api/rpc/update-arch/",
                json={"repo_path": "/workspace/svc"},
                headers=auth_headers,
            )

        # Assert
        task_id = response.json()["task_id"]
        registry = get_registry()
        cli_task = registry[task_id]
        assert cli_task.prompt_text == "/update-repo-arch-skill"

    async def test_invalid_engine_name_returns_422(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Arrange / Act
        response = await async_client.post(
            "/api/rpc/update-arch/",
            json={"repo_path": "/workspace/svc", "engine_name": "gpt4"},
            headers=auth_headers,
        )
        # Assert
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_codex_engine_accepted(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Arrange
        mock_proc = _make_mock_process(returncode=0, stdout=b"ok", stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            # Act
            response = await async_client.post(
                "/api/rpc/update-arch/",
                json={"repo_path": "/workspace/svc", "engine_name": "codex"},
                headers=auth_headers,
            )

        # Assert
        assert response.status_code == status.HTTP_202_ACCEPTED
        task_id = response.json()["task_id"]
        assert get_registry()[task_id].engine_name == "codex"

    async def test_background_task_completes_success(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Arrange
        mock_proc = _make_mock_process(returncode=0, stdout=b"docs updated successfully", stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await async_client.post(
                "/api/rpc/update-arch/",
                json={"repo_path": "/workspace/svc"},
                headers=auth_headers,
            )

        task_id = response.json()["task_id"]
        # Act — give event loop time to finish background task
        for _ in range(10):
            await asyncio.sleep(0)

        # Assert
        registry = get_registry()
        assert registry[task_id].task_status == TaskStatus.SUCCESS
        assert registry[task_id].task_result == "docs updated successfully"


class TestQueryArch:
    async def test_no_auth_returns_401(self, async_client: httpx.AsyncClient) -> None:
        # Arrange / Act
        response = await async_client.post(
            "/api/rpc/query-arch/",
            json={"question": "What is the DB schema?", "repo_path": "/workspace/svc"},
        )
        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_returns_202_with_pending_status(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Arrange
        mock_proc = _make_mock_process(returncode=0, stdout=b"PostgreSQL with asyncpg", stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            # Act
            response = await async_client.post(
                "/api/rpc/query-arch/",
                json={"question": "What DB is used?", "repo_path": "/workspace/svc"},
                headers=auth_headers,
            )

        # Assert
        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert data["task_status"] == TaskStatus.PENDING
        assert "task_id" in data
        assert "created_at" in data

    async def test_task_added_to_registry_with_query_prompt(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Arrange
        mock_proc = _make_mock_process(returncode=0, stdout=b"answer", stderr=b"")
        question = "What is the tech stack?"

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            # Act
            response = await async_client.post(
                "/api/rpc/query-arch/",
                json={"question": question, "repo_path": "/workspace/svc"},
                headers=auth_headers,
            )

        # Assert
        task_id = response.json()["task_id"]
        registry = get_registry()
        assert task_id in registry
        cli_task = registry[task_id]
        assert question in cli_task.prompt_text
        assert "arch-doc/" in cli_task.prompt_text

    async def test_invalid_engine_name_returns_422(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Arrange / Act
        response = await async_client.post(
            "/api/rpc/query-arch/",
            json={"question": "test?", "repo_path": "/workspace/svc", "engine_name": "openai"},
            headers=auth_headers,
        )
        # Assert
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_codex_engine_accepted(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Arrange
        mock_proc = _make_mock_process(returncode=0, stdout=b"answer", stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            # Act
            response = await async_client.post(
                "/api/rpc/query-arch/",
                json={"question": "Why?", "repo_path": "/workspace/svc", "engine_name": "codex"},
                headers=auth_headers,
            )

        # Assert
        assert response.status_code == status.HTTP_202_ACCEPTED
        task_id = response.json()["task_id"]
        assert get_registry()[task_id].engine_name == "codex"

    async def test_background_task_completes_success(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Arrange
        mock_proc = _make_mock_process(returncode=0, stdout=b"FastAPI + PostgreSQL", stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await async_client.post(
                "/api/rpc/query-arch/",
                json={"question": "What is the stack?", "repo_path": "/workspace/svc"},
                headers=auth_headers,
            )

        task_id = response.json()["task_id"]
        # Act — yield to event loop
        for _ in range(10):
            await asyncio.sleep(0)

        # Assert
        registry = get_registry()
        assert registry[task_id].task_status == TaskStatus.SUCCESS
        assert registry[task_id].task_result == "FastAPI + PostgreSQL"
