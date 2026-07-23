from __future__ import annotations

import datetime
import typing

import sqlalchemy as sa
import sqlalchemy.ext.asyncio as async_sa

from app.db.models import LlmProviderConnectionModel

if typing.TYPE_CHECKING:
    import uuid


async def list_llm_provider_connections(session: async_sa.AsyncSession) -> list[LlmProviderConnectionModel]:
    result = await session.execute(sa.select(LlmProviderConnectionModel).order_by(LlmProviderConnectionModel.name))
    return list(result.scalars())


async def get_llm_provider_connection_by_id(
    session: async_sa.AsyncSession, connection_id: uuid.UUID
) -> LlmProviderConnectionModel | None:
    return await session.get(LlmProviderConnectionModel, connection_id)


async def get_llm_provider_connection_by_name(
    session: async_sa.AsyncSession, name: str
) -> LlmProviderConnectionModel | None:
    result = await session.execute(sa.select(LlmProviderConnectionModel).where(LlmProviderConnectionModel.name == name))
    return result.scalar_one_or_none()


async def create_llm_provider_connection(  # noqa: PLR0913
    session: async_sa.AsyncSession,
    *,
    name: str,
    base_url: str,
    model: str,
    wire_api: str,
    requires_openai_auth: bool,
) -> LlmProviderConnectionModel:
    record = LlmProviderConnectionModel(
        name=name,
        base_url=base_url,
        model=model,
        wire_api=wire_api,
        requires_openai_auth=requires_openai_auth,
    )
    session.add(record)
    await session.commit()
    return record


async def update_llm_provider_connection(  # noqa: PLR0913
    session: async_sa.AsyncSession,
    *,
    connection_id: uuid.UUID,
    name: str,
    base_url: str,
    model: str,
    wire_api: str,
    requires_openai_auth: bool,
) -> LlmProviderConnectionModel | None:
    record = await session.get(LlmProviderConnectionModel, connection_id)
    if record is None:
        return None
    record.name = name
    record.base_url = base_url
    record.model = model
    record.wire_api = wire_api
    record.requires_openai_auth = requires_openai_auth
    record.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await session.commit()
    return record


async def delete_llm_provider_connection(
    session: async_sa.AsyncSession, connection_id: uuid.UUID
) -> LlmProviderConnectionModel | None:
    record = await session.get(LlmProviderConnectionModel, connection_id)
    if record is None:
        return None
    await session.delete(record)
    await session.commit()
    return record
