# Техническое задание: Arch Docs Service

## 1. Общее описание

**Название проекта:** Arch Docs Service  
**Назначение:** Веб-сервис, предоставляющий HTTP/WebSocket API поверх CLI-инструментов (`codex exec` / `claude -p`) запущенных внутри Docker-контейнера. Пользователь авторизует CLI один раз, сессия сохраняется в volume, последующие запросы через FastAPI выполняются в контейнере без повторной авторизации.

***

## 2. Контекст и мотивация

CLI-инструменты OpenAI Codex и Claude Code поддерживают неинтерактивный (`headless`) режим, что позволяет встраивать их в автоматизированные пайплайны. Codex CLI поддерживает флаг `codex exec` с потоковым выводом через stderr и финальным ответом в stdout. Claude Code поддерживает `-p` / `--print` для неинтерактивного запуска с опциями форматов вывода `text`, `json`, `stream-json`.

**Ключевое требование:** оба инструмента работают через подписочную авторизацию (ChatGPT Plus/Pro для Codex, Claude Pro/Max для Claude Code) — без API-ключей, которые оплачиваются отдельно по токенам. Авторизация выполняется один раз через OAuth/device-auth flow, сессионные токены сохраняются в named Docker volume и переживают рестарты контейнера.

***

## 3. Цели и границы проекта

**В скоупе:**
- Dockerfile с установленными CLI (`@openai/codex` и/или `@anthropic-ai/claude-code`)
- FastAPI-сервис внутри контейнера с REST + WebSocket эндпоинтами
- Механизм авторизации CLI с сохранением сессии через volume
- **API-инициация авторизации** в Claude Code и Codex без API-токенов (OAuth/device-auth flow через API-эндпоинт сервиса)
- Управление задачами: запуск, отмена, получение статуса/результата
- **Хранение всех сессий (запуск задач, вывод, статусы) в PostgreSQL**
- **Пул агентов**: управление пулом экземпляров Claude Code / Codex для параллельного выполнения задач
- Streaming вывода через WebSocket
- MCP-сервер: инструменты `init_arch`, `update_arch`, `query`
- Легковесный фронтенд (опционально)

**Вне скоупа:**

- Multi-tenant изоляция (разные пользователи с разными аккаунтами)
- Биллинг и квоты

***

## 4. Архитектура системы

```
┌───────────────────────────────────────────────────────────────────┐
│                         Host Machine                              │
│                                                                   │
│  ┌─────────────┐   HTTP/WS   ┌──────────────────────────────┐    │
│  │  Web Client  │ ──────────► │   Nginx (reverse proxy)      │    │
│  └─────────────┘             └──────────────┬───────────────┘    │
│                                             │                     │
│                              ┌──────────────▼───────────────┐    │
│                              │      Docker Container         │    │
│                              │                               │    │
│                              │  ┌─────────────────────────┐ │    │
│                              │  │  FastAPI (granian :8000) │ │    │
│                              │  │  + MCP SSE /api/mcp/     │ │    │
│                              │  └──────────┬──────────────┘ │    │
│                              │             │ subprocess      │    │
│                              │  ┌──────────▼──────────────┐ │    │
│                              │  │  Agent Pool              │ │    │
│                              │  │  codex exec / claude -p  │ │    │
│                              │  │  (несколько параллельных) │ │    │
│                              │  └──────────┬──────────────┘ │    │
│                              │             │                 │    │
│                              └─────────────┼─────────────────┘    │
│                                            │                      │
│  ┌─────────────────────────────────────────┘                      │
│  │         Named Docker Volumes / Services                        │
│  │  codex-auth  → /home/appuser/.codex                            │
│  │  claude-auth → /home/appuser/.claude                           │
│  │  workspace   → /workspace                                      │
│  │  PostgreSQL  → сессии задач, прогресс воркфлоу                 │
│  └────────────────────────────────────────────────────────────────┘
```

### Технологический стек

| Слой | Технология | Обоснование |
|------|-----------|-------------|
| Runtime | Python 3.14+ + Node.js 22 | FastAPI требует Python 3.14+ (pylines); Codex CLI — Node.js |
| Пакетный менеджер | `uv` | Стандарт pylines; `pyproject.toml` вместо `requirements.txt` |
| Web-фреймворк | FastAPI | Async, WebSocket, автодокументация |
| ASGI-сервер | `granian` | Предпочтительный сервер по pylines/stack |
| Bootstrapping | `microbootstrap` | Логирование через structlog, health, observability |
| DI | `that-depends` | Стандартный DI-инструмент pylines |
| Конфигурация | `pydantic-settings` | Типизированные settings из env |
| Процессы | `asyncio.create_subprocess_exec` | Неблокирующий запуск дочерних процессов |
| Очередь задач | asyncio + in-memory dict (координация) | Простота; пул агентов ограничен настройкой |
| Персистентность | PostgreSQL 16 + asyncpg + advanced-alchemy | Хранение сессий задач, прогресса воркфлоу |
| Миграции | Alembic | Стандарт для SQLAlchemy/advanced-alchemy проектов |
| Пул агентов | asyncio semaphore + subprocess | Ограничение параллельных CLI-процессов |
| MCP | `fastmcp` | Стандарт pylines для MCP-серверов |
| Логирование | `structlog` | Структурированное логирование через microbootstrap |
| Контейнер | Docker (node:22-bookworm-slim base) | Стандартный образ с Node.js для Codex |
| Auth storage | Docker named volume | Персистентность OAuth-сессий между рестартами |
| DB storage | PostgreSQL (docker-compose service) | Персистентность задач и воркфлоу |
| Reverse proxy | Nginx (опционально) | TLS termination, rate-limiting |

***

## 5. Docker-образ

### 5.1 Dockerfile

```dockerfile
FROM node:22-bookworm-slim

# System deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git ca-certificates ripgrep curl \
    && rm -rf /var/lib/apt/lists/*

# CLI tools
RUN npm install -g @openai/codex @anthropic-ai/claude-code

# Python 3.14 via uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Non-root user (security best practice)
RUN useradd -m -u 1000 appuser
USER appuser
WORKDIR /workspace

COPY --chown=appuser:appuser app/ /app/app/

EXPOSE 8000
CMD ["uv", "run", "granian", "--interface", "asgi", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 5.2 pyproject.toml

```toml
[project]
name = "arch-docs"
version = "1.0.0"
requires-python = ">=3.14"
dependencies = [
    "fastapi>=0.115.0",
    "granian>=1.5.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "httpx>=0.27.0",
    "that-depends>=0.13.0",
    "microbootstrap>=0.10.0",
    "structlog>=24.0.0",
    "fastmcp>=0.9.0",
    "stamina>=24.0.0",
    "python-multipart>=0.0.9",
    "langgraph>=0.2.0",
    "langchain-core>=0.3.0",
    "langgraph-checkpoint-postgres>=2.0.0",
    "asyncpg>=0.29.0",
    "advanced-alchemy>=0.20.0",
    "alembic>=1.13.0",
]

[project.optional-dependencies]
dev = [
    "ruff>=0.5.0",
    "ty>=0.0.1a0",
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-xdist>=3.5.0",
    "pytest-cov>=5.0.0",
    "httpx>=0.27.0",
    "faker>=25.0.0",
]

[tool.ruff]
fix = true
line-length = 120

[tool.ruff.lint]
select = ["ALL"]
ignore = ["EM", "FBT", "TRY003", "D1", "D203", "D213", "G004", "FA", "COM812", "ISC001"]

[tool.ruff.lint.extend-per-file-ignores]
"tests/*.py" = ["S101", "S311"]

[tool.coverage.report]
exclude_also = ["if typing.TYPE_CHECKING:"]
fail_under = 90
```

### 5.3 docker-compose.yml

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-arch_docs}
      POSTGRES_USER: ${POSTGRES_USER:-arch_docs}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-arch_docs}"]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  arch-docs:
    build: .
    ports:
      - "8000:8000"
    environment:
      - AUTH_SECRET=${AUTH_SECRET}            # Bearer token для Gateway API
      - WORKSPACE_DIR=/workspace
      - DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER:-arch_docs}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB:-arch_docs}
      - AGENT_POOL_SIZE=${AGENT_POOL_SIZE:-4} # Макс. число параллельных CLI-процессов
    volumes:
      - codex-auth:/home/appuser/.codex       # Сессия Codex CLI
      - claude-auth:/home/appuser/.claude     # Сессия Claude Code
      - workspace:/workspace
    depends_on:
      postgres:
        condition: service_healthy
    restart: unless-stopped
    command: >
      uv run granian --interface asgi app.main:app --host 0.0.0.0 --port 8000

volumes:
  codex-auth:
  claude-auth:
  workspace:
  postgres-data:
```

