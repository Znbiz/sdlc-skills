import asyncio

import pytest

import app.services.agent_pool as agent_pool_module
from app.services.agent_pool import AgentPool, get_agent_pool


async def test_agent_pool_semaphore_limits_concurrency() -> None:
    pool = AgentPool(pool_size=1)
    results: list[int] = []

    async def acquire_and_record(value: int) -> None:
        async with pool:
            results.append(value)

    await asyncio.gather(acquire_and_record(1), acquire_and_record(2))
    assert sorted(results) == [1, 2]


async def test_get_agent_pool_raises_when_not_initialized() -> None:
    saved = agent_pool_module._state.pool
    agent_pool_module._state.pool = None

    try:
        with pytest.raises(RuntimeError, match="AgentPool is not initialized"):
            get_agent_pool()
    finally:
        agent_pool_module._state.pool = saved
