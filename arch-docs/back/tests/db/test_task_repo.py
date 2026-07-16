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
    cli_task = _make_cli_task(
        workflow_id="wf-1",
        step_id="define_scope",
        repository_name="repo-a",
        domain_id="billing",
        expected_schema_name="init_arch_v1",
    )
    cli_task.stdout_lines = ["line1", "line2"]
    cli_task.stderr_lines = ["warn1"]
    cli_task.exit_code = 7
    await upsert_cli_task(mock_session, cli_task)
    added = mock_session.add.call_args[0][0]
    assert added.stdout_output == "line1\nline2"
    assert added.stderr_output == "warn1"
    assert added.exit_code == 7
    assert added.workflow_id == "wf-1"
    assert added.step_id == "define_scope"
    assert added.repository_name == "repo-a"
    assert added.domain_id == "billing"
    assert added.expected_schema_name == "init_arch_v1"


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


async def test_upsert_masks_and_truncates_persisted_audit_payloads(mock_session, monkeypatch):
    from app.settings import GatewaySettings

    monkeypatch.setattr(
        "app.db.task_repo.get_gateway_settings",
        lambda: GatewaySettings(
            auth_secret="secret",
            audit={
                "max_prompt_chars": 40,
                "max_output_chars": 40,
                "max_error_chars": 32,
            },
        ),
    )
    cli_task = _make_cli_task(
        prompt_text="prefix AUTH_TOKEN=abcdef1234567890 suffix trailing words",
        task_result="Authorization: Bearer secret-token suffix trailing words",
        task_error="DB_PASSWORD=supersecret suffix trailing words",
    )
    cli_task.stdout_lines = ["Authorization: Bearer secret-token suffix trailing words"]
    cli_task.stderr_lines = ["prefix API_KEY=abcdef1234567890 suffix"]

    await upsert_cli_task(mock_session, cli_task)

    added = mock_session.add.call_args[0][0]
    assert "[REDACTED]" in added.prompt_text
    assert added.prompt_text.endswith("...[truncated]")
    assert "[REDACTED]" in added.task_result
    assert added.task_result.endswith("...[truncated]")
    assert "[REDACTED]" in added.task_error
    assert added.task_error.endswith("...[truncated]")
    assert "[REDACTED]" in added.stdout_output
    assert added.stdout_output.endswith("...[truncated]")
    assert "[REDACTED]" in added.stderr_output
