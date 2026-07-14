# Postgres-only Test Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести весь тестовый контур `arch-docs` на обязательную работу с реальной PostgreSQL в Docker: отдельная test database, схема только через `alembic upgrade head`, никакого SQLite/`AsyncSession`-мокинга как основного пути проверки persistence.

**Architecture:** Docker lifecycle тестового Postgres остаётся снаружи `pytest` (`docker-compose.test.yml` + `just test-db-up`). Обязательность БД enforced внутри `pytest`: session-scoped bootstrap-фикстура в `tests/conftest.py` проверяет доступность Postgres, пересоздаёт `arch_docs_test`, накатывает миграции через `alembic upgrade head`, инициализирует engine приложения и включает `_db_enabled`. Между тестами — `TRUNCATE ... RESTART IDENTITY CASCADE` через autouse-фикстуру function-scope.

**Tech Stack:** Python 3.14, pytest/pytest-asyncio (`asyncio_mode = "auto"`), PostgreSQL 16, Docker Compose, SQLAlchemy 2.x async (`asyncpg`), Alembic.

## Global Constraints

- `pytest` без доступного Docker Postgres завершается ошибкой preflight, а не silently fallback на SQLite/in-memory.
- Тестовая схема создаётся только через `alembic upgrade head`; `Base.metadata.create_all()` не используется.
- Test database (`arch_docs_test`) изолирована от dev/runtime БД `arch_docs`.
- Тесты, которые сейчас мокают `AsyncSession`/`get_session()`/используют `sqlite+aiosqlite:///:memory:`, переводятся на реальные SQL-запросы к Postgres либо удаляются.
- Моки остаются допустимы только для внешних систем, не относящихся к БД (subprocess/CLI, network, LLM worker, auth side effects, filesystem).
- `just test`, `just agent-check` и прямой `uv run pytest` используют один и тот же DB-backed bootstrap.
- Одна test database на один pytest process; xdist/параллельный shared-DB запуск не включается.
- Код и идентификаторы — на английском, комментарии по делу — на русском, commit-сообщения — на русском.

---

## File Structure

- **Create:** `arch-docs/docker-compose.test.yml` — изолированный test Postgres сервис на отдельном порту.
- **Create:** `arch-docs/tests/helpers/__init__.py`, `arch-docs/tests/helpers/db.py` — resolve URL, recreate database, alembic runner, truncate helper.
- **Create:** `arch-docs/tests/helpers/test_db.py` — unit-тесты чистых URL-функций из `tests/helpers/db.py`.
- **Modify:** `arch-docs/tests/conftest.py` — preflight, session bootstrap, cleanup fixture, `db_session` fixture.
- **Modify:** `arch-docs/justfile` — `test-db-up`/`test-db-down`, зависимость `test`/`agent-check` от `test-db-up`.
- **Modify:** `arch-docs/tests/db/test_session.py` — убрать SQLite path.
- **Modify:** `arch-docs/tests/db/test_task_repo.py` — реальные DB-assertions вместо `AsyncMock`.
- **Modify:** `arch-docs/tests/db/test_workflow_repo.py` — реальные DB-assertions вместо `AsyncMock`.
- **Modify:** `arch-docs/tests/services/test_task_runner.py` — `TestDbPersistence` на реальном Postgres.
- **Modify:** `arch-docs/tests/services/test_init_arch_workflow.py` — 3 теста, патчащих `get_session`, переведены на реальный Postgres.
- **Modify:** `arch-docs/tests/workflows/init_arch/test_audit.py` — `test_persist_event_swallows_storage_errors` переведён на call-site mock вместо мока сессии.
- **Modify:** `arch-docs/pyproject.toml` — убрать `aiosqlite` из dev-зависимостей.

---

### Task 1: Test Postgres compose service и just lifecycle

**Files:**
- Create: `arch-docs/docker-compose.test.yml`
- Modify: `arch-docs/justfile`
- Modify: `arch-docs/.env.example`

**Interfaces:**
- Produces: контейнер `postgres-test`, доступный на `localhost:5433`, admin-user `arch_docs_test`/`arch_docs_test`, admin database `postgres`. Именно эти значения — дефолт для `TEST_DATABASE_ADMIN_URL` в Task 2.

- [ ] **Step 1: Создать `docker-compose.test.yml`**

```yaml
services:
  postgres-test:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: postgres
      POSTGRES_USER: arch_docs_test
      POSTGRES_PASSWORD: arch_docs_test
    ports:
      - "5433:5432"
    tmpfs:
      - /var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U arch_docs_test"]
      interval: 2s
      timeout: 3s
      retries: 20
```

- [ ] **Step 2: Добавить lifecycle-команды и зависимости в `justfile`**

Заменить текущие рецепты `agent-check` и `test` (`arch-docs/justfile:3-25`) на:

```just
set dotenv-load

# Поднять test Postgres контейнер тестового контура
test-db-up:
    docker compose -f docker-compose.test.yml up -d --wait

# Остановить и удалить test Postgres контейнер
test-db-down:
    docker compose -f docker-compose.test.yml down -v

# Полная проверка: линтер + типы + тесты с покрытием
agent-check: test-db-up
    uv run --extra dev ruff check .
    uv run --extra dev ruff format --check .
    uv run --extra dev python -m pytest --cov=app --cov-fail-under=74 -x

# Автофикс линтера
agent-fix:
    uv run --extra dev ruff check --fix .
    uv run --extra dev ruff format .

# Автофикс только изменённых файлов
agent-fix-changed:
    #!/usr/bin/env bash
    changed=$(git diff --name-only HEAD | grep '\.py$' | tr '\n' ' ')
    if [ -n "$changed" ]; then
        uv run --extra dev ruff check --fix $changed
        uv run --extra dev ruff format $changed
    fi

# Запуск тестов (требует test Postgres контейнер)
test *args: test-db-up
    uv run --extra dev python -m pytest {{ args }}

# Запуск dev-сервера локально
dev:
    uv run granian --interface asgi app.main:app --host 0.0.0.0 --port 8000 --reload
```