***

## 6. Процесс первичной авторизации

Авторизация выполняется **один раз** интерактивно через OAuth / device-auth flow подписочного аккаунта. API-ключи не используются. Токены сохраняются в named volume и переживают рестарты контейнера.

### 6.1 Codex CLI (ChatGPT Plus/Pro — device-auth flow)

Требуется активная подписка ChatGPT Plus или Pro.

```bash
docker run -it \
  -v codex-auth:/home/appuser/.codex \
  arch-docs \
  codex login --device-auth
```

CLI выводит код и ссылку на `chatgpt.com`. После подтверждения в браузере `auth.json` сохраняется в volume. Последующие вызовы `codex exec` используют сохранённую сессию без повторной авторизации.

**Истечение токена:** сессия может истечь. При получении exit code авторизационной ошибки от `codex exec` сервис выставляет статус `auth_expired` в `/auth/status` и требует повторного прохождения device-auth flow.

### 6.2 Claude Code (Claude Pro/Max — OAuth flow)

Требуется активная подписка Claude Pro или Max.

```bash
docker run -it \
  -v claude-auth:/home/appuser/.claude \
  arch-docs \
  claude auth login
```

После OAuth-подтверждения в браузере токены сохраняются в `~/.claude/` внутри volume. Последующие вызовы `claude -p` используют сохранённую сессию.

**Истечение токена:** при ошибке авторизации сервис выставляет `auth_expired` и требует повторного `claude auth login`.

### 6.3 Статус авторизации — API endpoint

`GET /auth/status` возвращает состояние каждого CLI.

***

## 7. FastAPI — спецификация эндпоинтов

Базовый путь API — `/api`. Версии в URL запрещены. Маршруты делятся на:

- `/api/rest/` — ресурсно-ориентированные (Tasks, Auth-статус)
- `/api/rpc/` — команды, не укладывающиеся в CRUD (запуск CLI)
- `/health` — вне `/api`, стандартная health-check точка

### 7.1 Аутентификация API

Все эндпоинты (кроме `/health`) требуют заголовок `Authorization: Bearer <AUTH_SECRET>`.

### 7.2 RPC эндпоинты

#### `POST /api/rpc/execute/`

Запуск CLI-команды — это команда, а не создание ресурса, поэтому живёт в `/api/rpc/`. Возвращает `task_id` немедленно (async).

**Request body:**
```json
{
  "engine": "codex",
  "prompt": "string",
  "workspace": "/workspace",
  "output_format": "json",
  "sandbox": "workspace-write",
  "allowed_tools": ["Read", "Edit", "Bash"],
  "session_id": null,
  "timeout_seconds": 300
}
```

**Response `202 Accepted`:**
```json
{
  "task_id": "uuid4",
  "task_status": "pending",
  "created_at": "ISO8601"
}
```

### 7.3 REST эндпоинты

#### `GET /api/rest/tasks/`

Список задач с фильтрацией: `?task_status=running&engine=codex&limit=20`.

#### `GET /api/rest/tasks/{task_id}/`

Статус задачи. Накопленный stdout включается при `?include_output=true` (вложенные пути запрещены).

**Response:**

```json
{
  "task_id": "uuid4",
  "task_status": "pending|running|success|failed|cancelled",
  "engine": "codex",
  "created_at": "ISO8601",
  "started_at": "ISO8601|null",
  "finished_at": "ISO8601|null",
  "task_result": "string|null",
  "task_error": "string|null",
  "stdout_output": "string|null"
}
```

#### `DELETE /api/rest/tasks/{task_id}/`

Отменить задачу (SIGTERM → дочернему процессу).

#### `GET /api/rest/cli-auth/`

Статус авторизации CLI-инструментов.

```json
{
  "codex": {
    "authenticated": true,
    "auth_status": "ok|auth_expired|not_initialized",
    "auth_file_exists": true
  },
  "claude": {
    "authenticated": true,
    "auth_status": "ok|auth_expired|not_initialized",
    "auth_file_exists": true
  }
}
```

#### `POST /api/rpc/cli-auth/init/`

Инициация OAuth/device-auth flow для указанного CLI через API — без ручного `docker exec`. Сервис запускает интерактивный процесс авторизации внутри контейнера и стримит инструкции (код, ссылку) обратно клиенту.

**Request body:**
```json
{
  "cli_engine": "codex|claude"
}
```

**Response `202 Accepted`:**
```json
{
  "auth_session_id": "uuid4",
  "cli_engine": "codex",
  "auth_flow_status": "pending",
  "instructions": "Откройте https://chatgpt.com/device и введите код: XXXX-XXXX",
  "expires_at": "ISO8601"
}
```

Клиент ждёт завершения через `GET /api/rest/cli-auth/auth-sessions/{auth_session_id}/` (polling) или SSE `GET /api/rest/cli-auth/auth-sessions/{auth_session_id}/stream/`.

#### `GET /api/rest/cli-auth/auth-sessions/{auth_session_id}/`

Polling статуса текущего flow авторизации.

```json
{
  "auth_session_id": "uuid4",
  "cli_engine": "codex",
  "auth_flow_status": "pending|success|failed|expired",
  "instructions": "string|null"
}
```

#### `GET /api/rest/cli-auth/auth-sessions/{auth_session_id}/stream/`

SSE-стриминг вывода процесса авторизации — клиент получает код устройства и ссылку в реальном времени, сервис нотифицирует о завершении.

**Сервер отправляет `text/event-stream` события (`data: <JSON>\n\n`):**
```json
{ "event_type": "instructions", "event_data": "Open https://chatgpt.com/device and enter: XXXX-XXXX" }
{ "event_type": "auth_success", "cli_engine": "codex" }
{ "event_type": "auth_failed",  "error_message": "Timeout waiting for device confirmation" }
```

#### `GET /health`

```json
{ "service_status": "ok", "version": "1.0.0" }
```

### 7.4 SSE эндпоинты для стриминга

Стриминг реализован через Server-Sent Events (SSE) — все события идут в одном направлении (server→client), что соответствует модели использования. Формат: `data: <JSON>\n\n` в потоке `text/event-stream`.

Для запуска и отслеживания задачи в реальном времени клиент:
1. Делает `POST /api/rpc/execute/` → получает `task_id`
2. Открывает `GET /api/rest/tasks/{task_id}/stream/` → получает события

#### `GET /api/rest/tasks/{task_id}/stream/`

Стриминг вывода задачи. Если задача ещё выполняется — поток открыт, события приходят по мере вывода CLI. Если уже завершена — буферизованный вывод отдаётся сразу, затем `done`.

**Ответ `200 OK`, `Content-Type: text/event-stream`.**

**Сервер отправляет события:**
```json
{ "event_type": "progress", "event_data": "...", "stream_source": "stderr" }
{ "event_type": "output", "event_data": "...", "stream_source": "stdout" }
{ "event_type": "done", "exit_code": 0, "task_id": "uuid4" }
```

**Ошибки:** `404 Not Found` если `task_id` не найден.

***

## 8. Внутренняя логика FastAPI

### 8.1 Управление процессами и пул агентов

```python
import asyncio
import dataclasses
import enum
import typing


class TaskStatus(enum.StrEnum):
    PENDING = enum.auto()
    RUNNING = enum.auto()
    SUCCESS = enum.auto()
    FAILED = enum.auto()
    CANCELLED = enum.auto()


@dataclasses.dataclass(kw_only=True, slots=True)
class CliTask:
    task_id: str
    engine_name: str
    task_status: TaskStatus = TaskStatus.PENDING
    subprocess_handle: asyncio.subprocess.Process | None = None
    stdout_lines: list[str] = dataclasses.field(default_factory=list)
    task_result: str | None = None
    task_error: str | None = None


TaskRegistry: typing.TypeAlias = dict[str, CliTask]
```

Замечания по дизайну:

- `frozen=True` не применяется к `CliTask`, т.к. статус и буфер мутируются в процессе выполнения; для иммутабельных DTO (запросы/ответы) `frozen=True` обязателен
- `TaskStatus` через `StrEnum` с `enum.auto()` — значения совпадают с именами в нижнем регистре
- Имена полей точные: `engine_name` вместо `engine`, `task_status` вместо `status`, `task_result`/`task_error` вместо `result`/`error` (во избежание конфликта с общими техническими словами)
- `subprocess_handle` вместо `process` (слишком общее)
- Логика runner выносится в `services/task_runner.py`, а не в dataclass

