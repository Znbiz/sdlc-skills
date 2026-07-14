import os
import unittest.mock

import pytest

from app.services.git_credentials import (
    GitAccessStatus,
    check_git_access,
    delete_git_token,
    ensure_git_credentials_store,
    list_configured_hosts,
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

        hosts = await list_configured_hosts()
        assert hosts == ["github.com"]

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

        hosts = await list_configured_hosts()
        assert hosts == ["github.com"]

    async def test_keeps_entries_for_different_hosts(self):
        await set_git_token(host="github.com", token="tok-a")
        await set_git_token(host="gitlab.com", token="tok-b")

        hosts = await list_configured_hosts()
        assert set(hosts) == {"github.com", "gitlab.com"}


class TestListConfiguredHosts:
    async def test_returns_empty_list_when_no_credentials_file(self):
        assert await list_configured_hosts() == []


class TestDeleteGitToken:
    async def test_removes_existing_host(self):
        await set_git_token(host="github.com", token="tok-a")
        await set_git_token(host="gitlab.com", token="tok-b")

        removed = await delete_git_token("github.com")

        assert removed is True
        assert await list_configured_hosts() == ["gitlab.com"]

    async def test_returns_false_when_host_not_configured(self):
        assert await delete_git_token("github.com") is False


class TestCheckGitAccess:
    @pytest.fixture(autouse=True)
    async def _store_already_configured(self):
        await ensure_git_credentials_store()
        await set_git_token(host="github.com", token="tok-a")

    async def test_accessible_when_ls_remote_succeeds(self):
        mock_proc = unittest.mock.AsyncMock()
        mock_proc.communicate = unittest.mock.AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await check_git_access("https://github.com/org/repo.git")

        assert result["accessible"] is True
        assert result["access_status"] == GitAccessStatus.OK

    async def test_auth_failed_on_permission_denied(self):
        mock_proc = unittest.mock.AsyncMock()
        mock_proc.communicate = unittest.mock.AsyncMock(
            return_value=(b"", b"remote: Invalid username or password.\nfatal: Authentication failed")
        )
        mock_proc.returncode = 128

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await check_git_access("https://github.com/org/private.git")

        assert result["accessible"] is False
        assert result["access_status"] == GitAccessStatus.AUTH_FAILED

    async def test_timeout_classified_as_timeout(self):
        mock_proc = unittest.mock.AsyncMock()
        mock_proc.communicate = unittest.mock.AsyncMock(side_effect=TimeoutError)
        mock_proc.kill = unittest.mock.MagicMock()
        mock_proc.wait = unittest.mock.AsyncMock()

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await check_git_access("https://example.com/org/repo.git")

        assert result["accessible"] is False
        assert result["access_status"] == GitAccessStatus.TIMEOUT

    async def test_unknown_failure_classified_as_error(self):
        mock_proc = unittest.mock.AsyncMock()
        mock_proc.communicate = unittest.mock.AsyncMock(return_value=(b"", b"fatal: repository not found"))
        mock_proc.returncode = 128

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await check_git_access("https://github.com/org/missing.git")

        assert result["accessible"] is False
        assert result["access_status"] == GitAccessStatus.ERROR


class TestCheckGitAccessReasonCodes:
    async def test_missing_pat_short_circuits_before_subprocess(self):
        with unittest.mock.patch("asyncio.create_subprocess_exec") as mock_exec:
            result = await check_git_access("https://github.com/org/repo.git")

        mock_exec.assert_not_called()
        assert result["accessible"] is False
        assert result["reason_code"] == "git_pat_missing"

    async def test_git_binary_missing_maps_to_reason_code(self):
        await set_git_token(host="github.com", token="tok-a")

        with unittest.mock.patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            result = await check_git_access("https://github.com/org/repo.git")

        assert result["accessible"] is False
        assert result["reason_code"] == "git_binary_missing"

    async def test_auth_failed_maps_to_reason_code(self):
        await set_git_token(host="github.com", token="tok-a")
        mock_proc = unittest.mock.AsyncMock()
        mock_proc.communicate = unittest.mock.AsyncMock(return_value=(b"", b"fatal: Authentication failed"))
        mock_proc.returncode = 128

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await check_git_access("https://github.com/org/repo.git")

        assert result["reason_code"] == "git_access_auth_failed"

    async def test_ok_result_has_no_reason_code(self):
        await set_git_token(host="github.com", token="tok-a")
        mock_proc = unittest.mock.AsyncMock()
        mock_proc.communicate = unittest.mock.AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await check_git_access("https://github.com/org/repo.git")

        assert result["reason_code"] is None
