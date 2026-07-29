import uuid

import pytest

from app.services.llm_provider_credentials import (
    delete_llm_provider_token,
    ensure_llm_provider_secrets_store,
    get_llm_provider_token,
    set_llm_provider_token,
)


@pytest.fixture(autouse=True)
def isolated_llm_provider_secrets_store(tmp_path, monkeypatch):
    store_dir = tmp_path / "llm-provider-secrets"
    monkeypatch.setattr("app.services.llm_provider_credentials._SECRETS_DIR", store_dir)
    return store_dir


class TestEnsureLlmProviderSecretsStore:
    def test_creates_store_dir(self, isolated_llm_provider_secrets_store):
        ensure_llm_provider_secrets_store()

        assert isolated_llm_provider_secrets_store.exists()


class TestSetLlmProviderToken:
    def test_writes_token_file(self):
        connection_id = uuid.uuid4()
        set_llm_provider_token(connection_id, "sk-abc123")

        assert get_llm_provider_token(connection_id) == "sk-abc123"

    def test_overwrites_existing_token(self):
        connection_id = uuid.uuid4()
        set_llm_provider_token(connection_id, "old-token")
        set_llm_provider_token(connection_id, "new-token")

        assert get_llm_provider_token(connection_id) == "new-token"

    def test_keeps_tokens_for_different_connections_isolated(self):
        connection_a = uuid.uuid4()
        connection_b = uuid.uuid4()
        set_llm_provider_token(connection_a, "token-a")
        set_llm_provider_token(connection_b, "token-b")

        assert get_llm_provider_token(connection_a) == "token-a"
        assert get_llm_provider_token(connection_b) == "token-b"


class TestGetLlmProviderToken:
    def test_returns_none_when_not_configured(self):
        assert get_llm_provider_token(uuid.uuid4()) is None


class TestDeleteLlmProviderToken:
    def test_removes_existing_token(self):
        connection_id = uuid.uuid4()
        set_llm_provider_token(connection_id, "token")

        removed = delete_llm_provider_token(connection_id)

        assert removed is True
        assert get_llm_provider_token(connection_id) is None

    def test_returns_false_when_not_configured(self):
        assert delete_llm_provider_token(uuid.uuid4()) is False