- [ ] **Step 3: Задокументировать test-переменные окружения в `.env.example`**

Добавить в конец `arch-docs/.env.example`:

```
# Тестовый контур (arch_docs_test, поднимается docker-compose.test.yml)
TEST_DATABASE_ADMIN_URL=postgresql+asyncpg://arch_docs_test:arch_docs_test@localhost:5433/postgres
TEST_DATABASE_NAME=arch_docs_test
```

- [ ] **Step 4: Проверить, что контейнер поднимается**

Run: `cd arch-docs && docker compose -f docker-compose.test.yml up -d --wait`
Expected: контейнер `postgres-test` в состоянии `healthy`.

Run: `docker compose -f docker-compose.test.yml down -v`
Expected: контейнер и его данные удалены (tmpfs, том не персистентный).

- [ ] **Step 5: Commit**

```bash
git add arch-docs/docker-compose.test.yml arch-docs/justfile arch-docs/.env.example
git commit -m "feat(arch-docs): добавить test postgres контур и just-команды"
```

---

### Task 2: `tests/helpers/db.py` — DB bootstrap helpers

**Files:**
- Create: `arch-docs/tests/helpers/__init__.py`
- Create: `arch-docs/tests/helpers/db.py`
- Create: `arch-docs/tests/helpers/test_db.py`

**Interfaces:**
- Consumes: `app.db.models.Base` (`arch-docs/app/db/models.py:10`) для списка таблиц.
- Produces (используется в Task 3 `conftest.py`):
  - `resolve_test_database_urls() -> tuple[str, str, str]` → `(admin_url, test_url, database_name)`
  - `async def check_admin_connection(admin_url: str) -> None`
  - `async def recreate_test_database(admin_url: str, database_name: str) -> None`
  - `def run_alembic_upgrade_head(database_url: str) -> None`
  - `async def truncate_all_tables(engine: async_sa.AsyncEngine) -> None`

- [ ] **Step 1: Создать `arch-docs/tests/helpers/__init__.py`** (пустой файл)

- [ ] **Step 2: Написать падающий тест для чистой URL-функции**

`arch-docs/tests/helpers/test_db.py`:

```python
import os

from tests.helpers.db import DEFAULT_ADMIN_DATABASE_URL, DEFAULT_TEST_DATABASE_NAME, resolve_test_database_urls


def test_resolve_test_database_urls_uses_defaults_without_env(monkeypatch):
    monkeypatch.delenv("TEST_DATABASE_ADMIN_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_NAME", raising=False)

    admin_url, test_url, database_name = resolve_test_database_urls()

    assert admin_url == DEFAULT_ADMIN_DATABASE_URL
    assert database_name == DEFAULT_TEST_DATABASE_NAME
    assert test_url.endswith(f"/{DEFAULT_TEST_DATABASE_NAME}")
    assert test_url.startswith(admin_url.rsplit("/", 1)[0])


def test_resolve_test_database_urls_respects_env_overrides(monkeypatch):
    monkeypatch.setenv("TEST_DATABASE_ADMIN_URL", "postgresql+asyncpg://u:p@db-host:5433/postgres")
    monkeypatch.setenv("TEST_DATABASE_NAME", "custom_test_db")

    admin_url, test_url, database_name = resolve_test_database_urls()

    assert admin_url == "postgresql+asyncpg://u:p@db-host:5433/postgres"
    assert database_name == "custom_test_db"
    assert test_url == "postgresql+asyncpg://u:p@db-host:5433/custom_test_db"
```

- [ ] **Step 3: Запустить тест и убедиться, что он падает**

Run: `cd arch-docs && uv run --extra dev python -m pytest tests/helpers/test_db.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'tests.helpers.db'`

- [ ] **Step 4: Реализовать `arch-docs/tests/helpers/db.py`**

```python
from __future__ import annotations

import os
import subprocess
import sys
import typing
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import sqlalchemy as sa
import sqlalchemy.ext.asyncio as async_sa

from app.db.models import Base

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
    subprocess.run(  # noqa: S603
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
```

- [ ] **Step 5: Запустить тест и убедиться, что он проходит**

Run: `cd arch-docs && uv run --extra dev python -m pytest tests/helpers/test_db.py -v`
Expected: PASS (2 теста, оба не требуют реального соединения с БД)

- [ ] **Step 6: Commit**

```bash
git add arch-docs/tests/helpers
git commit -m "feat(arch-docs): добавить helpers для postgres test bootstrap"
```

---

### Task 3: `tests/conftest.py` — preflight, session bootstrap, cleanup

**Files:**
- Modify: `arch-docs/tests/conftest.py`

**Interfaces:**
- Consumes: `resolve_test_database_urls`, `check_admin_connection`, `recreate_test_database`, `run_alembic_upgrade_head`, `truncate_all_tables` (Task 2); `app.db.session.init_engine`, `app.db.session.get_engine`, `app.db.session.get_session` (`arch-docs/app/db/session.py`); `app.services.task_runner.set_db_enabled` (`arch-docs/app/services/task_runner.py:23`).
- Produces (используется всеми последующими тестами):
  - autouse session-scoped фикстура `_db_bootstrap` — падает с `pytest.exit` при недоступном Postgres, иначе пересоздаёт БД, катит миграции, инициализирует engine, включает `_db_enabled`.
  - autouse function-scoped фикстура `_truncate_tables_between_tests` — чистит все таблицы после каждого теста.
  - фикстура `db_session` — реальная `AsyncSession` для DB-layer тестов.

- [ ] **Step 1: Переписать `arch-docs/tests/conftest.py`**

```python
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
from app.services.task_runner import set_db_enabled

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

    engine = init_engine(_TEST_URL)
    set_db_enabled(True)

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
```

