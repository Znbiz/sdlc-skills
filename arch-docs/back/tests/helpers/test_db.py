from tests.helpers.db import DEFAULT_ADMIN_DATABASE_URL, DEFAULT_TEST_DATABASE_NAME, resolve_test_database_urls


def test_resolve_test_database_urls_uses_defaults_without_env(monkeypatch):
    monkeypatch.delenv("TEST_DATABASE_ADMIN_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_NAME", raising=False)

    admin_url, test_url, database_name = resolve_test_database_urls()

    assert admin_url == DEFAULT_ADMIN_DATABASE_URL
    assert database_name == DEFAULT_TEST_DATABASE_NAME
    assert test_url.endswith(f"/{DEFAULT_TEST_DATABASE_NAME}")
    assert test_url.startswith(admin_url.rsplit("/", 1)[0])


def test_resolve_test_database_urls_respects_env_overrides(monkeypatch):
    monkeypatch.setenv("TEST_DATABASE_ADMIN_URL", "postgresql+asyncpg://u:p@db-host:5433/postgres")
    monkeypatch.setenv("TEST_DATABASE_NAME", "custom_test_db")

    admin_url, test_url, database_name = resolve_test_database_urls()

    assert admin_url == "postgresql+asyncpg://u:p@db-host:5433/postgres"
    assert database_name == "custom_test_db"
    assert test_url == "postgresql+asyncpg://u:p@db-host:5433/custom_test_db"
