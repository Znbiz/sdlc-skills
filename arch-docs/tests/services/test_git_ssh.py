import unittest.mock

import pytest

from app.services.git_ssh import (
    GitAccessStatus,
    check_git_access,
    ensure_ssh_key,
    get_public_key,
)


@pytest.fixture(autouse=True)
def isolated_ssh_dir(tmp_path, monkeypatch):
    ssh_dir = tmp_path / ".ssh"
    monkeypatch.setattr("app.services.git_ssh._SSH_DIR", ssh_dir)
    monkeypatch.setattr("app.services.git_ssh._PRIVATE_KEY_PATH", ssh_dir / "id_ed25519")
    monkeypatch.setattr("app.services.git_ssh._PUBLIC_KEY_PATH", ssh_dir / "id_ed25519.pub")
    monkeypatch.setattr("app.services.git_ssh._SSH_CONFIG_PATH", ssh_dir / "config")
    monkeypatch.setattr("app.services.git_ssh._KNOWN_HOSTS_PATH", ssh_dir / "known_hosts")
    return ssh_dir


class TestEnsureSshKey:
    async def test_generates_key_pair_when_missing(self, isolated_ssh_dir):
        public_key = await ensure_ssh_key()

        assert (isolated_ssh_dir / "id_ed25519").exists()
        assert (isolated_ssh_dir / "id_ed25519.pub").exists()
        assert public_key.startswith("ssh-ed25519")

    async def test_writes_ssh_config_and_known_hosts(self, isolated_ssh_dir):
        await ensure_ssh_key()

        config_text = (isolated_ssh_dir / "config").read_text()
        assert "StrictHostKeyChecking accept-new" in config_text
        assert (isolated_ssh_dir / "known_hosts").exists()

    async def test_reuses_existing_key_pair(self):
        first_public_key = await ensure_ssh_key()
        second_public_key = await ensure_ssh_key()

        assert first_public_key == second_public_key

    async def test_raises_when_keygen_fails(self):
        mock_proc = unittest.mock.AsyncMock()
        mock_proc.communicate = unittest.mock.AsyncMock(return_value=(b"", b"keygen exploded"))
        mock_proc.returncode = 1

        with (
            unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            pytest.raises(RuntimeError, match="keygen exploded"),
        ):
            await ensure_ssh_key()

    async def test_get_public_key_delegates_to_ensure(self):
        public_key = await get_public_key()
        assert public_key.startswith("ssh-ed25519")


class TestCheckGitAccess:
    @pytest.fixture(autouse=True)
    async def _key_already_generated(self):
        await ensure_ssh_key()

    async def test_accessible_when_ls_remote_succeeds(self):
        mock_proc = unittest.mock.AsyncMock()
        mock_proc.communicate = unittest.mock.AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await check_git_access("git@github.com:org/repo.git")

        assert result["accessible"] is True
        assert result["access_status"] == GitAccessStatus.OK

    async def test_auth_failed_on_permission_denied(self):
        mock_proc = unittest.mock.AsyncMock()
        mock_proc.communicate = unittest.mock.AsyncMock(
            return_value=(b"", b"git@github.com: Permission denied (publickey).")
        )
        mock_proc.returncode = 128

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await check_git_access("git@github.com:org/repo.git")

        assert result["accessible"] is False
        assert result["access_status"] == GitAccessStatus.AUTH_FAILED
        assert "Permission denied" in result["message"]

    async def test_timeout_classified_as_timeout(self):
        mock_proc = unittest.mock.AsyncMock()
        mock_proc.communicate = unittest.mock.AsyncMock(side_effect=TimeoutError)
        mock_proc.kill = unittest.mock.MagicMock()
        mock_proc.wait = unittest.mock.AsyncMock()

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await check_git_access("git@example.com:org/repo.git")

        assert result["accessible"] is False
        assert result["access_status"] == GitAccessStatus.TIMEOUT

    async def test_unknown_failure_classified_as_error(self):
        mock_proc = unittest.mock.AsyncMock()
        mock_proc.communicate = unittest.mock.AsyncMock(return_value=(b"", b"fatal: repository not found"))
        mock_proc.returncode = 128

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await check_git_access("git@github.com:org/missing.git")

        assert result["accessible"] is False
        assert result["access_status"] == GitAccessStatus.ERROR