**Пул агентов** — максимальное число параллельных CLI-процессов ограничивается через `asyncio.Semaphore` с размером из `GatewaySettings.agent_pool_size` (env `AGENT_POOL_SIZE`, default `4`). Задачи сверх лимита ожидают освобождения слота в очереди — `task_status` остаётся `pending`. Это предотвращает перегрузку подписочного rate-limit и CPU контейнера.

```python
class AgentPool:
    def __init__(self, pool_size: int) -> None:
        self._semaphore = asyncio.Semaphore(pool_size)

    async def run(self, coro: typing.Coroutine) -> typing.Any:
        async with self._semaphore:
            return await coro
```

`AgentPool` регистрируется как singleton в DI-контейнере (`that-depends`).

**Персистентность задач** — все записи `CliTask` сохраняются в PostgreSQL через `advanced-alchemy`. In-memory `TaskRegistry` используется только для хранения живых `subprocess_handle` в рамках одного процесса; при рестарте сервиса незавершённые задачи переводятся в `failed` через lifespan-хук. Полная история задач и их вывод (stdout) остаются в БД.

Схема таблицы `cli_tasks` (managed через Alembic):

```sql
CREATE TABLE cli_tasks (
    task_id         UUID PRIMARY KEY,
    engine_name     TEXT NOT NULL,
    task_status     TEXT NOT NULL DEFAULT 'pending',
    prompt_text     TEXT NOT NULL,
    workspace_dir   TEXT NOT NULL,
    session_id      TEXT,
    task_result     TEXT,
    task_error      TEXT,
    stdout_output   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ
);
```

Для Claude Code команда: `claude -p "{prompt}" --output-format stream-json` (без `--bare`, т.к. используется OAuth-сессия подписки, а не API-ключ).

### 8.2 Резюмирование сессии (Claude)

Claude Code поддерживает `--continue` и `--resume <session_id>` для продолжения предыдущего разговора. При передаче `session_id` в запросе команда модифицируется:

```bash
claude -p "<prompt>" --resume <session_id> --output-format json
```

Codex CLI поддерживает `codex exec resume --last` или `codex exec resume <SESSION_ID>`.

### 8.3 Таймаут и отмена

```python
async def cancel_cli_task(task_id: str, registry: TaskRegistry) -> None:
    cli_task = registry.get(task_id)
    if cli_task is None or cli_task.subprocess_handle is None:
        return
    if cli_task.subprocess_handle.returncode is not None:
        return
    cli_task.subprocess_handle.terminate()
    try:
        await asyncio.wait_for(cli_task.subprocess_handle.wait(), timeout=5)
    except asyncio.TimeoutError:
        cli_task.subprocess_handle.kill()
    cli_task.task_status = TaskStatus.CANCELLED
```

### 8.4 Конфигурация

```python
from pydantic_settings import BaseSettings


class GatewaySettings(BaseSettings):
    auth_secret: str
    workspace_dir: str = "/workspace"
    default_timeout_seconds: int = 300
    database_url: str                    # postgresql+asyncpg://...
    agent_pool_size: int = 4             # макс. параллельных CLI-процессов

    model_config = {"env_file": ".env"}
```

Настройки получаются из env-переменных через `pydantic-settings`. `GatewaySettings` регистрируется как singleton в DI-контейнере (`that-depends`).

### 8.5 Логирование

Используется `structlog` через `microbootstrap`. Каждая операция логирует `task_id` и `engine_name`:

```python
import structlog

logger = structlog.get_logger()

async def run_cli_task(cli_task: CliTask, ...) -> None:
    logger.info("cli_task.started", task_id=cli_task.task_id, engine=cli_task.engine_name)
    ...
    logger.info("cli_task.finished", task_id=cli_task.task_id, exit_code=exit_code)
```

***

## 9. Режимы sandbox для Codex

Codex CLI поддерживает три режима изоляции. Внутри Docker контейнер сам является sandbox, поэтому рекомендуется `workspace-write` или `danger-full-access` при монтировании только нужной директории.

| Режим | Права | Использование |
|-------|-------|--------------|
| `read-only` | Только чтение ФС | Анализ кода, ревью |
| `workspace-write` | Запись в рабочий каталог | Генерация кода, рефакторинг |
| `danger-full-access` | Полный доступ внутри контейнера | CI/CD, сложные задачи |

***

## 10. Безопасность

- **API**: Bearer token из env `AUTH_SECRET` на всех эндпоинтах
- **CLI Auth**: используются OAuth/device-auth сессии подписок (ChatGPT Plus/Pro, Claude Pro/Max) — API-ключи не используются и не хранятся
- **Volume**: `auth.json` / `.claude` содержат живые OAuth-токены — volume монтируется только для `appuser`, доступ снаружи контейнера закрыт
- **Контейнер**: non-root пользователь, no `--privileged`, no Docker socket
- **Workspace**: монтировать только проектный каталог, не весь хост
- **Rate limiting**: Nginx или FastAPI middleware (slowapi)
- **Таймауты**: обязательный `timeout_seconds` на все задачи (default 300s)

***

## 11. Конфигурация (`config.toml` в Codex volume)

```toml
# Монтируется в codex-auth volume
approval_policy = "never"
sandbox_mode = "workspace-write"
```

Это позволяет не передавать флаги каждый раз.

***

## 12. Структура репозитория

Структура следует слоям pylines: `api/`, `services/`, `external/`, зеркальные `tests/`.

```text
arch-docs/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml          # uv, зависимости, ruff, coverage
├── uv.lock
├── justfile                # agent-fix, agent-check, agent-fix-changed
├── .env.example
├── app/
│   ├── main.py             # FastAPI app, lifespan, microbootstrap
│   ├── settings.py         # GatewaySettings (pydantic-settings)
│   ├── container.py        # DI-контейнер (that-depends)
│   ├── api/
│   │   ├── __init__.py     # централизованное подключение роутеров
│   │   ├── rest/
│   │   │   ├── tasks.py    # GET /api/rest/tasks/, GET/DELETE /api/rest/tasks/{id}/
│   │   │   ├── cli_auth.py # GET /api/rest/cli-auth/
│   │   │   └── workflows.py # GET /api/rest/workflows/{id}/ — статус LangGraph-воркфлоу
│   │   ├── rpc/
│   │   │   ├── execute.py  # POST /api/rpc/execute/
│   │   │   └── workflows.py # POST /api/rpc/workflows/init/, POST /api/rpc/workflows/{id}/resume/
│   │   └── ws/
│   │       └── workflows.py       # GET /api/rest/workflows/{id}/stream/ — SSE события LangGraph-воркфлоу (v2)
│   ├── mcp_server.py       # fastmcp: определения инструментов; монтируется в main.py через http_app()
│   ├── services/
│   │   ├── task_runner.py  # бизнес-логика запуска и управления задачами
│   │   ├── task_registry.py # in-memory TaskRegistry
│   │   ├── cli_auth_checker.py # проверка статуса OAuth-сессий
│   │   └── workflow_registry.py # in-memory реестр запущенных LangGraph-воркфлоу
│   ├── workflows/
│   │   └── init_arch/
│   │       ├── graph.py    # сборка LangGraph StateGraph; точка входа InitArchGraph
│   │       ├── state.py    # InitArchState (TypedDict); схема состояния
│   │       ├── nodes.py    # по одному async def на каждый шаг STEP_DEFINITIONS
│   │       ├── prompts.py  # сборка промптов из reference-файлов скилла
│   │       ├── guard.py    # subprocess-обёртка вокруг analysis_guard.py
│   │       └── checkpointer.py # SqliteSaver, путь к БД из settings
│   ├── external/
│   │   ├── codex_cli.py    # subprocess-обёртка для codex exec
│   │   └── claude_cli.py   # subprocess-обёртка для claude -p
│   └── middleware/
│       └── bearer_auth.py  # Bearer token из AUTH_SECRET
├── tests/
│   ├── api/
│   │   ├── rest/
│   │   │   ├── test_tasks.py
│   │   │   ├── test_cli_auth.py
│   │   │   └── test_workflows.py
│   │   └── rpc/
│   │       ├── test_execute.py
│   │       └── test_workflows.py
│   ├── services/
│   │   └── test_task_runner.py
│   ├── workflows/
│   │   └── init_arch/
│   │       ├── test_graph.py      # end-to-end прогон графа с mock CLI
│   │       ├── test_nodes.py      # unit-тесты узлов с mock guard + mock CLI
│   │       └── test_prompts.py    # проверка сборки промптов
│   └── conftest.py         # httpx.AsyncClient fixture, fake CLI subprocess
├── scripts/
│   ├── auth-codex.sh       # интерактивная авторизация Codex
│   └── auth-claude.sh      # интерактивная авторизация Claude
└── docs/
    └── openapi.yaml
```