Важные детали реализации:
- `os.environ["DATABASE_URL"]` выставляется **до** `from app.main import app`, иначе `GatewaySettings` (закэшированный через `functools.lru_cache`, `arch-docs/app/settings.py:42-44`) захватит dev-URL.
- Cleanup — truncate **после** теста (`yield` в начале), а не до: это гарантирует чистое состояние независимо от порядка тестов и не требует truncate перед первым тестом (сразу после миграций БД уже пуста).
- `pytest.exit` в `_db_bootstrap` прерывает всю сессию сразу с понятным сообщением — соответствует критерию "падает без Docker Postgres".

- [ ] **Step 2: Убедиться, что Docker Postgres контейнер не поднят, и preflight падает понятно**

Run:
```bash
cd arch-docs
docker compose -f docker-compose.test.yml down -v 2>/dev/null
uv run --extra dev python -m pytest tests/test_settings.py -v
```
Expected: pytest завершается ошибкой с текстом, содержащим `just test-db-up` и `docker compose -f docker-compose.test.yml`.

- [ ] **Step 3: Поднять контейнер и убедиться, что bootstrap проходит**

Run:
```bash
just test-db-up
uv run --extra dev python -m pytest tests/test_settings.py -v
```
Expected: PASS, без ошибок подключения.

- [ ] **Step 4: Commit**

```bash
git add arch-docs/tests/conftest.py
git commit -m "feat(arch-docs): enforced postgres bootstrap в conftest"
```

---

### Task 4: `tests/db/test_session.py` — убрать SQLite path

**Files:**
- Modify: `arch-docs/tests/db/test_session.py`

**Interfaces:**
- Consumes: `resolve_test_database_urls` (Task 2), `app.db.session.get_engine`/`init_engine`.

- [ ] **Step 1: Переписать файл**

```python
import pytest

from app.db import session as db_session_module
from app.db.session import get_engine, init_engine
from tests.helpers.db import resolve_test_database_urls


def test_get_engine_raises_before_init():
    original = db_session_module._engine
    db_session_module._engine = None
    try:
        with pytest.raises(RuntimeError, match="not initialized"):
            get_engine()
    finally:
        db_session_module._engine = original


async def test_init_engine_sets_engine():
    _, test_url, _ = resolve_test_database_urls()
    original = db_session_module._engine
    try:
        engine = init_engine(test_url)
        assert engine is not None
        assert db_session_module._engine is engine
    finally:
        await db_session_module._engine.dispose()
        db_session_module._engine = original
```

Примечание: тест переинициализирует глобальный engine на время своего выполнения, но восстанавливает оригинальный `_engine` (тот, что создал session-scoped bootstrap) в `finally` — иначе последующие тесты в suite потеряют рабочий engine.

- [ ] **Step 2: Прогнать файл**

Run: `just test tests/db/test_session.py -v`
Expected: PASS (2 теста)

- [ ] **Step 3: Commit**

```bash
git add arch-docs/tests/db/test_session.py
git commit -m "test(arch-docs): убрать sqlite path из test_session"
```

---

### Task 5: `tests/db/test_task_repo.py` — реальный Postgres

**Files:**
- Modify: `arch-docs/tests/db/test_task_repo.py`

**Interfaces:**
- Consumes: фикстура `db_session` (Task 3); `app.db.models.CliTaskModel` (`arch-docs/app/db/models.py:14-45`); `app.db.task_repo.upsert_cli_task`/`mark_running_tasks_failed` (`arch-docs/app/db/task_repo.py`).

- [ ] **Step 1: Переписать файл**

