from __future__ import annotations

import datetime
import typing

import sqlalchemy as sa
import sqlalchemy.ext.asyncio as async_sa

from app.db.models import GitHostConnectionModel

if typing.TYPE_CHECKING:
    import uuid


async def list_git_hosts(session: async_sa.AsyncSession) -> list[GitHostConnectionModel]:
    result = await session.execute(sa.select(GitHostConnectionModel).order_by(GitHostConnectionModel.host))
    return list(result.scalars())


async def get_git_host_by_id(session: async_sa.AsyncSession, connection_id: uuid.UUID) -> GitHostConnectionModel | None:
    return await session.get(GitHostConnectionModel, connection_id)


async def get_git_host_by_host(session: async_sa.AsyncSession, host: str) -> GitHostConnectionModel | None:
    result = await session.execute(sa.select(GitHostConnectionModel).where(GitHostConnectionModel.host == host))
    return result.scalar_one_or_none()


async def create_git_host(session: async_sa.AsyncSession, *, host: str, connection_type: str) -> GitHostConnectionModel:
    record = GitHostConnectionModel(host=host, connection_type=connection_type)
    session.add(record)
    await session.commit()
    return record


async def update_git_host(
    session: async_sa.AsyncSession,
    *,
    connection_id: uuid.UUID,
    host: str,
    connection_type: str,
) -> GitHostConnectionModel | None:
    record = await session.get(GitHostConnectionModel, connection_id)
    if record is None:
        return None
    record.host = host
    record.connection_type = connection_type
    record.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await session.commit()
    return record


async def delete_git_host(session: async_sa.AsyncSession, connection_id: uuid.UUID) -> GitHostConnectionModel | None:
    record = await session.get(GitHostConnectionModel, connection_id)
    if record is None:
        return None
    await session.delete(record)
    await session.commit()
    return record
