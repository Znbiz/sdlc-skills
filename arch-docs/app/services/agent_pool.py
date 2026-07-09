import asyncio
import dataclasses
import typing


@typing.final
class AgentPool:
    __slots__ = ("_semaphore",)

    def __init__(self, pool_size: int) -> None:
        self._semaphore = asyncio.Semaphore(pool_size)

    async def __aenter__(self) -> "AgentPool":
        await self._semaphore.acquire()
        return self

    async def __aexit__(self, *_args: object) -> None:
        self._semaphore.release()


@dataclasses.dataclass(slots=True)
class _PoolState:
    pool: AgentPool | None = None


_state = _PoolState()


def init_agent_pool(pool_size: int) -> AgentPool:
    _state.pool = AgentPool(pool_size=pool_size)
    return _state.pool


def get_agent_pool() -> AgentPool:
    if _state.pool is None:
        raise RuntimeError("AgentPool is not initialized")
    return _state.pool
