from __future__ import annotations

import asyncio

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row

from app.settings import GatewaySettings

_checkpointer: AsyncPostgresSaver | None = None
_checkpointer_lock = asyncio.Lock()


async def get_checkpointer() -> AsyncPostgresSaver:
    global _checkpointer  # noqa: PLW0603
    async with _checkpointer_lock:
        if _checkpointer is None:
            settings = GatewaySettings()
            raw_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
            conn = await psycopg.AsyncConnection.connect(
                raw_url, autocommit=True, prepare_threshold=0, row_factory=dict_row
            )
            saver = AsyncPostgresSaver(conn)
            await saver.setup()
            _checkpointer = saver
    return _checkpointer