```python
import datetime
import uuid

import pytest

from app.db.models import CliTaskModel
from app.db.task_repo import mark_running_tasks_failed, upsert_cli_task
from app.services.task_registry import CliTask, TaskStatus


def _make_cli_task(**kwargs) -> CliTask:
    defaults = dict(
        task_id=str(uuid.uuid4()),
        engine_name="claude",
        prompt_text="test prompt",
        workspace_dir="/workspace",
    )
    defaults.update(kwargs)
    return CliTask(**defaults)


async def test_upsert_creates_new_record(db_session):
    cli_task = _make_cli_task()

    await upsert_cli_task(db_session, cli_task)

    persisted = await db_session.get(CliTaskModel, uuid.UUID(cli_task.task_id))
    assert persisted is not None
    assert persisted.engine_name == "claude"
    assert persisted.task_status == "pending"
    assert persisted.prompt_text == "test prompt"
    assert persisted.workspace_dir == "/workspace"


async def test_upsert_updates_existing_record(db_session):
    task_id = uuid.uuid4()
    db_session.add(
        CliTaskModel(
            task_id=task_id,
            engine_name="claude",
            task_status="pending",
            prompt_text="p",
            workspace_dir="/w",
        )
    )
    await db_session.commit()

    cli_task = _make_cli_task(
        task_id=str(task_id),
        task_status=TaskStatus.SUCCESS,
        task_result="done",
    )
    await upsert_cli_task(db_session, cli_task)

    persisted = await db_session.get(CliTaskModel, task_id)
    assert persisted.task_status == "success"
    assert persisted.task_result == "done"


async def test_upsert_includes_stdout(db_session):
    cli_task = _make_cli_task(
        workflow_id="wf-1",
        step_id="define_scope",
        repository_name="repo-a",
        domain_id="billing",
        expected_schema_name="init_arch_v1",
    )
    cli_task.stdout_lines = ["line1", "line2"]
    cli_task.stderr_lines = ["warn1"]
    cli_task.exit_code = 7

    await upsert_cli_task(db_session, cli_task)

    persisted = await db_session.get(CliTaskModel, uuid.UUID(cli_task.task_id))
    assert persisted.stdout_output == "line1\nline2"
    assert persisted.stderr_output == "warn1"
    assert persisted.exit_code == 7
    assert persisted.workflow_id == "wf-1"
    assert persisted.step_id == "define_scope"
    assert persisted.repository_name == "repo-a"
    assert persisted.domain_id == "billing"
    assert persisted.expected_schema_name == "init_arch_v1"


async def test_upsert_empty_stdout_is_none(db_session):
    cli_task = _make_cli_task()
    cli_task.stdout_lines = []

    await upsert_cli_task(db_session, cli_task)

    persisted = await db_session.get(CliTaskModel, uuid.UUID(cli_task.task_id))
    assert persisted.stdout_output is None


async def test_mark_running_tasks_failed(db_session):
    now = datetime.datetime.now(datetime.timezone.utc)
    db_session.add_all(
        [
            CliTaskModel(
                task_id=uuid.uuid4(),
                engine_name="claude",
                task_status="pending",
                prompt_text="p1",
                workspace_dir="/w",
                created_at=now,
            ),
            CliTaskModel(
                task_id=uuid.uuid4(),
                engine_name="claude",
                task_status="running",
                prompt_text="p2",
                workspace_dir="/w",
                created_at=now,
            ),
            CliTaskModel(
                task_id=uuid.uuid4(),
                engine_name="claude",
                task_status="success",
                prompt_text="p3",
                workspace_dir="/w",
                created_at=now,
            ),
        ]
    )
    await db_session.commit()

    count = await mark_running_tasks_failed(db_session)

    assert count == 2
    remaining_success = await db_session.get(CliTaskModel, None) if False else None  # noqa: SIM108
    from sqlalchemy import select

    result = await db_session.execute(select(CliTaskModel).where(CliTaskModel.task_status == "failed"))
    failed_rows = result.scalars().all()
    assert len(failed_rows) == 2
    assert all(row.task_error == "Service restarted" for row in failed_rows)


async def test_upsert_masks_and_truncates_persisted_audit_payloads(db_session, monkeypatch):
    from app.settings import GatewaySettings

    monkeypatch.setattr(
        "app.db.task_repo.get_gateway_settings",
        lambda: GatewaySettings(
            auth_secret="secret",
            audit={
                "max_prompt_chars": 40,
                "max_output_chars": 40,
                "max_error_chars": 32,
            },
        ),
    )
    cli_task = _make_cli_task(
        prompt_text="prefix AUTH_TOKEN=abcdef1234567890 suffix trailing words",
        task_result="Authorization: Bearer secret-token suffix trailing words",
        task_error="DB_PASSWORD=supersecret suffix trailing words",
    )
    cli_task.stdout_lines = ["Authorization: Bearer secret-token suffix trailing words"]
    cli_task.stderr_lines = ["prefix API_KEY=abcdef1234567890 suffix"]

    await upsert_cli_task(db_session, cli_task)

    persisted = await db_session.get(CliTaskModel, uuid.UUID(cli_task.task_id))
    assert "[REDACTED]" in persisted.prompt_text
    assert persisted.prompt_text.endswith("...[truncated]")
    assert "[REDACTED]" in persisted.task_result
    assert persisted.task_result.endswith("...[truncated]")
    assert "[REDACTED]" in persisted.task_error
    assert persisted.task_error.endswith("...[truncated]")
    assert "[REDACTED]" in persisted.stdout_output
    assert persisted.stdout_output.endswith("...[truncated]")
    assert "[REDACTED]" in persisted.stderr_output
```

Убрать закомментированный мусор из черновика (`remaining_success = ...`) при финальной вставке — оставить только реальный `select`-запрос.

- [ ] **Step 2: Прогнать файл**

Run: `just test tests/db/test_task_repo.py -v`
Expected: PASS (6 тестов)

- [ ] **Step 3: Commit**

```bash
git add arch-docs/tests/db/test_task_repo.py
git commit -m "test(arch-docs): перевести test_task_repo на реальный postgres"
```

---

### Task 6: `tests/db/test_workflow_repo.py` — реальный Postgres

**Files:**
- Modify: `arch-docs/tests/db/test_workflow_repo.py`

**Interfaces:**
- Consumes: `db_session` (Task 3); модели из `app/db/models.py`; функции из `app/db/workflow_repo.py`.

- [ ] **Step 1: Переписать DB-зависимые тесты, сохранив pure-function тесты без изменений**

