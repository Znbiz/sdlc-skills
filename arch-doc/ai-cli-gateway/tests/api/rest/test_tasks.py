import datetime
import unittest.mock
import uuid

import httpx
from fastapi import status

from app.services.task_registry import CliTask, TaskStatus, get_registry


def _make_task(
    task_status: TaskStatus = TaskStatus.PENDING,
    engine_name: str = "claude",
    task_result: str | None = None,
    task_error: str | None = None,
    stdout_lines: list[str] | None = None,
) -> CliTask:
    return CliTask(
        task_id=str(uuid.uuid4()),
        engine_name=engine_name,
        prompt_text="test prompt",
        workspace_dir="/workspace",
        task_status=task_status,
        task_result=task_result,
        task_error=task_error,
        stdout_lines=stdout_lines or [],
    )


def _add_task(cli_task: CliTask) -> CliTask:
    get_registry()[cli_task.task_id] = cli_task
    return cli_task


class TestListTasks:
    async def test_empty_registry_returns_empty_list(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        response = await async_client.get("/api/rest/tasks/", headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    async def test_returns_all_tasks(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        _add_task(_make_task(task_status=TaskStatus.SUCCESS))
        _add_task(_make_task(task_status=TaskStatus.RUNNING))

        response = await async_client.get("/api/rest/tasks/", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 2

    async def test_filters_by_task_status(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        _add_task(_make_task(task_status=TaskStatus.SUCCESS))
        _add_task(_make_task(task_status=TaskStatus.FAILED))
        _add_task(_make_task(task_status=TaskStatus.RUNNING))

        response = await async_client.get("/api/rest/tasks/?task_status=success", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        tasks = response.json()
        assert len(tasks) == 1
        assert tasks[0]["task_status"] == "success"

    async def test_filters_by_engine_name(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        _add_task(_make_task(engine_name="claude"))
        _add_task(_make_task(engine_name="codex"))
        _add_task(_make_task(engine_name="claude"))

        response = await async_client.get("/api/rest/tasks/?engine_name=claude", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        tasks = response.json()
        assert len(tasks) == 2
        assert all(t["engine_name"] == "claude" for t in tasks)

    async def test_respects_limit(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        for _ in range(5):
            _add_task(_make_task())

        response = await async_client.get("/api/rest/tasks/?limit=3", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 3

    async def test_requires_auth(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.get("/api/rest/tasks/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestGetTask:
    async def test_returns_task_by_id(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        cli_task = _add_task(_make_task(task_status=TaskStatus.SUCCESS, task_result="done"))

        response = await async_client.get(f"/api/rest/tasks/{cli_task.task_id}/", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["task_id"] == cli_task.task_id
        assert data["task_status"] == "success"
        assert data["task_result"] == "done"
        assert data["stdout_output"] is None

    async def test_returns_404_for_unknown_task(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        response = await async_client.get(f"/api/rest/tasks/{uuid.uuid4()}/", headers=auth_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_includes_stdout_output_when_requested(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        cli_task = _make_task(task_status=TaskStatus.SUCCESS)
        cli_task.stdout_lines.extend(["line1", "line2"])
        _add_task(cli_task)

        response = await async_client.get(
            f"/api/rest/tasks/{cli_task.task_id}/?include_output=true",
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["stdout_output"] == "line1\nline2"

    async def test_includes_timestamps(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        cli_task = _make_task(task_status=TaskStatus.SUCCESS)
        now = datetime.datetime.now(datetime.timezone.utc)
        cli_task.started_at = now
        cli_task.finished_at = now
        _add_task(cli_task)

        response = await async_client.get(f"/api/rest/tasks/{cli_task.task_id}/", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["started_at"] is not None
        assert data["finished_at"] is not None


class TestCancelTask:
    async def test_cancels_pending_task(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        cli_task = _add_task(_make_task(task_status=TaskStatus.PENDING))

        response = await async_client.delete(f"/api/rest/tasks/{cli_task.task_id}/", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["task_status"] == "cancelled"

    async def test_cancels_running_task_via_sigterm(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        cli_task = _make_task(task_status=TaskStatus.RUNNING)
        mock_proc = unittest.mock.AsyncMock()
        mock_proc.returncode = None
        mock_proc.terminate = unittest.mock.MagicMock()
        mock_proc.wait = unittest.mock.AsyncMock()
        cli_task.subprocess_handle = mock_proc
        _add_task(cli_task)

        response = await async_client.delete(f"/api/rest/tasks/{cli_task.task_id}/", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["task_status"] == "cancelled"
        mock_proc.terminate.assert_called_once()

    async def test_returns_404_for_unknown_task(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        response = await async_client.delete(f"/api/rest/tasks/{uuid.uuid4()}/", headers=auth_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_returns_409_for_finished_task(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        cli_task = _add_task(_make_task(task_status=TaskStatus.SUCCESS))

        response = await async_client.delete(f"/api/rest/tasks/{cli_task.task_id}/", headers=auth_headers)
        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_requires_auth(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.delete(f"/api/rest/tasks/{uuid.uuid4()}/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestSessionIdInResponse:
    async def test_session_id_returned_when_set(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        cli_task = CliTask(
            task_id=str(uuid.uuid4()),
            engine_name="claude",
            prompt_text="hello",
            workspace_dir="/workspace",
            session_id="my-session-42",
        )
        _add_task(cli_task)

        response = await async_client.get(f"/api/rest/tasks/{cli_task.task_id}/", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["session_id"] == "my-session-42"

    async def test_session_id_is_none_when_not_set(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        cli_task = _add_task(_make_task())

        response = await async_client.get(f"/api/rest/tasks/{cli_task.task_id}/", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["session_id"] is None
