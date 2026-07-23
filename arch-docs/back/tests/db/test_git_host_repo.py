import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.git_host_repo import (
    create_git_host,
    delete_git_host,
    get_git_host_by_host,
    get_git_host_by_id,
    list_git_hosts,
    update_git_host,
)
from app.db.models import GitHostConnectionModel


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    return session


async def test_list_git_hosts_returns_rows(mock_session):
    rows = [GitHostConnectionModel(host="github.com", connection_type="token")]
    execute_result = MagicMock()
    execute_result.scalars.return_value = rows
    mock_session.execute.return_value = execute_result

    result = await list_git_hosts(mock_session)

    assert result == rows


async def test_get_git_host_by_id_delegates_to_session_get(mock_session):
    connection_id = uuid.uuid4()
    row = GitHostConnectionModel(connection_id=connection_id, host="github.com", connection_type="ssh")
    mock_session.get.return_value = row

    result = await get_git_host_by_id(mock_session, connection_id)

    mock_session.get.assert_awaited_once_with(GitHostConnectionModel, connection_id)
    assert result is row


async def test_get_git_host_by_host_returns_matching_row(mock_session):
    row = GitHostConnectionModel(host="github.com", connection_type="token")
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = row
    mock_session.execute.return_value = execute_result

    result = await get_git_host_by_host(mock_session, "github.com")

    assert result is row


async def test_create_git_host_adds_new_row(mock_session):
    result = await create_git_host(mock_session, host="github.com", connection_type="token")

    mock_session.add.assert_called_once()
    mock_session.commit.assert_awaited_once()
    assert result.host == "github.com"
    assert result.connection_type == "token"


async def test_update_git_host_updates_existing_row(mock_session):
    connection_id = uuid.uuid4()
    existing = GitHostConnectionModel(connection_id=connection_id, host="github.com", connection_type="token")
    mock_session.get.return_value = existing

    result = await update_git_host(mock_session, connection_id=connection_id, host="gitlab.com", connection_type="ssh")

    mock_session.commit.assert_awaited_once()
    assert result is existing
    assert result.host == "gitlab.com"
    assert result.connection_type == "ssh"


async def test_update_git_host_returns_none_when_missing(mock_session):
    mock_session.get.return_value = None

    result = await update_git_host(mock_session, connection_id=uuid.uuid4(), host="gitlab.com", connection_type="ssh")

    assert result is None
    mock_session.commit.assert_not_awaited()


async def test_delete_git_host_returns_deleted_row(mock_session):
    connection_id = uuid.uuid4()
    existing = GitHostConnectionModel(connection_id=connection_id, host="github.com", connection_type="token")
    mock_session.get.return_value = existing

    result = await delete_git_host(mock_session, connection_id)

    assert result is existing
    mock_session.delete.assert_awaited_once_with(existing)
    mock_session.commit.assert_awaited_once()


async def test_delete_git_host_returns_none_when_missing(mock_session):
    mock_session.get.return_value = None

    result = await delete_git_host(mock_session, uuid.uuid4())

    assert result is None
    mock_session.commit.assert_not_awaited()