**Соответствие слоям pylines:**

- `app/api/rest/`, `app/api/rpc/`, `app/api/ws/` — HTTP/WS обработчики, тонкий слой без бизнес-логики
- `app/services/` — бизнес-логика: запуск задач, реестр, проверка auth-статуса CLI
- `app/external/` — CLI-клиенты через subprocess; retry через `stamina`
- `tests/` — зеркально повторяет структуру `app/`; покрытие не ниже 90%

***

## 13. Feature Checklist

Полный список функциональности сервиса по приоритету реализации.

- [x] **Сохранение работы всех сессий (запуск задач) в Postgres**
  - Все `CliTask` персистируются в таблице `cli_tasks`
  - История задач доступна после рестарта контейнера
  - Stdout/stderr каждой задачи сохраняется в БД

- [x] **Пул агентов (Claude Code и Codex)**
  - `asyncio.Semaphore` ограничивает параллельные CLI-процессы
  - Размер пула задаётся через `AGENT_POOL_SIZE` (default `4`)
  - Задачи сверх лимита ожидают освобождения слота с `task_status: pending`

- [x] **API: Авторизация в Claude Code и Codex (не через API-токен)**
  - `POST /api/rpc/cli-auth/init/` — инициация OAuth/device-auth flow через API
  - `GET /api/rest/cli-auth/auth-sessions/{id}/` — polling статуса авторизации
  - `GET /api/rest/cli-auth/auth-sessions/{id}/stream/` — SSE-стриминг инструкций авторизации клиенту

- [x] **API: Init — первый раз создать документацию**
  - `POST /api/rpc/workflows/init/` — запуск LangGraph-графа `InitArchGraph`
  - Возвращает `workflow_id` немедленно, граф работает в фоне

- [x] **API: Update — обновить документацию**
  - MCP-инструмент `update_arch` + эндпоинт `POST /api/rpc/update-arch/`
  - Принимает `diff_context` или читает `git diff` самостоятельно

- [x] **API: Query — ответить на вопрос по документации**
  - `POST /api/rpc/query-arch/` с промптом на чтение `arch-doc/`
  - Возвращает ответ через polling `GET /api/rest/tasks/{id}/`

- [x] **MCP: Query — ответить на вопрос по документации**
  - Инструмент `query` в `app/mcp_server.py`
  - Вызывается из Claude Code, Cursor или любого MCP-клиента
  - Использует CLI-subprocess, без Python SDK

***

## 14. Этапы реализации

## Версия 1. Core Gateway

Цель: рабочий HTTP-сервис внутри Docker-контейнера, поверх подписочных CLI без API-ключей.

### Этап 1. Docker-образ и CLI-окружение ✅ ВЫПОЛНЕНО

Цель: собрать образ с установленными `codex` и `claude`, настроить volume-based auth, проверить что оба CLI запускаются headless через OAuth-сессию.

Состав:

- `Dockerfile` — node:22-bookworm-slim, Python venv, `npm install -g @openai/codex @anthropic-ai/claude-code`, non-root `appuser`;
- `docker-compose.yml` — volumes `codex-auth`, `claude-auth`, `workspace`; env только `AUTH_SECRET` и `WORKSPACE_DIR`;
- `scripts/auth-codex.sh` — интерактивный `codex login --device-auth` с монтированием volume;
- `scripts/auth-claude.sh` — интерактивный `claude auth login` с монтированием volume;
- `config.toml` для Codex volume (`approval_policy = "never"`, `sandbox_mode = "workspace-write"`).

Критерий готовности:

- `docker compose up` поднимает контейнер без ошибок;
- после однократного прохождения device-auth `codex exec "echo ok"` выполняется внутри контейнера без повторной авторизации;
- аналогично `claude -p "echo ok"` работает через сохранённую OAuth-сессию;
- рестарт контейнера не требует повторного логина.

### Этап 2. FastAPI skeleton и синхронный `POST /api/rpc/execute/` ✅ ВЫПОЛНЕНО

Цель: минимальный рабочий эндпоинт, который принимает промпт, запускает CLI синхронно и возвращает результат.

Состав:

- `app/main.py` — FastAPI app, lifespan через `microbootstrap`, подключение роутеров из `app/api/__init__.py`;
- `app/settings.py` — `GatewaySettings` на базе `pydantic-settings`, читает `AUTH_SECRET`, `WORKSPACE_DIR`;
- `app/container.py` — DI-контейнер (`that-depends`), регистрирует `GatewaySettings` и сервисы;
- `app/middleware/bearer_auth.py` — Bearer token из `AUTH_SECRET` на всех маршрутах кроме `/health`;
- `app/api/rpc/execute.py` — `POST /api/rpc/execute/` (sync v0: ждёт завершения процесса, возвращает результат);
- `app/external/codex_cli.py`, `app/external/claude_cli.py` — subprocess-обёртки, строят `cmd`, читают stdout/stderr;
- `GET /health` — `{"service_status": "ok", "version": "1.0.0"}`.

Критерий готовности:

- `POST /api/rpc/execute/ {"engine": "claude", "prompt": "..."}` возвращает результат;
- Bearer auth работает: без токена — `HTTP 401`, с токеном — `HTTP 202`;
- stdout и stderr обоих CLI корректно захватываются;
- `just agent-check` проходит без ошибок (ruff, ty, pytest);
- покрытие новой дельты — 100%.

### Этап 3. Async задачи и управление процессами ✅ ВЫПОЛНЕНО

Цель: перевести выполнение CLI на фоновые задачи, чтобы сервер не блокировался на долгих задачах.

Состав:

- `app/services/task_registry.py` — `TaskRegistry` (in-memory dict), `CliTask` dataclass с `TaskStatus` enum;
- `app/services/task_runner.py` — `run_cli_task(cli_task, request)`: запускает subprocess в фоне через `asyncio.create_task`, пишет stdout в `cli_task.stdout_lines`;
- `app/api/rpc/execute.py` — `POST /api/rpc/execute/` возвращает `HTTP 202` с `task_id` немедленно;
- `app/api/rest/tasks.py`:
  - `GET /api/rest/tasks/` — список с фильтрацией `?task_status=&engine=&limit=`;
  - `GET /api/rest/tasks/{task_id}/` — статус, результат, timestamps; `?include_output=true` добавляет `stdout_output`;
  - `DELETE /api/rest/tasks/{task_id}/` — SIGTERM → SIGKILL через 5 с, статус `cancelled`;
- тесты в `tests/api/rest/test_tasks.py`, `tests/api/rpc/test_execute.py` через `httpx.AsyncClient`.

Критерий готовности:

- запрос возвращает `task_id` немедленно, задача выполняется в фоне;
- `GET /api/rest/tasks/{task_id}/` отражает актуальный `task_status`;
- `DELETE /api/rest/tasks/{task_id}/` корректно завершает дочерний процесс;
- `timeout_seconds` применяется, задача завершается в `TaskStatus.FAILED`;
- `just agent-check` проходит; покрытие дельты — 100%.

### Этап 4. SSE streaming ✅ ВЫПОЛНЕНО

Цель: клиент получает вывод CLI в реальном времени через Server-Sent Events (SSE).

Состав:

- `GET /api/rest/tasks/{task_id}/stream/` в `app/api/rest/tasks.py` — SSE endpoint;
  - если задача ещё выполняется — поток открыт, события приходят по мере вывода CLI;
  - если уже завершена — буферизованный вывод отдаётся сразу, затем `done`;
- поля событий: `event_type`, `event_data`, `stream_source` (не `type`/`data` — слишком общие имена);
- чтение stdout и stderr одновременно (`asyncio.gather`): Codex пишет прогресс в stderr, результат в stdout;
- аутентификация через `BearerAuthMiddleware` (работает для обычных HTTP-запросов, включая SSE).

Критерий готовности:

- клиент получает события `progress`/`output`/`done` по мере вывода CLI;
- `stream_source: "stdout" | "stderr"` корректно проставлен;
- повторное подключение через `GET /api/rest/tasks/{task_id}/stream/` отдаёт накопленный буфер;
- `404 Not Found` если `task_id` не найден.

### Этап 5. Auth flow и `GET /api/rest/cli-auth/` ✅ ВЫПОЛНЕНО

Цель: сервис умеет детектировать состояние авторизации CLI и сигнализировать об истёкшей сессии.

Состав:

