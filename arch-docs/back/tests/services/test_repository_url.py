from unittest.mock import AsyncMock

from app.services.repository_url import canonicalize_repo_path, extract_repo_host_and_path, normalize_repository_url


class TestCanonicalizeRepoPath:
    def test_strips_trailing_slash_and_git_suffix(self):
        assert canonicalize_repo_path("org/repo.git/") == "org/repo"

    def test_strips_surrounding_whitespace(self):
        assert canonicalize_repo_path("  org/repo  ") == "org/repo"


class TestExtractRepoHostAndPath:
    def test_parses_scp_like_ssh_url(self):
        assert extract_repo_host_and_path("git@github.com:org/repo.git") == ("ssh", "github.com", "org/repo")

    def test_parses_https_url(self):
        assert extract_repo_host_and_path("https://github.com/org/repo") == ("https", "github.com", "org/repo")

    def test_parses_http_url(self):
        assert extract_repo_host_and_path("http://github.com/org/repo.git/") == ("http", "github.com", "org/repo")

    def test_returns_none_for_bare_repo_name(self):
        assert extract_repo_host_and_path("org/repo") is None


class TestNormalizeRepositoryUrl:
    async def test_rewrites_to_ssh_when_host_registered_as_ssh(self, monkeypatch):
        monkeypatch.setattr("app.services.repository_url.get_connection_type_for_host", AsyncMock(return_value="ssh"))

        result = await normalize_repository_url("https://github.com/org/repo")

        assert result == "git@github.com:org/repo.git"

    async def test_rewrites_ssh_form_to_ssh_when_host_registered_as_ssh(self, monkeypatch):
        monkeypatch.setattr("app.services.repository_url.get_connection_type_for_host", AsyncMock(return_value="ssh"))

        result = await normalize_repository_url("git@github.com:org/repo.git")

        assert result == "git@github.com:org/repo.git"

    async def test_rewrites_to_https_when_host_registered_as_token(self, monkeypatch):
        monkeypatch.setattr("app.services.repository_url.get_connection_type_for_host", AsyncMock(return_value="token"))

        result = await normalize_repository_url("git@github.com:org/repo.git")

        assert result == "https://github.com/org/repo.git"

    async def test_keeps_original_scheme_when_host_unregistered(self, monkeypatch):
        monkeypatch.setattr("app.services.repository_url.get_connection_type_for_host", AsyncMock(return_value=None))

        assert await normalize_repository_url("https://example.com/org/repo") == "https://example.com/org/repo.git"
        assert await normalize_repository_url("git@example.com:org/repo.git") == "git@example.com:org/repo.git"

    async def test_returns_bare_repo_name_unchanged(self, monkeypatch):
        monkeypatch.setattr("app.services.repository_url.get_connection_type_for_host", AsyncMock(return_value="ssh"))

        assert await normalize_repository_url("svc-a") == "svc-a"

    async def test_strips_surrounding_whitespace(self, monkeypatch):
        monkeypatch.setattr("app.services.repository_url.get_connection_type_for_host", AsyncMock(return_value=None))

        result = await normalize_repository_url("  https://example.com/org/repo  ")

        assert result == "https://example.com/org/repo.git"
