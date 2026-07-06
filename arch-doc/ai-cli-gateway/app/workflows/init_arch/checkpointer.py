from __future__ import annotations

import asyncio

import asyncpg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.settings import GatewaySettings

_checkpointer: AsyncPostgresSaver | None = None
_checkpointer_lock = asyncio.Lock()


async def get_checkpointer() -> AsyncPostgresSaver:
    global _checkpointer  # noqa: PLW0603
    async with _checkpointer_lock:
        if _checkpointer is None:
            settings = GatewaySettings()
            raw_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
            conn = await asyncpg.connect(raw_url)
            saver: AsyncPostgresSaver = AsyncPostgresSaver(conn)  # type: ignore[arg-type]
            await saver.setup()
            _checkpointer = saver
    return _checkpointer
