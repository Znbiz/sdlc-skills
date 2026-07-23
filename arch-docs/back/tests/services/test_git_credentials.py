import os
import unittest.mock

import pytest

from app.services.git_credentials import (
    delete_git_token,
    ensure_git_credentials_store,
    get_stored_token,
    set_git_token,
)


@pytest.fixture(autouse=True)
def isolated_git_credentials_store(tmp_path, monkeypatch):
    store_dir = tmp_path / "git-credentials-store"
    monkeypatch.setattr("app.services.git_credentials._CREDENTIALS_DIR", store_dir)
    monkeypatch.setattr("app.services.git_credentials._CREDENTIALS_FILE", store_dir / "credentials")
    monkeypatch.setattr("app.services.git_credentials._GIT_CONFIG_GLOBAL_PATH", store_dir / "gitconfig")
    monkeypatch.delenv("GIT_CONFIG_GLOBAL", raising=False)
    return store_dir


class TestEnsureGitCredentialsStore:
    async def test_creates_store_dir_and_credentials_file(self, isolated_git_credentials_store):
        await ensure_git_credentials_store()

        assert isolated_git_credentials_store.exists()
        assert (isolated_git_credentials_store / "credentials").exists()

    async def test_configures_git_config_global_env_var(self, isolated_git_credentials_store):
        await ensure_git_credentials_store()

        assert os.environ["GIT_CONFIG_GLOBAL"] == str(isolated_git_credentials_store / "gitconfig")

    async def test_raises_when_git_config_fails(self):
        mock_proc = unittest.mock.AsyncMock()
        mock_proc.communicate = unittest.mock.AsyncMock(return_value=(b"", b"git config exploded"))
        mock_proc.returncode = 1

        with (
            unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            pytest.raises(RuntimeError, match="git config exploded"),
        ):
            await ensure_git_credentials_store()


class TestSetGitToken:
    async def test_adds_new_host_entry(self):
        await set_git_token(host="github.com", token="ghp_abc123")

        assert await get_stored_token("github.com") is not None

    async def test_includes_username_when_provided(self, isolated_git_credentials_store):
        await set_git_token(host="gitlab.com", token="glpat-xyz", username="custom-user")

        credentials_text = (isolated_git_credentials_store / "credentials").read_text()
        assert "https://custom-user:glpat-xyz@gitlab.com" in credentials_text

    async def test_uses_placeholder_username_when_not_provided(self, isolated_git_credentials_store):
        await set_git_token(host="github.com", token="ghp_abc123")

        credentials_text = (isolated_git_credentials_store / "credentials").read_text()
        assert "https://oauth2:ghp_abc123@github.com" in credentials_text

    async def test_replaces_existing_entry_for_same_host(self):
        await set_git_token(host="github.com", token="old-token")
        await set_git_token(host="github.com", token="new-token")

        assert await get_stored_token("github.com") == ("oauth2", "new-token")

    async def test_keeps_entries_for_different_hosts(self):
        await set_git_token(host="github.com", token="tok-a")
        await set_git_token(host="gitlab.com", token="tok-b")

        assert await get_stored_token("github.com") is not None
        assert await get_stored_token("gitlab.com") is not None


class TestDeleteGitToken:
    async def test_removes_existing_host(self):
        await set_git_token(host="github.com", token="tok-a")
        await set_git_token(host="gitlab.com", token="tok-b")

        removed = await delete_git_token("github.com")

        assert removed is True
        assert await get_stored_token("github.com") is None
        assert await get_stored_token("gitlab.com") is not None

    async def test_returns_false_when_host_not_configured(self):
        assert await delete_git_token("github.com") is False


class TestGetStoredToken:
    async def test_returns_none_when_no_credentials_file(self):
        assert await get_stored_token("github.com") is None

    async def test_returns_none_when_host_not_configured(self):
        await set_git_token(host="github.com", token="tok-a")

        assert await get_stored_token("gitlab.com") is None

    async def test_returns_username_and_token_for_placeholder_username(self):
        await set_git_token(host="github.com", token="ghp_abc123")

        assert await get_stored_token("github.com") == ("oauth2", "ghp_abc123")

    async def test_returns_username_and_token_for_custom_username(self):
        await set_git_token(host="gitlab.com", token="glpat-xyz", username="custom-user")

        assert await get_stored_token("gitlab.com") == ("custom-user", "glpat-xyz")

    async def test_reflects_most_recent_token_for_host(self):
        await set_git_token(host="github.com", token="old-token")
        await set_git_token(host="github.com", token="new-token")

        assert await get_stored_token("github.com") == ("oauth2", "new-token")
