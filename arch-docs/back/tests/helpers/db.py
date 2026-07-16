from __future__ import annotations

import os
import subprocess
import sys
import typing
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import sqlalchemy as sa
import sqlalchemy.exc
import sqlalchemy.ext.asyncio as async_sa

from app.db.models import Base

_TRUNCATE_DEADLOCK_RETRIES: typing.Final[int] = 3

REPO_ROOT: typing.Final[Path] = Path(__file__).resolve().parents[2]
DEFAULT_TEST_DATABASE_NAME: typing.Final[str] = "arch_docs_test"
DEFAULT_ADMIN_DATABASE_URL: typing.Final[str] = (
    "postgresql+asyncpg://arch_docs_test:arch_docs_test@localhost:5433/postgres"
)


def _replace_database_name(url: str, database_name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database_name}", parts.query, parts.fragment))


def resolve_test_database_urls() -> tuple[str, str, str]:
    admin_url = os.environ.get("TEST_DATABASE_ADMIN_URL", DEFAULT_ADMIN_DATABASE_URL)
    database_name = os.environ.get("TEST_DATABASE_NAME", DEFAULT_TEST_DATABASE_NAME)
    test_url = _replace_database_name(admin_url, database_name)
    return admin_url, test_url, database_name


async def check_admin_connection(admin_url: str) -> None:
    engine = async_sa.create_async_engine(admin_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
    finally:
        await engine.dispose()


async def recreate_test_database(admin_url: str, database_name: str) -> None:
    engine = async_sa.create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                sa.text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            await conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{database_name}"'))
            await conn.execute(sa.text(f'CREATE DATABASE "{database_name}"'))
    finally:
        await engine.dispose()


def run_alembic_upgrade_head(database_url: str) -> None:
    env = {**os.environ, "DATABASE_URL": database_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


async def truncate_all_tables(engine: async_sa.AsyncEngine) -> None:
    table_names = [table.name for table in Base.metadata.sorted_tables]
    if not table_names:
        return
    quoted = ", ".join(f'"{name}"' for name in table_names)
    async with engine.begin() as conn:
        await conn.execute(sa.text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
