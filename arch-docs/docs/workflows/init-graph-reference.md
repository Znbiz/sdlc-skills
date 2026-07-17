# Init Workflow — Graph Reference

Компактный справочник по `init_arch` LangGraph state machine: визуальная схема графа и разбор каждой ноды —
что делает, задействован ли LLM (и зачем), какие файлы формируются/меняются на диске, что происходит в
Postgres, что получаем на выходе в `session`, что происходит при ошибке, что логируется и видит пользователь,
и — человеческим языком — зачем этот шаг вообще существует.

Для истории реализации по этапам, quality gates, temporal contract и audit-событий — смотри
[init.md](init.md). Этот документ — навигационный срез, а не замена.

Источники: [graph.py](../../back/app/workflows/init_arch/graph.py),
[nodes.py](../../back/app/workflows/init_arch/nodes.py),
[steps.py](../../back/app/workflows/init_arch/domain/steps.py),
[prompts.py](../../back/app/workflows/init_arch/prompts.py).

## Визуальная схема

```mermaid
flowchart TD
    START([START]) --> defScope[define_scope]
    defScope --> reqRepos[request_repository_list]
    reqRepos -. interrupt: user_input .-> reqRepos
    reqRepos --> prepWs[prepare_temp_workspace]
    prepWs --> clone[clone_repositories\nLLM]
    clone --> refresh[refresh_main_branches]
    refresh --> plan[plan_repository_order]
    plan --> assess[assess_scope_and_domains\nLLM]
    assess --> analyze[analyze_repositories\nLLM x N]
    analyze --> interview[interview_user]
    interview -. interrupt: user_question .-> interview
    interview --> refine[refine_features\nLLM]
    refine --> nav[build_navigation_index]
    nav --> lint[run_knowledge_lint]
    lint --> validate[validate_final\nLLM]
    validate --> release[generate_release_notes\nLLM]
    release --> confirm[confirm_next_temporal_window]
    confirm -. interrupt: temporal_window_confirmation .-> confirm
    confirm -- continue_to_next_window --> refresh
    confirm -- finish / no more windows --> finalize[finalize_progress]
    finalize --> END([END])

    defScope -. retry ≤3, затем .-> err[handle_error]
    reqRepos -. retry ≤3, затем .-> err
    prepWs -. retry ≤3, затем .-> err
    clone -. retry ≤3, затем .-> err
    refresh -. retry ≤3, затем .-> err
    plan -. retry ≤3, затем .-> err
    assess -. retry ≤3, затем .-> err
    analyze -. retry ≤3, затем .-> err
    interview -. retry ≤3, затем .-> err
    refine -. retry ≤3, затем .-> err
    nav -. retry ≤3, затем .-> err
    lint -. retry ≤3, затем .-> err
    validate -. retry ≤3, затем .-> err
    release -. retry ≤3, затем .-> err
    confirm -. retry ≤3, затем .-> err
    finalize -. retry ≤3, затем .-> err
    err -. interrupt: step_failed → action=retry .-> defScope
    err -. interrupt: step_failed → action=retry .-> reqRepos
    err -. interrupt: step_failed → action=retry .-> prepWs
    err -. interrupt: step_failed → action=retry .-> clone
    err -. interrupt: step_failed → action=retry .-> refresh
    err -. interrupt: step_failed → action=retry .-> plan
    err -. interrupt: step_failed → action=retry .-> assess
    err -. interrupt: step_failed → action=retry .-> analyze
    err -. interrupt: step_failed → action=retry .-> interview
    err -. interrupt: step_failed → action=retry .-> refine
    err -. interrupt: step_failed → action=retry .-> nav
    err -. interrupt: step_failed → action=retry .-> lint
    err -. interrupt: step_failed → action=retry .-> validate
    err -. interrupt: step_failed → action=retry .-> release
    err -. interrupt: step_failed → action=retry .-> confirm
    err -. interrupt: step_failed → action=retry .-> finalize
    err -- action=abort --> END
```

Правила, которые не влезли в картинку без клаттера ([graph.py](../../back/app/workflows/init_arch/graph.py)):

- **Retry.** Для любой ноды (кроме `handle_error`): если `state["step_error"]` не пуст и `retry_count < 3` —
  LangGraph повторяет **ту же самую** ноду; при `retry_count >= 3` — переход в `handle_error`.
  Это единственная общая retry-семантика, `_route_after_node()`.
- **`handle_error` — не дед-энд, а четвёртая точка паузы.** Раньше это было терминальное ребро в `END`; теперь
  нода сама делает `interrupt({"interrupt_type": "step_failed", ...})` и ждёт решение пользователя. На
  `action="retry"` граф возвращается **в ту самую ноду, которая упала** (`_route_after_handle_error()` читает
  `state["session"].current_step` — он не продвигается, пока упавшая нода не завершится успешно, поэтому это
  всегда именно она); `retry_count`/`step_error` при этом сбрасываются в 0/`None`, так что упавшая нода
  получает полный новый бюджет retry. На `action="abort"` — как и раньше, `END` и `WorkflowStatus.FAILED`.
  Подробности — в разделе про `handle_error` ниже.
- **Единственная развилка вне retry/error-петли** — после `confirm_next_temporal_window`: либо loop-back на
  `refresh_main_branches` (следующее temporal-окно), либо вперёд на `finalize_progress`
  (`_route_after_confirm_next_temporal_window()`).
- **Четыре точки паузы** (`interrupt(...)`, LangGraph останавливает граф и ждёт resume от пользователя):
  `request_repository_list`, `interview_user`, `confirm_next_temporal_window`, `handle_error`.

## Как читать таблицу по каждой ноде

Для каждой ноды:

