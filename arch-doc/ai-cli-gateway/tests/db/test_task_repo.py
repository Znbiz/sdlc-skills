import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.task_repo import mark_running_tasks_failed, upsert_cli_task
from app.services.task_registry import CliTask, TaskStatus


def _make_cli_task(**kwargs) -> CliTask:
    defaults = dict(
        task_id=str(uuid.uuid4()),
        engine_name="claude",
        prompt_text="test prompt",
        workspace_dir="/workspace",
    )
    defaults.update(kwargs)
    return CliTask(**defaults)


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


async def test_upsert_creates_new_record(mock_session):
    cli_task = _make_cli_task()
    await upsert_cli_task(mock_session, cli_task)
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()


async def test_upsert_updates_existing_record(mock_session):
    from app.db.models import CliTaskModel

    existing = CliTaskModel(
        task_id=uuid.uuid4(),
        engine_name="claude",
        task_status="pending",
        prompt_text="p",
        workspace_dir="/w",
    )
    mock_session.get = AsyncMock(return_value=existing)
    cli_task = _make_cli_task(
        task_id=str(existing.task_id),
        task_status=TaskStatus.SUCCESS,
        task_result="done",
    )
    await upsert_cli_task(mock_session, cli_task)

    assert existing.task_status == "success"
    assert existing.task_result == "done"
    mock_session.commit.assert_called_once()


async def test_upsert_includes_stdout(mock_session):
    cli_task = _make_cli_task()
    cli_task.stdout_lines = ["line1", "line2"]
    await upsert_cli_task(mock_session, cli_task)
    added = mock_session.add.call_args[0][0]
    assert added.stdout_output == "line1\nline2"


async def test_upsert_empty_stdout_is_none(mock_session):
    cli_task = _make_cli_task()
    cli_task.stdout_lines = []
    await upsert_cli_task(mock_session, cli_task)
    added = mock_session.add.call_args[0][0]
    assert added.stdout_output is None


async def test_mark_running_tasks_failed(mock_session):
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [("id1",), ("id2",)]
    mock_session.execute = AsyncMock(return_value=mock_result)

    count = await mark_running_tasks_failed(mock_session)
    assert count == 2
    mock_session.commit.assert_called_once()
