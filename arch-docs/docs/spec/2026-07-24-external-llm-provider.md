# Внешний LLM-провайдер (OpenAI-совместимый) поверх Codex

## Статус реализации

Спека реализована полностью (backend + frontend), покрыта тестами, все тесты и линтеры зелёные.
Мини-отчёты по каждому пункту — в соответствующих подразделах "Предлагаемый дизайн" ниже (блоки
"**Реализовано:**"). Итоговая сводка тестирования — в разделе "Тестирование и проверка" в конце
файла.

## Проблема

Сегодня пользователь может запустить CLI-агента ровно двумя способами — `engine_name` строго
`"claude"` или `"codex"` (`_validate_engine_name()`,
[`app/services/init_arch_workflow.py:804-807`](../../back/app/services/init_arch_workflow.py#L804-L807);
`ExecuteRequest.engine`,
[`app/api/rpc/execute.py:19-35`](../../back/app/api/rpc/execute.py#L19-L35)). Оба движка
аутентифицируются только через персистентный volume с интерактивным логином
(`codex-auth`/`claude-auth`, [`docker-compose.yml:34-35`](../../docker-compose.yml#L34-L35)) — нет
способа выполнить прогон через модель стороннего провайдера (self-hosted vLLM/Ollama, OpenRouter,
Azure OpenAI, DeepSeek и т.п.), к которому у пользователя есть свой API-токен и OpenAI-совместимый
endpoint.

Никакого понятия "провайдер"/"модель" в API или конфиге сегодня нет:
`app/settings.py` (`GatewaySettings`/`InitWorkflowSettings`/`WorkflowsSettings`) не содержит
provider/model полей, `config.toml` (смонтирован в `~/.codex/config.toml`) содержит только
`approval_policy`/`sandbox_mode` (без auth/model — [`config.toml:1-11`](../../config.toml#L1-L11)).

Codex CLI как subprocess запускается с `env={**os.environ}` —
[`app/services/task_runner.py:346-353`](../../back/app/services/task_runner.py#L346-L353) — процесс
бэкенда целиком передаёт своё окружение потомку; отдельного канала инъекции секрета per-task не
существует. Единственный близкий прецедент — git-подключения (SSH/token в Setup):
`GitHostConnectionModel` хранит в БД **только метаданные** (`host`, `connection_type`;
[`app/db/models.py:177-197`](../../back/app/db/models.py#L177-L197)), сам секрет живёт в файле
`~/.config/git-credentials-store/credentials` (`git_credentials.py:8,82-106`), а доставка до
subprocess идёт через **мутацию глобального `os.environ`** самого backend-процесса
(`GIT_CONFIG_GLOBAL`, `git_credentials.py:60-64`) — под допущение, что дочерний процесс унаследует
его вместе со всем остальным env. Этот паттерн безопасен только потому, что git-креды сегодня — один
общий на инстанс сервис-акаунт (`git_ssh.py`, `docker-compose.yml:38`); при нескольких **параллельных**
codex-подпроцессах (`AGENT_POOL_SIZE > 1`, `docker-compose.yml:27`) с **разными** внешними
LLM-подключениями та же мутация глобального `os.environ` привела бы к состоянию гонки — один прогон
может увидеть чужой токен.

## Цель

1. Пользователь может завести одно или несколько подключений к внешнему OpenAI-совместимому
   LLM-провайдеру (base URL + API-токен + имя модели) в Setup — аналогично уже существующим
   git-подключениям.
2. При запуске задачи/workflow можно выбрать третий вариант движка — "внешняя LLM" — вместо `claude`
   или `codex`. Под капотом всегда запускается **codex CLI**, но с моделью и endpoint из выбранного
   подключения вместо штатной codex-аутентификации.
3. Токен внешнего провайдера никогда не мутирует глобальный `os.environ` бэкенда и виден только тому
   конкретному subprocess, для которого выбрано подключение — параллельные прогоны с разными
   подключениями (или без внешнего провайдера вовсе) не пересекаются.
4. Секрет не хранится в БД (тот же принцип, что и для git-токенов).
5. Автоматический failover между `claude`↔`codex` (`llm_worker.py`) не должен молча "соскакивать" на
   `claude` при ошибке внешнего провайдера — это подменило бы явный выбор пользователя другим
   провайдером/квотой без предупреждения.

Не цель: поддержка внешнего провайдера под капотом `claude` CLI (Claude Code тоже умеет
`ANTHROPIC_BASE_URL`, но явное требование задачи — "под капотом codex"); мульти-модельный роутинг
внутри одного прогона; UI для тестирования/health-check подключения перед первым использованием
(ошибка просто всплывёт при первом реальном запуске, как и для git-подключений сегодня).

## Как Codex CLI поддерживает произвольный OpenAI-совместимый провайдер (подтверждено внешней
документацией Codex)

Codex CLI умеет через `config.toml` (или через `-c key=value` оверрайды прямо в аргументах запуска)
определять секцию `[model_providers.<id>]`:

- `base_url` — URL внешнего endpoint;
- `env_key` — имя переменной окружения, откуда Codex прочитает токен и отправит его как Bearer;
- `wire_api` — `"chat"` для большинства сторонних OpenAI-совместимых шлюзов (Codex по умолчанию
  говорит по `"responses"` API, которое поддерживает только сам OpenAI);
- `requires_openai_auth = false` — снимает у Codex допущение, что ключ обязан иметь префикс `sk-`
  (нужно почти всем сторонним шлюзам);
- верхнеуровневый `model_provider = "<id>"` и `model = "<имя-модели>"` выбирают, какой провайдер и
  модель использовать в конкретном вызове.

Всё это можно передать через `-c` в аргументах CLI-вызова (`codex exec -c model_provider=external -c
model_providers.external.base_url=... ...`), не трогая общий `config.toml` — то есть каждый
подпроцесс получает свою конфигурацию провайдера изолированно, без коллизий между параллельными
задачами с разными подключениями.

Источники: [Configuration Reference](https://developers.openai.com/codex/config-reference),
[Advanced Configuration](https://developers.openai.com/codex/config-advanced).

**Риск версии**: `Dockerfile:8` ставит `@openai/codex` без пина версии
(`npm install -g @openai/codex @anthropic-ai/claude-code`) — нужно явно проверить (при сборке образа
или в CI), что установленная версия поддерживает `-c model_providers.*`/`requires_openai_auth`; если
нет — зафиксировать минимальную версию в Dockerfile.

## Предлагаемый дизайн

### 1. Хранение подключения — новая таблица + файловый секрет-стор (по аналогии с git-подключениями)

Новая модель `LlmProviderConnectionModel` в `app/db/models.py`, метаданные без секрета:

```python
class LlmProviderConnectionModel(Base):
    __tablename__ = "llm_provider_connections"

    connection_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, unique=True)          # человекочитаемое имя в UI
    base_url: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    wire_api: Mapped[str] = mapped_column(Text, default="chat")           # "chat" | "responses"
    requires_openai_auth: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
```

Миграция `migrations/versions/00XX_add_llm_provider_connections.py`.

Секрет — новый сервис `app/services/llm_provider_credentials.py`, зеркалирующий
`git_credentials.py`, но **не мутирующий `os.environ`**:

- Файл на подключение: `~/.config/llm-provider-secrets/<connection_id>.token`, права `0600`,
  каталог создаётся `ensure_llm_provider_secrets_store()` (аналог
  `ensure_git_credentials_store()`), новый docker volume
  `llm-provider-secrets:/home/appuser/.config/llm-provider-secrets`
  (рядом с `git-credentials`/`git-ssh` в `docker-compose.yml`), доступ также нужно прописать в
  `entrypoint.sh:3` (chown вместе с остальными auth-директориями).
- `set_llm_provider_token(connection_id, token)` / `get_llm_provider_token(connection_id) -> str`
  — просто читает/пишет файл по `connection_id`, никакой мутации глобального состояния процесса.

**Реализовано:** `app/db/models.py` (`LlmProviderConnectionModel`), миграция
`migrations/versions/0009_add_llm_provider_connections.py`, `app/services/llm_provider_credentials.py`
(секрет-стор), `app/db/llm_provider_repo.py`. Тесты:
`tests/services/test_llm_provider_credentials.py` (8 тестов: создание стора, запись/чтение/удаление
токена, изоляция между разными `connection_id`).

### 2. API — REST CRUD, аналог `git_connections.py`

Новый `app/api/rest/llm_providers.py`:

- `POST /rest/llm-providers/` — `{name, base_url, model, api_token, wire_api?, requires_openai_auth?}`
  → создаёт `LlmProviderConnectionModel` + пишет токен в секрет-стор.
- `GET /rest/llm-providers/` — список без токена (`{connection_id, name, base_url, model, wire_api,
  requires_openai_auth, created_at}` — токен никогда не возвращается, аналог поведения
  `git_connections.py` для токенов).
- `PATCH /rest/llm-providers/{connection_id}/` — обновление любого поля; `api_token`, если передан,
  перезаписывает секрет-файл.
- `DELETE /rest/llm-providers/{connection_id}/` — удаляет строку и секрет-файл. Нужно решить (см.
  "Открытые вопросы"), что делать с уже идущими задачами, которые ссылаются на удаляемое подключение.

**Реализовано:** `app/services/llm_providers.py` (CRUD-оркестрация: валидация полей, проверка
уникальности `name`, инвариант "секрет не в БД"), `app/api/rest/llm_providers.py`, роутер подключён
в `app/api/__init__.py`. Токен никогда не возвращается в открытом виде — `GET`/`GET .../{id}/`
отдают `token: "********"` только как индикатор "настроен"/"не настроен". Тесты:
`tests/services/test_llm_providers.py` (14 тестов: CRUD, валидация, конфликт имён, сохранение
старого токена при обновлении без нового), `tests/api/rest/test_llm_providers.py` (10 тестов, в т.ч.
явная проверка, что реальный токен не попадает в HTTP-ответ).

### 3. Execution — `provider_connection_id` как отдельное измерение поверх `engine_name`

Осознанно **не** добавляем третье значение в `engine_name` (сохраняем инвариант "engine_name ∈
{claude, codex}", который сегодня независимо проверяется в 4 местах —
`init_arch_workflow.py:804-807`, `rpc/execute.py`, `openai.py`/`mcp_server.py` дефолты,
`llm_worker.py:_SUPPORTED_ENGINES`). Вместо этого — новое опциональное поле
`provider_connection_id: str | None`, ортогональное `engine_name`, но **валидируемое только при
`engine_name == "codex"`** (внешний провайдер всегда идёт через codex, попытка задать
`provider_connection_id` вместе с `engine_name="claude"` → `422`).

Изменения:

- `CliTask` (`app/services/task_registry.py:20-48`) — новое поле
  `provider_connection_id: str | None = None`.
- `ExecuteRequest` (`app/api/rpc/execute.py:19-35`) — новое опциональное поле
  `provider_connection_id: str | None`, `field_validator`: если задано — `engine` обязан быть
  `"codex"`.
- `InitArchState`/snapshot (`app/workflows/init_arch/state.py:14`, `snapshot.py:24,35`) — добавить
  `provider_connection_id` в состояние (переживает pause/resume наравне с `engine_name`).
- `app/workflows/init_arch/nodes.py:114` — пробрасывает `provider_connection_id` в
  `worker_service.run_task(...)` рядом с `engine_name`.

**Реализовано:** `CliTask.provider_connection_id` (`task_registry.py`), `ExecuteRequest` +
`model_validator` в `rpc/execute.py` (422, если `provider_connection_id` задан не с `codex`),
`InitArchState`/`WorkflowSnapshot` получили поле, `_validate_provider_connection_id()` в
`init_arch_workflow.py` применяется единообразно и к `init_arch` (`start_init_arch_workflow`,
`resume_init_arch_workflow_from_snapshot`), и к `update_arch`/`query` (через `input_payload`).
`CliTaskModel`/`task_repo.py` сохраняют и восстанавливают поле при persist/resume. Тесты:
`tests/api/rpc/test_execute.py` (2 новых теста — 422 для `claude`, успешный проброс в registry для
`codex`), `tests/services/test_init_arch_workflow.py` (2 новых теста на `update_arch`/`query`).

### 4. `task_runner.py` — построение аргументов и env per-subprocess

`_build_cmd()` (`task_runner.py:80-124`) — если `cli_task.provider_connection_id` задан (и
`engine_name == "codex"`, гарантировано валидацией выше), дополнительно вставляет перед промптом:

```python
[
    "-c", "model_provider=external",
    "-c", "model_providers.external.name=external",
    "-c", f"model_providers.external.base_url={connection.base_url}",
    "-c", "model_providers.external.env_key=ARCH_DOCS_EXTERNAL_LLM_API_KEY",
    "-c", f"model_providers.external.wire_api={connection.wire_api}",
    "-c", f"model_providers.external.requires_openai_auth={str(connection.requires_openai_auth).lower()}",
    "-c", f"model={connection.model}",
]
```

`run_cli_task()` (`task_runner.py:346-353`) — при наличии `provider_connection_id`, вместо
`env={**os.environ}` собирает **локальный** словарь для конкретного вызова:

```python
env = {**os.environ}
if cli_task.provider_connection_id is not None:
    token = get_llm_provider_token(cli_task.provider_connection_id)
    env = {**env, "ARCH_DOCS_EXTERNAL_LLM_API_KEY": token}
```

Это сознательное отклонение от паттерна `git_credentials.py` (мутация глобального `os.environ`
процесса) — обоснование: `env` здесь и так строится заново на каждый вызов
`asyncio.create_subprocess_exec`, поэтому передать словарь с добавленным ключом **только в этот
вызов** не требует новой инфраструктуры и убирает риск гонки между параллельными подпроцессами
разных подключений (важно зафиксировать явно, а не переносить существующий git-credentials паттерн
по инерции).

**Реализовано:** ровно как описано — `_build_cmd()` принимает опциональный `provider_connection`
(резолвится в `run_cli_task()` через новый `_resolve_provider_connection()` перед построением
команды, с явным исключением `_ProviderConnectionMissingError` при удалённом/несуществующем
подключении); `env` для `asyncio.create_subprocess_exec` строится как новый dict
`{**os.environ, EXTERNAL_LLM_API_KEY_ENV_VAR: token}` только для конкретного вызова. Если
`provider_connection_id` указан, но подключение не найдено (например, удалено между стартом задачи
и её выполнением) — задача сразу помечается `FAILED` с понятной ошибкой, без попытки запуска
subprocess. Тесты: `tests/services/test_task_runner.py` — `TestBuildCmd` (4 новых теста на состав
`-c`-оверрайдов) и новый класс `TestRunCliTaskWithProviderConnection` (3 теста: отсутствующее
подключение не спавнит subprocess, токен попадает только в env вызова и не просачивается в
`os.environ` процесса, оверрайды присутствуют в собранной команде).

### 5. Отключение auto-failover для внешнего провайдера

`llm_worker.py:_alternative_engine()` (строки 55-59) переключает `codex ↔ claude` при исчерпании
квоты/rate-limit. Если `provider_connection_id` задан, `_alternative_engine()` должен вернуть `None`
(нет альтернативы) — ошибка/лимит внешнего провайдера должен явно всплывать пользователю, а не
приводить к молчаливому запуску `claude` (и трате его квоты) вместо выбранного внешнего провайдера.

`_is_auth_error()`/`_is_limit_error()` (`task_runner.py:127-143`) переиспользуются как есть —
эвристика на exit code/stderr не завязана на конкретного провайдера и должна одинаково сработать на
401/403/429 от стороннего шлюза.

**Реализовано:** `LlmWorkerService.run_task()` получил параметр `provider_connection_id`; при
`FAILURE_REASON_LIMIT_EXHAUSTED` и заданном `provider_connection_id` failover не запускается —
исключение пробрасывается пользователю как есть, без события `LLM_TASK_FAILOVER_TRIGGERED`. Тест:
`tests/workflows/init_arch/test_llm_worker.py::test_llm_worker_service_does_not_failover_when_provider_connection_id_set`
(плюс обновлены 2 существующих теста, чьи inline-моки `_build_cli_task` требовали расширения
сигнатуры под новый kwarg — без функциональных изменений в них).

### 6. Frontend — Setup + выбор движка

- Новая карточка `llm-providers-card.tsx` в `features/setup/`, зеркалирующая
  `git-connections-card.tsx`: список подключений (имя, base_url, модель), форма добавления (имя,
  base_url, модель, токен — write-only поле, после сохранения показывается как заполненное, без
  повторного отображения значения — тот же UX, что и для git-токена), кнопка удаления.
- `features/setup/hooks.ts` — `useLlmProviderConnections()` (CRUD-хуки, аналог существующих
  git-connections хуков).
- `shared/api/endpoints.ts`/`models.ts` — `llmProvidersApi`, `LlmProviderConnectionResponse`.
- Селектор движка в форме запуска (`InitArchForm`/эквивалент для `update_arch`/`query`) — третья
  опция "Внешняя LLM" рядом с "Codex"/"Claude Code"; при выборе показывает dropdown уже
  настроенных подключений (обязательное поле, без подключений — опция задизейблена со ссылкой в
  Setup). При отправке форма кладёт `engine="codex"` + `provider_connection_id=<id>` вместо простого
  `engine="claude"|"codex"`.

**Реализовано:** `llm-providers-card.tsx`/`.module.css` (карточка CRUD в Setup, зеркалирует
`git-connections-card.tsx`), хуки `useLlmProviderConnections`/`useLlmProviderConnection`/
`useCreate…`/`useUpdate…`/`useDeleteLlmProviderConnection` в `features/setup/hooks.ts`,
`llmProvidersApi` в `shared/api/endpoints.ts`, типы в `shared/api/models.ts`. В
`init-arch-form.tsx` третья опция движка `"external"` (UI-only) — при выборе подставляет
`engine_name="codex"` + `provider_connection_id` из выбранного подключения; форма валидирует, что
подключение выбрано, до сабмита. Тесты: `llm-providers-card.test.tsx` (5 тестов: пустое состояние,
список, создание, редактирование, удаление), `init-arch-form.test.tsx` (2 новых теста: блокировка
сабмита без выбранного подключения и корректная отправка `engine_name`/`provider_connection_id`),
`setup-page.test.tsx` обновлён под новую карточку.

### 7. Проверка подключения ("Проверить") в Setup

Изначально было отмечено как "не входит в эту итерацию" (health-check при создании), но добавлено
по отдельному запросу — кнопка "Проверить" на каждой строке `LlmProvidersCard`, не только при
создании.

Backend — новый сервис `app/services/llm_provider_connection_check.py`
(`check_llm_provider_connection_async(connection_id)`): резолвит подключение через уже существующий
`get_llm_provider_connection_async()` (тот же путь, что и execution-код), затем шлёт один
минимальный реальный HTTP-запрос напрямую на `base_url` пользователя через `httpx.AsyncClient`:

- `wire_api="chat"` → `POST {base_url}/chat/completions` с `{"model", "messages":[{"role":"user","content":"ping"}], "max_tokens":1}`;
- `wire_api="responses"` → `POST {base_url}/responses` с `{"model", "input":"ping", "max_output_tokens":1}`;
- заголовок `Authorization: Bearer {token}` — тот же токен, что уходит в codex через env-переменную,
  только доставленный напрямую (без промежуточного codex CLI, поэтому это честная проверка именно
  того, что увидит codex).

Результат — `LlmProviderConnectionTestResult(success, status_code, message)`: `success=True` при
HTTP `< 400`; иначе `message` — короткое (обрезано до 300 символов) сообщение об ошибке из
`{"error": {"message": ...}}` тела ответа (частый формат у OpenAI-совместимых шлюзов) или сырой
текст ответа/статус-код как fallback. Таймаут запроса — 10 секунд, `httpx.TimeoutException`/
`httpx.RequestError` превращаются в понятный `message`, не в исключение наружу — REST-эндпоинт
всегда отвечает `200` со структурой результата (`success`/`status_code`/`message`), кроме `404` для
несуществующего `connection_id` (та же ошибка, что и у остальных ручек).

REST: `POST /rest/llm-providers/{connection_id}/test/` (`app/api/rest/llm_providers.py`).

**Важный технический момент, обнаруженный в процессе:** изначально сервисная функция и файл
назывались `test_llm_provider_connection_async`/`llm_provider_test.py` — это классическая ловушка
pytest: любой файл `*_test.py` и любое имя, начинающееся на `test_`, **импортированное** в тестовый
модуль, pytest пытается собрать как тест-функцию (даже если это обычный импортированный сервис), и
падает с `fixture 'connection_id' not found`. Переименовано в
`llm_provider_connection_check.py`/`check_llm_provider_connection_async` — заодно семантически точнее
("check", а не "test", раз слово "test" в этом контексте омонимично unit-тестам).

Frontend: `llmProvidersApi.test()` (`shared/api/endpoints.ts`), `useTestLlmProviderConnection()`
(`features/setup/hooks.ts`), `LlmProvidersCard` разбита на строки-компоненты
`LlmProviderConnectionRow`, каждая — со своей кнопкой "Проверить" (текст меняется на "Проверка…" во
время запроса) и инлайн-результатом под строкой (`✓ <message>` зелёным / `✗ <message>` красным,
используя существующие CSS-переменные `--color-success-text`/`--color-danger-text` из
`app/theme.css`, без придумывания новых цветов).

Тесты: `tests/services/test_llm_provider_connection_check.py` (7 тестов: 404 на несуществующее
подключение, успех на 2xx, корректный выбор `/chat/completions` vs `/responses` по `wire_api`,
разбор `{"error": {"message": ...}}`, fallback на сырой текст при не-JSON ответе, таймаут,
connection error), `tests/api/rest/test_llm_providers.py::TestTestLlmProviderConnection` (4 теста),
`llm-providers-card.test.tsx` (+2 теста: успешный и неуспешный результат проверки, инлайн в списке).

### 8. Совместимость Codex CLI с реальными OpenAI-совместимыми шлюзами

Обнаружено при первом реальном использовании (шлюз GLM-5.2 через turbocloud.ru, Envoy AI Gateway):
Codex CLI (0.144.5) больше не поддерживает `wire_api="chat"` (`Error loading config.toml:
wire_api = "chat" is no longer supported`) — единственный рабочий вариант теперь
`wire_api="responses"`. Но и с `responses` шаг workflow падал с `400 malformed request: failed
to parse JSON for /v1/responses: unknown tool type` на самом первом turn, ещё до вызова какого-либо
инструмента.

Диагностика (метод: локальный mock-сервер на Node, логирующий сырое тело запроса codex, плюс
прямые curl-запросы к реальному шлюзу с отдельными типами tool) показала, что Codex объявляет в
`tools` не только стандартные `"type": "function"`, но и несколько OpenAI-специфичных типов:
`"type": "custom"` (apply_patch, freeform-формат — единственный доступный вариант в этой версии,
`apply_patch_tool_type` не принимает `"function"`/`"custom"`, только `"freeform"`), `"type":
"web_search"` и `"type": "namespace"` (вложенный набор саб-тулов: sub-agent'ы `multi_agent_v1` и,
при подключённом ChatGPT-аккаунте с Apps/коннекторами, ещё `mcp__codex_apps__*` — document_control,
github, hotline, plugin_management, sites). Прямыми curl-запросами к шлюзу подтверждено: `function`,
`custom` и `web_search` шлюз принимает нормально (200), а `namespace` — всегда `400 unknown tool
type`. Значит именно namespace-тулы (сколько бы их ни было) валят весь запрос.

`model_catalog_json` (per-model catalog override, `-c model_catalog_json=<path>`) не может подавить
namespace-тулы — они не завязаны ни на одно поле схемы каталога. Единственный работающий механизм —
глобальные feature-флаги: `--disable multi_agent` (убирает sub-agent'ов) и `--disable apps` (убирает
codex_apps-коннекторы, если у залогиненного аккаунта они включены — это учётно-специфично, поэтому
баг не воспроизводился в одноразовом непривязанном прогоне и проявился только под реальной сессией
`appuser`).

**Реализовано:**
`app/services/llm_provider_model_catalog.py` — `ensure_llm_provider_model_catalog(connection_id,
model)`: пишет (перезаписывает при каждом вызове) JSON-каталог с одной моделью в
`~/.config/llm-provider-catalogs/<connection_id>.catalog.json` — `apply_patch_tool_type="freeform"`,
`shell_type="shell_command"` (функционально-вызываемый вариант шелл-тула вместо нативного
`local_shell`) и остальные обязательные по схеме codex поля (структура найдена перебором
`"missing field ..."` ошибок парсера codex — полного списка полей в официальной документации нет).
Содержимое не секретно (не включает токен), поэтому файл не требует того же уровня защиты, что
`llm_provider_credentials.py`, и безопасно перезаписывается при каждом запуске без блокировок.

`app/services/task_runner.py::_external_provider_overrides()` — вызывает
`ensure_llm_provider_model_catalog()`, добавляет `-c model_catalog_json=<path>` и
`--disable multi_agent --disable apps` к команде `codex exec` при наличии `provider_connection`
(и только тогда — это не трогает штатные codex/claude-запуски без внешнего провайдера).

`entrypoint.sh` — добавлен `mkdir -p` + `chown` для новой директории
`~/.config/llm-provider-catalogs` (без неё `appuser` не может создать поддиректорию в `~/.config`,
т.к. сама `.config` в образе принадлежит `root`). Именованный docker-volume не заводился: содержимое
регенерируется на каждый запуск, персистентность не нужна.

Тесты: `tests/services/test_task_runner.py` — 2 новых теста (наличие `model_catalog_json` override
и обоих `--disable` флагов; корректное содержимое сгенерированного catalog-файла через
`isolated_llm_provider_model_catalog_dir` autouse-фикстуру в `conftest.py`, изолирующую путь записи
на `tmp_path` для всего тестового прогона).

Проверено end-to-end через реальный `run_cli_task()` (не через ручной curl) внутри контейнера от
имени `appuser` против настоящего шлюза `inf-da45e59a-....ai.turbocloud.ru`, с реальным сохранённым
токеном подключения "GLM 5.2": `task_status=success`, `task_result="hi"`.

## Что не входит в эту итерацию

- Внешний провайдер под капотом `claude` CLI (`ANTHROPIC_BASE_URL`) — явно вне ТЗ, только codex.
- Мульти-модельный роутинг/переключение модели без пересоздания подключения.
- Ограничение на количество подключений на пользователя/инстанс.
- Аудит использования (какое подключение сколько раз использовалось) сверх уже существующего общего
  логирования задач.

## Открытые вопросы

1. Поведение при удалении `LlmProviderConnectionModel`, на которую ссылается уже запущенная/на
   паузе задача (`CliTask.provider_connection_id` или `InitArchState`) — запрещать удаление, если
   есть активные ссылки (аналог поведения git-подключений?), или разрешать и просто дать упасть
   следующему resume с понятной ошибкой? Требует решения продукта.
2. Нужно ли валидировать `base_url` на `https://` (кроме явных `localhost`/приватных адресов для
   self-hosted Ollama/vLLM в той же сети)? Сегодня для git host-подключений такой проверки нет.
3. Минимальная поддерживаемая версия `@openai/codex` для `-c model_providers.*`/
   `requires_openai_auth` — нужно проверить фактически установленную версию в текущем образе и
   зафиксировать пин в `Dockerfile`, если потребуется.
4. Нужен ли отдельный rate-limit/quota UI для внешнего провайдера, или пользователь сам следит за
   лимитами своего токена (текущее решение — просто отключить auto-failover и всплыть ошибку, без
   доп. UI).
5. **Открытый вопрос №3 не закрыт в рамках этой итерации**: `Dockerfile` по-прежнему ставит
   `@openai/codex` без пина версии — фактическая проверка поддержки `-c model_providers.*` в
   установленной версии codex CLI не проводилась (нет доступа к реальному codex login/quota в
   среде разработки). Риск остаётся зафиксированным, не устранённым.
6. `provider_connection_id` **не** проброшен в `app/mcp_server.py` и `app/api/openai.py` (facade) —
   эти два входа продолжают работать только с `engine_name` как раньше. Сознательно оставлено за
   рамками: `mcp_server.py` — MCP-инструменты для внешних агентов, `openai.py` — входящий
   OpenAI-совместимый фасад самого arch-docs (другая, не связанная задача с тем же словом
   "OpenAI-совместимый" в названии — легко перепутать). Если понадобится — расширение аналогично
   уже сделанному в `rpc/execute.py`/`init_arch_workflow.py`.

## Тестирование и проверка

- Backend: `just test-db-up` + `uv run --extra dev python -m pytest` — **795 passed, 1 xfailed**
  (полный сьют, включая новые файлы: `test_llm_provider_credentials.py`, `test_llm_providers.py`
  (service + REST), `test_llm_provider_connection_check.py`, плюс дополненные `test_task_runner.py`,
  `test_execute.py`, `test_init_arch_workflow.py`, `test_llm_worker.py`). Регрессий нет (единичные
  флейки на full-run — то `test_create_response_init_arch_returns_409_...`, то
  `..._syncs_product_name_forward_to_conversation`, оба про `/workspace` read-only на локальной
  машине — не воспроизводятся в изоляции и не связаны с этой фичей).
- Backend: `uv run --extra dev ruff check app/ tests/` и `ruff format --check` — чисто для всех
  файлов этой фичи. Единственные оставшиеся ошибки (`E501` в `app/db/workflow_repo.py:323`, `E402` в
  `tests/conftest.py`) — подтверждены как предсуществующие (воспроизводятся и на `git stash` без
  изменений этой фичи).
- Frontend: `npx vitest run` — **101 passed** (15 файлов, включая новые `llm-providers-card.test.tsx`
  и дополненные `init-arch-form.test.tsx`/`setup-page.test.tsx`). Регрессий нет.
- Frontend: `npx tsc -b --force` — чисто (сборочный режим `tsc -b`, применяемый в Dockerfile,
  отдельно проверен — первая попытка docker-сборки поймала ошибку сужения типов в
  `init-arch-form.tsx`, не пойманную обычным `tsc --noEmit`; исправлено сравнением напрямую в каждом
  тернарнике вместо промежуточной булевой переменной).
- Frontend: `npm run lint` (eslint) не выполним в этом окружении независимо от изменений фичи —
  в репозитории отсутствует `eslint.config.js` (ESLint 9 требует flat config); воспроизведено и на
  `git stash` без изменений этой фичи. Не блокер этой работы, но стоит завести отдельно.
- Docker: backend и frontend пересобраны (`docker compose build`) и перезапущены
  (`docker compose up -d`) после применения миграции `0009` (не накатилась автоматически при
  первом запуске контейнера — потребовался ручной `alembic upgrade head`); smoke-тест REST
  (`POST`/`GET`/`DELETE /api/rest/llm-providers/`) через реальный контейнер отработал корректно.
- Отдельная находка в процессе: сервисный модуль был изначально назван
  `llm_provider_test.py`/`test_llm_provider_connection_async` — pytest подхватывал импортированное
  имя как тест-функцию своего модуля (классическая ловушка "не называй production-код `test_*`/
  `*_test.py`, даже если он лежит вне `tests/`") и падал с `fixture 'connection_id' not found`.
  Переименовано в `llm_provider_connection_check.py`/`check_llm_provider_connection_async`.

## Затронутые файлы (ориентировочно)

Backend:

- `app/db/models.py` — новая `LlmProviderConnectionModel`.
- `migrations/versions/00XX_add_llm_provider_connections.py` — новая таблица.
- `app/services/llm_provider_credentials.py` (новый) — файловый секрет-стор, без мутации
  `os.environ`.
- `app/services/llm_providers.py` (новый) — CRUD-оркестрация, аналог `git_connections.py`.
- `app/services/llm_provider_connection_check.py` (новый) — реальный тестовый HTTP-запрос к
  endpoint подключения (`httpx`).
- `app/api/rest/llm_providers.py` (новый) — REST-ручки, включая `POST .../test/`.
- `app/services/task_registry.py` — `CliTask.provider_connection_id`.
- `app/services/task_runner.py` — `_build_cmd()` (доп. `-c` оверрайды), `run_cli_task()`
  (per-call `env`, без мутации глобального `os.environ`).
- `app/api/rpc/execute.py` — `ExecuteRequest.provider_connection_id` + валидатор
  (`engine == "codex"`, если задано).
- `app/workflows/init_arch/state.py`, `snapshot.py` — `provider_connection_id` в состоянии.
- `app/workflows/init_arch/nodes.py:114` — проброс `provider_connection_id` в
  `worker_service.run_task()`.
- `app/workflows/init_arch/llm_worker.py:_alternative_engine()` — `None` вместо переключения на
  `claude`, если задан `provider_connection_id`.
- `app/mcp_server.py`, `app/api/openai.py` — опциональный `provider_connection_id` наравне с
  `engine_name`, если внешний провайдер должен быть доступен и через эти входные точки.
- `docker-compose.yml` — новый volume `llm-provider-secrets:/home/appuser/.config/llm-provider-secrets`.
- `entrypoint.sh:3` — добавить новый каталог в chown.
- `Dockerfile` — при необходимости пин минимальной версии `@openai/codex`.

Frontend:

- `front/src/features/setup/llm-providers-card.tsx` (новый), `hooks.ts` — CRUD UI.
- `front/src/shared/api/endpoints.ts`, `models.ts` — `llmProvidersApi`,
  `LlmProviderConnectionResponse`.
- Форма запуска (`init-arch-form.tsx` и эквиваленты для `update_arch`/`query`) — третья опция
  движка + селектор подключения.