- `app/services/cli_auth_checker.py` — проверяет наличие auth-файлов (`~/.codex/auth.json`, `~/.claude/`); запускает smoke-команду и по exit code возвращает `ok | auth_expired | not_initialized`;
- `app/api/rest/cli_auth.py` — `GET /api/rest/cli-auth/` делегирует в `CliAuthChecker`;
- `app/external/codex_cli.py`, `app/external/claude_cli.py` — обновление: при auth-ошибке бросать типизированное исключение, не возвращать generic `failed`;
- тесты в `tests/api/rest/test_cli_auth.py`.

Критерий готовности:

- `GET /api/rest/cli-auth/` возвращает `auth_status: "ok"` после успешного логина;
- при протухшем токене — `auth_status: "auth_expired"` (не `ok` и не `HTTP 500`);
- при отсутствии volume-файлов — `auth_status: "not_initialized"`;
- покрытие дельты — 100%.

### Этап 6. Session resume ✅ ВЫПОЛНЕНО

Цель: клиент может продолжить предыдущий разговор с Claude или Codex по `session_id`.

Состав:

- в Pydantic-схеме запроса `ExecuteRequest` — опциональное поле `session_id: str | None = None`;
- в `app/external/claude_cli.py` — при наличии `session_id` добавляет `--resume <session_id>`;
- в `app/external/codex_cli.py` — при наличии `session_id` использует `codex exec resume <session_id>`;
- `CliTask.session_id` сохраняется в `TaskRegistry`, отдаётся в `GET /api/rest/tasks/{task_id}/`.

Критерий готовности:

- передача `session_id` в `POST /api/rpc/execute/` подхватывает контекст предыдущего разговора;
- без `session_id` поведение не меняется;
- `GET /api/rest/tasks/{task_id}/` отдаёт `session_id` для сохранения на стороне клиента.

***

## Версия 2. MCP и Production

Цель: интеграция с AI-агентами через MCP и подготовка сервиса к продуктивной эксплуатации.

### Этап 7. MCP-сервис: `init_arch`, `update_arch`, `query` ✅ ВЫПОЛНЕНО (упрощённая версия без LangGraph)

Цель: экспортировать три MCP-инструмента для управления архитектурной документацией. Все вызовы к моделям — исключительно через CLI-subprocess, без Python SDK (`anthropic`, `openai`). Библиотека — `fastmcp` (стандарт pylines).

Инструмент `init_arch` реализуется **не** как простой subprocess-вызов скилла, а через LangGraph-граф (подробности в разделе 16). Инструмент запускает граф, возвращает `workflow_id` немедленно; прогресс доступен через REST/WS API.

Состав:

- `app/mcp_server.py`:
  - MCP-сервер на базе `fastmcp` (не `mcp`);
  - функция `run_cli_subprocess(engine_name, prompt_text, workspace_dir, timeout_seconds)` — вызывает `codex exec` или `claude -p` через `asyncio.create_subprocess_exec`; никакого SDK;
  - инструмент `init_arch` — запускает LangGraph-граф `InitArchGraph` (см. раздел 17), возвращает `workflow_id` и URL для polling/streaming; вопросы к пользователю в шаге `interview_user` передаются через MCP-ответ с `interrupt_type: "user_question"`;
  - инструмент `update_arch` — запускает `update-repo-arch-skill` через прямой subprocess (до реализации LangGraph-варианта в v3); принимает опциональный `diff_context`;
  - инструмент `query` — читает `arch-doc/` и отвечает на произвольный вопрос об архитектуре;
- в `app/main.py` — `app.mount("/api/mcp", mcp_server.http_app())` подключает MCP SSE-эндпоинт в тот же FastAPI-процесс; отдельный процесс и `supervisord` не нужны.

Критерий готовности:

- `claude mcp add arch-docs --transport sse http://localhost:8000/api/mcp/sse` регистрирует сервер без ошибок;
- все три инструмента вызываются из Claude Code через SSE-транспорт и возвращают результат;
- MCP-сервер запускается в том же процессе, что и FastAPI — второй процесс или supervisord не нужны;
- `init_arch` возвращает `workflow_id` немедленно и запускает граф в фоне;
- `run_cli_subprocess` не импортирует `anthropic` или `openai`; единственный способ вызвать модель — subprocess к CLI;
- auth-сессии из volume используются теми же путями, что и в REST-эндпоинтах;
- `just agent-check` проходит.

### Этап 8. Production hardening ✅ ВЫПОЛНЕНО

Цель: сервис готов к эксплуатации: защита трафика, ограничение нагрузки, корректное завершение.

Состав:

- Nginx как reverse proxy: проксирование HTTP и SSE на порт 8000; TLS termination через reverse proxy на хосте;
- rate limiting: Nginx `limit_req_zone` — строгий лимит на execute/update-arch/query-arch, мягкий на остальные;
- graceful shutdown: lifespan в `app/main.py` отменяет все активные subprocess через SIGTERM перед остановкой;
- структурированное логирование: structlog через microbootstrap, `task_id` в каждой записи;
- `.env.example` с документацией всех переменных окружения (включая `POSTGRES_PASSWORD`, `DATABASE_URL`, `AGENT_POOL_SIZE`);
- OpenAPI-схема автогенерируется FastAPI и доступна на `/docs` и `/openapi.json` — ручная генерация `openapi.yaml` не нужна.

Критерий готовности:

- `docker compose up` поднимает postgres + arch-docs + nginx без ошибок;
- `docker compose stop` завершает все запущенные задачи без потери вывода;
- логи содержат `task_id` и достаточно информации для диагностики без доступа к контейнеру;
- rate limiting отклоняет избыточные запросы с `429`, не роняя сервис.

***

## 15. MCP-сервис

Сервис экспортирует MCP-инструменты, доступные AI-агентам (Claude Code, Cursor, любой MCP-совместимый клиент) для управления архитектурной документацией репозитория напрямую из контекста работы агента.

### 15.1 Транспорт

MCP-сервер реализован на `fastmcp` и работает **в одном процессе с FastAPI** через HTTP SSE-транспорт. Отдельный процесс не нужен.

`fastmcp` позволяет смонтировать MCP-сервер в существующее ASGI-приложение через `mcp_server.http_app()`. Итоговый роутер подключается к FastAPI на маршруте `/api/mcp/`:

```python
# app/main.py
from app.mcp_server import mcp_server

app.mount("/api/mcp", mcp_server.http_app())
```

Granian запускает один процесс, обслуживающий одновременно REST/WS API и MCP SSE-эндпоинт:

```yaml
# docker-compose.yml
services:
  arch-docs:
    command: >
      uv run granian --interface asgi app.main:app --host 0.0.0.0 --port 8000
```

Регистрация в Claude Code через SSE-транспорт:

```bash
claude mcp add arch-docs --transport sse http://localhost:8000/api/mcp/sse
```

Stdio-транспорт (`uv run python -m app.mcp_server`) остаётся доступным как резервный вариант для окружений без сетевого доступа к контейнеру, но не является основным.

### 15.2 Инструменты (Tools)

#### `init_arch`

Инициализирует архитектурную документацию для репозитория: запускает `init-repo-arch-skill` внутри контейнера через `claude -p`, создаёт папку `arch-doc/` со всеми артефактами (HLD, tech-stack, domain-entities, glossary и т.д.).

**Input schema:**
```json
{
  "repo_path": {
    "type": "string",
    "description": "Абсолютный путь к репозиторию внутри /workspace"
  },
  "engine": {
    "type": "string",
    "enum": ["claude", "codex"],
    "default": "claude"
  },
  "timeout_seconds": {
    "type": "integer",
    "default": 600
  }
}
```

**Поведение:**

1. Запускает `POST /execute` с `engine=claude`, `prompt` — промпт активации `init-repo-arch-skill`
2. Стримит прогресс через внутренний WebSocket
3. Возвращает `task_id` и список созданных файлов после завершения

**Output:**

```json
{
  "task_id": "uuid4",
  "status": "success",
  "artifacts": [
    "arch-doc/architecture/hld.md",
    "arch-doc/architecture/tech-stack.md",
    "arch-doc/architecture/domain-entities.md"
  ],
  "summary": "string"
}
```

***

#### `update_arch`

Обновляет архитектурную документацию на основе диффа текущей ветки: запускает `update-repo-arch-skill` внутри контейнера, анализирует изменения и обновляет затронутые артефакты.

**Input schema:**

```json
{
  "repo_path": {
    "type": "string",
    "description": "Абсолютный путь к репозиторию внутри /workspace"
  },
  "diff_context": {
    "type": "string",
    "description": "git diff или описание изменений (опционально; если не передано — агент сам читает git diff)"
  },
  "engine": {
    "type": "string",
    "enum": ["claude", "codex"],
    "default": "claude"
  },
  "timeout_seconds": {
    "type": "integer",
    "default": 600
  }
}
```