```python
from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from app.db.models import (
    ArtifactEventModel,
    ConversationItemModel,
    ConversationModel,
    WorkflowRunModel,
    WorkflowStepTransitionModel,
)
from app.db.workflow_repo import (
    _build_artifact_event_model,
    _build_required_actions,
    _session_payload,
    append_workflow_event,
    create_conversation,
    get_workflow_run,
    list_conversation_items,
    mark_running_workflows_failed,
    upsert_workflow_run,
)
from app.services.workflow_registry import WorkflowRecord, WorkflowStatus
from app.workflows.init_arch.domain import (
    AuditActor,
    EventType,
    OpenQuestionRecord,
    StepId,
    WorkflowEventRecord,
    WorkflowSessionRecord,
)


async def test_upsert_workflow_run_creates_conversation_and_actions(db_session):
    record = WorkflowRecord(
        workflow_id="wf-1",
        conversation_id="conv-1",
        workflow_status=WorkflowStatus.INTERRUPTED,
        current_step_id="interview_user",
        pending_interrupt={"interrupt_type": "user_question", "question_id": "Q-1", "question": "Need details?"},
        session=WorkflowSessionRecord(
            session_id="wf-1",
            product_name="arch-docs",
            analysis_scope="full",
            current_step=StepId.INTERVIEW_USER,
            open_questions=[OpenQuestionRecord(question_id="Q-1", question_text="Need details?")],
        ),
    )

    await upsert_workflow_run(db_session, record)

    conversation = await db_session.get(ConversationModel, "conv-1")
    workflow_run = await db_session.get(WorkflowRunModel, "wf-1")
    assert conversation is not None
    assert workflow_run is not None
    assert workflow_run.workflow_status == "interrupted"
    required_actions = (
        await db_session.execute(sa.text('SELECT count(*) FROM required_actions WHERE workflow_id = :wid'), {"wid": "wf-1"})
    ).scalar_one()
    assert required_actions == 1


async def test_upsert_workflow_run_persists_step_transition_record(db_session):
    record = WorkflowRecord(
        workflow_id="wf-1",
        conversation_id="conv-1",
        workflow_status=WorkflowStatus.RUNNING,
        current_step_id="request_repository_list",
        completed_steps=["define_scope"],
    )

    await upsert_workflow_run(db_session, record)

    result = await db_session.execute(
        sa.select(WorkflowStepTransitionModel).where(WorkflowStepTransitionModel.workflow_id == "wf-1")
    )
    step_transition = result.scalar_one()
    assert step_transition.conversation_id == "conv-1"
    assert step_transition.previous_step_id is None
    assert step_transition.current_step_id == "request_repository_list"
    assert step_transition.completed_steps == ["define_scope"]


async def test_append_workflow_event_writes_conversation_item(db_session):
    event = WorkflowEventRecord(
        event_type=EventType.GUARD_COMMAND_APPLIED,
        actor=AuditActor.SERVICE,
        session_id="wf-1",
        step_id=StepId.DEFINE_SCOPE,
        payload={"command": "init"},
    )

    await append_workflow_event(db_session, event)

    result = await db_session.execute(
        sa.select(ConversationItemModel).where(ConversationItemModel.workflow_id == "wf-1")
    )
    item = result.scalar_one()
    assert item.item_kind == "guard_command_applied"
    assert item.conversation_id == "wf-1"


async def test_append_workflow_event_persists_artifact_event_record(db_session):
    event = WorkflowEventRecord(
        event_type=EventType.ARTIFACT_WRITTEN,
        actor=AuditActor.SERVICE,
        session_id="wf-1",
        step_id=StepId.REFINE_FEATURES,
        payload={"artifact_path": "wiki/index.md", "artifact_kind": "navigation_artifact"},
    )

    await append_workflow_event(db_session, event)

    result = await db_session.execute(
        sa.select(ArtifactEventModel).where(ArtifactEventModel.workflow_id == "wf-1")
    )
    artifact_event = result.scalar_one()
    assert artifact_event.event_type == "artifact_written"
    assert artifact_event.artifact_path == "wiki/index.md"
    assert artifact_event.artifact_kind == "navigation_artifact"
    assert artifact_event.step_id == "refine_features"


async def test_get_workflow_run_deserializes_session(db_session):
    record = WorkflowRecord(
        workflow_id="wf-1",
        conversation_id="conv-1",
        workflow_status=WorkflowStatus.INTERRUPTED,
        current_step_id="interview_user",
        completed_steps=["define_scope"],
        session=WorkflowSessionRecord(
            session_id="wf-1",
            product_name="arch-docs",
            analysis_scope="full",
            current_step=StepId.INTERVIEW_USER,
            completed_steps=[StepId.DEFINE_SCOPE],
        ),
        pending_interrupt={"interrupt_type": "user_question"},
    )
    await upsert_workflow_run(db_session, record)

    resolved = await get_workflow_run(db_session, "wf-1")

    assert resolved is not None
    assert resolved.conversation_id == "conv-1"
    assert resolved.session is not None
    assert resolved.session.current_step is StepId.INTERVIEW_USER


async def test_mark_running_workflows_failed_returns_count(db_session):
    for workflow_id, conversation_id in [("wf-1", "conv-1"), ("wf-2", "conv-2")]:
        db_session.add(ConversationModel(conversation_id=conversation_id))
        db_session.add(
            WorkflowRunModel(
                workflow_id=workflow_id,
                conversation_id=conversation_id,
                workflow_status=str(WorkflowStatus.RUNNING),
                current_step_id="define_scope",
            )
        )
    await db_session.commit()

    count = await mark_running_workflows_failed(db_session)

    assert count == 2
    for workflow_id in ["wf-1", "wf-2"]:
        run = await db_session.get(WorkflowRunModel, workflow_id)
        assert run.workflow_status == str(WorkflowStatus.FAILED)
    conversation_items = (
        await db_session.execute(
            sa.select(sa.func.count()).select_from(ConversationItemModel).where(
                ConversationItemModel.item_kind == "workflow_status_changed"
            )
        )
    ).scalar_one()
    assert conversation_items == 2


def test_session_payload_returns_none_for_missing_session():
    assert _session_payload(None) is None


def test_build_required_actions_merges_interrupt_and_open_questions():
    record = WorkflowRecord(
        workflow_id="wf-actions",
        conversation_id="conv-actions",
        workflow_status=WorkflowStatus.INTERRUPTED,
        pending_interrupt={"interrupt_type": "user_question", "question_id": "Q-1"},
        session=WorkflowSessionRecord(
            session_id="wf-actions",
            product_name="arch-docs",
            analysis_scope="full",
            current_step=StepId.INTERVIEW_USER,
            open_questions=[
                OpenQuestionRecord(question_id="Q-1", question_text="duplicate"),
                OpenQuestionRecord(question_id="Q-2", question_text="new"),
            ],
        ),
    )

    actions = _build_required_actions(record, conversation_id="conv-actions")

    assert [action.question_id for action in actions] == ["Q-1", "Q-2"]


def test_build_artifact_event_model_returns_none_for_irrelevant_or_invalid_events():
    ignored_event = WorkflowEventRecord(
        event_type=EventType.GUARD_COMMAND_APPLIED,
        actor=AuditActor.SERVICE,
        session_id="wf-1",
        step_id=StepId.DEFINE_SCOPE,
        payload={},
    )
    invalid_event = WorkflowEventRecord(
        event_type=EventType.ARTIFACT_WRITTEN,
        actor=AuditActor.SERVICE,
        session_id="wf-1",
        step_id=StepId.DEFINE_SCOPE,
        payload={"artifact_path": "wiki/index.md"},
    )

    assert _build_artifact_event_model(ignored_event, conversation_id="conv-1") is None
    assert _build_artifact_event_model(invalid_event, conversation_id="conv-1") is None


async def test_append_workflow_event_ignores_missing_session_id(db_session):
    event = WorkflowEventRecord(
        event_type=EventType.GUARD_COMMAND_APPLIED,
        actor=AuditActor.SERVICE,
        session_id="",
        step_id=StepId.DEFINE_SCOPE,
        payload={},
    )

    await append_workflow_event(db_session, event)

    count = (await db_session.execute(sa.select(sa.func.count()).select_from(ConversationItemModel))).scalar_one()
    assert count == 0


async def test_create_conversation_returns_existing_conversation(db_session):
    existing = ConversationModel(conversation_id="conv-1")
    db_session.add(existing)
    await db_session.commit()
    original_created_at = existing.created_at

    conversation = await create_conversation(db_session, conversation_id="conv-1")

    assert conversation.conversation_id == "conv-1"
    assert conversation.created_at == original_created_at


async def test_list_conversation_items_returns_empty_without_filters(db_session):
    items = await list_conversation_items(db_session)

    assert items == []
```