- **Что делает** — по факту, из `nodes.py`.
- **LLM** — вызывается ли `claude`/`codex` через `_run_step_worker`/`_simple_llm_step`, и если да — какой
  reference-файл (`STEP_TO_REFERENCE`/`CHECKLIST_ITEM_TO_REFERENCE`) подмешивается в промпт поверх
  [SKILL.md](../../back/app/workflows/shared_assets/init_arch/SKILL.md); ссылка на сборку промпта —
  всегда [`build_step_prompt()`](../../back/app/workflows/init_arch/prompts.py#L204).
- **Файлы** — что физически появляется/меняется на диске (в `workspace_dir`/raw layer `.temp`/`arch_repo_dir`),
  а что — нет.
- **В базе** — что дополнительно к общему паттерну (см. ниже) пишется в Postgres.
- **На выходе** — что записывается в `session`/`InitArchState` и какой следующий `StepId`.
- **При ошибке** — что именно ловится и как это соотносится с общей retry/`handle_error` схемой выше.
- **Логи и что видит пользователь** — конкретный `structlog`-вызов + что долетает до клиента через SSE
  (`_conversation_item_to_sse_payload` в [init_arch_workflow.py](../../back/app/services/init_arch_workflow.py)).
- **Зачем (по-человечески)** — какую реальную задачу этот шаг решает, без терминов реализации.

### Общий паттерн для «В базе» (одинаков для всех 16 нод, кроме отмеченного отдельно)

Три независимых механизма персистентности срабатывают на **каждой** ноде, включая полностью детерминированные:

1. **Audit-события** — `WORKFLOW_STEP_STARTED` перед началом, `WORKFLOW_STEP_COMPLETED` (или `WORKFLOW_STEP_FAILED`)
   после; `WorkflowAuditService.record()` ([audit.py](../../back/app/workflows/init_arch/audit.py)) асинхронно
   (fire-and-forget task) дублирует их в таблицу **`conversation_items`** — это то, что видно как лог/таймлайн
   выполнения по `session_id`.
2. **`workflow_runs`** — после каждой ноды `_drive_graph_stream()` вызывает `apply_node_output()` +
   `persist_workflow_record()` ([init_arch_workflow.py:106](../../back/app/services/init_arch_workflow.py#L106)),
   который делает `upsert_workflow_run()` — целиком перезаписывает сериализованный `WorkflowRecord`, включая
   весь `session` (репозитории, artifacts, historical state, open questions), `current_step_id`,
   `pending_interrupt`. Это canonical source of truth о состоянии workflow.
3. **LangGraph checkpointer** — отдельно от двух вышеперечисленных, `AsyncPostgresSaver`
   ([checkpointer.py](../../back/app/workflows/init_arch/checkpointer.py)) чекпоинтит сам graph state (какая
   нода следующая, накопленный `InitArchState`) в своих собственных таблицах, по `thread_id = workflow_id`.
   Именно это позволяет `retry`/`resume` продолжать с места остановки после падения процесса.

Для LLM-нод (`_run_step_worker` → `LlmCliService.run_task()` → `task_runner.run_cli_task()`) добавляется
четвёртый источник: `EventType.LLM_TASK_REQUESTED` → `LLM_TASK_COMPLETED`/`LLM_TASK_FAILED`
([task_runner.py:293-312](../../back/app/services/task_runner.py#L293-L312)), плюс сам `CliTask` (prompt,
stdout, stderr, exit_code — с маскированием секретов и обрезкой, см. [init.md → Audit retention и masking](init.md#audit-retention-и-masking))
персистится в таблицу **`cli_tasks`**.

---

### 1. `define_scope` — не LLM

**Что делает** ([nodes.py:117](../../back/app/workflows/init_arch/nodes.py#L117)): инициализирует progress-файл
(`guard_service.init_progress`), затем `advance_step` на `request_repository_list`.

**LLM**: нет (убрано). Изначально нода звала агента, но `product_name`/`analysis_scope`/`repo_list` уже
приходят в `start_init_arch_workflow()` как typed API input — интерпретировать на этом шаге нечего, а
результат LLM-вызова никуда не парсился: переход на `REQUEST_REPOSITORY_LIST` шёл с захардкоженным
`note="Scope определён через LangGraph"`, не из `llm_result`. Единственным потребителем был `last_cli_output`
(чисто нарративный `cli_output` SSE-эвент для UX) — решили, что это не стоит реального LLM-вызова, и убрали
`_run_step_worker` из ноды. `StepDefinition.uses_llm_worker` для `DEFINE_SCOPE`
([steps.py:18](../../back/app/workflows/init_arch/domain/steps.py#L18)) приведён в соответствие (`False`).

**Файлы**: нет. Ни один файл на диске не создаётся и не меняется — `init_progress`/`advance_step` работают
только с in-memory `session`; `repo-initialization-progress.yaml` тоже не создаётся (см. ниже, раздел
«Compatibility-поле `progress_file_path`»).

**В базе**: только общий паттерн (`GUARD_COMMAND_REQUESTED`/`APPLIED` x2 — по разу от `init_progress` и от
`advance_step` — плюс `WORKFLOW_STEP_STARTED`/`COMPLETED`), без дополнений.

**На выходе**: `session.current_step = REQUEST_REPOSITORY_LIST`; `last_llm_result = None`.

**При ошибке**: любое исключение из `init_progress`/`advance_step` ловится общим `try/except`, эмитит
`WORKFLOW_STEP_FAILED`, возвращает `{"step_error": ..., "retry_count": +1}` → входит в общий retry-цикл графа.

**Логи и что видит пользователь**: `logger.info("workflow.node.define_scope", workflow_id=..., current_step=...)`
на старте; audit `WORKFLOW_STEP_STARTED` → `WORKFLOW_STEP_COMPLETED` (или `WORKFLOW_STEP_FAILED`) с payload
`next_step=...`. Пользователю через SSE это долетает как `{"event_type": "step_started", "step_id": "define_scope", ...}`
(см. `_conversation_item_to_sse_payload`, ветка `step_transition`).

**Зачем (по-человечески)**: это стартовая отметка — сервис фиксирует, что прогон вообще начался, под каким
именем продукта и с каким scope анализа, и переводит workflow в состояние "жду список репозиториев". Без
этого шага не с чем было бы сверять весь последующий прогресс.

---

### 2. `request_repository_list` — не LLM, ⏸ interrupt

**Что делает** ([nodes.py:157](../../back/app/workflows/init_arch/nodes.py#L157)): если `session.repositories`
уже заполнен — просто `advance_step` на `prepare_temp_workspace`; если нет —
`interrupt({"interrupt_type": "user_input", "field": "repo_list", "question": "..."})`.

**LLM**: нет. Это чистая маршрутизация/пауза на человека, промпт не строится.

**Файлы**: нет.

**В базе**: если пауза — только `WORKFLOW_STEP_STARTED` (без `COMPLETED`), но `persist_workflow_record()` всё
равно вызывается сразу после `apply_interrupt()` ([init_arch_workflow.py:747-748](../../back/app/services/init_arch_workflow.py#L747-L748))
— так что `pending_interrupt` и текущее состояние `session` уже лежат в `workflow_runs` до получения ответа
от пользователя (иначе `resume` после рестарта сервиса был бы невозможен).

**На выходе**: либо `session.current_step = PREPARE_TEMP_WORKSPACE`, либо граф останавливается и
`WorkflowRecord.pending_interrupt` заполняется interrupt-payload'ом.

**При ошибке**: ветка "репозитории уже есть" (`advance_step`) обёрнута в `try/except`, как и у всех остальных
нод — падение уходит в `step_error`/`retry_count` и проходит обычный retry/`handle_error` путь. Ветка
"нет списка" (`interrupt(...)`) намеренно **не** обёрнута — она должна свободно поднимать LangGraph-овское
control-flow исключение прерывания, а не перехватываться как ошибка шага.

**Логи и что видит пользователь**: `logger.info("workflow.node.request_repository_list", ...)`; при паузе —
audit `WORKFLOW_STEP_STARTED` без `WORKFLOW_STEP_COMPLETED` (граф просто остановлен). Пользователь получает
через SSE `{"event_type": "interrupted", "interrupt_type": "user_input", "field": "repo_list", "question": "Укажите список репозиториев..."}`
— это то, что фронт должен отрисовать как форму ввода.

**Зачем (по-человечески)**: получить от пользователя список репозиториев для анализа, если он не был передан
сразу при запуске. Без этого списка почти весь дальнейший pipeline (клонирование, анализ, документация)
бессмысленен — поэтому это первая точка, где сервис в принципе может остановиться и подождать человека.

---

### 3. `prepare_temp_workspace` — не LLM

**Что делает** ([nodes.py:241](../../back/app/workflows/init_arch/nodes.py#L241)): детерминированно создаёт на
диске `workspace_dir`, `raw_workspace_dir` и `arch_repo_dir` через
`pathlib.Path(...).mkdir(parents=True, exist_ok=True)` ([nodes.py:233](../../back/app/workflows/init_arch/nodes.py#L233))
и сразу `advance_step` на `CLONE_REPOSITORIES`.

**LLM**: нет. Раньше это был `_simple_llm_step`, который просил CLI-агента выполнить те же `mkdir` внутри
контейнера — чистое файловое действие без какого-либо reasoning, поэтому шаг переведён на прямой Python-вызов
по аналогии с `refresh_main_branches`/`plan_repository_order` (см. `uses_llm_worker=False` в
[steps.py](../../back/app/workflows/init_arch/domain/steps.py#L27)). Промпт для этого шага больше не строится.

**Файлы**: сервис сам создаёт каталоги — `_resolve_init_arch_paths()`
([init_arch_workflow.py](../../back/app/services/init_arch_workflow.py)) резолвит и валидирует пути ещё на
старте workflow, но `mkdir` не вызывает, так что до этой ноды `workspace_dir` может физически не существовать.
Эта нода создаёт: сам `workspace_dir`, raw layer (по умолчанию `{workspace_dir}/.temp`,
`WORKFLOWS__INIT__RAW_WORKSPACE_SUBDIR`) и `arch_repo_dir` (по умолчанию `{workspace_dir}/arch-doc`,
`WORKFLOWS__INIT__ARCH_REPO_DIRNAME`). `mkdir(..., exist_ok=True)` — идемпотентно, повторный запуск/retry не
падает на уже существующих каталогах.

**В базе**: только `WORKFLOW_STEP_STARTED`/`COMPLETED`/`FAILED` — без `LLM_TASK_*` и без записи в `cli_tasks`,
как и у остальных не-LLM нод.

**На выходе**: `session.current_step = CLONE_REPOSITORIES`.

**При ошибке**: `try/except` вокруг `mkdir`/`advance_step` → `step_error` → retry ≤3 → `handle_error` (тот же
паттерн, что у `refresh_main_branches`).

**Логи и что видит пользователь**: `logger.info("workflow.node.prepare_temp_workspace", ...)`; audit
`WORKFLOW_STEP_STARTED`/`COMPLETED`/`FAILED`. Пользователю — `step_started`/следующий `step_started` по мере
продвижения; `cli_output` для этого шага не публикуется, т.к. CLI-агент не запускается.

**Зачем (по-человечески)**: подготовить рабочую площадку на диске — раздельные каталоги под "сырые"
исходники репозиториев и под итоговую документацию — прежде чем в них вообще что-то класть. Разделение layer'ов
важно: raw-слой только для чтения/checkout, arch-repo-слой только для synthesis-артефактов, они не должны
смешиваться.

---

### 4. `clone_repositories` — LLM

**Что делает** ([nodes.py:274](../../back/app/workflows/init_arch/nodes.py#L274)): `_simple_llm_step` просит
агента выполнить `git clone <url> <путь>` для каждого репозитория из списка.

**LLM**: да. Reference не задан → [SKILL.md](../../back/app/workflows/shared_assets/init_arch/SKILL.md) +
жёстко вшитая в промпт инструкция `git clone`
([prompts.py:226-232](../../back/app/workflows/init_arch/prompts.py#L226-L232)) + список репозиториев.
LLM здесь используется как исполнитель shell-команды внутри изолированного workspace — сервис сам `git clone`
не делает.

**Файлы**: полные checkout'ы репозиториев появляются в raw layer — `{raw_workspace_dir}/<repository_name>`
(например `.temp/svc-a/`), по одному подкаталогу на репозиторий из `session.repositories`. Это единственная
нода, где реально скачивается весь исходный код, с которым потом будет работать анализ.

**В базе**: + `LLM_TASK_REQUESTED`/`COMPLETED`/`cli_tasks`, как и у любой LLM-ноды.

**На выходе**: `session.current_step = REFRESH_MAIN_BRANCHES`.

**При ошибке**: стандартный `_simple_llm_step` путь (см. выше).

**Логи и что видит пользователь**: `logger.info("workflow.node.clone_repositories", ...)` + те же
`WORKFLOW_STEP_*` события. Пример реального провала: агент не смог склонировать приватный репозиторий
(нет доступа) → `llm_result`/exit code некорректны → исключение → `step_error = "..."` → после 3 попыток
`WORKFLOW_STEP_FAILED(step_id=clone_repositories, error=...)` → граф уходит в `handle_error`, который
приостанавливает workflow и ждёт решения пользователя — см. раздел про `handle_error` ниже.

**Зачем (по-человечески)**: получить реальный исходный код репозиториев локально — без него анализировать
физически нечего, все последующие шаги (git log, чтение файлов, построение diff) работают именно с этими
checkout'ами.

---

### 5. `refresh_main_branches` — не LLM

**Что делает** ([nodes.py:283](../../back/app/workflows/init_arch/nodes.py#L283)):
`historical_service.refresh_main_branches(...)` — детерминированный git fetch/read main branch, remote HEAD,
`created_at` по каждому репозиторию.

**LLM**: нет. Чисто механическая git-операция, нет интерпретации контента.

**Файлы**: нет новых файлов и нет изменений working tree — только read-only git-команды внутри уже
склонированных репозиториев (`git rev-parse`, `git log -1 --format=...` и т.п., см.
`_read_repository_facts()` в [historical.py:417](../../back/app/workflows/init_arch/historical.py#L417)).
Working tree остаётся на том же коммите, на котором был после `clone_repositories`.

**В базе**: + `GUARD_COMMAND_REQUESTED`/`APPLIED(command="refresh_main_branches")` из
`HistoricalPrepService._record_event()`.

**На выходе**: `session.current_step = PLAN_REPOSITORY_ORDER`; заполнены `repositories[*].main_branch`,
`remote_head_commit`, `created_at`.

**При ошибке**: собственный `try/except` вокруг `historical_service.refresh_main_branches` +
`guard_service.advance_step` → `step_error` → тот же retry-цикл.

**Логи и что видит пользователь**: `logger.info("workflow.node.refresh_main_branches", ...)`; audit
`WORKFLOW_STEP_STARTED`/`COMPLETED` с `note=historical_result.summary` (человекочитаемая сводка, например
"3 repositories refreshed, 1 remote unreachable").

**Зачем (по-человечески)**: узнать актуальное состояние main branch каждого репозитория (текущий HEAD, дату
создания репозитория) — это опорные факты, без которых нельзя построить временную шкалу для исторического
анализа на следующем шаге.

---

### 6. `plan_repository_order` — не LLM

**Что делает** ([nodes.py:320](../../back/app/workflows/init_arch/nodes.py#L320)):
`historical_service.plan_repository_order(...)` (выбор anchor-репозитория, snapshot date, порядок обхода) +
`resolve_target_commits(..., checkout=True)` (резолв target-коммитов под дату и checkout).

**LLM**: нет.

**Файлы**: единственная детерминированная нода, которая реально **меняет содержимое working tree** —
`resolve_target_commits(..., checkout=True)` вызывает `git checkout <commit_sha>`
(`_checkout_commit()`, [historical.py:468](../../back/app/workflows/init_arch/historical.py#L468)) в каждом
репозитории из raw layer, переключая его на снапшот нужной даты. Новых файлов не создаётся, но состав файлов
в `.temp/<repo>` физически меняется на то, каким репозиторий был на выбранный `analysis_target_commit`.

**В базе**: + `GUARD_COMMAND_*` (`plan_repository_order`, `resolve_target_commits`) и temporal-события
`TEMPORAL_RANGE_REQUESTED`/`TEMPORAL_DIFF_COLLECTED`/`TEMPORAL_RANGE_RESOLVED`/`TEMPORAL_DIFF_MISSING`/`TEMPORAL_RANGE_INVALID`
— по одному набору на каждый repository-window (`_record_temporal_delta_event()`).

**На выходе**: `session.current_step = ASSESS_SCOPE_AND_DOMAINS`; заполнены `historical_analysis.*`,
`repositories[*].analysis_target_commit`, `commit_range*`, `diff_stat_summary`, `commit_log_summary` и т.д.
(temporal-delta слой — подробности в [init.md → Temporal Contract](init.md#temporal-contract)).

**При ошибке**: тот же паттерн `try/except` → `step_error` → retry. Отдельно стоит помнить про quality gate:
если historical prep не прошёл (`historical_prep_is_complete()` вернул `False`), `advance_step` кидает
`DomainOperationError` — это тоже попадает в тот же `except`, т.е. с точки зрения графа неотличимо от любой
другой ошибки шага (тот же retry/handle_error путь).

**Логи и что видит пользователь**: `logger.info("workflow.node.plan_repository_order", ...)`; audit `note`
объединяет `planned_result.summary` и `resolved_result.summary`. Пример: если для репозитория не удалось
построить commit range (`invalid_range`), это уже не ошибка самой ноды — нода завершится успешно, а
проблема всплывёт позже, на попытке перейти к `assess_scope_and_domains` (см. quality gate выше).

**Зачем (по-человечески)**: решить, в каком порядке и на каком именно "срезе времени" анализировать каждый
репозиторий (чтобы все репозитории описывались согласованно, "как будто сфотографированы в один момент"), и
физически переключить рабочие копии на этот момент — а заодно посчитать, что изменилось с прошлого такого
среза (diff), если это не первое окно.

---

### 7. `assess_scope_and_domains` — LLM

**Что делает** ([nodes.py:359](../../back/app/workflows/init_arch/nodes.py#L359)): `_simple_llm_step` просит
агента разбить репозитории на домены/модули (`DomainDefinition`).

**LLM**: да. Reference: [checklist-scope-and-domain-assessment.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-scope-and-domain-assessment.md)
([prompts.py:24](../../back/app/workflows/init_arch/prompts.py#L24)). Нужен LLM для смыслового разбиения
кодовой базы на домены — требует понимания структуры и назначения кода.

**Файлы**: агент может писать в `arch_repo_dir` по общей инструкции промпта (`"Все knowledge-артефакты и
synthesis-результаты пиши только в {arch_repo_dir}"`), но **находка**: `node_assess_scope_and_domains` не
вызывает `knowledge_service.collect_worker_artifacts(...)`, в отличие от `refine_features`/`interview_user`/
`generate_release_notes` — то есть если агент что-то реально запишет на этом шаге, оно не попадёт в
`session.artifacts` и не получит audit `ARTIFACT_WRITTEN`. Более того, сами структурированные результаты
разбиения на домены (`repositories[*].domain_strategy`/`.domains` в `RepositoryExecution`) нигде в коде не
заполняются — ни один модуль не пишет в эти поля. Reference-чеклист шага говорит, что результат должен
храниться в `domain_map` ([checklist-scope-and-domain-assessment.md:5](../../back/app/workflows/shared_assets/init_arch/references/checklist-scope-and-domain-assessment.md#L5))
— это терминология legacy standalone CLI (`analysis_guard.py`), а не текущей backend-модели; в
service-owned workflow результат этого шага фактически нигде структурно не сохраняется, только в
собственном тексте/файлах агента (если он их пишет) и в стенограмме диалога.

**В базе**: + `LLM_TASK_*`/`cli_tasks`, без `ARTIFACT_WRITTEN`.

**На выходе**: `session.current_step = ANALYZE_REPOSITORIES`; поля `domain_strategy`/`domains` формально
существуют в модели, но фактически остаются пустыми (см. «Файлы» выше).

**При ошибке**: стандартный `_simple_llm_step` путь.

**Логи и что видит пользователь**: те же `WORKFLOW_STEP_*` события; примечательно, что этот шаг требует
`requires_historical_prep=True` ([steps.py:53](../../back/app/workflows/init_arch/domain/steps.py#L53)) —
если historical prep неполный, сюда вообще не попадём (см. ноду 6).

**Зачем (по-человечески)**: по замыслу — решить, насколько крупный репозиторий и есть ли в нём выраженные
бизнес-домены, чтобы на следующем шаге анализировать его либо целиком, либо домен за доменом. По факту, из-за
находки выше, это решение сейчас остаётся "в голове" у агента и в его тексте, а не в структурированном
состоянии, которое использовалось бы дальше по графу.

---

### 8. `analyze_repositories` — LLM (несколько вызовов подряд), самый тяжёлый узел

**Что делает** ([nodes.py:368](../../back/app/workflows/init_arch/nodes.py#L368)): для каждого репозитория —
`start_repository` → `route_checklist_items(...)` (детерминированно выбирает релевантные пункты чеклиста по
diff severity, без LLM) → на **каждый** выбранный пункт отдельный LLM-вызов
(`task_kind=REPOSITORY_CHECKLIST_ITEM`) → `complete_repository_item` → если найдены open questions —
`register_open_questions` → в конце `complete_repository`; после всех репозиториев — `sync_open_questions` и
`advance_step` на `interview_user`.

**LLM**: да, per checklist item. Своего единого reference у шага нет (`STEP_TO_REFERENCE["analyze_repositories"] = ""`);
вместо этого на каждый пункт подставляется свой файл через
[`CHECKLIST_ITEM_TO_REFERENCE`](../../back/app/workflows/init_arch/prompts.py#L36-L58)
(см. подстановку в [prompts.py:207-208](../../back/app/workflows/init_arch/prompts.py#L207-L208)):

| checklist item | reference |
|---|---|
| `repository_classification` | [checklist-repository-classification.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-repository-classification.md) |
| `repository_structure_mapping` | [checklist-repository-structure-mapping.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-repository-structure-mapping.md) |
| `entrypoints_and_interfaces` | [checklist-entrypoints-and-interfaces.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-entrypoints-and-interfaces.md) |
| `business_flow_orchestration` | [checklist-business-flow-orchestration.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-business-flow-orchestration.md) |
| `configs_and_runtime` | [checklist-configs-and-runtime.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-configs-and-runtime.md) |
| `tech_stack_collection` | [checklist-tech-stack.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-tech-stack.md) |
| `contracts_and_schemas` | [checklist-contracts-and-schemas.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-contracts-and-schemas.md) |
| `data_and_storage` | [checklist-data-and-storage.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-data-and-storage.md) |
| `domain_entities` | [checklist-domain-entities.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-domain-entities.md) |
| `integrations_and_dependencies` | [checklist-integrations-and-dependencies.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-integrations-and-dependencies.md) |
| `tests_and_behavior_evidence` | [checklist-tests-and-behavior-evidence.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-tests-and-behavior-evidence.md) |
| `glossary_updates`, `open_questions_review_and_updates` | [checklist-glossary-and-open-questions.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-glossary-and-open-questions.md) |
| `feature_discovery_and_updates`, `features_index_updates` | [checklist-features-and-index.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-features-and-index.md) |
| `roles_and_permissions_updates`, `security_and_auth_updates`, `deployment_and_operability`, `risks_and_tech_debt_updates` | [checklist-roles-security-operability-risks.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-roles-security-operability-risks.md) |
| `architecture_artifact_updates` | [checklist-architecture-artifact-updates.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-architecture-artifact-updates.md) |
| `repository_consistency_review` | [checklist-repository-consistency-review.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-repository-consistency-review.md) |

**Файлы**: это основной "пишущий" шаг всего workflow — агент реально читает код в raw layer и пишет находки
в `arch_repo_dir` (какие именно файлы — зависит от routed checklist item: `features/*.md`,
`architecture/*.md`, `architecture/contracts/*`, `architecture/storage/*.yml` и т.д., см. reference-таблицу
выше). **Находка, аналогичная ноде 7**: `node_analyze_repositories` тоже не вызывает
`collect_worker_artifacts(...)` ни разу за весь цикл — файлы, которые агент пишет здесь, физически
появляются на диске, но не регистрируются в `session.artifacts`/audit `ARTIFACT_WRITTEN`. Единственное, что
регистрируется структурно — `checklist_items_completed` (какие пункты прошли) и `open_questions` (если
агент вернул `open_questions_found` в JSON-контракте).

**В базе**: `DIFF_SIGNAL_ROUTED` на каждый репозиторий (routing-решение) + `LLM_TASK_*`/`cli_tasks` на
**каждый** пункт чеклиста отдельно — на репозиторий с полным чеклистом это может быть 15-17 отдельных
LLM-вызовов, каждый со своей строкой в `cli_tasks`.

**На выходе**: `session.current_step = INTERVIEW_USER`; по каждому репозиторию —
`checklist_items_completed`, `analysis_status = "completed"`, новые `open_questions` (если найдены).
Файлы в `arch_repo_dir` уже написаны агентом, но в `session.artifacts` не отражены (см. «Файлы» выше).

**При ошибке**: один общий `try/except` вокруг всего цикла по всем репозиториям и всем пунктам чеклиста —
если упадёт LLM-вызов на любом пункте любого репозитория, весь узел считается failed
(`step_error`), а не только этот конкретный пункт; retry ≤3 повторяет **весь** узел заново (включая уже
пройденные репозитории/пункты, если session state не сохранил частичный прогресс на диске — стоит явно
проверить идемпотентность при реальном прогоне).

**Логи и что видит пользователь**: на каждый репозиторий — audit `DIFF_SIGNAL_ROUTED`
(`diff_severity`, `routed_items`, `total_items`); пользователю в UI имеет смысл показывать прогресс
"репозиторий N из M, пункт K из routed". Пример реальной ошибки: агент вернул невалидный JSON
(не соответствует `LlmTaskResult`-контракту) → парсинг падает → `step_error` → после исчерпания retry
пользователь видит карточку `step_failed` с текстом ошибки парсинга и может нажать «Повторить», не теряя
уже пройденные репозитории/пункты чеклиста (см. раздел про `handle_error`).

**Зачем (по-человечески)**: это и есть сам анализ — по каждому релевантному аспекту (структура кода, API,
данные и хранилища, безопасность, тесты и т.д.) агент реально читает исходники и пишет находки в
документацию. `route_checklist_items` заранее сужает объём работы для репозиториев, где изменилось немного
(diff-based routing), чтобы не гонять полный 17-пунктовый чеклист там, где это не нужно.

---

### 9. `interview_user` — LLM внутри цикла, ⏸ interrupt

**Что делает** ([nodes.py:465](../../back/app/workflows/init_arch/nodes.py#L465)): `while True` по открытым
`open_questions`: если вопросов нет — `advance_step` на `refine_features`; иначе `interrupt(...)` с текущим
вопросом → на resume `record_user_answer` → LLM reconciliation → `collect_worker_artifacts` →
`close_user_question` → `sync_open_questions` → следующая итерация.

**LLM**: да, `task_kind=INTERVIEW_RECONCILIATION`. Reference:
[checklist-glossary-and-open-questions.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-glossary-and-open-questions.md)
([prompts.py:26](../../back/app/workflows/init_arch/prompts.py#L26)). Нужен LLM, чтобы интерпретировать
свободный ответ пользователя и обновить knowledge-артефакты соответствующим образом.

**Файлы**: `arch_repo_dir/open-questions.md` **перезаписывается целиком** на каждой итерации
(`sync_open_questions()` — рендерит markdown-таблицу заново из `session.open_questions`, не аппендит,
[knowledge.py:192](../../back/app/workflows/init_arch/knowledge.py#L192)). Плюс агент во время
`INTERVIEW_RECONCILIATION`-вызова может создавать/обновлять knowledge-файлы по итогам ответа пользователя —
эти уже регистрируются через `collect_worker_artifacts` (в отличие от нод 7-8).

**В базе**: + `USER_ANSWER_RECORDED` на каждый принятый ответ, `ARTIFACT_WRITTEN(open-questions.md)` на
каждую итерацию, `ARTIFACT_WRITTEN` на артефакты, которые реально вернул агент, `LLM_TASK_*`/`cli_tasks` на
каждый LLM-вызов reconciliation.

**На выходе**: закрытые `open_questions[*].status = "answered"`, обновлённый `open-questions.md`; когда
вопросов не осталось — `session.current_step = REFINE_FEATURES`.

**При ошибке**: один `try/except` вокруг всего `while`-цикла — падение на любой итерации (например, ответ
пользователя пустой — см. `_extract_question_answer`, кидает `ValueError`) уводит весь узел в `step_error` и
общий retry.

**Логи и что видит пользователь**: audit `USER_ANSWER_RECORDED` на каждый принятый ответ. Пользователь видит
серию SSE `interrupted` (`{"event_type": "interrupted", "interrupt_type": "user_question", "question_id": "Q-3", "question": "...", "remaining_count": 2}`)
— по одному на каждый открытый вопрос, до полного закрытия списка.

**Зачем (по-человечески)**: разрешить неоднозначности, которые агент не смог закрыть сам во время анализа
(например, непонятно назначение модуля, или неясно, кто отвечает за конкретный домен). Без ответа
пользователя часть документации так и осталась бы помечена как открытый вопрос.

---

### 10. `refine_features` — LLM

**Что делает** ([nodes.py:551](../../back/app/workflows/init_arch/nodes.py#L551)):
`knowledge_service.bootstrap_arch_repo` (детерминированно создаёт скелет `features/`, `architecture/`,
`wiki/`) → LLM пишет/уточняет фичи → `collect_worker_artifacts` фиксирует созданные файлы.

**LLM**: да. Reference: [checklist-features-and-index.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-features-and-index.md)
([prompts.py:27](../../back/app/workflows/init_arch/prompts.py#L27)). Нужен для синтеза текстовых
артефактов фич из собранных находок.

**Файлы**: `bootstrap_arch_repo()` ([knowledge.py:85](../../back/app/workflows/init_arch/knowledge.py#L85))
детерминированно создаёт каталоги `features/`, `architecture/`, `architecture/integrations`,
`architecture/contracts`, `architecture/storage`, `architecture/structure`, `release-notes/`, `wiki/`,
`wiki/maps/` и — **только если файла ещё нет** (`if target_path.exists(): continue`) — заполняет из
шаблонов: `features-index.md`, `glossary.md`, `open-questions.md`, `wiki/index.md`, `wiki/log.md`,
`wiki/maps/compile-report.md` и 10 одиночных `architecture/*.md`/`architecture/landscape.yaml`
(`_ARCHITECTURE_TEMPLATE_ASSETS`). После этого LLM пишет/уточняет сами файлы фич в `features/*.md`.

**В базе**: `ARTIFACT_WRITTEN` на каждый реально созданный bootstrap-файл (не на пропущенные существующие) +
`ARTIFACT_WRITTEN` на каждый артефакт, который вернул агент, + `LLM_TASK_*`/`cli_tasks`.

**На выходе**: `session.current_step = BUILD_NAVIGATION_INDEX`; новые/обновлённые файлы в
`arch_repo_dir/features/*`.

**При ошибке**: стандартный путь (`try/except` → `step_error` → retry).

**Логи и что видит пользователь**: audit `ARTIFACT_WRITTEN` на каждый созданный/обновлённый файл —
это то, что стоит показывать пользователю как "создан файл features/checkout.md" по мере прогона.

**Зачем (по-человечески)**: заложить структуру будущей документации (каталоги и файлы-заглушки, если их ещё
нет) и описать сами фичи продукта — это первый шаг, где сырые находки из анализа превращаются в
человекочитаемые артефакты, а не просто накапливаются в session state.

---

### 11. `build_navigation_index` — не LLM

**Что делает** ([nodes.py:598](../../back/app/workflows/init_arch/nodes.py#L598)):
`knowledge_service.compile_navigation(...)` — механическая сборка `wiki/index.md` и
`wiki/maps/compile-report.md` по уже написанным файлам.

**LLM**: нет. Хотя в `STEP_TO_REFERENCE` для этого шага числится
[knowledge-workflow.md](../../back/app/workflows/shared_assets/init_arch/references/knowledge-workflow.md)
([prompts.py:28](../../back/app/workflows/init_arch/prompts.py#L28)) — это мёртвая запись, промпт для этой
ноды никогда не строится, т.к. `_run_step_worker` тут не вызывается вовсе. Стоит либо убрать эту строку из
словаря, либо (если по замыслу здесь должен быть LLM-шаг) добавить вызов.

**Файлы**: `wiki/index.md` и `wiki/maps/compile-report.md` **перезаписываются целиком** —
`compile_navigation()` ([knowledge.py:135](../../back/app/workflows/init_arch/knowledge.py#L135)) читает уже
существующие markdown-файлы в `arch_repo_dir` (в первую очередь то, что написали ноды 8/10) и пересобирает
индекс/отчёт заново. Новых знаний не добавляет — только переупаковывает уже написанное.

**В базе**: `ARTIFACT_WRITTEN` x2 (по одному на каждый из двух файлов).

**На выходе**: `session.current_step = RUN_KNOWLEDGE_LINT`.

**При ошибке**: `try/except` вокруг `compile_navigation` → `step_error` → retry.

**Логи и что видит пользователь**: audit `ARTIFACT_WRITTEN(wiki/index.md)`, `ARTIFACT_WRITTEN(wiki/maps/compile-report.md)`.

**Зачем (по-человечески)**: собрать оглавление и карту связей по уже написанной документации, чтобы по ней
можно было ориентироваться (найти нужный файл, увидеть неразрешённые ссылки), не читая весь repo целиком.

---

### 12. `run_knowledge_lint` — не LLM

**Что делает** ([nodes.py:635](../../back/app/workflows/init_arch/nodes.py#L635)):
`knowledge_service.lint_knowledge(...)` — формальные структурные проверки knowledge-слоя (residue от
шаблонов, обязательные файлы, контракты OpenAPI/AsyncAPI, консистентность commit между landscape и structure
— см. [init.md → Knowledge Pipeline Gates](init.md#knowledge-pipeline-gates)).

**LLM**: нет — reference [knowledge-workflow.md](../../back/app/workflows/shared_assets/init_arch/references/knowledge-workflow.md)
тоже мёртвый по той же причине, что и в ноде 11.

**Файлы**: нет — `lint_knowledge()` ([knowledge.py:169](../../back/app/workflows/init_arch/knowledge.py#L169))
только читает файлы в `arch_repo_dir` и валидирует их (residue от шаблонов, обязательные секции, контракты
OpenAPI/AsyncAPI, консистентность commit между landscape и structure), ничего не пишет
(`written_artifacts=[]` всегда).

**В базе**: без дополнений к общему паттерну — `ARTIFACT_WRITTEN` не эмитится.

**На выходе**: `session.current_step = VALIDATE_FINAL`.

**При ошибке**: важное отличие от прочих — `lint_knowledge` при blocking-проблемах не просто "падает
случайно", а осознанно кидает `ValueError` с текстом вида `"ERROR: ..."` при обнаруженных нарушениях; это
всё равно попадает в тот же общий `try/except` → `step_error` → retry ≤3 → `handle_error`, т.е. с точки
зрения графа неотличимо от инфраструктурной ошибки — семантика "это осмысленный lint-fail, а не баг"
теряется на уровне графа и видна только в тексте `error_message`.

**Логи и что видит пользователь**: audit `note=lint_result.summary`. Пример: после трёх неудачных попыток
пользователь увидит карточку `step_failed` с текстом вида
`"ERROR: architecture/hld.md still contains template placeholder <...>"` и выбор «Повторить» (после ручного
фикса шаблона) или «Прервать».

**Зачем (по-человечески)**: проверить, что документация не осталась с незаполненными шаблонными
плейсхолдерами, битыми ссылками между секциями или рассинхронизированными commit'ами между обзорным и
детальным слоями — прежде чем считать анализ содержательно завершённым, а не просто "все шаги пройдены".

---

### 13. `validate_final` — LLM (несмотря на `uses_llm_worker=False` в декларации шага)

**Что делает** ([nodes.py:672](../../back/app/workflows/init_arch/nodes.py#L672)): `_simple_llm_step` —
просит агента выполнить финальную ревизию консистентности knowledge-слоя.

**LLM**: да, фактически. Reference:
[checklist-repository-consistency-review.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-repository-consistency-review.md)
([prompts.py:30](../../back/app/workflows/init_arch/prompts.py#L30)). **Несостыковка**: в
[steps.py:87](../../back/app/workflows/init_arch/domain/steps.py#L87) шаг объявлен как
`uses_llm_worker=False`, но `node_validate_final` жёстко вызывает `_simple_llm_step`, которая всегда зовёт
`_run_step_worker`. Похоже, поле `uses_llm_worker` в `StepDefinition` сейчас не влияет на реальное
поведение ноды (просто метаданные/декларация) — стоит либо синхронизировать флаг, либо перепроверить, где
ещё он используется.

**Файлы**: как и в нодах 7-8, агент может писать/дополнять файлы в `arch_repo_dir` по общей инструкции
промпта, но `node_validate_final` тоже не вызывает `collect_worker_artifacts` — реальные правки (если агент
их вносит в рамках "финальной ревизии") на диске появляются, но в `session.artifacts`/`ARTIFACT_WRITTEN` не
регистрируются.

**В базе**: + `LLM_TASK_*`/`cli_tasks`, без `ARTIFACT_WRITTEN`.

**На выходе**: `session.current_step = GENERATE_RELEASE_NOTES`.

**При ошибке**: стандартный `_simple_llm_step` путь.

**Логи и что видит пользователь**: стандартные `WORKFLOW_STEP_*` события.

**Зачем (по-человечески)**: финальная ревизия консистентности всего knowledge-слоя целиком (не файл за
файлом, как в `run_knowledge_lint`, а по смыслу) — человекоподобная проверка "не противоречит ли одна часть
документации другой" перед тем, как переходить к генерации release notes.

---

### 14. `generate_release_notes` — LLM

**Что делает** ([nodes.py:681](../../back/app/workflows/init_arch/nodes.py#L681)): зовёт агента с
контекстным блоком release notes (`_build_release_notes_context_block`, temporal delta текущего окна) →
`collect_worker_artifacts` → `advance_step`.

**LLM**: да. Reference: [checklist-release-notes.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-release-notes.md)
([prompts.py:31](../../back/app/workflows/init_arch/prompts.py#L31)). Нужен для генерации связного текста
на основе диффов окна.

**Файлы**: один новый файл с именем по строгому шаблону —
`release-notes/window-<window_index>-<snapshot_date>.md` (например `release-notes/window-3-2020-01-01.md`,
[checklist-release-notes.md:7](../../back/app/workflows/shared_assets/init_arch/references/checklist-release-notes.md#L7)),
куда агент пишет summary изменений за текущее temporal-окно со ссылками на изменённые артефакты.

**В базе**: `ARTIFACT_WRITTEN` на этот файл + `LLM_TASK_*`/`cli_tasks`.

**На выходе**: `session.current_step = CONFIRM_NEXT_TEMPORAL_WINDOW`; новый файл release notes за окно.

**При ошибке**: стандартный путь (`try/except` вокруг worker + `collect_worker_artifacts` + `advance_step`).

**Логи и что видит пользователь**: audit `ARTIFACT_WRITTEN` на файл release notes, `note=knowledge_result.summary`.

**Зачем (по-человечески)**: зафиксировать человекочитаемое summary того, что реально поменялось в продукте с
прошлого temporal-снапшота — это то, что можно показать человеку без необходимости читать все diff'ы и
внутренние артефакты самому.

---

### 15. `confirm_next_temporal_window` — не LLM, ⏸ interrupt, единственная развилка вне error-петли

**Что делает** ([nodes.py:741](../../back/app/workflows/init_arch/nodes.py#L741)):
`historical_service.compute_next_window(...)`; если следующего окна нет — сразу `advance_step` на
`finalize_progress`; если есть — `interrupt({"interrupt_type": "temporal_window_confirmation", "next_snapshot_at": ...})`,
на resume читает `action` (`continue_to_next_window` / `finish_temporal_analysis`). При `continue` — сбрасывает
`checklist_items_completed`/`analysis_status` у всех репозиториев и уходит на `refresh_main_branches`
(реальный loop-back графа); при `finish` — на `finalize_progress`.

**LLM**: нет. Чисто управляющая логика дат/state.

**Файлы**: нет — только сброс `checklist_items_completed`/`analysis_status` у репозиториев в `session` (не
файлы), если пользователь выбрал продолжить.

**В базе**: без дополнений к общему паттерну (кроме сохранения `pending_interrupt` перед паузой, как у любой
interrupt-ноды — см. ноду 2).

**На выходе**: либо `session.current_step = REFRESH_MAIN_BRANCHES` (новый цикл), либо
`session.current_step = FINALIZE_PROGRESS`.

**При ошибке**: `try/except` вокруг всей ноды; отдельно — `_extract_window_confirmation_action` кидает
`ValueError`, если resume payload не содержит валидного `action` — тоже уходит в `step_error`/retry.

**Логи и что видит пользователь**: SSE `interrupted` с `{"interrupt_type": "temporal_window_confirmation", "current_snapshot_at": "...", "next_snapshot_at": "...", "window_index": N}`
— это то место, где пользователь явно решает, продолжать ли исторический анализ дальше во времени.

**Зачем (по-человечески)**: решить, нужно ли реконструировать ещё один temporal-срез истории продукта
(например, следующий квартал), или на текущем моменте реконструкция закончена. Явное подтверждение
пользователя — осознанное решение, а не автоматическое зацикливание до бесконечности.

---

### 16. `finalize_progress` — не LLM, terminal

**Что делает** ([nodes.py:823](../../back/app/workflows/init_arch/nodes.py#L823)):
`guard_service.finalize_progress(...)` — закрывающая механика progress-файла/сессии.

**LLM**: нет.

**Файлы**: нет.

**В базе**: без дополнений к общему паттерну; сразу после ноды `run_workflow()` дополнительно апдейтит
верхнеуровневый `record.workflow_status` (`SUCCESS`/`FAILED`) в том же `workflow_runs`.

**На выходе**: `session.status` фиксируется как завершённый; это последняя нода перед `END` (или
`handle_error`, если и она сама упадёт после исчерпания retry — единственная нода с отдельным условным
ребром вне общего `_route_after_node()`, `graph.py:99-103`).

**При ошибке**: тот же `try/except` → `step_error` → retry ≤3 → `handle_error` → `END`.

**Логи и что видит пользователь**: после этой ноды `run_workflow()` выставляет
`WorkflowStatus.SUCCESS`/`FAILED` на верхнем уровне ([init_arch_workflow.py:779-784](../../back/app/services/init_arch_workflow.py#L779-L784)),
пользователь получает финальный SSE `{"event_type": "workflow_done", "workflow_status": "success"}`.

**Зачем (по-человечески)**: формально закрыть workflow run — зафиксировать, что все данные собраны и сессия
завершена, чтобы UI и API перестали ждать дальнейших событий и показали финальный статус.

---

## `handle_error` — не LLM, ⏸ interrupt, точка восстановления после отказа шага

**Что делает** ([nodes.py:856](../../back/app/workflows/init_arch/nodes.py#L856)): логирует
(`logger.error("workflow.node.error", step=..., error=..., retry_count=...)`), затем **сама делает паузу**:

```python
resume_payload = interrupt({
    "interrupt_type": "step_failed",
    "step_id": step_id.value,
    "step_title": STEP_DEFINITION_BY_ID[step_id].title,
    "error": step_error,
    "retry_count": retry_count,
})
```

и ждёт от пользователя `{"action": "retry"}` или `{"action": "abort"}`
(`_extract_step_failure_recovery_action()`, зеркало `_extract_window_confirmation_action` у
`confirm_next_temporal_window`). На `"retry"` возвращает `{"step_error": None, "retry_count": 0}` — граф
маршрутизируется обратно в упавшую ноду с чистым retry-бюджетом (`_route_after_handle_error()` в
[graph.py](../../back/app/workflows/init_arch/graph.py), читает `state["session"].current_step`, которая всё
ещё указывает на упавший шаг — `advance_step` для него так и не выполнился). На `"abort"` возвращает
`step_error`/`retry_count` как есть — граф уходит в `END`, а `run_workflow()` ставит `FAILED`, как и раньше.

Это переиспользует ровно тот же generic interrupt/resume путь, что и три других паузы в графе: LangGraph
репортит `handle_error` через `__interrupt__`-событие, `_drive_graph_stream()` → `apply_interrupt()` кладёт
payload в `record.pending_interrupt` без единой правки в этой функции, а SSE-билдер
(`{"event_type": "interrupted", **(record.pending_interrupt or {})}`) автоматически прокидывает
`step_id`/`step_title`/`error`/`retry_count` пользователю — новых полей в транспортном слое не потребовалось.

**Что в итоге получает пользователь при отказе шага** (сквозной пример по всей цепочке):

1. Нода (например, `clone_repositories`) 3 раза подряд ловит `step_error`, ретраи исчерпаны →
   `_route_after_node()` ведёт в `handle_error`.
2. `handle_error` логирует и вызывает `interrupt({"interrupt_type": "step_failed", "step_id": "clone_repositories", "step_title": "Clone repositories", "error": "...", "retry_count": 3})`.
3. `_drive_graph_stream()` видит `__interrupt__` → `record.workflow_status = WorkflowStatus.INTERRUPTED`,
   `record.pending_interrupt` = payload interrupt'а.
4. Пользователь получает через SSE `{"event_type": "interrupted", "interrupt_type": "step_failed", "step_id": "clone_repositories", "step_title": "Clone repositories", "error": "...", "retry_count": 3}`
   — фронт (`RequiredActionCard`, [required-action-card.tsx](../../front/src/features/workflow/required-action-card.tsx))
   рендерит карточку с шагом, полным текстом ошибки, числом попыток и кнопками «Повторить»/«Прервать».
5. Клик «Повторить» → `POST /api/rest/responses/{response_id}/actions/` с `{"action_type": "retry"}` →
   `submit_response_action_async()` → `retry_init_arch_workflow(workflow_id, action="retry")`
   ([init_arch_workflow.py](../../back/app/services/init_arch_workflow.py)) → `schedule_resume(record, resume_value={"action": "retry"})`
   → `graph.astream({"action": "retry"}, config={"configurable": {"thread_id": workflow_id}})` продолжает
   **тот же** LangGraph `thread_id`/checkpoint — не новый workflow, не новая сессия. `handle_error`
   резолвится в `{"step_error": None, "retry_count": 0}`, граф возвращается в `clone_repositories` и
   выполняет его заново с уже накопленным `session` (репозитории, artifacts, historical state — всё, что
   было собрано до сбоя, сохраняется).
6. Клик «Прервать» → `{"action_type": "retry", "value": "abort"}` → тот же `retry_init_arch_workflow(..., action="abort")`
   → `handle_error` возвращает исходный `step_error` → граф в `END` → `WorkflowStatus.FAILED`,
   `record.error_message = step_error`, финальный SSE `{"event_type": "workflow_failed", "error_message": "..."}`
   — как и раньше, но теперь это осознанный выбор пользователя, а не единственный возможный исход.

Отдельный путь отказа — необработанное исключение вне графа (например, в `compile_graph`/`get_checkpointer`
до первого `astream`): тогда `run_workflow()` ловит его собственным внешним `except Exception`
([init_arch_workflow.py:793-797](../../back/app/services/init_arch_workflow.py#L793-L797)) и сразу ставит
`FAILED` + `error_message = str(exc)` — без прохода через `handle_error`/retry графа и без возможности
retry вообще. Это по-прежнему единственный по-настоящему терминальный путь отказа; все отказы *внутри* графа
(включая `request_repository_list`, у которой раньше не было своего `try/except`, — теперь исправлено) идут
через retryable `handle_error`.

**Файлы**: сам `handle_error` ничего не пишет — но важно понимать, что файлы, уже написанные упавшей нодой
или предыдущими нодами (например, частично записанные knowledge-артефакты из `analyze_repositories`),
**остаются на диске как есть** между падением и повтором — retry не откатывает файловые изменения, только
`step_error`/`retry_count` в state графа.

**В базе**: `pending_interrupt` с полным payload'ом (`step_id`/`step_title`/`error`/`retry_count`) уходит в
`workflow_runs` тем же путём, что и у любой другой interrupt-ноды (нода 2) — до получения ответа пользователя.

**Зачем (по-человечески)**: не терять уже проделанную работу при сбое. Раньше единственный вариант при
падении шага — начинать весь workflow заново с нуля; теперь пользователь видит, что именно и почему упало, и
может либо попробовать тот же шаг ещё раз (например, после того как почитал права доступа к репозиторию),
либо осознанно прервать прогон.

## Compatibility-поле `progress_file_path`

Отдельно стоит явно зафиксировать, раз тема всплывала: `progress_file_path`
(`{arch_repo_dir}/repo-initialization-progress.yaml`, формируется один раз в
[init_arch_workflow.py:946](../../back/app/services/init_arch_workflow.py#L946)) **не создаётся и не
пишется ни одной нодой графа**. Путь прокидывается как metadata-поле во все `_record_guard_event(...)`
вызовы ([guard.py](../../back/app/workflows/init_arch/guard.py)) и один раз показывается агенту в промпте
как informational bridge ([prompts.py:302](../../back/app/workflows/init_arch/prompts.py#L302)) с прямой
оговоркой "не используй его как источник решений". Ни `yaml.dump`, ни `write_text` рядом с этим путём в
кодовой базе нет. Canonical state — это `WorkflowSessionRecord`, персистентный через `workflow_runs` (см.
общий паттерн «В базе» в начале документа), а не YAML-файл в workspace. Поле выглядит как хвост миграции с
legacy standalone CLI (`init-repo-arch-skill/scripts/analysis_guard/`), который такой файл реально пишет.

## Известные несостыковки, найденные при разборе

1. `STEP_TO_REFERENCE["build_navigation_index"]` и `["run_knowledge_lint"]` указывают на
   [knowledge-workflow.md](../../back/app/workflows/shared_assets/init_arch/references/knowledge-workflow.md),
   но обе ноды никогда не вызывают LLM — файл фактически мёртвый в контексте промптов.
2. `StepDefinition.uses_llm_worker=False` для `validate_final` ([steps.py:87](../../back/app/workflows/init_arch/domain/steps.py#L87))
   не соответствует реальному коду ноды (`_simple_llm_step` всегда зовёт LLM). Поле, похоже, сейчас не
   является source of truth для поведения графа.
3. `run_knowledge_lint` кодирует смысловой "lint failed" как обычное исключение — на уровне графа это
   неотличимо от инфраструктурного сбоя (сеть, таймаут CLI и т.д.), различие видно только в тексте
   `error_message`, который пользователь увидит в карточке `step_failed` перед тем, как решить —
   повторять или прерывать.
4. Три LLM-ноды — `assess_scope_and_domains`, `analyze_repositories`, `validate_final` — не вызывают
   `knowledge_service.collect_worker_artifacts(...)`, в отличие от `refine_features`/`interview_user`/
   `generate_release_notes`. Файлы, которые агент пишет в `arch_repo_dir` на этих трёх шагах, физически
   появляются на диске, но не попадают в `session.artifacts` и не эмитят audit `ARTIFACT_WRITTEN` — то есть
   artifact-registry (то, на что опирается `wiki/index.md`/`compile-report.md` и общая наблюдаемость) не
   полный.
5. `RepositoryExecution.domain_strategy`/`.domains` — поля, которые по смыслу должен заполнять
   `assess_scope_and_domains`, — ни разу не устанавливаются ни одним модулем backend'а. Reference-чеклист
   шага говорит о `domain_map` ([checklist-scope-and-domain-assessment.md:5](../../back/app/workflows/shared_assets/init_arch/references/checklist-scope-and-domain-assessment.md#L5)) —
   это терминология legacy standalone CLI (`analysis_guard.py`), не текущей backend-модели данных. Результат
   разбиения на домены сейчас нигде структурно не сохраняется.
6. `progress_file_path` (`repo-initialization-progress.yaml`) формируется как строка один раз при старте
   workflow, но ни одна нода/сервис его не создаёт и не пишет — см. отдельный раздел
   «Compatibility-поле `progress_file_path`» выше.