**Поведение:**

1. Запускает `POST /execute` с промптом активации `update-repo-arch-skill`
2. После завершения возвращает список изменённых артефактов и краткий changelog

**Output:**

```json
{
  "task_id": "uuid4",
  "status": "success",
  "updated_artifacts": [
    "arch-doc/architecture/tech-stack.md"
  ],
  "release_note": "string"
}
```

***

#### `query`

Задаёт произвольный вопрос по архитектуре репозитория. Агент читает артефакты из `arch-doc/` и отвечает в контексте системы.

**Input schema:**

```json
{
  "question": {
    "type": "string",
    "description": "Вопрос об архитектуре, стеке, доменных сущностях, интеграциях и т.д."
  },
  "repo_path": {
    "type": "string",
    "description": "Путь к репозиторию внутри /workspace"
  },
  "engine": {
    "type": "string",
    "enum": ["claude", "codex"],
    "default": "claude"
  },
  "timeout_seconds": {
    "type": "integer",
    "default": 120
  }
}
```

**Поведение:**

1. Запускает `POST /execute` с промптом: прочитать артефакты `arch-doc/` и ответить на вопрос
2. Возвращает ответ синхронно (короткий таймаут) или через polling

**Output:**

```json
{
  "task_id": "uuid4",
  "status": "success",
  "answer": "string"
}
```

### 15.3 Реализация

**Принципиальное требование:** MCP-скрипты вызывают `codex` и `claude` **исключительно через CLI** (`asyncio.create_subprocess_exec`), используя те же OAuth/device-auth сессии из volume. Никаких Python SDK (`anthropic`, `openai`) — только subprocess к CLI-инструментам.

MCP-сервер (`app/mcp_server.py`) реализован на `fastmcp` (стандарт pylines) и переиспользует логику из `app/external/`:

```python
import asyncio
import os
import typing
import fastmcp


mcp_server = fastmcp.FastMCP("arch-docs")

INIT_ARCH_PROMPT: typing.Final = "/init-repo-arch-skill"


async def run_cli_subprocess(
    engine_name: str,
    prompt_text: str,
    workspace_dir: str,
    timeout_seconds: int,
) -> str:
    if engine_name == "claude":
        cmd = ["claude", "-p", prompt_text, "--output-format", "stream-json"]
    else:
        cmd = [
            "codex", "exec",
            "--sandbox", "workspace-write",
            "--skip-git-repo-check",
            "--json",
            prompt_text,
        ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=workspace_dir,
        env={**os.environ},
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode())
    return stdout.decode()


@mcp_server.tool()
async def init_arch(repo_path: str, engine_name: str = "claude", timeout_seconds: int = 600) -> dict:
    cli_output = await run_cli_subprocess(engine_name, INIT_ARCH_PROMPT, repo_path, timeout_seconds)
    return {"operation_status": "success", "cli_output": cli_output}


@mcp_server.tool()
async def update_arch(
    repo_path: str,
    diff_context: str = "",
    engine_name: str = "claude",
    timeout_seconds: int = 600,
) -> dict:
    prompt_text = f"/update-repo-arch-skill\n{diff_context}" if diff_context else "/update-repo-arch-skill"
    cli_output = await run_cli_subprocess(engine_name, prompt_text, repo_path, timeout_seconds)
    return {"operation_status": "success", "cli_output": cli_output}


@mcp_server.tool()
async def query(
    question: str,
    repo_path: str,
    engine_name: str = "claude",
    timeout_seconds: int = 120,
) -> dict:
    prompt_text = f"Прочитай arch-doc/ и ответь на вопрос: {question}"
    answer_text = await run_cli_subprocess(engine_name, prompt_text, repo_path, timeout_seconds)
    return {"answer_text": answer_text}
```

Замечания по именованию:

- `engine_name` вместо `engine` (слишком общее)
- `prompt_text` вместо `prompt` (конфликт с встроенным `prompt()`)
- `workspace_dir` вместо `workspace`
- `operation_status` вместо `status` (слишком общее)
- `answer_text` вместо `answer`

**Зависимость от CLI в PATH:** `codex` и `claude` установлены через `npm install -g` и доступны в `$PATH` — гарантируется Dockerfile.

### 15.4 Структура дополнительных файлов

```text
app/
└── mcp_server.py          # fastmcp: определения инструментов; монтируется в FastAPI через http_app()
```

`app/api/ws/mcp_sse.py` больше не нужен — маршрут `/api/mcp/` создаётся через `app.mount()` в `main.py`, отдельного модуля не требуется.

В `docker-compose.yml` — единственная команда:

```yaml
services:
  arch-docs:
    command: >
      uv run granian --interface asgi app.main:app --host 0.0.0.0 --port 8000
```

***

## 16. Известные ограничения

- **Codex `codex exec`**: требует Git-репозиторий внутри рабочей директории (обходится флагом `--skip-git-repo-check`)
- **Истечение OAuth-токенов**: сессии Codex (ChatGPT) и Claude могут протухнуть — сервис обязан детектировать ошибку авторизации по exit code и выставлять `auth_expired` в `/api/rest/cli-auth/`; повторный логин выполняется через API-эндпоинт `POST /api/rpc/cli-auth/init/`
- **Подписочные лимиты**: rate limit и usage cap определяются тарифом подписки (Plus/Pro/Max), а не API-квотами — пул агентов (`agent_pool_size`) должен быть настроен с учётом лимитов аккаунта
- **stdout/stderr**: Codex пишет прогресс в stderr, финальный ответ в stdout — необходимо читать оба потока
- **Рестарт сервиса**: при рестарте контейнера задачи в статусе `running` переводятся в `failed` через lifespan-хук; история задач в PostgreSQL не теряется
- **subprocess_handle при рестарте**: живые subprocess-хэндлы существуют только в памяти процесса — после рестарта дочерние процессы теряются, что оправдывает перевод задач в `failed`

***

## 17. LangGraph-оркестрация команды `init`

### 17.1 Зачем LangGraph

`init-repo-arch-skill` — явная state machine с 14 шагами (`STEP_DEFINITIONS`) и вложенным чеклистом (~21 пункт) для каждого репозитория. Без внешнего оркестратора управление переходами остаётся внутри текстовых инструкций скилла, что делает состояние непрозрачным и непроверяемым извне.

LangGraph берёт на себя роль внешнего оркестратора: каждый шаг скилла — узел графа, переходы между ними — рёбра, состояние между узлами — персистентный TypedDict, пауза на вопрос пользователю — `interrupt()`. Вызовы LLM остаются исключительно через CLI-subprocess (`claude -p` / `codex exec`) — без Python SDK. `analysis_guard.py` работает как инструмент ведения progress-файла, вызывается subprocess-обёрткой из каждого узла.

***

### 17.2 Зависимости

```toml
"langgraph>=0.2.0",       # StateGraph, interrupt, checkpointing
"langchain-core>=0.3.0",  # базовые абстракции: только Messages и Runnable
"aiosqlite>=0.20.0",      # персистентный checkpointer (SqliteSaver)
```

`langchain` (full) не добавляется. Prompt-рендеринг — через f-strings и `jinja2` (уже доступен через FastAPI). LLM-клиенты из langchain не используются — только CLI-subprocess.

***

### 17.3 Схема состояния `InitArchState`

```python
import typing
from langgraph.graph import add_messages


class InitArchState(typing.TypedDict):
    # параметры запуска
    product_name: str
    analysis_scope: str
    workspace_dir: str            # абсолютный путь к репозиторию внутри /workspace
    arch_repo_dir: str            # куда пишутся arch-артефакты (обычно <workspace_dir>/arch-doc)
    engine_name: str              # "claude" | "codex"
    timeout_seconds: int

    # состояние прогресса
    progress_file_path: str       # путь к repo-initialization-progress.yaml
    current_step_id: str          # текущий шаг из STEP_DEFINITIONS
    current_repo_name: str        # текущий анализируемый репозиторий (пусто если N/A)
    completed_steps: list[str]    # список завершённых step_id

    # данные для шагов
    repo_list: list[str]          # имена репозиториев (из request_repository_list)
    domain_strategy: str          # "per_module" | "per_domain"
    open_questions: list[str]     # вопросы, требующие ответа пользователя (для interview_user)
    pending_user_question: str    # один открытый вопрос для текущего interrupt

    # последний вывод CLI
    last_cli_output: str
    last_guard_output: str

    # ошибки
    step_error: str | None        # ошибка текущего узла (None если OK)
    retry_count: int              # число повторных попыток текущего узла
```

`add_messages` не используется в основном состоянии — история чата не нужна; каждый узел строит prompt заново из reference-файлов и progress-файла.