Убрать неиспользуемый импорт `uuid`, если он не понадобится (используется только имплицитно через модели — при финальной вставке проверить `ruff check`).

- [ ] **Step 2: Прогнать файл**

Run: `just test tests/db/test_workflow_repo.py -v`
Expected: PASS (12 тестов)

- [ ] **Step 3: Commit**

```bash
git add arch-docs/tests/db/test_workflow_repo.py
git commit -m "test(arch-docs): перевести test_workflow_repo на реальный postgres"
```

---

### Task 7: `tests/services/test_task_runner.py` — `TestDbPersistence` на реальном Postgres

**Files:**
- Modify: `arch-docs/tests/services/test_task_runner.py:307-371` (класс `TestDbPersistence`)

**Interfaces:**
- Consumes: `db_session` (Task 3); `app.db.models.CliTaskModel`; `app.services.task_runner.set_db_enabled`/`run_cli_task`.

- [ ] **Step 1: Заменить класс `TestDbPersistence`**

Убрать импорт `unittest.mock.AsyncMock`-контекста сессии там, где он не нужен; оставить только реальные assertions. Новая версия класса (заменяет `arch-docs/tests/services/test_task_runner.py:307-371`):

```python
class TestDbPersistence:
    def setup_method(self) -> None:
        set_db_enabled(False)

    def teardown_method(self) -> None:
        set_db_enabled(True)

    def test_set_db_enabled_toggles(self) -> None:
        set_db_enabled(True)
        assert task_runner_module._db_enabled is True  # type: ignore[attr-defined]
        set_db_enabled(False)
        assert task_runner_module._db_enabled is False  # type: ignore[attr-defined]

    async def test_run_cli_task_calls_upsert_when_db_enabled(self, db_session) -> None:
        from app.db.models import CliTaskModel

        set_db_enabled(True)
        cli_task = _make_task(engine_name="claude")
        pool = _make_pool()
        mock_proc = _make_mock_process(returncode=0, stdout=b"ok", stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await run_cli_task(cli_task, pool)

        persisted = await db_session.get(CliTaskModel, uuid.UUID(cli_task.task_id))
        assert persisted is not None
        assert persisted.task_status == "success"

    async def test_run_cli_task_skips_upsert_when_db_disabled(self, db_session) -> None:
        from app.db.models import CliTaskModel

        set_db_enabled(False)
        cli_task = _make_task(engine_name="claude")
        pool = _make_pool()
        mock_proc = _make_mock_process(returncode=0, stdout=b"ok", stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await run_cli_task(cli_task, pool)

        persisted = await db_session.get(CliTaskModel, uuid.UUID(cli_task.task_id))
        assert persisted is None

    async def test_run_cli_task_survives_db_error(self) -> None:
        set_db_enabled(True)
        cli_task = _make_task(engine_name="claude")
        pool = _make_pool()
        mock_proc = _make_mock_process(returncode=0, stdout=b"ok", stderr=b"")

        with (
            unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            unittest.mock.patch(
                "app.services.task_runner.upsert_cli_task",
                new=unittest.mock.AsyncMock(side_effect=RuntimeError("db down")),
            ),
        ):
            await run_cli_task(cli_task, pool)  # не должно бросить
```

Ключевое изменение: `test_run_cli_task_survives_db_error` больше не мокает `get_session`/`AsyncSession` — вместо этого патчится `upsert_cli_task` (call-site вызываемой функции), а реальный `get_session()` подключается к настоящей test database. Это тестирует устойчивость orchestration-кода к ошибке персистентности, а не саму персистентность, поэтому не подпадает под запрет мокать DB-слой.

`teardown_method` теперь возвращает `_db_enabled` в `True` (а не `False`), потому что глобальный bootstrap в `conftest.py` включает `_db_enabled=True` на всю сессию — тест не должен ломать это состояние для последующих тестов.

- [ ] **Step 2: Прогнать файл**

Run: `just test tests/services/test_task_runner.py -v`
Expected: PASS (все тесты класса, включая ранее существующие)

- [ ] **Step 3: Commit**

```bash
git add arch-docs/tests/services/test_task_runner.py
git commit -m "test(arch-docs): TestDbPersistence на реальном postgres"
```

---

### Task 8: `tests/services/test_init_arch_workflow.py` — 3 DB-теста на реальном Postgres

**Files:**
- Modify: `arch-docs/tests/services/test_init_arch_workflow.py` (тесты на строках 32-47, 50-86, 178-207)

