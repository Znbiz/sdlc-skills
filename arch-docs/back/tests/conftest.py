import asyncio
import os
import typing

os.environ["AUTH_SECRET"] = "test-secret-token"  # noqa: S105

from tests.helpers.db import (
    check_admin_connection,
    recreate_test_database,
    resolve_test_database_urls,
    run_alembic_upgrade_head,
    truncate_all_tables,
)

_ADMIN_URL, _TEST_URL, _TEST_DATABASE_NAME = resolve_test_database_urls()
os.environ["DATABASE_URL"] = _TEST_URL

import httpx
import pytest
import sqlalchemy.ext.asyncio as async_sa

from app.db.session import get_engine, get_session, init_engine
from app.main import app
from app.services.agent_pool import init_agent_pool
from app.services.cli_auth_session import reset_auth_session_registry
from app.services.task_registry import reset_registry

_PREFLIGHT_HELP = (
    "arch-docs test suite требует запущенный Docker Postgres тестового контура. "
    "Поднимите его командой `just test-db-up` (эквивалент: "
    "`docker compose -f docker-compose.test.yml up -d --wait`) и повторите запуск pytest. "
    f"Исходная ошибка подключения к {_ADMIN_URL}: {{error}}"
)


@pytest.fixture(scope="session", autouse=True)
def _db_bootstrap() -> typing.Iterator[None]:
    try:
        asyncio.run(check_admin_connection(_ADMIN_URL))
    except Exception as exc:  # noqa: BLE001
        pytest.exit(_PREFLIGHT_HELP.format(error=exc), returncode=1)

    asyncio.run(recreate_test_database(_ADMIN_URL, _TEST_DATABASE_NAME))
    run_alembic_upgrade_head(_TEST_URL)

    # _db_enabled в app.services.task_runner остаётся выключенным по умолчанию:
    # сессия/движок/схема живые для всего suite, но task_runner-запись
    # включается точечно тестами, которые её проверяют (см. TestDbPersistence).
    engine = init_engine(_TEST_URL)

    yield

    asyncio.run(engine.dispose())


@pytest.fixture(autouse=True)
async def _truncate_tables_between_tests() -> typing.AsyncGenerator[None, None]:
    yield
    await truncate_all_tables(get_engine())


@pytest.fixture
async def db_session() -> typing.AsyncGenerator[async_sa.AsyncSession, None]:
    async with get_session() as session:
        yield session


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