***

### 17.4 Структура графа

Граф строится в `app/workflows/init_arch/graph.py` как `StateGraph(InitArchState)`.

**Линейная последовательность верхнего уровня** (порядок из `STEP_DEFINITIONS`):

```text
START
  → node_define_scope
  → node_request_repository_list         [interrupt → ответ пользователя]
  → node_prepare_temp_workspace
  → node_clone_repositories
  → node_refresh_main_branches
  → node_plan_repository_order
  → node_assess_scope_and_domains
  → node_analyze_repositories            [вложенный цикл]
  → node_interview_user                  [interrupt на каждый вопрос]
  → node_refine_features
  → node_build_navigation_index
  → node_run_knowledge_lint
  → node_validate_final
  → node_finalize_progress
  → END
```

**Ветвление в `node_assess_scope_and_domains`** — по результату определяет `domain_strategy` в состоянии; граф не ветвится структурно, но `node_analyze_repositories` читает `domain_strategy` из состояния.

**Вложенный цикл `node_analyze_repositories`** — один большой узел реализует внутренний цикл по репозиториям и чеклист-пунктам через `asyncio`-цепочку: для каждого репозитория вызывает `analysis_guard repo --start`, затем по одному чеклист-пункту строит промпт, вызывает CLI, вызывает `analysis_guard repo --checklist-item`. После завершения одного репозитория вызывает `analysis_guard repo --complete`.

**Обработка ошибок** — при `step_error is not None` ребро ведёт в `node_handle_error`, который логирует ошибку через structlog и при `retry_count < 3` возвращает к текущему узлу; при исчерпании — в `END` с финальным статусом `failed`.

***

### 17.5 Реализация узлов (`nodes.py`)

Каждый узел — `async` функция `(state: InitArchState) -> dict` (частичное обновление состояния).

Общий паттерн узла:

```python
import asyncio
import typing

from .guard import run_guard
from .prompts import build_step_prompt
from app.external.claude_cli import run_cli_subprocess


async def node_define_scope(state: InitArchState) -> dict[str, typing.Any]:
    # 1. Инициализируем progress-файл через guard
    guard_out = await run_guard(
        "init",
        "--output", state["progress_file_path"],
        "--product", state["product_name"],
        "--scope", state["analysis_scope"],
    )

    # 2. Строим prompt для LLM
    prompt_text = build_step_prompt(
        step_id="define_scope",
        state=state,
    )

    # 3. Вызываем LLM через CLI
    cli_output = await run_cli_subprocess(
        engine_name=state["engine_name"],
        prompt_text=prompt_text,
        workspace_dir=state["workspace_dir"],
        timeout_seconds=state["timeout_seconds"],
    )

    # 4. Записываем advance в guard
    await run_guard(
        "advance",
        "--progress", state["progress_file_path"],
        "--step", "define_scope",
        "--note", "Scope определён через LangGraph",
    )

    return {
        "current_step_id": "request_repository_list",
        "last_cli_output": cli_output,
        "last_guard_output": guard_out,
        "step_error": None,
    }
```

**Узел `node_request_repository_list`** — использует `interrupt()` для получения списка репозиториев от пользователя:

```python
from langgraph.types import interrupt


async def node_request_repository_list(state: InitArchState) -> dict[str, typing.Any]:
    # Если список уже есть (resume после interrupt) — продолжаем
    if state.get("repo_list"):
        await run_guard("advance", "--progress", state["progress_file_path"],
                        "--step", "request_repository_list",
                        "--note", f"Репозитории: {', '.join(state['repo_list'])}")
        return {"current_step_id": "prepare_temp_workspace", "step_error": None}

    # Иначе — прерываем и запрашиваем список у пользователя
    interrupt({
        "interrupt_type": "user_input",
        "field": "repo_list",
        "question": "Укажите список репозиториев для анализа (имена через запятую или JSON-массив)",
    })
    # Управление не доходит сюда до resume; LangGraph перезапустит узел с обновлённым state
    return {}
```

**Узел `node_interview_user`** — повторяет interrupt по одному вопросу из `open_questions`:

```python
async def node_interview_user(state: InitArchState) -> dict[str, typing.Any]:
    remaining = [q for q in state["open_questions"] if q not in state.get("answered_questions", [])]
    if not remaining:
        await run_guard("advance", "--progress", state["progress_file_path"],
                        "--step", "interview_user", "--note", "Все вопросы закрыты")
        return {"current_step_id": "refine_features", "step_error": None}

    current_question = remaining[0]
    interrupt({
        "interrupt_type": "user_question",
        "question": current_question,
        "remaining_count": len(remaining) - 1,
    })
    return {}
```

***

### 17.6 Сборка промптов (`prompts.py`)

Каждый узел получает промпт из двух частей:

1. **System context** — сжатое содержимое `SKILL.md` скилла (константа, загружается один раз при старте).
2. **Step reference** — содержимое соответствующего reference-чеклиста из `init-repo-arch-skill/references/`.
3. **Контекст состояния** — текущий шаг, имя продукта, список репозиториев, последний вывод guard (JSON progress), артефакты уже созданные.

```python
import pathlib
import typing

_SKILL_ROOT = pathlib.Path("/app/skills/init-repo-arch-skill")

STEP_TO_REFERENCE: typing.Final[dict[str, str]] = {
    "define_scope": "",  # нет reference — контекст из SKILL.md достаточен
    "request_repository_list": "",
    "prepare_temp_workspace": "",
    "clone_repositories": "",
    "refresh_main_branches": "",
    "plan_repository_order": "",
    "assess_scope_and_domains": "references/checklist-scope-and-domain-assessment.md",
    "analyze_repositories": "",  # reference выбирается динамически по текущему checklist-item
    "interview_user": "references/checklist-glossary-and-open-questions.md",
    "refine_features": "references/checklist-features-and-index.md",
    "build_navigation_index": "references/knowledge-workflow.md",
    "run_knowledge_lint": "references/knowledge-workflow.md",
    "validate_final": "references/checklist-repository-consistency-review.md",
    "finalize_progress": "",
}

CHECKLIST_ITEM_TO_REFERENCE: typing.Final[dict[str, str]] = {
    "repository_classification": "references/checklist-repository-classification.md",
    "repository_structure_mapping": "references/checklist-repository-structure-mapping.md",
    "entrypoints_and_interfaces": "references/checklist-entrypoints-and-interfaces.md",
    "business_flow_orchestration": "references/checklist-business-flow-orchestration.md",
    "configs_and_runtime": "references/checklist-configs-and-runtime.md",
    "tech_stack_collection": "references/checklist-tech-stack.md",
    "contracts_and_schemas": "references/checklist-contracts-and-schemas.md",
    "data_and_storage": "references/checklist-data-and-storage.md",
    "domain_entities": "references/checklist-domain-entities.md",
    "integrations_and_dependencies": "references/checklist-integrations-and-dependencies.md",
    "tests_and_behavior_evidence": "references/checklist-tests-and-behavior-evidence.md",
    "glossary_updates": "references/checklist-glossary-and-open-questions.md",
    "open_questions_review_and_updates": "references/checklist-glossary-and-open-questions.md",
    "feature_discovery_and_updates": "references/checklist-features-and-index.md",
    "features_index_updates": "references/checklist-features-and-index.md",
    "roles_and_permissions_updates": "references/checklist-roles-security-operability-risks.md",
    "security_and_auth_updates": "references/checklist-roles-security-operability-risks.md",
    "deployment_and_operability": "references/checklist-roles-security-operability-risks.md",
    "risks_and_tech_debt_updates": "references/checklist-roles-security-operability-risks.md",
    "architecture_artifact_updates": "references/checklist-architecture-artifact-updates.md",
    "repository_consistency_review": "references/checklist-repository-consistency-review.md",
}


def build_step_prompt(step_id: str, state: InitArchState, checklist_item_id: str = "") -> str:
    skill_md = (_SKILL_ROOT / "SKILL.md").read_text()
    reference_path_rel = STEP_TO_REFERENCE.get(step_id, "")
    if step_id == "analyze_repositories" and checklist_item_id:
        reference_path_rel = CHECKLIST_ITEM_TO_REFERENCE.get(checklist_item_id, "")
    reference_text = (_SKILL_ROOT / reference_path_rel).read_text() if reference_path_rel else ""

    return f"""# Контекст навыка

{skill_md}

---

# Текущее задание

Шаг: `{step_id}`
Продукт: {state["product_name"]}
Контур анализа: {state["analysis_scope"]}
Рабочий каталог: {state["workspace_dir"]}
Архитектурный репозиторий: {state["arch_repo_dir"]}
Текущий репозиторий: {state.get("current_repo_name", "—")}
Завершённые шаги: {", ".join(state.get("completed_steps", [])) or "нет"}

---

# Reference-чеклист для этого шага

{reference_text or "(нет дополнительного reference — следуй SKILL.md)"}

---

# Инструкции

Выполни шаг `{step_id}` строго по reference-чеклисту выше.
Работай только с файлами внутри {state["workspace_dir"]}.
Все артефакты пиши в {state["arch_repo_dir"]}.
Путём к progress-файлу является {state["progress_file_path"]} — не трогай его напрямую,
он управляется через analysis_guard.py.
Выведи краткий структурированный JSON-отчёт о выполненных действиях в формате:
{{
  "completed_actions": ["..."],
  "created_artifacts": ["..."],
  "open_questions_found": ["..."],
  "notes": "..."
}}
"""
```