**Interfaces:**
- Consumes: `db_session` (Task 3); `app.db.workflow_repo.upsert_workflow_run`/`append_workflow_event`.

- [ ] **Step 1: Заменить `test_get_workflow_record_async_loads_from_db_when_registry_empty`**

```python
async def test_get_workflow_record_async_loads_from_db_when_registry_empty(db_session):
    from app.db.workflow_repo import upsert_workflow_run

    record = WorkflowRecord(workflow_id="wf-db", conversation_id="wf-db")
    await upsert_workflow_run(db_session, record)

    resolved = await workflow_module.get_workflow_record_async("wf-db")

    assert resolved.workflow_id == "wf-db"
    assert workflow_module.get_workflow_registry()["wf-db"] is resolved
```

- [ ] **Step 2: Заменить `test_answer_init_arch_question_loads_interrupted_record_from_db`**

```python
async def test_answer_init_arch_question_loads_interrupted_record_from_db(db_session):
    from app.db.workflow_repo import upsert_workflow_run

    record = WorkflowRecord(
        workflow_id="wf-db-question",
        conversation_id="conv-db-question",
        workflow_status=WorkflowStatus.INTERRUPTED,
        current_step_id="interview_user",
        pending_interrupt={
            "interrupt_type": "user_question",
            "question_id": "Q-7",
            "question": "What transport?",
        },
        session=WorkflowSessionRecord(
            session_id="wf-db-question",
            product_name="arch-docs",
            analysis_scope="full",
            current_step=StepId.INTERVIEW_USER,
            open_questions=[OpenQuestionRecord(question_id="Q-7", question_text="What transport?")],
        ),
    )
    await upsert_workflow_run(db_session, record)

    with (
        patch("app.services.init_arch_workflow.schedule_resume") as mock_schedule_resume,
        patch("app.services.init_arch_workflow.persist_workflow_record", new=AsyncMock()) as mock_persist,
    ):
        resolved = await workflow_module.answer_init_arch_question("wf-db-question", question_id="Q-7", answer="REST")

    assert resolved.workflow_id == "wf-db-question"
    mock_schedule_resume.assert_called_once()
    assert mock_schedule_resume.call_args.kwargs["resume_value"] == {"answer": "REST"}
    mock_persist.assert_awaited_once()
    assert workflow_module.get_workflow_registry()["wf-db-question"] is resolved
```

Изменение assertion со `assert_called_once_with(record, ...)` на проверку `call_args` без сравнения объекта `record`: после загрузки из БД `resolved` — новый десериализованный объект, не тот же `record`, который мы построили для setup, поэтому сравнение по идентичности больше не применимо.

- [ ] **Step 3: Заменить `test_list_workflow_events_async_reads_persisted_conversation_items`**

```python
async def test_list_workflow_events_async_reads_persisted_conversation_items(db_session):
    from app.db.workflow_repo import append_workflow_event
    from app.workflows.init_arch.domain import EventType, WorkflowEventRecord

    event = WorkflowEventRecord(
        event_type=EventType.ARTIFACT_WRITTEN,
        actor=AuditActor.SERVICE,
        session_id="wf-events",
        step_id=StepId.REFINE_FEATURES,
        payload={"artifact_path": "wiki/index.md", "artifact_kind": "navigation_artifact"},
    )
    await append_workflow_event(db_session, event)

    events = await workflow_module.list_workflow_events_async("wf-events")

    assert len(events) == 1
    assert events[0]["item_kind"] == "artifact_written"
    assert events[0]["actor"] == "service"
    assert events[0]["step_id"] == "refine_features"
    assert events[0]["payload"]["artifact_path"] == "wiki/index.md"
```

Добавить недостающий импорт `AuditActor` в начало файла, если его ещё нет (проверить текущий блок импортов `arch-docs/tests/services/test_init_arch_workflow.py:1-13` — там уже нет `AuditActor`, добавить его в `from app.workflows.init_arch.domain import (...)`).

- [ ] **Step 4: Прогнать файл**

Run: `just test tests/services/test_init_arch_workflow.py -v`
Expected: PASS (все тесты файла)

- [ ] **Step 5: Commit**

```bash
git add arch-docs/tests/services/test_init_arch_workflow.py
git commit -m "test(arch-docs): db-тесты init_arch_workflow на реальном postgres"
```

---

### Task 9: `tests/workflows/init_arch/test_audit.py` — call-site mock вместо мока сессии

**Files:**
- Modify: `arch-docs/tests/workflows/init_arch/test_audit.py:36-47`

**Interfaces:**
- Consumes: `app.workflows.init_arch.audit.WorkflowAuditService._persist_event`.

- [ ] **Step 1: Заменить `test_persist_event_swallows_storage_errors`**

```python
async def test_persist_event_swallows_storage_errors():
    service = WorkflowAuditService()

    with patch(
        "app.workflows.init_arch.audit.append_workflow_event",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        await service._persist_event(_event())  # не должно бросить
```

`get_session` больше не мокается — реальный engine из session bootstrap подключается к test database, а ошибку симулирует `append_workflow_event`, что тестирует именно устойчивость `_persist_event` к сбою записи, а не саму персистентность. Импорты `asynccontextmanager`/`MagicMock` в начале файла (`arch-docs/tests/workflows/init_arch/test_audit.py:3-6`) можно оставить как есть — `MagicMock` больше не используется в этом тесте, но остаётся нужен для остальных, если применяется где-то ещё в файле; проверить неиспользуемые импорты через `ruff check` на Step 2 и убрать при необходимости.

- [ ] **Step 2: Прогнать файл и линтер**

Run: `just test tests/workflows/init_arch/test_audit.py -v`
Expected: PASS (5 тестов)

Run: `cd arch-docs && uv run --extra dev ruff check tests/workflows/init_arch/test_audit.py`
Expected: без ошибок неиспользуемых импортов (при необходимости убрать `asynccontextmanager`/`MagicMock`, если больше нигде не используются в файле).

