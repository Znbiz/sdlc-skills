from __future__ import annotations

import contextlib
import typing

import sqlalchemy.ext.asyncio as async_sa

_engine: async_sa.AsyncEngine | None = None


def init_engine(database_url: str) -> async_sa.AsyncEngine:
    global _engine  # noqa: PLW0603
    _engine = async_sa.create_async_engine(database_url, echo=False)
    return _engine


def get_engine() -> async_sa.AsyncEngine:
    if _engine is None:
        raise RuntimeError("DB engine is not initialized")
    return _engine


def _make_session_factory() -> async_sa.async_sessionmaker[async_sa.AsyncSession]:
    return async_sa.async_sessionmaker(get_engine(), expire_on_commit=False)


@contextlib.asynccontextmanager
async def get_session() -> typing.AsyncGenerator[async_sa.AsyncSession, None]:
    factory = _make_session_factory()
    async with factory() as session:
        yield session
