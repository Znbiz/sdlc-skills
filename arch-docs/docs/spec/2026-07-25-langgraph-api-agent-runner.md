# LangGraph-агент как четвёртый способ исполнения (прямой API, без CLI-subprocess)

## Статус реализации

Реализовано полностью (backend + frontend), покрыто тестами (unit + реальный e2e против
production-подключения "GLM 5.2"), все тесты и линтеры зелёные. Мини-отчёты — в блоках
"**Реализовано:**"/пометках по разделам ниже. Итоговая сводка — в разделе "Тестирование и
проверка" в конце файла.

**Важная находка e2e, изменившая дизайн относительно черновика (2026-07-25):** черновая версия
этого документа планировала `use_responses_api=(connection.wire_api == "responses")` — то есть
доверять полю `wire_api` подключения. Реальный e2e-прогон против уже настроенного production
подключения "GLM 5.2" (`wire_api="responses"`, заведено для codex в рамках
[2026-07-24-external-llm-provider.md](2026-07-24-external-llm-provider.md)) обнаружил, что это
падает: `langchain_openai` кидает `TypeError: unsupported operand type(s) for +: 'NoneType' and
'NoneType'` внутри собственного парсинга ответа Responses API этого шлюза (`input_tokens`/
`output_tokens` в `usage` шлюз оставляет пустыми, а `langchain_openai` пытается сложить их как
fallback для `total_tokens`). Прямая проверка тем же клиентом в режиме Chat Completions против
того же шлюза/модели прошла успешно с корректным usage. Вывод: `wire_api="responses"` в модели
подключения отражает потребность **codex** (у более новых версий codex CLI нет других вариантов,
см. [2026-07-24-external-llm-provider.md, секция 8](2026-07-24-external-llm-provider.md)), а не
универсальную характеристику шлюза и не требование LangGraph-пути. Решение: `_build_model()`
(раздел 4) **всегда** использует Chat Completions (`use_responses_api=False`), независимо от
`connection.wire_api`. Подробности — в комментарии к `_build_model()` в
`app/services/langgraph_task_runner.py`.

Основные открытые вопросы разобраны и закрыты (2026-07-25): совместимость с `wire_api="responses"`
закрыта описанной выше находкой (а не изначальным планом использовать флаг из подключения), модель
прав `run_shell` и UI-нейминг решены пользователем, вопрос про resume снят как основанный на
неверном предположении (см. разделы ниже и "Открытые вопросы"). `recursion_limit=50` — принятое
решение (раздел 4, п.7). Единственный оставшийся открытый вопрос — будущий вопрос про deprecation
codex-пути, вне рамок этой итерации.

## Проблема