***

### 17.7 Обёртка вокруг `analysis_guard.py` (`guard.py`)

`analysis_guard.py` находится внутри скилла и вызывается как subprocess. Путь к нему прокидывается через settings.

```python
import asyncio
import pathlib

from app.settings import GatewaySettings


async def run_guard(*args: str) -> str:
    settings = GatewaySettings()
    guard_script = pathlib.Path(settings.skill_root_dir) / "init-repo-arch-skill/scripts/analysis_guard.py"
    cmd = ["python", str(guard_script), *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"analysis_guard failed: {stderr.decode()}")
    return stdout.decode()
```

В `GatewaySettings` добавляется поле:

```python
skill_root_dir: str = "/app/skills"
```

В Dockerfile скилл монтируется из volume или копируется в образ:

```dockerfile
COPY --chown=appuser:appuser skills/ /app/skills/
```

***

### 17.8 Checkpointing

Состояние LangGraph-графа сохраняется в **PostgreSQL** через `AsyncPostgresSaver` (из `langgraph-checkpoint-postgres`) — тот же экземпляр Postgres из docker-compose, что и для хранения задач. Отдельная SQLite-БД не нужна.

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
import asyncpg


async def get_checkpointer(database_url: str) -> AsyncPostgresSaver:
    conn = await asyncpg.connect(database_url)
    checkpointer = AsyncPostgresSaver(conn)
    await checkpointer.setup()  # создаёт таблицы checkpoints, если нет
    return checkpointer
```

В `GatewaySettings` используется то же поле `database_url`. `workflow_id` = `thread_id` в терминах LangGraph checkpointer. Позволяет возобновить граф после interrupt или перезапуска сервиса — состояние хранится в Postgres, не теряется при рестарте контейнера.

Зависимость добавляется в `pyproject.toml`:

```toml
"langgraph-checkpoint-postgres>=2.0.0",
```

***

### 17.9 Новые API эндпоинты для LangGraph-воркфлоу

Маршруты добавляются в `app/api/rpc/workflows.py` и `app/api/rest/workflows.py`.

#### `POST /api/rpc/workflows/init/`

Запуск нового `init_arch` воркфлоу. Возвращает `workflow_id` немедленно.

**Request body:**

```json
{
  "product_name": "My Service",
  "analysis_scope": "full",
  "workspace_dir": "/workspace/my-service",
  "arch_repo_dir": "/workspace/my-service/arch-doc",
  "repo_list": ["my-service", "my-service-worker"],
  "engine_name": "claude",
  "timeout_seconds": 600
}
```

Поле `repo_list` опционально — если не передано, граф выполнит `interrupt` и запросит у пользователя через `POST /api/rpc/workflows/{id}/resume/`.

**Response `202 Accepted`:**

```json
{
  "workflow_id": "uuid4",
  "workflow_status": "running",
  "current_step_id": "define_scope",
  "created_at": "ISO8601"
}
```

#### `GET /api/rest/workflows/{workflow_id}/`

Статус и текущий шаг воркфлоу.

**Response:**

```json
{
  "workflow_id": "uuid4",
  "workflow_status": "running|interrupted|success|failed",
  "current_step_id": "analyze_repositories",
  "current_repo_name": "my-service",
  "completed_steps": ["define_scope", "request_repository_list"],
  "pending_interrupt": {
    "interrupt_type": "user_question",
    "question": "Какой протокол использует интеграция с платёжной системой?"
  },
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "last_cli_output_snippet": "..."
}
```

#### `POST /api/rpc/workflows/{workflow_id}/resume/`

Возобновление воркфлоу после interrupt. Тело содержит ответ пользователя.

**Request body (при `interrupt_type: "user_input"`):**

```json
{
  "field": "repo_list",
  "value": ["my-service", "my-service-worker"]
}
```

**Request body (при `interrupt_type: "user_question"`):**

```json
{
  "answer": "Используется синхронный REST через HTTPS"
}
```

**Response `202 Accepted`:**

```json
{
  "workflow_id": "uuid4",
  "workflow_status": "running",
  "current_step_id": "interview_user"
}
```

#### `GET /api/rest/workflows/{workflow_id}/stream/` (SSE)

Стриминг событий LangGraph-воркфлоу в реальном времени.

**Сервер отправляет события:**

```json
{ "event_type": "step_started", "step_id": "analyze_repositories", "repo_name": "my-service" }
{ "event_type": "cli_output", "event_data": "...", "stream_source": "stdout" }
{ "event_type": "step_completed", "step_id": "analyze_repositories", "notes": "..." }
{ "event_type": "interrupted", "interrupt_type": "user_question", "question": "..." }
{ "event_type": "workflow_done", "workflow_status": "success" }
{ "event_type": "workflow_failed", "error_message": "..." }
```

***

### 17.10 Размещение скилла в образе

Файлы `init-repo-arch-skill/` монтируются в контейнер как read-only volume или копируются в образ при сборке. Рекомендуется volume — позволяет обновлять скилл без пересборки образа.

```yaml
# docker-compose.yml
services:
  arch-docs:
    volumes:
      - ./skills:/app/skills:ro   # init-repo-arch-skill, update-repo-arch-skill
```

В `Dockerfile` путь `/app/skills` создаётся заранее:

```dockerfile
RUN mkdir -p /app/skills
```

В settings добавляется:

```python
skill_root_dir: str = "/app/skills"
```

***

### 17.11 Этапы реализации (Версия 2 дополнение)

#### Этап 9. LangGraph-граф `InitArchGraph` ✅ ВЫПОЛНЕНО

Цель: LangGraph-граф управляет полным workflow `init-repo-arch-skill`; CLI-subprocess вызывается из каждого узла; progress-файл ведёт `analysis_guard.py`.

Состав:

- `app/workflows/init_arch/state.py` — `InitArchState` TypedDict;
- `app/workflows/init_arch/guard.py` — `run_guard()` subprocess-обёртка;
- `app/workflows/init_arch/prompts.py` — `build_step_prompt()`, `STEP_TO_REFERENCE`, `CHECKLIST_ITEM_TO_REFERENCE`;
- `app/workflows/init_arch/nodes.py` — по одной async-функции на каждый из 14 шагов `STEP_DEFINITIONS`; узел `node_analyze_repositories` реализует вложенный цикл по репозиториям и чеклист-пунктам;
- `app/workflows/init_arch/graph.py` — `StateGraph`, регистрация узлов и рёбер, `compile()` с `checkpointer`;
- `app/workflows/init_arch/checkpointer.py` — `AsyncSqliteSaver`, путь из `GatewaySettings.langgraph_db_path`;
- `app/services/workflow_registry.py` — in-memory реестр `workflow_id → asyncio.Task`;
- `app/api/rpc/workflows.py` — `POST /api/rpc/workflows/init/`, `POST /api/rpc/workflows/{id}/resume/`;
- `app/api/rest/workflows.py` — `GET /api/rest/workflows/{id}/`;
- `app/api/rest/workflows.py` — `GET /api/rest/workflows/{id}/stream/` (SSE);
- `tests/workflows/init_arch/` — тесты с mock CLI subprocess и mock guard.

Критерий готовности:

- `POST /api/rpc/workflows/init/` запускает граф, возвращает `workflow_id` немедленно;
- граф последовательно проходит все 14 шагов, вызывая CLI через subprocess на каждом шаге;
- interrupt срабатывает на `node_request_repository_list` и `node_interview_user`; `resume` возобновляет граф корректно;
- `analysis_guard.py advance` вызывается после каждого шага, progress-файл консистентен;
- при ошибке CLI на шаге — retry до 3 раз, затем `workflow_status: failed`;
- restart контейнера при наличии checkpoint возобновляет граф с последнего шага;
- `just agent-check` проходит; покрытие дельты — 100%.
