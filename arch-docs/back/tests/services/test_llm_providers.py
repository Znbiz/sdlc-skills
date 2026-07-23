import uuid

import pytest

from app.services.llm_providers import (
    LlmProviderConnectionAlreadyExistsError,
    LlmProviderConnectionNotFoundError,
    LlmProviderConnectionValidationError,
    create_llm_provider_connection_async,
    delete_llm_provider_connection_async,
    get_llm_provider_connection_async,
    list_llm_provider_connections_async,
    update_llm_provider_connection_async,
)


@pytest.fixture(autouse=True)
def isolated_llm_provider_secrets_store(tmp_path, monkeypatch):
    store_dir = tmp_path / "llm-provider-secrets"
    monkeypatch.setattr("app.services.llm_provider_credentials._SECRETS_DIR", store_dir)
    return store_dir


class TestListLlmProviderConnections:
    async def test_returns_empty_list_when_none_configured(self):
        assert await list_llm_provider_connections_async() == []

    async def test_returns_all_configured_connections(self):
        await create_llm_provider_connection_async(
            name="my-provider", base_url="https://api.example.com/v1", model="my-model", token="sk-abc"
        )

        connections = await list_llm_provider_connections_async()

        assert [(c.name, c.model) for c in connections] == [("my-provider", "my-model")]


class TestCreateLlmProviderConnection:
    async def test_creates_connection_and_stores_secret(self):
        summary = await create_llm_provider_connection_async(
            name="my-provider", base_url="https://api.example.com/v1", model="my-model", token="sk-abc"
        )

        assert summary.name == "my-provider"
        assert summary.wire_api == "chat"
        assert summary.requires_openai_auth is False
        detail = await get_llm_provider_connection_async(summary.connection_id)
        assert detail.token == "sk-abc"  # noqa: S105

    async def test_rejects_empty_name(self):
        with pytest.raises(LlmProviderConnectionValidationError):
            await create_llm_provider_connection_async(
                name="  ", base_url="https://api.example.com/v1", model="my-model", token="sk-abc"
            )

    async def test_rejects_empty_token(self):
        with pytest.raises(LlmProviderConnectionValidationError):
            await create_llm_provider_connection_async(
                name="my-provider", base_url="https://api.example.com/v1", model="my-model", token="   "
            )

    async def test_rejects_unknown_wire_api(self):
        with pytest.raises(LlmProviderConnectionValidationError):
            await create_llm_provider_connection_async(
                name="my-provider",
                base_url="https://api.example.com/v1",
                model="my-model",
                token="sk-abc",
                wire_api="carrier-pigeon",
            )

    async def test_rejects_duplicate_name(self):
        await create_llm_provider_connection_async(
            name="my-provider", base_url="https://api.example.com/v1", model="my-model", token="sk-abc"
        )

        with pytest.raises(LlmProviderConnectionAlreadyExistsError):
            await create_llm_provider_connection_async(
                name="my-provider", base_url="https://other.example.com/v1", model="other-model", token="sk-def"
            )


class TestUpdateLlmProviderConnection:
    async def test_updates_fields_and_keeps_previous_token_when_omitted(self):
        summary = await create_llm_provider_connection_async(
            name="my-provider", base_url="https://api.example.com/v1", model="my-model", token="sk-abc"
        )

        updated = await update_llm_provider_connection_async(
            connection_id=summary.connection_id,
            name="my-provider",
            base_url="https://api.example.com/v2",
            model="my-model-2",
        )

        assert updated.base_url == "https://api.example.com/v2"
        detail = await get_llm_provider_connection_async(summary.connection_id)
        assert detail.token == "sk-abc"  # noqa: S105

    async def test_replaces_token_when_provided(self):
        summary = await create_llm_provider_connection_async(
            name="my-provider", base_url="https://api.example.com/v1", model="my-model", token="sk-abc"
        )

        await update_llm_provider_connection_async(
            connection_id=summary.connection_id,
            name="my-provider",
            base_url="https://api.example.com/v1",
            model="my-model",
            token="sk-new",
        )

        detail = await get_llm_provider_connection_async(summary.connection_id)
        assert detail.token == "sk-new"  # noqa: S105

    async def test_raises_not_found_for_missing_connection(self):
        with pytest.raises(LlmProviderConnectionNotFoundError):
            await update_llm_provider_connection_async(
                connection_id=uuid.uuid4(), name="x", base_url="https://x", model="x"
            )

    async def test_raises_conflict_when_renaming_to_existing_name(self):
        await create_llm_provider_connection_async(
            name="provider-a", base_url="https://a.example.com", model="model-a", token="sk-a"
        )
        other = await create_llm_provider_connection_async(
            name="provider-b", base_url="https://b.example.com", model="model-b", token="sk-b"
        )

        with pytest.raises(LlmProviderConnectionAlreadyExistsError):
            await update_llm_provider_connection_async(
                connection_id=other.connection_id, name="provider-a", base_url="https://b.example.com", model="model-b"
            )


class TestGetLlmProviderConnection:
    async def test_raises_not_found_for_missing_connection(self):
        with pytest.raises(LlmProviderConnectionNotFoundError):
            await get_llm_provider_connection_async(uuid.uuid4())


class TestDeleteLlmProviderConnection:
    async def test_removes_connection_and_stored_secret(self):
        summary = await create_llm_provider_connection_async(
            name="my-provider", base_url="https://api.example.com/v1", model="my-model", token="sk-abc"
        )

        await delete_llm_provider_connection_async(summary.connection_id)

        assert await list_llm_provider_connections_async() == []
        with pytest.raises(LlmProviderConnectionNotFoundError):
            await get_llm_provider_connection_async(summary.connection_id)

    async def test_raises_not_found_for_missing_connection(self):
        with pytest.raises(LlmProviderConnectionNotFoundError):
            await delete_llm_provider_connection_async(uuid.uuid4())
