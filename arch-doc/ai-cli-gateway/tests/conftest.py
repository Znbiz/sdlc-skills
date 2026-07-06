import os

os.environ["AUTH_SECRET"] = "test-secret-token"  # noqa: S105

import httpx
import pytest

from app.main import app
from app.services.agent_pool import init_agent_pool
from app.services.cli_auth_session import reset_auth_session_registry
from app.services.task_registry import reset_registry


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-secret-token"}


@pytest.fixture(autouse=True)
def reset_task_registry() -> None:
    reset_registry()
    reset_auth_session_registry()
    yield
    reset_registry()
    reset_auth_session_registry()


@pytest.fixture(autouse=True)
def setup_agent_pool() -> None:
    init_agent_pool(pool_size=2)


@pytest.fixture
async def async_client() -> httpx.AsyncClient:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
