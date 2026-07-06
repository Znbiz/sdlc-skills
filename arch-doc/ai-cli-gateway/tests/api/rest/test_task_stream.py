import asyncio
import json
import unittest.mock
import uuid

import httpx
import pytest
from fastapi import status

from app.services.agent_pool import init_agent_pool
from app.services.task_registry import CliTask, TaskStatus, get_registry, reset_registry


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


def _parse_sse(raw: str) -> list[dict]:
    return [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_registry()
    init_agent_pool(pool_size=2)
    yield
    reset_registry()


class TestStreamTask:
    async def test_returns_404_for_unknown_task(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        fake_id = str(uuid.uuid4())
        response = await async_client.get(f"/api/rest/tasks/{fake_id}/stream/", headers=auth_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_requires_auth(self, async_client: httpx.AsyncClient) -> None:
        cli_task = CliTask(
            task_id=str(uuid.uuid4()),
            engine_name="claude",
            prompt_text="test",
            workspace_dir="/workspace",
            task_status=TaskStatus.SUCCESS,
        )
        get_registry()[cli_task.task_id] = cli_task
        response = await async_client.get(f"/api/rest/tasks/{cli_task.task_id}/stream/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_streams_completed_task_stdout(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        cli_task = CliTask(
            task_id=str(uuid.uuid4()),
            engine_name="claude",
            prompt_text="test",
            workspace_dir="/workspace",
            task_status=TaskStatus.SUCCESS,
        )
        cli_task.stdout_lines.extend(["line1", "line2"])
        get_registry()[cli_task.task_id] = cli_task

        response = await async_client.get(
            f"/api/rest/tasks/{cli_task.task_id}/stream/",
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert "text/event-stream" in response.headers["content-type"]

        events = _parse_sse(response.text)
        output_events = [e for e in events if e["event_type"] == "output"]
        assert len(output_events) == 2
        assert output_events[0]["event_data"] == "line1"
        assert output_events[0]["stream_source"] == "stdout"
        assert output_events[1]["event_data"] == "line2"

    async def test_streams_completed_task_stderr(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        cli_task = CliTask(
            task_id=str(uuid.uuid4()),
            engine_name="codex",
            prompt_text="test",
            workspace_dir="/workspace",
            task_status=TaskStatus.SUCCESS,
        )
        cli_task.stderr_lines.extend(["step1", "step2"])
        get_registry()[cli_task.task_id] = cli_task

        response = await async_client.get(
            f"/api/rest/tasks/{cli_task.task_id}/stream/",
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        progress_events = [e for e in events if e["event_type"] == "progress"]
        assert len(progress_events) == 2
        assert progress_events[0]["stream_source"] == "stderr"

    async def test_streams_done_event_at_end(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        cli_task = CliTask(
            task_id=str(uuid.uuid4()),
            engine_name="claude",
            prompt_text="test",
            workspace_dir="/workspace",
            task_status=TaskStatus.SUCCESS,
        )
        get_registry()[cli_task.task_id] = cli_task

        response = await async_client.get(
            f"/api/rest/tasks/{cli_task.task_id}/stream/",
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        assert events[-1]["event_type"] == "done"
        assert events[-1]["task_id"] == cli_task.task_id

    async def test_streams_failed_task(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        cli_task = CliTask(
            task_id=str(uuid.uuid4()),
            engine_name="claude",
            prompt_text="test",
            workspace_dir="/workspace",
            task_status=TaskStatus.FAILED,
        )
        cli_task.stdout_lines.append("partial output")
        get_registry()[cli_task.task_id] = cli_task

        response = await async_client.get(
            f"/api/rest/tasks/{cli_task.task_id}/stream/",
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        assert any(e["event_type"] == "output" for e in events)
        assert events[-1]["event_type"] == "done"

    async def test_streams_running_task_via_execute(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        mock_proc = _make_mock_process(returncode=0, stdout=b"hello world", stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            execute_response = await async_client.post(
                "/api/rpc/execute/",
                json={"engine": "claude", "prompt": "say hello"},
                headers=auth_headers,
            )

        assert execute_response.status_code == status.HTTP_202_ACCEPTED
        task_id = execute_response.json()["task_id"]

        await asyncio.sleep(0.2)

        stream_response = await async_client.get(
            f"/api/rest/tasks/{task_id}/stream/",
            headers=auth_headers,
        )

        assert stream_response.status_code == status.HTTP_200_OK
        events = _parse_sse(stream_response.text)
        assert any(e["event_type"] == "done" for e in events)
