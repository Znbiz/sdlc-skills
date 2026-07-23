from __future__ import annotations

import dataclasses
import typing

from app.db.llm_provider_repo import (
    create_llm_provider_connection,
    delete_llm_provider_connection,
    get_llm_provider_connection_by_id,
    get_llm_provider_connection_by_name,
    list_llm_provider_connections,
    update_llm_provider_connection,
)
from app.db.session import get_session
from app.services.llm_provider_credentials import (
    delete_llm_provider_token,
    get_llm_provider_token,
    set_llm_provider_token,
)

if typing.TYPE_CHECKING:
    import uuid

_DEFAULT_WIRE_API: typing.Final[str] = "chat"
_WIRE_APIS: typing.Final[frozenset[str]] = frozenset({"chat", "responses"})


class LlmProviderConnectionNotFoundError(Exception):
    pass


class LlmProviderConnectionAlreadyExistsError(Exception):
    pass


class LlmProviderConnectionValidationError(Exception):
    pass


@dataclasses.dataclass(frozen=True, slots=True)
class LlmProviderConnectionSummary:
    connection_id: uuid.UUID
    name: str
    base_url: str
    model: str
    wire_api: str
    requires_openai_auth: bool


@dataclasses.dataclass(frozen=True, slots=True)
class LlmProviderConnectionDetail:
    connection_id: uuid.UUID
    name: str
    base_url: str
    model: str
    wire_api: str
    requires_openai_auth: bool
    token: str | None


def _validate_fields(*, name: str, base_url: str, model: str, token: str | None, wire_api: str) -> None:
    if not name.strip():
        raise LlmProviderConnectionValidationError("name must not be empty")
    if not base_url.strip():
        raise LlmProviderConnectionValidationError("base_url must not be empty")
    if not model.strip():
        raise LlmProviderConnectionValidationError("model must not be empty")
    if wire_api not in _WIRE_APIS:
        msg = f"wire_api must be one of {sorted(_WIRE_APIS)}, got {wire_api!r}"
        raise LlmProviderConnectionValidationError(msg)
    if token is not None and not token.strip():
        raise LlmProviderConnectionValidationError("token must not be empty when provided")


def _summary(model_row) -> LlmProviderConnectionSummary:
    return LlmProviderConnectionSummary(
        connection_id=model_row.connection_id,
        name=model_row.name,
        base_url=model_row.base_url,
        model=model_row.model,
        wire_api=model_row.wire_api,
        requires_openai_auth=model_row.requires_openai_auth,
    )


async def list_llm_provider_connections_async() -> list[LlmProviderConnectionSummary]:
    async with get_session() as session:
        rows = await list_llm_provider_connections(session)
    return [_summary(row) for row in rows]


async def get_llm_provider_connection_async(connection_id: uuid.UUID) -> LlmProviderConnectionDetail:
    async with get_session() as session:
        row = await get_llm_provider_connection_by_id(session, connection_id)
    if row is None:
        raise LlmProviderConnectionNotFoundError(connection_id)
    token = get_llm_provider_token(row.connection_id)
    return LlmProviderConnectionDetail(
        connection_id=row.connection_id,
        name=row.name,
        base_url=row.base_url,
        model=row.model,
        wire_api=row.wire_api,
        requires_openai_auth=row.requires_openai_auth,
        token=token,
    )


async def create_llm_provider_connection_async(  # noqa: PLR0913
    *,
    name: str,
    base_url: str,
    model: str,
    token: str,
    wire_api: str = _DEFAULT_WIRE_API,
    requires_openai_auth: bool = False,
) -> LlmProviderConnectionSummary:
    _validate_fields(name=name, base_url=base_url, model=model, token=token, wire_api=wire_api)

    async with get_session() as session:
        existing = await get_llm_provider_connection_by_name(session, name)
    if existing is not None:
        raise LlmProviderConnectionAlreadyExistsError(name)

    async with get_session() as session:
        row = await create_llm_provider_connection(
            session,
            name=name,
            base_url=base_url,
            model=model,
            wire_api=wire_api,
            requires_openai_auth=requires_openai_auth,
        )
    set_llm_provider_token(row.connection_id, token)
    return _summary(row)


async def update_llm_provider_connection_async(  # noqa: PLR0913
    *,
    connection_id: uuid.UUID,
    name: str,
    base_url: str,
    model: str,
    token: str | None = None,
    wire_api: str = _DEFAULT_WIRE_API,
    requires_openai_auth: bool = False,
) -> LlmProviderConnectionSummary:
    _validate_fields(name=name, base_url=base_url, model=model, token=token, wire_api=wire_api)

    async with get_session() as session:
        current = await get_llm_provider_connection_by_id(session, connection_id)
        if current is None:
            raise LlmProviderConnectionNotFoundError(connection_id)

        conflicting = await get_llm_provider_connection_by_name(session, name)
        if conflicting is not None and conflicting.connection_id != connection_id:
            raise LlmProviderConnectionAlreadyExistsError(name)

    async with get_session() as session:
        row = await update_llm_provider_connection(
            session,
            connection_id=connection_id,
            name=name,
            base_url=base_url,
            model=model,
            wire_api=wire_api,
            requires_openai_auth=requires_openai_auth,
        )
    if row is None:
        raise LlmProviderConnectionNotFoundError(connection_id)

    if token is not None:
        set_llm_provider_token(connection_id, token)
    return _summary(row)


async def delete_llm_provider_connection_async(connection_id: uuid.UUID) -> None:
    async with get_session() as session:
        deleted = await delete_llm_provider_connection(session, connection_id)
    if deleted is None:
        raise LlmProviderConnectionNotFoundError(connection_id)
    delete_llm_provider_token(connection_id)