- [ ] **Step 3: Commit**

```bash
git add arch-docs/tests/workflows/init_arch/test_audit.py
git commit -m "test(arch-docs): test_audit без мока db-сессии"
```

---

### Task 10: Убрать `aiosqlite` из зависимостей

**Files:**
- Modify: `arch-docs/pyproject.toml:29`

**Interfaces:** нет — чисто удаление больше не нужной dev-зависимости.

- [ ] **Step 1: Убедиться, что `aiosqlite` больше нигде не используется**

Run: `cd arch-docs && grep -rn "aiosqlite\|sqlite" app tests --include="*.py" 2>/dev/null || grep -rln "aiosqlite\|sqlite" app tests`
Expected: пусто (после Task 4 все упоминания SQLite удалены)

- [ ] **Step 2: Удалить строку из `pyproject.toml`**

В `arch-docs/pyproject.toml` в секции `[project.optional-dependencies].dev` (строки 21-30) удалить строку `"aiosqlite>=0.20.0",`.

- [ ] **Step 3: Обновить lock-файл**

Run: `cd arch-docs && uv lock`
Expected: `uv.lock` обновлён, `aiosqlite` исчезает из графа зависимостей.

- [ ] **Step 4: Переустановить окружение и прогнать полный suite**

Run: `cd arch-docs && uv sync --extra dev && just agent-check`
Expected: PASS — линтер, форматирование и весь test suite (включая coverage gate `--cov-fail-under=74`) зелёные.

- [ ] **Step 5: Commit**

```bash
git add arch-docs/pyproject.toml arch-docs/uv.lock
git commit -m "chore(arch-docs): убрать aiosqlite после перехода на postgres-only тесты"
```

---

### Task 11: Финальная сквозная проверка

**Files:** нет изменений, только верификация.

- [ ] **Step 1: Проверить полный сценарий "нет Docker → падение"**

Run:
```bash
cd arch-docs
docker compose -f docker-compose.test.yml down -v
uv run --extra dev python -m pytest
```
Expected: FAIL с понятным preflight-сообщением (см. Task 3), без попытки создать SQLite или замокать БД.

- [ ] **Step 2: Проверить полный сценарий "есть Docker → успех" через все три входные точки**

Run:
```bash
just test
just agent-check
just test-db-up  # уже поднят предыдущими шагами — идемпотентно
uv run --extra dev python -m pytest -v
```
Expected: все три пути зелёные и используют один и тот же bootstrap (видно по одинаковому времени старта suite — session bootstrap логируется один раз на процесс).

- [ ] **Step 3: Проверить точечный запуск одного теста без ручной подготовки**

Run: `cd arch-docs && uv run --extra dev python -m pytest tests/db/test_task_repo.py -k test_upsert_creates_new_record -v`
Expected: PASS, schema уже смигрирована предыдущим запуском suite или создаётся заново bootstrap-фикстурой этого процесса.

- [ ] **Step 4: Проверить детерминированность cleanup между тестами**

Run: `cd arch-docs && uv run --extra dev python -m pytest tests/db -v` (дважды подряд)
Expected: оба прогона PASS с одинаковым результатом — truncate между тестами не оставляет данных, влияющих на следующий тест.

- [ ] **Step 5: Финальный `just test-db-down` для чистоты**

Run: `cd arch-docs && just test-db-down`
Expected: контейнер и tmpfs-данные удалены.

---

## Self-Review

**Spec coverage:**
- Preflight-падение без Docker Postgres → Task 3, Step 2; Task 11, Step 1.
- Fresh test database + `alembic upgrade head` → Task 2 (`recreate_test_database`, `run_alembic_upgrade_head`), Task 3 (`_db_bootstrap`).
- Изоляция test/dev БД → Task 1 (отдельный порт 5433, отдельный контейнер), Task 2 (отдельное имя `arch_docs_test`).
- Truncate cleanup между тестами → Task 2 (`truncate_all_tables`), Task 3 (`_truncate_tables_between_tests`).
- Перевод DB-layer тестов (класс 1) → Task 4, 5, 6.
- Перевод service/API тестов, зависящих от persisted state (класс 2) → Task 7, 8, 9.
- Класс 3 (не-DB тесты) под тем же bootstrap → достигается автоматически через autouse-фикстуры в Task 3, отдельных задач не требует.
- Единый механизм для `just test`/`just agent-check`/`uv run pytest` → Task 1, Step 2 (`test`/`agent-check` зависят от `test-db-up`; preflight в conftest покрывает прямой `uv run pytest`).
- Запрет xdist для shared-DB → не добавляется `-n auto` нигде в плане, явно фиксируется в Global Constraints.
- Удаление SQLite backend полностью → Task 4, Task 10.

**Placeholder scan:** пройден — каждый шаг содержит конкретный код/команду/ожидаемый результат, нет "TBD"/"добавить обработку ошибок"/ссылок на "аналогично Task N" без кода.

**Type consistency:** `resolve_test_database_urls`, `check_admin_connection`, `recreate_test_database`, `run_alembic_upgrade_head`, `truncate_all_tables` объявлены в Task 2 и используются с теми же именами и сигнатурами в Task 3. Фикстуры `db_session`, `_db_bootstrap`, `_truncate_tables_between_tests` объявлены в Task 3 и используются в Task 4-9 без переименований.

---

## Execution Handoff

Plan complete and saved to `arch-docs/docs/superpowers/plans/2026-07-14-postgres-only-test-harness.md`. Два варианта выполнения:

1. **Subagent-Driven (рекомендуется)** — я запускаю отдельного subagent на каждую задачу, ревью между задачами, быстрая итерация.
2. **Inline Execution** — выполняю задачи в этой сессии через executing-plans, батчами с чекпоинтами.

Какой подход выбираете?
