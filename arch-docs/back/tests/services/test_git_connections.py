import uuid

import pytest

from app.services.git_connections import (
    GitConnectionAlreadyExistsError,
    GitConnectionNotFoundError,
    GitConnectionValidationError,
    create_git_connection_async,
    delete_git_connection_async,
    get_git_connection_async,
    list_git_connections_async,
    update_git_connection_async,
)


@pytest.fixture(autouse=True)
def isolated_git_credentials_store(tmp_path, monkeypatch):
    store_dir = tmp_path / "git-credentials-store"
    monkeypatch.setattr("app.services.git_credentials._CREDENTIALS_DIR", store_dir)
    monkeypatch.setattr("app.services.git_credentials._CREDENTIALS_FILE", store_dir / "credentials")
    monkeypatch.setattr("app.services.git_credentials._GIT_CONFIG_GLOBAL_PATH", store_dir / "gitconfig")
    monkeypatch.delenv("GIT_CONFIG_GLOBAL", raising=False)
    return store_dir


class TestListGitConnections:
    async def test_returns_empty_list_when_none_configured(self):
        assert await list_git_connections_async() == []

    async def test_returns_all_configured_connections(self):
        await create_git_connection_async(host="github.com", connection_type="token", token="ghp_abc")
        await create_git_connection_async(host="example.org", connection_type="ssh")

        connections = await list_git_connections_async()

        assert sorted((c.host, c.connection_type) for c in connections) == [
            ("example.org", "ssh"),
            ("github.com", "token"),
        ]


class TestCreateGitConnection:
    async def test_creates_token_connection_and_stores_secret(self):
        summary = await create_git_connection_async(
            host="github.com", connection_type="token", token="ghp_abc", username="custom"
        )

        assert summary.host == "github.com"
        assert summary.connection_type == "token"
        detail = await get_git_connection_async(summary.connection_id)
        assert detail.token == "ghp_abc"  # noqa: S105
        assert detail.username == "custom"

    async def test_creates_ssh_connection_without_secret(self):
        summary = await create_git_connection_async(host="example.org", connection_type="ssh")

        assert summary.connection_type == "ssh"
        detail = await get_git_connection_async(summary.connection_id)
        assert detail.token is None
        assert detail.username is None

    async def test_rejects_empty_token_for_token_type(self):
        with pytest.raises(GitConnectionValidationError):
            await create_git_connection_async(host="github.com", connection_type="token", token="   ")

    async def test_rejects_unknown_connection_type(self):
        with pytest.raises(GitConnectionValidationError):
            await create_git_connection_async(host="github.com", connection_type="carrier-pigeon")

    async def test_rejects_duplicate_host(self):
        await create_git_connection_async(host="github.com", connection_type="ssh")

        with pytest.raises(GitConnectionAlreadyExistsError):
            await create_git_connection_async(host="github.com", connection_type="token", token="ghp_abc")


class TestUpdateGitConnection:
    async def test_switches_token_to_ssh_and_drops_stored_secret(self):
        summary = await create_git_connection_async(host="github.com", connection_type="token", token="ghp_abc")

        updated = await update_git_connection_async(
            connection_id=summary.connection_id, host="github.com", connection_type="ssh"
        )

        assert updated.connection_type == "ssh"
        detail = await get_git_connection_async(summary.connection_id)
        assert detail.token is None

    async def test_switches_ssh_to_token_and_stores_new_secret(self):
        summary = await create_git_connection_async(host="github.com", connection_type="ssh")

        await update_git_connection_async(
            connection_id=summary.connection_id, host="github.com", connection_type="token", token="ghp_new"
        )

        detail = await get_git_connection_async(summary.connection_id)
        assert detail.connection_type == "token"
        assert detail.token == "ghp_new"  # noqa: S105

    async def test_renames_host_and_moves_stored_secret(self):
        summary = await create_git_connection_async(host="github.com", connection_type="token", token="ghp_abc")

        updated = await update_git_connection_async(
            connection_id=summary.connection_id, host="gitlab.com", connection_type="token", token="ghp_abc"
        )

        assert updated.host == "gitlab.com"
        detail = await get_git_connection_async(summary.connection_id)
        assert detail.host == "gitlab.com"
        assert detail.token == "ghp_abc"  # noqa: S105

    async def test_raises_not_found_for_missing_connection(self):
        with pytest.raises(GitConnectionNotFoundError):
            await update_git_connection_async(connection_id=uuid.uuid4(), host="github.com", connection_type="ssh")

    async def test_raises_conflict_when_renaming_to_existing_host(self):
        await create_git_connection_async(host="github.com", connection_type="ssh")
        other = await create_git_connection_async(host="gitlab.com", connection_type="ssh")

        with pytest.raises(GitConnectionAlreadyExistsError):
            await update_git_connection_async(
                connection_id=other.connection_id, host="github.com", connection_type="ssh"
            )

    async def test_rejects_empty_token_for_token_type(self):
        summary = await create_git_connection_async(host="github.com", connection_type="ssh")

        with pytest.raises(GitConnectionValidationError):
            await update_git_connection_async(
                connection_id=summary.connection_id, host="github.com", connection_type="token", token="   "
            )


class TestGetGitConnection:
    async def test_raises_not_found_for_missing_connection(self):
        with pytest.raises(GitConnectionNotFoundError):
            await get_git_connection_async(uuid.uuid4())


class TestDeleteGitConnection:
    async def test_removes_connection_and_stored_secret(self):
        summary = await create_git_connection_async(host="github.com", connection_type="token", token="ghp_abc")

        await delete_git_connection_async(summary.connection_id)

        assert await list_git_connections_async() == []
        with pytest.raises(GitConnectionNotFoundError):
            await get_git_connection_async(summary.connection_id)

    async def test_raises_not_found_for_missing_connection(self):
        with pytest.raises(GitConnectionNotFoundError):
            await delete_git_connection_async(uuid.uuid4())
