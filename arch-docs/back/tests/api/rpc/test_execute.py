import asyncio
import unittest.mock

import httpx
from fastapi import status

from app.services.task_registry import CliTask, TaskStatus, get_registry


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


_TERMINAL_TASK_STATUSES = frozenset({TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED})


async def _wait_for_task_completion(task_id: str, *, timeout_seconds: float = 2.0) -> CliTask:
    """Poll the registry until the background task reaches a terminal status.

    A fixed number of `asyncio.sleep(0)` yields is a race under any scheduler that
    needs more (or fewer) turns than assumed to run `run_cli_task` to completion.
    """
    registry = get_registry()
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        cli_task = registry[task_id]
        if cli_task.task_status in _TERMINAL_TASK_STATUSES:
            return cli_task
        await asyncio.sleep(0.01)
    return registry[task_id]


class TestExecuteAuth:
    async def test_no_auth_header_returns_401(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.post(
            "/api/rpc/execute/",
            json={"engine": "claude", "prompt": "hello"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_wrong_token_returns_401(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.post(
            "/api/rpc/execute/",
            json={"engine": "claude", "prompt": "hello"},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_malformed_auth_header_returns_401(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.post(
            "/api/rpc/execute/",
            json={"engine": "claude", "prompt": "hello"},
            headers={"Authorization": "test-secret-token"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestExecuteResponse:
    async def test_returns_202_with_pending_status(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Arrange
        mock_proc = _make_mock_process(returncode=0, stdout=b"result", stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            # Act
            response = await async_client.post(
                "/api/rpc/execute/",
                json={"engine": "claude", "prompt": "write hello world"},
                headers=auth_headers,
            )

        # Assert
        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert data["task_status"] == TaskStatus.PENDING
        assert "task_id" in data
        assert "created_at" in data

    async def test_task_added_to_registry(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        mock_proc = _make_mock_process(returncode=0, stdout=b"ok", stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await async_client.post(
                "/api/rpc/execute/",
                json={"engine": "codex", "prompt": "do something"},
                headers=auth_headers,
            )

        task_id = response.json()["task_id"]
        registry = get_registry()
        assert task_id in registry
        assert registry[task_id].engine_name == "codex"

    async def test_invalid_engine_returns_422(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        response = await async_client.post(
            "/api/rpc/execute/",
            json={"engine": "gpt4", "prompt": "hello"},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_background_task_completes_success(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        # `claude --output-format stream-json` emits NDJSON; the answer lives in the `result`
        # field of the `type: result` event (see `_extract_claude_result_text`).
        mock_proc = _make_mock_process(
            returncode=0,
            stdout=b'{"type":"result","result":"generated result"}',
            stderr=b"",
        )

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await async_client.post(
                "/api/rpc/execute/",
                json={"engine": "claude", "prompt": "hello"},
                headers=auth_headers,
            )

        task_id = response.json()["task_id"]
        cli_task = await _wait_for_task_completion(task_id)

        assert cli_task.task_status == TaskStatus.SUCCESS
        assert cli_task.task_result == "generated result"

    async def test_background_task_fails_on_nonzero_exit(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        mock_proc = _make_mock_process(returncode=1, stdout=b"", stderr=b"command failed")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await async_client.post(
                "/api/rpc/execute/",
                json={"engine": "claude", "prompt": "failing"},
                headers=auth_headers,
            )

        task_id = response.json()["task_id"]
        cli_task = await _wait_for_task_completion(task_id)

        assert cli_task.task_status == TaskStatus.FAILED
        assert cli_task.task_error == "command failed"

    async def test_background_task_detects_auth_error(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        mock_proc = _make_mock_process(
            returncode=1,
            stdout=b"",
            stderr=b"not logged in, please run claude auth login",
        )

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await async_client.post(
                "/api/rpc/execute/",
                json={"engine": "claude", "prompt": "hello"},
                headers=auth_headers,
            )

        task_id = response.json()["task_id"]
        cli_task = await _wait_for_task_completion(task_id)

        assert cli_task.task_status == TaskStatus.FAILED
        assert "auth_expired" in cli_task.task_error


class TestHealth:
    async def test_health_no_auth_required(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.get("/health")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["service_status"] == "ok"
        assert data["version"] == "1.0.0"
