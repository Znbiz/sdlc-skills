import asyncio
import contextlib
import typing

import fastapi
import structlog

from app.api import setup_routers
from app.container import AppContainer
from app.db.session import get_session, init_engine
from app.db.task_repo import mark_running_tasks_failed
from app.mcp_server import mcp_server
from app.middleware.bearer_auth import BearerAuthMiddleware
from app.services.agent_pool import init_agent_pool
from app.services.task_registry import TaskStatus, get_registry
from app.services.task_runner import cancel_cli_task, set_db_enabled
from app.settings import GatewaySettings

logger = structlog.get_logger()


async def _init_db(database_url: str) -> None:
    init_engine(database_url)
    async with get_session() as session:
        failed_count: int = await mark_running_tasks_failed(session)
    set_db_enabled(True)
    logger.info("ai_cli_gateway.db_connected", failed_tasks_reset=failed_count)


@contextlib.asynccontextmanager
async def lifespan(_app: fastapi.FastAPI) -> typing.AsyncGenerator[None, None]:
    await AppContainer.init_resources()
    settings = GatewaySettings()
    init_agent_pool(pool_size=settings.agent_pool_size)

    try:
        await _init_db(settings.database_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ai_cli_gateway.db_unavailable", error=str(exc))

    logger.info("ai_cli_gateway.started", agent_pool_size=settings.agent_pool_size)
    yield

    registry = get_registry()
    running_tasks = [t for t in registry.values() if t.task_status == TaskStatus.RUNNING]
    if running_tasks:
        logger.info("ai_cli_gateway.cancelling_running_tasks", count=len(running_tasks))
        await asyncio.gather(*[cancel_cli_task(t.task_id, registry) for t in running_tasks])
    logger.info("ai_cli_gateway.stopped")


def create_app() -> fastapi.FastAPI:
    settings = GatewaySettings()

    application = fastapi.FastAPI(
        title="AI CLI Gateway",
        version="1.0.0",
        description="HTTP/WebSocket API поверх CLI-инструментов codex и claude",
        lifespan=lifespan,
    )

    application.add_middleware(BearerAuthMiddleware, auth_secret=settings.auth_secret)
    setup_routers(application)
    application.mount("/api/mcp", mcp_server.http_app(transport="sse"))

    @application.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"service_status": "ok", "version": "1.0.0"}

    return application


app = create_app()