Сегодня ровно два способа исполнить шаг workflow (или разовый `execute`/`query`/`update_arch`) —
`engine_name ∈ {"claude", "codex"}` (`_validate_engine_name()`,
[`app/services/init_arch_workflow.py:808-811`](../../back/app/services/init_arch_workflow.py#L808-L811);
`ExecuteRequest.validate_engine()`,
[`app/api/rpc/execute.py:27-33`](../../back/app/api/rpc/execute.py#L27-L33)). Третий вариант,
добавленный в [2026-07-24-external-llm-provider.md](2026-07-24-external-llm-provider.md), — не новый
движок, а `provider_connection_id` поверх `engine_name="codex"`: под капотом всё равно спавнится
настоящий `codex` CLI-бинарник как subprocess (`_build_cmd()`/`run_cli_task()`,
[`app/services/task_runner.py:175-223`](../../back/app/services/task_runner.py#L175-L223),
[`:577-664`](../../back/app/services/task_runner.py#L577-L664)), только с оверрайдами `-c
model_provider=...` вместо штатной codex-аутентификации.

Это означает, что при работе через внешний OpenAI-совместимый шлюз пользователь платит двойной
overhead: (1) latency самого codex CLI как процесса — старт Node-рантайма, инициализация,
собственный tool-calling слой, health-check каталога модели (`model_catalog_json`, см. секцию 8
[`2026-07-24-external-llm-provider.md`](2026-07-24-external-llm-provider.md)) — поверх (2) latency
самого HTTP-вызова к внешней модели. Пользователь наблюдает это как "внешняя модель через codex
работает медленно" и предлагает разорвать эту связку: общаться с внешней моделью напрямую по HTTP
(через уже существующую абстракцию `LlmProviderConnectionDetail`), а не через посредника-CLI,
запуская вместо этого LangGraph tool-calling агента **в процессе backend**, без отдельного
subprocess/PTY вообще.

Технически это не "ещё один `if engine_name == ...`" в `run_cli_task()` — это принципиально другая
модель исполнения:

- Нет subprocess/exit-code/stdout-парсинга — единственный существующий путь построения результата,
  usage и live-событий (`_extract_result_text`, `_extract_usage`, `_classify_live_stream_line`,
  [`task_runner.py:391-478`](../../back/app/services/task_runner.py#L391-L478)) целиком построен на
  парсинге построчного JSON из `stdout` CLI-бинарника.
- Нет "бесплатного" набора инструментов (файлы/git/shell). Сегодня файловые/git/shell-операции
  агенту предоставляет сам `codex`/`claude` бинарник, запущенный с `--sandbox danger-full-access` /
  `--permission-mode bypassPermissions` — единственная граница безопасности сегодня это изоляция
  самого Docker-контейнера, не что-либо на уровне приложения (см. комментарии
  [`task_runner.py:178-183`](../../back/app/services/task_runner.py#L178-L183),
  [`:208-213`](../../back/app/services/task_runner.py#L208-L213)). LangGraph-агент такого набора
  инструментов не имеет — его нужно спроектировать и реализовать в самом сервисе, включая явную
  модель прав на файлы/git/shell внутри `workspace_dir`.
- `langgraph` в `pyproject.toml` (`langgraph>=0.2.0`, `langgraph-checkpoint-postgres>=2.0.0`) уже
  используется, но только как **оркестратор графа шагов workflow** (`StateGraph(InitArchState)`,
  [`app/workflows/init_arch/graph.py:112-113`](../../back/app/workflows/init_arch/graph.py#L112-L113))
  — каждый узел графа сам по себе вызывает `run_cli_task()`. Tool-calling ReAct-агент поверх
  LangGraph (`create_react_agent` или эквивалент) в кодовой базе сегодня не используется вообще —
  это новый паттерн, а не расширение существующего.

## Цель

1. Добавить четвёртый способ исполнения шага/задачи — LangGraph tool-calling агент, который вызывает
   внешнюю LLM напрямую по HTTP (через уже настроенное подключение `LlmProviderConnectionModel`,
   [2026-07-24-external-llm-provider.md](2026-07-24-external-llm-provider.md)) и сам, в процессе
   backend, исполняет файловые/git/shell-инструменты в `workspace_dir` — без запуска `codex`/`claude`
   как отдельного процесса.
2. Сохранить действующий контракт шага без изменений: `LlmTaskRequest.prompt_text` (структура промпта
   из `prompts.py`, включая требование финального ответа в виде JSON-отчёта) и `LlmTaskResult`
   (`completed_actions`/`created_artifacts`/`open_questions_found`/…) должны работать одинаково вне
   зависимости от того, какой из четырёх движков выполнил шаг — вызывающий код в `nodes.py` не должен
   знать, что изменился движок.
3. Снизить latency прогонов с внешним провайдером за счёт исключения codex/claude как
   промежуточного слоя.
4. Явно спроектировать модель безопасности нового набора инструментов (файлы/git/shell в
   `workspace_dir`) — сегодня эта ответственность целиком лежала на codex/claude бинарнике и границе
   контейнера; теперь она частично переходит в код сервиса.
5. Не ломать существующие способы (`claude`, `codex`, `codex` + внешний провайдер) — это
   добавление, а не замена.

Не цель: убирать codex/claude пути; поддержка LangGraph-агента поверх подключений с
`wire_api="responses"` без предварительной проверки совместимости (см. "Открытые вопросы", п.1);
переиспользование этого агента как MCP-инструмента (`mcp_server.py`) или во входящем
OpenAI-совместимом фасаде (`app/api/openai.py`) в этой итерации — по аналогии с тем, как предыдущая
фича сознательно не пробрасывала `provider_connection_id` в эти два входа
([2026-07-24-external-llm-provider.md, открытый вопрос №6](2026-07-24-external-llm-provider.md)).

## Как сегодня устроена точка расширения (evidence)

- `CliTask` (`app/services/task_registry.py:20-48`) уже engine-агностичен по данным: `engine_name:
  str` (не enum), `provider_connection_id: str | None`, `workspace_dir`, `timeout_seconds`,
  `session_id`. Ни одно поле не предполагает именно subprocess — `subprocess_handle:
  asyncio.subprocess.Process | None` единственное поле, специфичное для CLI-пути, и оно уже
  `Optional` (используется только для `cancel_cli_task()`, чтобы послать `terminate()` работающему
  процессу).
- `LlmProviderConnectionDetail` (`app/services/llm_providers.py:51-58`) — уже готовая модель
  подключения: `base_url`, `model`, `wire_api` (`"chat"|"responses"`), `requires_openai_auth`,
  `token`. Это ровно то, что нужно LangChain/LangGraph-клиенту для прямого HTTP-вызова — не нужно
  придумывать новую сущность подключения, только новый потребитель существующей.
- `get_llm_provider_connection_async()` — единая точка резолва подключения, уже используется
  `_resolve_provider_connection()` в `task_runner.py:540-546`; новый исполнитель использует ту же
  функцию.
- `LlmTaskRequest`/`LlmTaskResult` (`app/workflows/init_arch/domain/models.py:197-219`) не содержат
  ничего CLI-специфичного — оба пригодны без изменений.
- `WorkflowEventBus`/`get_workflow_event_bus().publish(workflow_id, event)` — общая шина live-событий
  для SSE, уже используется и `_publish_live_stdout_line()` (`task_runner.py:501-525`), и напрямую
  `LlmCliService._publish_live_event()` (`task_runner.py:849-864`) для событий уровня "весь вызов"
  (`llm_call_started`/`llm_call_completed`/`llm_call_failed`). Формат события (`event_type`,
  `actor`, `step_id`, `step_label`, `repo_name`, `domain_id`, …) engine-агностичен — новый
  исполнитель публикует в ту же шину, тем же форматом.
- `AgentPool`/`get_agent_pool()` (`app/services/agent_pool.py`) — просто `asyncio.Semaphore`,
  ограничивает число параллельных исполнений вне зависимости от движка. Переиспользуется как есть.
- `LlmWorkerService` (`app/workflows/init_arch/llm_worker.py`) — тонкая обёртка над
  `LlmCliService.run_task()`, добавляющая failover `codex ↔ claude` при
  `FAILURE_REASON_LIMIT_EXHAUSTED`, но **уже** отключает failover, если `provider_connection_id`
  задан (`llm_worker.py:20-26`, обоснование в
  [2026-07-24-external-llm-provider.md, секция 5](2026-07-24-external-llm-provider.md)). Поскольку
  новый движок обязан всегда иметь `provider_connection_id` (иначе бессмысленен — некуда стучаться),
  этот guard уже защищает его от случайного failover на `claude`/`codex`, дополнительный код не
  нужен, но стоит закрепить явным тестом (см. "Затронутые файлы").
- `arch_repo_dir` — **отдельный** от `workspace_dir` путь (`_prepare_workspace_directories()`,
  `app/workflows/init_arch/nodes.py:259-261`, создаёт `[workspace_dir, raw_workspace_dir,
  arch_repo_dir]` как три разных каталога). Сегодня codex/claude, получая `cwd=workspace_dir`, но
  `danger-full-access`, свободно читает/пишет и в `arch_repo_dir`, если промпт просит. Значит модель
  прав файлового тулсета LangGraph-агента **не может** быть наивно "только `cwd`" — нужен явный
  список разрешённых корней на конкретный вызов (см. "Открытые вопросы", п.3).
- `pyproject.toml` **не** содержит `langchain-openai` (или другой пакет с готовым
  OpenAI-совместимым chat-моделью для LangChain) — это новая зависимость, не переиспользование
  существующей.

## Предлагаемый дизайн

### 1. `engine_name` — третье значение сверх `{"claude", "codex"}`, обязательный `provider_connection_id`

В отличие от предыдущей фичи (где сознательно не вводили третий `engine_name`, а добавляли
ортогональное поле поверх `codex`), здесь это оправданно, потому что это не вариант codex, а
самостоятельный, принципиально другой механизм исполнения: `engine_name = "langgraph"`.

Изменения валидации (симметрично существующим, но с обратной обязательностью):

- `_validate_engine_name()` (`app/services/init_arch_workflow.py:808-811`) — расширить множество до
  `{"claude", "codex", "langgraph"}`.
- Новая проверка (аналог `_validate_provider_connection_id`, но в другую сторону): если
  `engine_name == "langgraph"`, `provider_connection_id` обязателен (`None` → `WorkflowValidationError`).
  У `codex`/`claude` он остаётся опциональным как сегодня.
- `ExecuteRequest` (`app/api/rpc/execute.py:19-40`) — `validate_engine()` расширяется тем же
  множеством, новый `model_validator`, требующий `provider_connection_id` при
  `engine == "langgraph"`.
- `InitArchState`/`WorkflowSnapshot` (`app/workflows/init_arch/state.py:14`, `snapshot.py:24,35`) —
  поля уже нетипизированы под конкретный движок (`engine_name: str`), изменений структуры не
  требуется.
- `app/mcp_server.py`, `app/api/openai.py` — **сознательно не расширяются** в этой итерации (см.
  "Не цель").

**Реализовано:** `_validate_engine_name()`/`_validate_provider_connection_id()`
(`app/services/init_arch_workflow.py`) и `ExecuteRequest.validate_engine()`/
`validate_provider_connection_requires_codex()` (`app/api/rpc/execute.py`) — ровно как описано.
Тесты: `tests/services/test_init_arch_workflow.py` (принятие `langgraph`+`provider_connection_id`,
отказ без него, обновлённое сообщение об ошибке для неподдерживаемого движка),
`tests/api/rpc/test_execute.py` (422 без `provider_connection_id`, диспетчеризация в
`run_langgraph_task` при валидном запросе).

### 2. Резолюция подключения и требование к `wire_api`

`run_langgraph_task()` (новый модуль, см. п.4) резолвит подключение той же функцией, что и
CLI-путь — `get_llm_provider_connection_async()` — никакого нового способа хранения/чтения секрета
не вводится, переиспользуется файловый секрет-стор из
[2026-07-24-external-llm-provider.md, секция 1](2026-07-24-external-llm-provider.md).

Ключевое отличие от CLI-пути: там секрет доставлялся в `env` codex-подпроцесса и *codex сам* говорил
по HTTP с шлюзом. Здесь backend-процесс сам становится HTTP-клиентом к шлюзу — токен передаётся
напрямую в конструктор LangChain chat-модели (`api_key=connection.token`), не через переменные
окружения вообще. Это даже проще и безопаснее по изоляции между параллельными задачами, чем текущий
паттерн — токен живёт только в памяти конкретного вызова, никогда не пересекает границу процесса.

**`wire_api` — решено, но иначе, чем в черновике.** `langchain_openai.ChatOpenAI` технически
поддерживает Responses API (`/v1/responses`) через флаг `use_responses_api=True` (доступен с
`langchain-openai>=0.3.9`) и совместим с произвольным `base_url` — подтверждено официальным
примером в документации LangChain. Черновая версия этого документа планировала
`use_responses_api=(connection.wire_api == "responses")`, доверяя полю подключения. **Реальный
e2e-прогон против production-подключения "GLM 5.2" (`wire_api="responses"`) это опроверг** —
`langchain_openai` падает с `TypeError` внутри своего парсинга ответа этого шлюза (`usage.
input_tokens`/`output_tokens` шлюз оставляет `None`, `langchain_openai` пытается их сложить как
fallback для `total_tokens`). Прямая проверка тем же клиентом в режиме Chat Completions против
того же шлюза/модели прошла успешно с корректным usage. Значит `wire_api="responses"` в модели
подключения отражает требование конкретно **codex** (см.
[2026-07-24-external-llm-provider.md, секция 8](2026-07-24-external-llm-provider.md)), а не
универсальную характеристику шлюза и не требование LangGraph-пути. **Итоговое решение:**
`_build_model()` всегда строит `ChatOpenAI(base_url=connection.base_url,
api_key=connection.token, model=connection.model, use_responses_api=False)` — Chat Completions
безусловно, `connection.wire_api` для LangGraph-движка не читается вообще.

### 3. Инструменты (tools) — новый модуль `app/services/langgraph_agent_tools.py`

Минимальный набор, покрывающий то же функциональное пространство, что сегодня "бесплатно" даёт
codex/claude:

- `read_file(path: str) -> str`
- `write_file(path: str, content: str) -> str` (создаёт родительские директории при необходимости)
- `list_directory(path: str = ".") -> list[str]`
- `run_shell(command: str, timeout_seconds: int | None = None) -> dict` — `{stdout, stderr,
  exit_code}`; покрывает и git-операции (`git status`/`git diff`/`git add`/`git commit`/`git log`
  и т.п.) без отдельного git-тула — как и сегодня, codex/claude используют один и тот же shell для
  git, отдельного "git-инструмента" в них тоже нет (ponytail-принцип: не плодить два тула там, где
  хватает одного).

Общая функция подтверждения границ `_resolve_within_roots(candidate_path: str, allowed_roots:
list[pathlib.Path]) -> pathlib.Path`: резолвит `candidate_path` (`Path.resolve()`, чтобы схлопнуть
`..`/симлинки) и проверяет `is_relative_to()` хотя бы одного разрешённого корня; иначе — исключение,
возвращаемое инструментом как текстовая ошибка модели (не наружу как HTTP 500), чтобы агент мог
скорректироваться, как это делает LLM при `Permission denied` от реального shell.

`run_shell` выполняется через `asyncio.create_subprocess_shell(command, cwd=<первый разрешённый
корень>, env=...)` — то есть допускает произвольные shell-конструкции (pipe, `&&`, redirects), как и
сегодняшний прямой shell-доступ codex/claude.

**Решено (2026-07-25):** паритет модели угроз с существующими движками, не ужесточение — граница
безопасности остаётся на уровне контейнера/пользователя `appuser`, а не на уровне разрешённых
команд. Allowlist команд рассмотрен и отклонён явно: он ограничил бы функциональность агента (часть
шагов `prompts.py` рассчитана на полный shell-доступ) без соответствующего выигрыша, раз граница
безопасности и так проходит по контейнеру.

**Разрешённые корни — решено.** `arch_repo_dir` сегодня не является отдельным полем `CliTask`/
`LlmTaskRequest` — он передаётся codex/claude только как текст внутри промпта (`prompts.py:317,362`:
"Архитектурный репозиторий: {state['arch_repo_dir']}"), и агент достаёт его оттуда пользуясь полным
доступом к ФС. Для тул-агента текстовой ссылки в промпте недостаточно — нужно явное поле. Решение:
добавить `extra_allowed_roots: list[str] = []` в `CliTask` (`task_registry.py`) и в `LlmTaskRequest`
(`domain/models.py`); там, где `nodes.py` строит `LlmTaskRequest` для шагов, ссылающихся на
`arch_repo_dir` в промпте, заполнять `extra_allowed_roots=[state["arch_repo_dir"]]`. Точная построчная
сверка, какому конкретно `StepId` какие корни нужны, — часть имплементации (не архитектурное
решение), делается по остаточному принципу: если промпт шага упоминает `arch_repo_dir`, поле
заполняется, иначе остаётся пустым. `allowed_roots` для конкретного вызова тулов =
`[workspace_dir, *extra_allowed_roots]`.

**Реализовано с упрощением:** в `nodes.py` есть ровно одна функция, строящая `LlmTaskRequest` —
`_build_task_request()` — и у неё `state["arch_repo_dir"]` доступен всегда, поэтому построчная
сверка по `StepId` не потребовалась: `extra_allowed_roots=[state["arch_repo_dir"]]` проставляется
безусловно для всех шагов init_arch (лишний разрешённый корень не сужает, а расширяет доступ, что
безопасно при уже принятой модели паритета с `danger-full-access`). Прямые пути построения `CliTask`
в обход `LlmTaskRequest` (`update_arch`/`query` в `init_arch_workflow.py`, `execute_engine_task` в
`rpc/execute.py`) не имеют понятия `arch_repo_dir` вовсе — `extra_allowed_roots` там остаётся
пустым по умолчанию, как и предполагалось.

`app/services/langgraph_agent_tools.py` (`read_file`/`write_file`/`list_directory`/`run_shell`,
`_resolve_within_roots()`) — построен через отдельные `_make_*_tool()`-фабрики (не один большой
конструктор), иначе `ruff`/`C901` считает единую функцию с 4 инструментами избыточно сложной.
Подтверждено e2e: реальный агент вызвал `list_directory` → `read_file` → `write_file` в правильном
порядке и действительно создал файл `result.txt` с ожидаемым содержимым внутри `workspace_dir`.
Тесты: `tests/services/test_langgraph_agent_tools.py` (21 тест: резолюция путей — относительные,
абсолютные внутри корня, path traversal, symlink-побег, второй разрешённый корень; read/write/list
— успех, отсутствующий файл/не-директория, путь вне корней, `OSError`; `run_shell` — cwd,
ненулевой exit code, таймаут), 100% покрытие модуля.

### 4. Исполнитель — новый модуль `app/services/langgraph_task_runner.py`

```python
async def run_langgraph_task(cli_task: CliTask, agent_pool: AgentPool) -> None:
    ...
```

Сигнатура и жизненный цикл статусов (`PENDING → RUNNING → SUCCESS|FAILED|CANCELLED`,
`started_at`/`finished_at`, персист через `_persist_task()`) — зеркалит `run_cli_task()`.

**Реализовано с уточнением по ходу разработки:** общие для обоих движков куски —
`_persist_task()`/`_persist_token_usage()`/`_task_log_context()`/`_resolve_provider_connection()`/
`_ProviderConnectionMissingError`/`_resolve_cli_prompt()`/`FAILURE_REASON_*` — вынесены из
`task_runner.py` в новый нейтральный модуль `app/services/cli_task_support.py` (без него
`langgraph_task_runner.py`, которому эти хелперы нужны, и `task_runner.py`, которому нужен
`run_langgraph_task` для диспетчера из раздела 5, образовали бы циклический импорт друг на друга).
`task_runner.py` реэкспортирует нужные имена оттуда, так что внешние потребители
(`app.main.set_db_enabled`, существующие тесты, патчащие `app.services.task_runner._persist_token_usage`
по имени) не заметили изменения.

Дальше поток принципиально другой:

1. Резолвит `provider_connection` (см. п.2); если не найдено — `FAILED` с тем же текстом ошибки, что
   и в `_ProviderConnectionMissingError`-пути сегодня.
2. Строит LangChain chat-модель — `_build_model()`: `ChatOpenAI(base_url=connection.base_url,
   api_key=connection.token, model=connection.model, use_responses_api=False)` — **всегда** Chat
   Completions, `connection.wire_api` не читается (см. раздел 2 — реальный e2e показал, что
   доверие `wire_api="responses"` ломает парсинг ответа у реального шлюза).
3. Строит LangGraph tool-calling агента — **`langchain.agents.create_agent(model, tools=[...])`**,
   не `langgraph.prebuilt.create_react_agent` (последний в установленной версии `langgraph`
   (`1.2.7`) уже помечен deprecated в пользу первого — обнаружено при реализации, взят
   не-deprecated вариант с идентичной сигнатурой и поведением) — с инструментами из п.3,
   привязанными к `allowed_roots` этого конкретного `cli_task`.
4. Промпт — `_resolve_cli_prompt(cli_task)` **переиспользуется как есть** (тот же
   `cli_task_support.py`, та же логика overflow в файл при промпте > `_MAX_INLINE_PROMPT_CHARS`) —
   контракт промпта один на все четыре движка.
5. Вызывает агента с ограничением по времени: `asyncio.wait_for(invoke_task,
   timeout=cli_task.timeout_seconds)`, где `invoke_task = asyncio.create_task(_invoke_agent(...))` —
   на `TimeoutError` результат тот же, что и у CLI-пути (`FAILED`, `"Timeout exceeded"`), плюс явная
   `invoke_task.cancel()` (в отличие от `_terminate_subprocess()`, нужной для убийства процесса,
   здесь просто отменяется корутина).
6. Точно так же для `asyncio.CancelledError` (пауза workflow) — `invoke_task.cancel()` и `raise`,
   никакого дополнительного cleanup для subprocess не нужно.
7. Ограничение на число итераций tool-calling цикла — **решено:** `recursion_limit=50` (константа
   `_RECURSION_LIMIT`, передаётся в `agent.ainvoke(..., config={"recursion_limit": 50, ...})`).
8. Результат — `AIMessage.content` последнего сообщения ассистента становится `cli_task.task_result`
   (тот же JSON-контракт, что модель обязана вернуть согласно `prompts.py`, парсится дальше тем же
   `_extract_json_object()` — без изменений).
9. Usage — `AIMessage.usage_metadata` (`input_tokens`/`output_tokens`, стандартное поле LangChain) —
   подтверждено e2e: реальный вызов вернул `input_tokens=600`, `output_tokens=80`, персистировано в
   `cli_tasks.model_name/input_tokens/output_tokens` корректно.
10. Ошибки аутентификации/лимитов — LangChain/`openai`-клиент бросает типизированные исключения
    (`openai.AuthenticationError`, `openai.RateLimitError`), которые ловятся напрямую и
    мапятся на существующие константы `FAILURE_REASON_AUTH_EXPIRED`/`FAILURE_REASON_LIMIT_EXHAUSTED`
    (теперь в `cli_task_support.py`) — точнее, чем сегодняшняя эвристика по подстрокам в `stderr`
    (`_is_auth_error`/`_is_limit_error`), которая остаётся нужна только для CLI-пути.

**Реализовано:** `app/services/langgraph_task_runner.py` (`run_langgraph_task()`,
`_resolve_langgraph_provider_connection()`, `_execute_langgraph_agent()`, `_invoke_agent()`,
`_build_model()`, `_finalize_langgraph_result()`, `_LiveEventCallbackHandler`, `_emit_agent_event()`,
`_format_trace_line()`). Тесты: `tests/services/test_langgraph_task_runner.py` (16 тестов: успех
с усечением usage/model_name, `allowed_roots` включает `extra_allowed_roots`, `recursion_limit`/
промпт передаются в `ainvoke`, отсутствие/ненайденное подключение, `CANCELLED`-пропуск, таймаут с
отменой `async_task_handle`, `AuthenticationError`/`RateLimitError`/произвольное исключение,
внешняя отмена всего вызова, колбэки `_LiveEventCallbackHandler` — 4 теста), 100% покрытие модуля.

### 5. Дефолтный диспетчер вызова движка

Сегодня оба вызывающих места (`rpc/execute.py:53` и
`LlmCliService._run_cli_task()`, `task_runner.py:820-821`) напрямую вызывают `run_cli_task()`. Нужен
единый диспетчер (например, `execute_engine_task(cli_task, agent_pool)` в `task_runner.py`),
который делает единственную ветку:

```python
async def execute_engine_task(cli_task: CliTask, agent_pool: AgentPool) -> None:
    if cli_task.engine_name == "langgraph":
        await run_langgraph_task(cli_task, agent_pool)
    else:
        await run_cli_task(cli_task, agent_pool)
```

Оба вызывающих места переключаются на этот диспетчер вместо прямого `run_cli_task()`. Это
единственная точка ветвления по движку на уровне вызова — дальше `LlmCliService`,
`WorkflowAuditService`, `WorkflowEventBus`, `task_repo.py` продолжают работать одинаково, потому что
общий контракт (`CliTask`, статусы, `task_result`/`task_error`, usage-поля) не меняется.

**Реализовано:** `execute_engine_task()` в `task_runner.py`, три вызывающих места переключены —
`LlmCliService._run_cli_task()`, `rpc/execute.py::execute()`, `init_arch_workflow.py::_enqueue_cli_task()`
(последнее не было явно перечислено в черновике, но использует тот же паттерн
`asyncio.create_task(run_cli_task(...))` для `update_arch`/`query`, поэтому тоже переключено на
диспетчер). Тесты: `TestExecuteEngineTask` в `test_task_runner.py` (2 теста — диспетчеризация в
`run_langgraph_task` для `engine_name="langgraph"`, в `run_cli_task` для `claude`/`codex`),
`test_langgraph_engine_with_provider_connection_id_dispatches_to_langgraph_runner` в
`test_execute.py` (через реальный HTTP-роут).

### 6. Live-события / observability

`_publish_live_stdout_line()` (`task_runner.py:501-525`) сегодня парсит **текстовые строки**
stdout построчно. У LangGraph-агента такого текстового потока нет — вместо парсинга событие строится
напрямую из колбэков LangGraph/LangChain (`agent.astream_events(...)` или `on_tool_start`/
`on_tool_end`/`on_chat_model_stream` callbacks): `on_tool_start` → `{"event_type": "llm_tool_call",
"tool_name": ..., "tool_input": ...}`, финальный текст ассистента → `{"event_type": "llm_message",
"text": ...}` — тот же формат события, что и сегодня, публикуется в ту же
`get_workflow_event_bus().publish(cli_task.workflow_id, event)`, с той же санитизацией
(`sanitize_text`, `max_output_chars`/`max_prompt_chars`). Это даже надёжнее сегодняшнего подхода —
структурированные колбэки не требуют угадывания формата по `type`-полю чужого JSON, как сегодняшние
`_classify_claude_stream_line`/`_classify_codex_stream_line`.

**Реализовано:** `_LiveEventCallbackHandler` (наследник `langchain_core.callbacks.AsyncCallbackHandler`)
использует `on_tool_start`/`on_llm_end`, а не `astream_events`/`on_chat_model_stream` из черновика —
`on_llm_end` даёт готовый `AIMessage` с `content`/`tool_calls` без необходимости собирать текст из
токен-стрима по кусочкам, что проще для разового финального события на шаг (а не токен-за-токеном
стриминга, которого этот дизайн и не обещал). Подтверждено e2e: реальный прогон дал
`stdout_output` вида `[tool] list_directory({...})\n[tool] read_file({...})\n[tool]
write_file({...})\n[assistant] <финальный текст>` — то есть и живая SSE-шина, и debug-трейс
получают события в реальном времени и в правильном порядке.

### 7. Наблюдаемость — паритет с codex/claude по логам, аудиту и debug-API

Требование "не хуже codex/claude" проверено по всем существующим точкам наблюдаемости, не только по
live-SSE из раздела 6. Разбор по каждой точке:

**Структурные логи (`structlog`) — паритет достигается переиспользованием, без нового кода.**
`run_cli_task()` логирует `cli_task.queued`/`started`/`finished`/`failed`/`timeout`/`cancelled`/
`auth_error`/`limit_error` через общий `_task_log_context()` (`task_runner.py:497-498`).
`run_langgraph_task()` обязан логировать те же имена событий с тем же контекстом
(`task_id`/`workflow_id`/`step_id`) в тех же точках жизненного цикла — простое переиспользование
`_task_log_context()`, без новой инфраструктуры логирования.

**Аудит (`WorkflowAuditService`/`EventType.LLM_TASK_*`) — уже паритетен, изменений не требует.**
`EventType.LLM_TASK_REQUESTED`/`LLM_TASK_COMPLETED`/`LLM_TASK_FAILED`/`LLM_TASK_FAILOVER_*`
(`domain/models.py:55-59`) записываются в `LlmCliService.run_task()`
(`task_runner.py:697-793`) — на уровень **выше** диспетчера `execute_engine_task()` из раздела 5.
Это означает, что аудит-трейл уже одинаков для всех движков автоматически, раз
`run_langgraph_task()` вызывается через тот же `LlmCliService`/`LlmWorkerService`, а не в обход
него. Гранулярность аудита сегодня — "весь вызов", отдельного события на каждый tool-call в
аудите нет ни у одного из движков (только в live-SSE, раздел 6) — паритет по построению, специально
проектировать нечего.

**Пробел №1 (найден) — `cli_task.stdout_lines`/`stderr_lines` не заполняются, ломает существующий
debug-API.** `GET /rest/tasks/{id}/stream/` (`app/api/rest/tasks.py:123-134`) стримит по SSE
инкрементальные добавления в `cli_task.stdout_lines`/`stderr_lines` пока задача `RUNNING`
(`_stream_task_events()`, `tasks.py:97-121`), а `GET /rest/tasks/{id}/?include_output=true`
возвращает их итоговую склейку (`_to_response()`, `tasks.py:38-49`). В БД та же склейка
персистится как `stdout_output`/`stderr_output` (`upsert_cli_task()`, `task_repo.py:18-27`) — это
основной канал post-hoc отладки зависшего/упавшего шага для инженера поддержки. Если
`run_langgraph_task()` их не трогает, оба этих канала для LangGraph-задач будут молча пустыми —
регресс относительно codex/claude, а не просто отсутствие новой возможности.

Решение: та же точка, где раздел 6 генерирует live-события для `workflow_event_bus` (колбэки
`on_tool_start`/`on_chat_model_stream` и т.п.), дополнительно форматирует человекочитаемую строку
(`[tool] read_file(path=...)`, `[assistant] <текст>` и т.п.) и добавляет её в `cli_task.stdout_lines`
— один источник событий, два потребителя (шина + debug-трейс), без дублирования логики сборки
события.

**Реализовано:** `_emit_agent_event()`/`_format_trace_line()` в `langgraph_task_runner.py` — один
источник, оба потребителя. Подтверждено e2e через `GET /rest/tasks/{id}/?include_output=true` (см.
раздел "Тестирование и проверка").

**Пробел №2 (найден) — `cancel_cli_task()` не умеет отменять запущенный LangGraph-вызов.**
`cancel_cli_task()` (`task_runner.py:667-690`) обрабатывает ровно два случая: `PENDING` → пометить
`CANCELLED`, либо `subprocess_handle` есть и жив → `terminate()`/`kill()`. Для `RUNNING`
LangGraph-задачи `subprocess_handle` всегда `None` (нет subprocess) — условие
`if cli_task.subprocess_handle is None or ...: return` на строке 678 сработает и **молча ничего не
сделает**: `DELETE /rest/tasks/{task_id}/` вернёт `200 OK` (роут не проверяет результат отмены), но
задача продолжит выполняться до собственного таймаута — то есть пользователь и пауза workflow
(`pause_init_arch_workflow`, которая тоже полагается на отмену через тот же путь) не смогут
остановить LangGraph-шаг руками, только через общий `asyncio.CancelledError` при паузе всего графа.
Это худший результат, чем у codex/claude, где ручная отмена конкретной задачи работает.

Решение: добавить `CliTask.async_task_handle: asyncio.Task | None = None` (аналог
`subprocess_handle`, но для корутины `agent.ainvoke(...)`, обёрнутой в `asyncio.create_task()`
внутри `run_langgraph_task()`). `cancel_cli_task()` получает третью ветку: если
`subprocess_handle is None` и `async_task_handle` есть и не завершён — `async_task_handle.cancel()`,
дождаться `CancelledError`, пометить `CANCELLED`, как и в subprocess-варианте.

**Реализовано и подтверждено e2e:** реальный `DELETE /rest/tasks/{id}/` на запущенном
LangGraph-шаге (агент внутри `run_shell("sleep 30")`) перевёл задачу `RUNNING → CANCELLED` за
секунды, `task_result` остался `null`. Тесты: `test_cancels_running_langgraph_task_with_no_subprocess`,
`test_noop_for_already_done_async_task_handle` в `test_task_runner.py::TestCancelCliTask`.

### 8. Не входит в изменения (переиспользуется без модификации)

- `LlmWorkerService`/failover-логика — не требует изменений (см. "Как сегодня устроена точка
  расширения" — существующий guard `provider_connection_id is not None` уже защищает).
- `AgentPool` — переиспользуется как есть.
- `WorkflowAuditService`/`WorkflowEventRecord` — переиспользуются как есть, движок — это просто ещё
  одно значение `engine_name` в уже существующих полях событий.
- `task_repo.py`/`CliTaskModel` — персистентность `CliTask` не меняется, поле `engine_name` уже
  `TEXT`, миграция не нужна.
- `_run_git_clone()` (`nodes.py:303` и окрестности) — клонирование репозиториев по-прежнему делает
  сам сервис до запуска агента, тем же кодом, вне зависимости от движка.

### 9. Frontend

Четвёртая опция движка в форме запуска (`init-arch-form.tsx` и эквиваленты `update_arch`/`query`) —
"LangGraph-агент (прямой API)" (нейминг подтверждён пользователем 2026-07-25), рядом с "Codex" /
"Claude Code" / "Внешняя LLM" (последняя — тоже codex под капотом). При выборе — тот же
селектор `provider_connection_id` из уже существующей карточки `llm-providers-card.tsx`, что и для
"Внешняя LLM"; поле обязательно (без выбранного подключения кнопка запуска задизейблена — сильнее,
чем сегодняшнее поведение "Внешняя LLM", где подключение тоже обязательно фактически, но это разные
движки под одним UI-паттерном выбора подключения).

**Реализовано:** `WorkflowEngine = CliEngine | "langgraph"` (новый тип в `shared/api/models.ts`,
`InitArchInput.engine_name` расширен до него — `CliEngine` сам по себе не тронут, он отдельно
используется для CLI-auth сессий, к которым `langgraph` не имеет отношения). В `init-arch-form.tsx`
`EngineSelection` расширен до `CliEngine | "external" | "langgraph"`, четвёртый `<option>`, и
условие показа селектора подключения обобщено до `ENGINES_REQUIRING_PROVIDER_CONNECTION.has(...)`
(множество `{"external", "langgraph"}`) вместо точечной проверки `=== "external"`. Отдельных форм
для `update_arch`/`query` с выбором `provider_connection_id` в репозитории не нашлось — эти
эндпоинты сегодня принимают `provider_connection_id` только по RPC, без своего UI-виджета, поэтому
"эквиваленты" из черновика ограничены единственной существующей формой. Тесты:
`init-arch-form.test.tsx` (+2 теста — блокировка сабмита без подключения, корректная отправка
`engine_name="langgraph"`+`provider_connection_id`), `npx tsc -b --force` чисто, весь фронтовый
сьют (120 тестов) зелёный.

## Что не входит в эту итерацию

- Замена или удаление codex/claude путей — это строго дополнение.
- Проброс `engine_name="langgraph"` в `app/mcp_server.py` и `app/api/openai.py`.
- Allowlist/ограничение набора shell-команд для `run_shell` — MVP даёт паритет угроз с
  `danger-full-access` codex/claude, не более узкую модель.
- UI для health-check LangGraph-подключения отдельно от уже существующей кнопки "Проверить" на
  `LlmProviderConnectionModel` (она уже покрывает и этот случай — проверяет тот же `base_url`/токен).
- Поддержка нескольких LLM-провайдеров/multi-agent маршрутизации внутри одного шага.
- Персистентность истории сообщений агента **между отдельными вызовами** (шагами воркфлоу,
  повторными `query`/`update_arch`) через LangGraph checkpointer. **Решено пользователем
  (2026-07-25):** каждый шаг воркфлоу и каждый разовый `query`/`update_arch` — один независимый
  вызов `run_langgraph_task()`. Внутри этого одного вызова у react-агента и так есть полная память —
  ReAct-цикл `create_react_agent` сам ведёт историю сообщений между последовательными вызовами
  инструментов в рамках одного `ainvoke()` (это и есть многократные вызовы тулов из раздела 3/4,
  например "изучить код → заполнить контракт" за несколько tool-calls). Переносить рассуждения и
  историю вызовов тулов *дальше*, в следующий отдельный вызов (следующий шаг графа или следующий
  `query`), не нужно: весь нужный контекст для следующего вызова и так приходит через промпт и
  текущее состояние проекта на диске — ровно так же, как сегодня работает каждый отдельный вызов
  codex/claude без `--resume`. Поэтому `langgraph-checkpoint-postgres` для меж-вызовной памяти в
  этой фиче не используется; `session_id`/`--resume`-подобный механизм для LangGraph-движка не
  проектируется вообще (это и закрывает то, что раньше было открытым вопросом про resume).

## Открытые вопросы

Основные вопросы дизайна закрыты 2026-07-25 (совместимость `wire_api="responses"` — раздел
"Резолюция подключения"; модель прав `run_shell` — раздел 3; разрешённые корни — раздел 3
(`extra_allowed_roots`); resume/меж-вызовная память — раздел "Что не входит в эту итерацию";
UI-нейминг — раздел 9 "Frontend"; паритет по логам/аудиту/debug-API, включая два найденных пробела
(`stdout_lines`-трейс и отмена без `subprocess_handle`) — раздел 7; `recursion_limit=50` — см. ниже).
Остаётся один пункт, не блокирующий начало разработки:

1. **Дедлайн deprecation `codex` + внешний провайдер.** Если LangGraph-путь окажется стабильно
   быстрее и покрывает те же сценарии, встаёт вопрос, остаётся ли режим "codex + внешний провайдер"
   постоянным вторым вариантом для внешних LLM или со временем становится legacy-путём. Вне
   решения этой итерации, но стоит зафиксировать как будущий вопрос продукта — пересмотреть после
   того, как LangGraph-путь пройдёт реальную эксплуатацию.

## Тестирование и проверка

- Backend: `just test-db-up` + `uv run --extra dev python -m pytest --cov=app --cov-fail-under=74`
  — **878 passed, 1 xfailed**, покрытие **93.55%** (порог 74%). Новые/изменённые модули —
  `langgraph_task_runner.py`, `langgraph_agent_tools.py`, `cli_task_support.py` — **100%**
  покрытие. Регрессий в существующем сьюте нет.
- Backend: `uv run --extra dev ruff check .` и `ruff format --check .` — чисто для всех файлов
  этой фичи. Оставшиеся сообщения (`E402` в `tests/conftest.py`, `E501` в
  `app/db/workflow_repo.py:354`, форматирование 4 файлов вне зоны фичи) — подтверждены как
  предсуществующие, не относящиеся к этой работе.
- Frontend: `npx vitest run` — **120 passed** (17 файлов, включая +2 теста в
  `init-arch-form.test.tsx`). `npx tsc -b --force` — чисто.
- Docker: backend пересобран (`docker compose build arch-docs && docker compose up -d arch-docs`)
  дважды в процессе — второй раз после фикса циклического импорта и бага с `wire_api`/Responses
  API (см. ниже).
- **E2E против реального production-подключения "GLM 5.2"** (`wire_api="responses"`, шлюз
  turbocloud.ru, уже настроен в этом окружении для `2026-07-24-external-llm-provider.md`), через
  реальный `POST /api/rpc/execute/` с `engine="langgraph"`:
  - Первый прогон **упал** с `TypeError: unsupported operand type(s) for +: 'NoneType' and
    'NoneType'` — см. находку про `wire_api`/Responses API в разделе "Статус реализации" и
    разделе 2. Дополнительно этот же прогон вскрыл **отдельный, не связанный с гейтвеем баг**:
    прямой запуск `import app.services.langgraph_task_runner` до `app.services.task_runner`
    падал с `ImportError` циклического импорта, потому что модуль по ошибке импортировал общие
    хелперы из `task_runner.py`, а не из `cli_task_support.py` (упущение при рефакторинге,
    случайно не проявлявшееся в pytest из-за фиксированного порядка импорта в `conftest.py`).
    Оба бага исправлены, после чего:
  - Успешный сценарий: агент вызвал `list_directory` → `read_file(marker.txt)` →
    `write_file(result.txt, "OK")` → финальный ответ, в правильном порядке. Файл `result.txt`
    реально создан на диске с содержимым `OK`. `stdout_output` (раздел 7, "Пробел №1") корректно
    показал все 4 события. В БД (`cli_tasks`) сохранились `model_name="GLM-5.2"`,
    `input_tokens=600`, `output_tokens=80`, `task_status="success"`.
  - Сценарий отмены: `run_shell("sleep 30")` запущен, затем `DELETE /rest/tasks/{id}/` — статус
    перешёл `RUNNING → CANCELLED` за секунды, `task_result` остался `null` (раздел 7, "Пробел №2"
    подтверждён исправленным).

## Затронутые файлы

Backend:

- `app/services/init_arch_workflow.py` — `_validate_engine_name()` (третье значение), новая
  проверка обязательности `provider_connection_id` для `engine_name == "langgraph"`.
- `app/api/rpc/execute.py` — `ExecuteRequest.validate_engine()`, новый `model_validator`.
- `app/services/cli_task_support.py` (новый) — общие для CLI- и LangGraph-путей хелперы,
  вынесенные из `task_runner.py`, чтобы избежать циклического импорта (см. раздел 4).
- `app/services/langgraph_task_runner.py` (новый) — `run_langgraph_task()`, построение
  LangChain chat-модели (`ChatOpenAI(..., use_responses_api=False)` — безусловно, не по
  `wire_api`, см. раздел 2) и LangGraph-агента через `langchain.agents.create_agent`, обработка
  таймаута/отмены/ошибок аутентификации и лимитов, извлечение результата и usage,
  `_LiveEventCallbackHandler`.
- `app/services/langgraph_agent_tools.py` (новый) — `read_file`/`write_file`/`list_directory`/
  `run_shell`, общая функция подтверждения границ `_resolve_within_roots()`.
- `app/services/task_registry.py` — `CliTask.extra_allowed_roots: list[str] = []`,
  `CliTask.async_task_handle: asyncio.Task | None = None`.
- `app/services/task_runner.py` — новый диспетчер `execute_engine_task()`; реэкспорт хелперов из
  `cli_task_support.py`; новая ветка `cancel_cli_task()` для `async_task_handle`.
- `app/workflows/init_arch/domain/models.py` — `LlmTaskRequest.extra_allowed_roots: list[str] = []`.
- `app/workflows/init_arch/nodes.py` — `_build_task_request()` безусловно заполняет
  `extra_allowed_roots=[state["arch_repo_dir"]]`.
- `app/workflows/init_arch/llm_worker.py` — без функциональных изменений.
- `pyproject.toml` — новые зависимости `langchain-openai>=0.3.9`, `langchain>=1.0.0` (последняя —
  ради не-deprecated `create_agent`, см. раздел 4, п.3).

Backend, тесты (все новые файлы/секции, 100% покрытие новых модулей):

- `tests/services/test_langgraph_task_runner.py` (новый, 16 тестов).
- `tests/services/test_langgraph_agent_tools.py` (новый, 21 тест).
- `tests/services/test_cli_task_support.py` (новый, 5 тестов — закрывает `_persist_token_usage`,
  не тронутое напрямую мокающими тестами `task_runner.py`).
- `tests/services/test_task_runner.py` — `TestExecuteEngineTask` (2 теста), `TestCancelCliTask`
  (+2 теста на `async_task_handle`), обновлены пути патчинга `_MAX_INLINE_PROMPT_CHARS`/
  `get_session`/`upsert_cli_task`/`_db_enabled` на `app.services.cli_task_support`.
- `tests/services/test_init_arch_workflow.py` — +2 теста (`langgraph`+`provider_connection_id`
  принят/отклонён), обновлено сообщение об ошибке в существующем тесте.
- `tests/api/rpc/test_execute.py` — +2 теста (422 без подключения, диспетчеризация в
  `run_langgraph_task`).
- `tests/workflows/init_arch/test_nodes.py` — +1 тест (`extra_allowed_roots` в `_build_task_request`).

Frontend:

- `src/shared/api/models.ts` — новый тип `WorkflowEngine`, `InitArchInput.engine_name` расширен.
- `src/features/workflow/init-arch-form.tsx` — четвёртая опция движка, обобщённая проверка
  `ENGINES_REQUIRING_PROVIDER_CONNECTION`.
- `src/features/workflow/init-arch-form.test.tsx` — +2 теста.

## Источники (evidence)

- `app/services/task_runner.py`, `app/services/task_registry.py`, `app/workflows/init_arch/llm_worker.py`,
  `app/services/git_credentials.py`, `app/workflows/init_arch/nodes.py`, `app/workflows/init_arch/graph.py`,
  `app/workflows/init_arch/checkpointer.py`, `app/services/llm_providers.py`, `app/api/rpc/execute.py`,
  `app/workflows/init_arch/domain/models.py`, `pyproject.toml` — прочитаны напрямую в рамках подготовки
  этого документа (2026-07-25).
- [2026-07-24-external-llm-provider.md](2026-07-24-external-llm-provider.md) — предшествующая фича,
  вводящая `LlmProviderConnectionModel`/секрет-стор/failover-guard, на которых базируется этот дизайн.
