import unittest.mock
import uuid

from app.main import lifespan
from app.services.agent_pool import get_agent_pool
from app.services.task_registry import CliTask, TaskStatus, get_registry


async def test_lifespan_startup_initializes_pool() -> None:
    app_stub = object()

    async with lifespan(app_stub):
        pool = get_agent_pool()
        assert pool is not None


async def test_lifespan_shutdown_cancels_running_tasks() -> None:
    app_stub = object()
    registry = get_registry()

    running_task = CliTask(
        task_id=str(uuid.uuid4()),
        engine_name="claude",
        prompt_text="hello",
        workspace_dir="/workspace",
        task_status=TaskStatus.RUNNING,
    )
    mock_proc = unittest.mock.AsyncMock()
    mock_proc.returncode = None
    mock_proc.terminate = unittest.mock.MagicMock()
    mock_proc.wait = unittest.mock.AsyncMock()
    running_task.subprocess_handle = mock_proc
    registry[running_task.task_id] = running_task

    async with lifespan(app_stub):
        pass  # shutdown triggered when context exits

    assert running_task.task_status == TaskStatus.CANCELLED


async def test_lifespan_shutdown_no_running_tasks() -> None:
    app_stub = object()

    async with lifespan(app_stub):
        pass
