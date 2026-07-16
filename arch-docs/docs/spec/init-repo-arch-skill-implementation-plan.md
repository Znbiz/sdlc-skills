# План реализации `init-repo-arch-skill` в `arch-docs`

## 1. Общее описание

**Цель:** довести `arch-doc/arch-docs` до состояния, в котором сервис сам управляет полным workflow первичного `as-is` анализа репозиториев: хранит progress/state, определяет текущий этап, выполняет переходы между шагами, запускает historical prep, knowledge-artifacts, user interview loop, knowledge lint и compile. LLM при этом не управляет процессом, а вызывается через CLI только как исполнитель отдельных аналитических задач внутри шагов, которые уже оркестрирует сервис.

**Базовый ориентир:** поведение и структура исходного skill из `init-repo-arch-skill/`, а формат постановки работ и уровень детализации этапов берём из [ТЗ — Arch Docs Service](./ТЗ%20—%20Arch%20Docs%20Service.md).

## 2. Текущее состояние проекта

Сейчас в `arch-docs` уже есть заготовка для `init_arch`:

- `app/workflows/init_arch/graph.py` содержит линейный `langgraph` workflow;
- `app/workflows/init_arch/guard.py` вызывает внешний `analysis_guard.py` через subprocess;
- `app/workflows/init_arch/prompts.py` подставляет `SKILL.md` и reference-чеклисты в prompt для Claude/Codex;
- `app/api/rpc/arch_ops.py` и `app/mcp_server.py` умеют запускать `update_arch` и `query`, но `init_arch` пока не доведён до полноценной сервисной операции;
- тесты для `init_arch` есть, но они покрывают только каркас, а не parity с реальным skill.

Ключевой вывод: в проекте уже есть orchestration shell, но нет внутренней реализации доменной логики skill. Сейчас сервис в основном делегирует управление процессом внешнему CLI-агенту, тогда как целевая модель должна быть обратной: процессом управляет сервис, а CLI-вызов LLM выполняет только локальную аналитическую подзадачу текущего шага.

## 3. Целевое состояние

`arch-docs` должен стать gateway-исполнителем `init-repo-arch-skill` с четырьмя обязательными слоями:

1. **Workflow layer**: строгая state machine шагов `define_scope -> ... -> finalize_progress`.
2. **Historical analysis layer**: вычисление snapshot window, order репозиториев, target commit и checkout.
3. **Knowledge layer**: bootstrap, index, lint, compile и работа с wiki/layout артефактами.
4. **Gateway/API layer**: запуск, возобновление, статус, stream, user-interview answer loop и MCP entrypoints.
5. **Audit/Dialog layer**: полный журнал шагов skill, действий сервиса, входов/выходов worker-задач и всех CLI-вызовов LLM, сохраняемый в БД как воспроизводимый диалог исполнения.

Дополнительный обязательный принцип:

- **Service-driven orchestration**: только сервис решает, какой шаг сейчас активен, какие предусловия выполнены, какой prompt нужно отдать LLM, что считать результатом шага и можно ли переходить дальше.
- **CLI-LLM as worker**: `codex exec` / `claude -p` не принимают архитектурных решений о ходе workflow; они получают узкую задачу от сервиса и возвращают структурированный результат, который сервис валидирует и применяет.
- **Persistent execution dialog**: вся работа skill логгируется и сохраняется в БД как последовательность событий и сообщений: системное решение orchestrator, сформированная worker-задача, prompt, stdout/stderr, результат валидации, retry, user answer, переход шага.

## 4. Наблюдаемые разрывы с исходным skill

- `run_guard()` пока лишь оборачивает CLI `analysis_guard.py`, а не даёт typed service API и не делает сервис владельцем workflow state.
- `nodes.py` использует сигнатуры `repo`-команд, которые уже расходятся с реальным CLI skill и показывают, что orchestration всё ещё мыслится как shell orchestration.
- workflow не моделирует progress как first-class persisted state в БД и не принимает решения по шагам независимо от LLM.
- historical prep описан в исходном skill как обязательный happy path, но в сервисе пока не валидируется как отдельный quality gate.
- knowledge workflow (`bootstrap`, `index`, `lint`, `compile`) не встроен как полноценный domain pipeline с диагностикой и resume.
- нет управляемого цикла “один открытый вопрос пользователю за раз” с фиксацией ответа и обновлением артефактов.
- отсутствует явная граница между orchestration-логикой сервиса и execution-логикой LLM worker через CLI.
- нет полной persist-аудитории хода skill в формате диалога действий и вызовов LLM, пригодной для replay, отладки и расследования ошибок.

## 5. План реализации по этапам

### Этап 1. [x] Зафиксировать контракт целевого workflow

**Задача:** зафиксировать как главный инвариант, что `arch-docs` сам реализует `init-repo-arch-skill`, а CLI LLM используется только как worker внутри отдельных шагов.

**Что сделать:**
- собрать matrix соответствия между `init-repo-arch-skill/SKILL.md`, `references/`, `assets/`, `scripts/analysis_guard/*` и текущими файлами `app/workflows/init_arch/*`;
- отдельно зафиксировать обязательные команды/состояния: `init`, `status`, `advance`, `repo`, `domain`, `timeline`, `bootstrap`, `index`, `lint`, `compile`, `validate`;
- явно разделить orchestration decisions и LLM execution responsibilities;
- зафиксировать, что status/progress-файл в новой реализации перестаёт быть механизмом, которым “руководствуется LLM”, и становится внутренним состоянием, которым руководствуется сам сервис.
- зафиксировать event model для audit trail: шаг workflow, команда orchestrator, запрос к worker, ответ worker, системная валидация, пользовательский ответ, итоговое решение.

**Результат этапа:** короткий gap-analysis документ, service/worker contract и список инвариантов parity.

**Статус выполнения:** выполнено

**Мини-отчёт:**
- собран matrix соответствия между skill-артефактами и текущими файлами `arch-docs`;
- зафиксирован service/worker contract, список обязательных guard-операций и event model audit trail;
- результат оформлен в [init-repo-arch-skill-gap-analysis.md](/Users/aanekraso2/github.com/znbiz/sdlc/arch-docs/docs/init-repo-arch-skill-gap-analysis.md).

### Этап 2. [x] Выделить внутренний domain-модуль skill

**Задача:** перенести владение бизнес-логикой skill в сервисный доменный слой.

**Что сделать:**
- создать внутри `app/workflows/init_arch/` отдельный доменный слой: progress model, step definitions, repo checklist, domain map, historical analysis model, knowledge artifact registry;
- перенести или адаптировать логику из `init-repo-arch-skill/scripts/analysis_guard/{definitions,models,contracts,validation}.py`;
- унифицировать типы состояния между `langgraph`, БД и API.
- определить typed result-contract для ответов LLM worker по каждому виду подзадачи.
- определить typed audit entities: `workflow_session`, `workflow_event`, `llm_call`, `llm_message`, `step_transition`, `user_answer`.

**Целевые зоны проекта:**
- `app/workflows/init_arch/state.py`
- новый подкаталог `app/workflows/init_arch/domain/`
- тесты `tests/workflows/init_arch/`

**Результат этапа:** typed domain API, в котором сервис владеет state machine, а LLM подключён как подчинённый исполнитель.

**Статус выполнения:** выполнено

**Мини-отчёт:**
- проведён ребейз статуса этапа: подтверждено, что исходный `domain/` был только каркасом, а `state.py`, `nodes.py`, `graph.py`, `prompts.py`, `app/api/rpc/workflows.py`, `workflow_registry` и тесты всё ещё жили на строковых step ids и progress-file semantics;
- зафиксирован рабочий verification baseline после переезда репозитория: вместо сломанного shebang у `.venv/bin/pytest` используется `.venv/bin/python -m pytest ...`;
- добавлены typed domain operations: `start_session`, `advance_step`, `fail_step`, `open_question`, `record_answer`, `register_repository`, `mark_checklist_item`, `finalize_session`;
- `InitArchState`, `nodes.py`, `graph.py`, prompts и RPC переведены на `WorkflowSessionRecord` как runtime source of truth; проверка: `58 passed` в `tests/workflows/init_arch`, `tests/api/rpc/test_workflows.py`, `tests/services/test_workflow_registry.py`.

### Этап 3. [x] Реализовать guard-service вместо shell-only guard

**Задача:** заменить текущую модель “каждый шаг вызывает внешний python-скрипт и полагается на внешний orchestration” на внутренний сервис, который сам управляет workflow и одинаково вызывается из workflow, RPC и MCP.

**Что сделать:**
- ввести `InitArchGuardService` с методами уровня домена: `init_progress()`, `advance_step()`, `register_repo()`, `plan_timeline()`, `run_lint()` и т.д.;
- subprocess-adapter для старого `analysis_guard.py` оставить только как временный миграционный мост, но не как часть целевой архитектуры;
- привести `guard.py` и `nodes.py` к реальным операциям skill, а не к строковым CLI-костылям.
- ввести отдельный `LlmWorkerService`, который получает от orchestrator уже подготовленную задачу, prompt, рабочую директорию, timeout и ожидаемый schema result.
- сделать обязательным audit hook на каждой операции guard/orchestrator и на каждом worker execution.

**Результат этапа:** сервис сам ведёт workflow, а CLI становится управляемым execution backend.

**Статус выполнения:** выполнено

**Мини-отчёт:**
- введён `InitArchGuardService` с typed `GuardOperationResult` и сервисный LLM execution path; `nodes.py` больше не собирает argv для `analysis_guard.py` и CLI напрямую;
- subprocess bridge к `analysis_guard.py` убран из `app/workflows/init_arch/guard.py`: guard-операции `init/advance/repo/validate/finalize` теперь выполняются как внутренняя сервисная логика и возвращают service-generated summaries вместо shell stdout;
- `workflow_registry` и RPC начали хранить typed `session` наряду с compatibility-полями `current_step_id` / `completed_steps`;
- добавлен service-side audit hook: `guard`, `nodes` и `LlmCliService` теперь публикуют typed `WorkflowEventRecord` через `WorkflowAuditService`, покрывая `WORKFLOW_STEP_*`, `GUARD_COMMAND_*` и `LLM_TASK_*` события;
- в `LlmTaskRequest` добавлен `session_id`, чтобы worker-аудит коррелировался с workflow session без shell-state;
- введён отдельный `app/workflows/init_arch/llm_worker.py` с `LlmWorkerService` / `get_llm_worker_service()`, а `nodes.py` переведён на worker-сервис уровня workflow вместо прямой привязки к `task_runner`;
- audit hook доведён до полного stage-3 coverage: кроме `define_scope`, события шага публикуются для `request_repository_list`, simple LLM steps, `analyze_repositories`, `interview_user` и `finalize_progress`, а guard-покрытие расширено на repo/item/finalize/validate/user-answer операции;
- verification: `95 passed` в `tests/workflows/init_arch`, `tests/services/test_task_runner.py`, `tests/api/rpc/test_workflows.py`, `tests/services/test_workflow_registry.py`;
- audit persistence hook и расширение typed audit trail до полноценного execution dialog в БД остаются на следующих этапах, но stage-3 service contract и worker boundary закрыты.

### Этап 4. [x] Встроить historical prep как обязательный pipeline

**Задача:** реализовать в сервисе тот же стандартный happy path, который skill требует до содержательного анализа, причём решения о переходах и проверках принимает сам сервис.

**Что сделать:**
- хранить для каждого repo `created_at`, `main_branch`, `remote_head_commit`, `analysis_target_date`, `analysis_target_commit`, `analysis_target_commit_status`;
- реализовать planning snapshot windows и ordering репозиториев по `created_at`;
- добавить safe git-операции для `.temp/` checkout и перевода repo на commit не позже snapshot date;
- сделать historical prep отдельным quality gate перед `assess_scope_and_domains`.
- логгировать в БД все решения historical prep: какой repo выбран anchor, какой snapshot date рассчитан, какие commit resolution попытки были сделаны и чем закончились.

**Целевые зоны проекта:**
- `app/workflows/init_arch/nodes.py`
- новый сервис для git/timeline операций
- `tests/workflows/init_arch/` и, при необходимости, отдельные fixture-репозитории

**Результат этапа:** воспроизводимый temporal analysis workflow, а не разовый prompt.

**Статус выполнения:** выполнено

**Мини-отчёт:**
- добавлен internal `HistoricalPrepService`, который забрал на сторону сервиса шаги `refresh_main_branches`, `plan_repository_order` и `resolve_target_commits`, включая расчёт anchor repo, snapshot date и target commit resolution;
- `node_refresh_main_branches` и `node_plan_repository_order` перестали быть LLM-заглушками и теперь выполняют service-driven historical prep с audit events, `.temp` checkout на snapshot commit и последующим `advance_step` только после успешного snapshot planning / commit resolution;
- historical gate в domain-операциях усилен: для перехода к `assess_scope_and_domains` теперь недостаточно одного `ordered_repository_names`, требуется полный snapshot state (`anchor`, `current_snapshot_at`, ordered repos, propagated `analysis_target_date`, resolved/missing target commit statuses);
- расширена typed historical state-модель (`completed_snapshot_dates`, `prep_notes`) и добавлены regression tests на historical planning, commit resolution и node orchestration;
- verification: `19 passed` в targeted red/green срезе (`tests/workflows/init_arch/domain/test_operations.py`, `tests/workflows/init_arch/test_historical.py`, `tests/workflows/init_arch/test_nodes.py`), затем `67 passed` в `tests/workflows/init_arch`, `tests/api/rpc/test_workflows.py`, `tests/services/test_workflow_registry.py`.

### Этап 5. [x] Встроить knowledge-artifact pipeline

**Задача:** реализовать слой синтеза артефактов так, как он описан в `repository-layout.md` и `knowledge-workflow.md`, без делегирования контроля над прогрессом LLM.

**Что сделать:**
- подключить шаблоны `assets/` как runtime-ресурс сервиса;
- реализовать bootstrap wiki/layout для целевого arch-repo;
- поддержать генерацию и обновление `features/`, `architecture/`, `glossary.md`, `open-questions.md`, `wiki/index.md`, `wiki/log.md`, `wiki/maps/compile-report.md`;
- ввести artifact registry и трассировку источников.
- разделить шаги, где LLM генерирует черновой synthesis output, и шаги, где сервис валидирует, нормализует и коммитит это в knowledge-state.
- сохранять в БД диалог по каждому knowledge-шагу: какой prompt был сформирован, какие артефакты ожидались, что вернул worker, что было принято, что было отклонено и почему.

**Результат этапа:** сервис умеет создавать и поддерживать knowledge-слой, а не только запускать агент с общей инструкцией.

**Статус выполнения:** выполнено

**Мини-отчёт:**
- добавлен внутренний `KnowledgeArtifactService`, который использует vendored templates из `app/workflows/shared_assets/knowledge_base/`, bootstrap-ит базовый knowledge layout и ведёт typed artifact registry в `WorkflowSessionRecord`;
- knowledge-этапы `refine_features`, `build_navigation_index`, `run_knowledge_lint` переведены на service-driven pipeline: LLM остаётся только на synthesis-шаге `refine_features`, а compile/navigation и knowledge lint теперь выполняются самим сервисом;
- в сервис перенесён knowledge runtime для `compile_knowledge_graph()` и `run_knowledge_lint()`, а audit дополнен событиями `artifact_written` при bootstrap/compile;
- добавлены regression tests для bootstrap, compile, lint и knowledge-node orchestration; verification: `27 passed` в targeted knowledge/domain срезе и `74 passed` в `tests/workflows/init_arch`, `tests/api/rpc/test_workflows.py`, `tests/services/test_workflow_registry.py`;
- knowledge execution dialog доведён до persisted read-model: workflow пишет `conversation_items`, `artifact_events`, `workflow_step_transitions`, а transport-слой умеет читать эти события через `GET /api/rest/workflows/{workflow_id}/events/` и DB-backed SSE fallback после рестарта;
- worker-аудит knowledge-шагов теперь воспроизводим по `llm_task_*` событиям с `llm_call_id`, а сервисные artifact decisions доступны как отдельные persisted события и через status/event API;
- финальная verification после закрытия хвоста этапов 5-7: `161 passed` в `tests/workflows/init_arch`, `tests/services/test_init_arch_workflow.py`, `tests/services/test_task_runner.py`, `tests/services/test_workflow_registry.py`, `tests/api/rest/test_workflows.py`, `tests/api/rest/test_workflow_stream.py`, `tests/api/rpc/test_workflows.py`, `tests/mcp/test_mcp_server.py`, `tests/db/test_workflow_repo.py`, `tests/db/test_task_repo.py`.

### Этап 6. [x] Реализовать interview loop и resume-семантику

**Задача:** адаптировать ограничение исходного skill “один открытый вопрос за раз” к long-running gateway workflow так, чтобы именно сервис контролировал паузу, ожидание ответа и продолжение.

**Что сделать:**
- хранить open questions и статус их закрытия в БД;
- добавить API для ответа пользователя на конкретный вопрос;
- после ответа запускать обязательный post-answer cycle: сверка, обновление артефактов, фиксация `Q-*` ссылок, закрытие вопроса;
- вместо требования “новый чат на следующий репозиторий” реализовать сервисное resume через workflow session / checkpoint.
- запретить LLM worker самостоятельно переходить к следующему вопросу или следующему repo без явного решения orchestration-слоя.
- сохранять user interview как часть общего execution dialog: вопрос сервиса, ответ пользователя, связанные LLM-вызовы, решение о закрытии вопроса.

**Результат этапа:** skill становится управляемым асинхронным процессом, совместимым с HTTP/MCP.

**Статус выполнения:** выполнено

**Мини-отчёт:**
- `analyze_repositories` теперь поднимает `open_questions` из `LlmTaskResult.open_questions_found`, сервис сам назначает `Q-*` id и синхронизирует `open-questions.md` до входа в `interview_user`;
- `node_interview_user` перестал быть passive interrupt-point: после resume он записывает ответ пользователя, запускает `INTERVIEW_RECONCILIATION` worker-task, регистрирует созданные артефакты, закрывает вопрос и только затем решает, нужен ли следующий interrupt или можно двигаться в `refine_features`;
- в RPC добавлен явный endpoint `POST /workflows/{workflow_id}/questions/{question_id}/answer/`, который валидирует pending question и резюмирует тот же backend workflow без обходного shell-path;
- `KnowledgeArtifactService` получил service-side sync `open-questions.md`, поэтому question lifecycle теперь отражается не только в runtime `session`, но и в knowledge-слое;
- verification: `44 passed` в targeted срезе (`tests/workflows/init_arch/domain/test_operations.py`, `tests/workflows/init_arch/test_guard.py`, `tests/workflows/init_arch/test_nodes.py`, `tests/api/rpc/test_workflows.py`), затем `75 passed` в `tests/workflows/init_arch` и `tests/api/rpc/test_workflows.py`;
- interview state и required actions перестали быть только memory-backed: статус workflow lazy-restore-ится из БД, `required_actions` читаются через persisted `required_actions`, а `answer_init_arch_question()` покрыт тестом на resume после DB-only восстановления workflow;
- REST status теперь возвращает `conversation_id` и current `required_actions`, а SSE может воспроизвести persisted interrupt/event trail даже если in-memory registry пуст после рестарта сервиса;
- финальная verification после закрытия хвоста этапов 5-7: `161 passed` в общем workflow/db/transport срезе.

### Этап 7. [x] Довести внешние API до продуктового контура

**Задача:** сделать `init_arch` полноценной пользовательской операцией сервиса, а не оболочкой над prompt `/init-repo-arch-skill`.

**Что сделать:**
- добавить REST/RPC endpoint для запуска `init_arch`;
- добавить endpoint/метод для `status`, `resume`, `answer_open_question`, `cancel`;
- транслировать progress и node events в SSE stream;
- унифицировать MCP tool `init_arch` с тем же backend service, а не с отдельным subprocess path.

**Целевые зоны проекта:**
- `app/api/rest/`
- `app/api/rpc/`
- # sse
- `app/mcp_server.py`

**Результат этапа:** один backend workflow, несколько одинаково корректных transport-слоёв.

**Статус выполнения:** выполнено

**Мини-отчёт:**
- orchestration runtime для `init_arch` вынесен в общий service-layer `app/services/init_arch_workflow.py`, чтобы REST, RPC и MCP работали через один backend path, а не дублировали lifecycle workflow в transport-коде;
- REST доведён до продуктового контура: добавлены `POST /api/rest/workflows/init/`, `POST /api/rest/workflows/{workflow_id}/resume/`, `POST /api/rest/workflows/{workflow_id}/questions/{question_id}/answer/` и `DELETE /api/rest/workflows/{workflow_id}/`, при этом существующие `GET /api/rest/workflows/{workflow_id}/` и `/stream/` продолжают читать тот же `WorkflowRecord`;
- RPC переведён на тот же runtime API и получил `DELETE /api/rpc/workflows/{workflow_id}/` для штатной отмены long-running workflow;
- `WorkflowStatus` расширен состоянием `cancelled`, а SSE stream теперь умеет эмитить terminal event `workflow_cancelled` для transport-level наблюдаемости;
- MCP tool `init_arch` больше не запускает legacy `/init-repo-arch-skill` subprocess path и теперь стартует тот же backend workflow, возвращая `workflow_id`, `workflow_status`, `current_step_id` и `created_at`;
- transport read-model расширен до execution-dialog surface: `GET /api/rest/workflows/{workflow_id}/` теперь возвращает `conversation_id` и `required_actions`, `GET /api/rest/workflows/{workflow_id}/events/` отдаёт persisted event log, а `GET /api/rest/workflows/{workflow_id}/stream/` умеет падать обратно на DB-backed replay, если runtime registry уже пуст;
- это закрывает продуктовый контур для `init_arch` как для long-running capability gateway: status, answer, cancel, event-log и SSE работают через единый backend workflow независимо от transport-а и переживают потерю in-memory runtime;
- verification: `23 passed` в targeted red/green (`tests/services/test_init_arch_workflow.py`, `tests/api/rest/test_workflows.py`, `tests/api/rest/test_workflow_stream.py`), затем `161 passed` в общем workflow/db/transport/regression срезе.

**Дополнение по целевому дизайну transport-слоя:**
- текущий `/workflows/*` API следует считать переходным compatibility-layer, а не финальным публичным контрактом сервиса;
- целевой внешний контракт должен стать `conversation-first`, максимально близким к `Responses API`: базовые сущности `conversation`, `response`, `input items`, `output items`, единый SSE event stream;
- первый продуктовый срез ограничивается только workflow-сессиями: conversation не используется для обычного model-chat, а служит контейнером для последовательности `workflow_run`;
- в рамках одного `conversation` пользователь может последовательно запускать несколько workflow разных типов, но одновременно активен не более одного `run`;
- все события workflow, включая user-facing сообщения, questions/required actions и низкоуровневые технические события (`step_started`, `guard_command_applied`, `artifact_written`, `llm_task_*`), должны попадать в единую хронологическую ленту conversation как typed items;
- вместо набора специализированных endpoint-ов под каждый workflow целевой transport должен свестись к небольшому универсальному набору операций: `create conversation`, `create response/run`, `append user item`, `submit action`, `get conversation`, `get response`, `stream conversation events`;
- workflow-specific semantics (`resume`, `answer question`, `pause`, `cancel`, `restart run`) должны моделироваться как стандартные conversation actions, а не как отдельные REST-ручки на каждый тип workflow.
- этот следующий шаг больше не блокирует готовность этапа 7: текущий product contour закрыт, а conversation-first API остаётся отдельным расширением transport-модели поверх уже persisted execution dialog.

### Этап 8. Персистентность и операционная модель

**Задача:** сохранить жизненный цикл skill между рестартами контейнера и запусками задач так, чтобы состояние процесса принадлежало сервису, а не терялось между CLI-вызовами.

**Что сделать:**
- расширить PostgreSQL schema уже не только под `workflow_session`, а под conversation-driven модель: `conversations`, `conversation_items`, `workflow_runs`, `workflow_run_steps`, `required_actions`, `artifact_events`, `llm_calls`, `llm_messages`, `step_transitions`;
- связать текущие `workflow_registry` и `task_registry` с persisted `conversation` / `workflow_run` state и затем постепенно превратить их в runtime-cache поверх БД, а не в source of truth;
- логировать важные переходы на уровне conversation/run: `conversation_created`, `run_started`, `step_advanced`, `required_action_opened`, `user_action_submitted`, `lint_result`, `compile_result`, `run_completed`, `run_cancelled`;
- хранить каждый CLI-вызов LLM как отдельную запись с engine, prompt, cwd, timeout, stdout, stderr, exit_code, parsed_result, correlation_id;
- хранить каждый orchestration event как отдельную запись с типом события, actor (`service`, `llm_worker`, `user`), `conversation_id`, `run_id`, step_id, repo/domain context и causal link к предыдущим событиям;
- персистить mixed event timeline в форме, близкой к `Responses API`: conversation содержит ordered items, где рядом живут user messages, workflow messages, technical workflow events, required actions и terminal results;
- обеспечить возможность продолжать один и тот же `conversation` после завершения предыдущего run и запускать в нём следующий workflow без потери общей истории.

**Результат этапа:** conversation и все входящие в него workflow-runs переживают рестарт контейнера, а весь ход исполнения воспроизводим из БД как единая лента conversation items, событий orchestration и вызовов LLM worker.

**Статус выполнения:** частично выполнено

**Мини-отчёт:**
- добавлен persisted runtime slice в PostgreSQL: `conversations`, `workflow_runs`, `conversation_items`, `required_actions`, а существующий `cli_tasks` расширен полями `stderr_output` и `exit_code`;
- `start/status/resume/cancel` для `init_arch` больше не зависят только от `workflow_registry`: runtime пытается lazy-restore `WorkflowRecord` из БД и использует registry как cache поверх persisted state;
- `WorkflowAuditService` начал дублировать `WorkflowEventRecord` в `conversation_items`, а lifecycle workflow пишет в БД step/status snapshots и required actions;
- на startup сервис теперь помечает застрявшие `running` workflow-runs как `failed` c причиной `Service restarted`, чтобы после рестарта не оставались «висящие» состояния без terminal transition;
- `cli_tasks` дополнительно расширен workflow-метаданными `workflow_id`, `step_id`, `repository_name`, `domain_id`, `expected_schema_name`, а audit-события `llm_task_requested/completed/failed` теперь несут `llm_call_id`, связывающий execution dialog с конкретным persisted LLM-вызовом;
- добавлены отдельные persisted сущности `workflow_step_transitions` и `artifact_events`: смена шага теперь пишется не только в `conversation_items`, но и в специализированную таблицу переходов, а `artifact_written/artifact_rejected` сохраняются как отдельные artifact-events с repo/domain context и полным payload;
- verification: `44 passed` в targeted workflow/db/transport срезе (`tests/db/test_task_repo.py`, `tests/db/test_workflow_repo.py`, `tests/services/test_workflow_registry.py`, `tests/services/test_init_arch_workflow.py`, `tests/api/rest/test_workflows.py`, `tests/api/rpc/test_workflows.py`) и ещё `39 passed` в смежном срезе (`tests/services/test_task_runner.py`, `tests/db/test_session.py`, `tests/test_main.py`);
- открытый хвост этапа: conversation-first public API, полноценное хранение `llm_messages`/causal links и несколько `workflow_run` внутри одного `conversation` ещё не реализованы, поэтому этап остаётся частично закрытым.

### Этап 9. Целевой conversation-first API-контракт

**Задача:** убрать переходные workflow-specific transport-слои и перейти на единый внешний HTTP-контракт, в котором backend workflow запускаются и сопровождаются через conversation/run model.

**Что сделать:**
- удалить текущие реализации `app/api/rest/workflows.py` и `app/api/rpc/workflows.py` как legacy workflow-specific transport layer;
- ввести единый REST transport с базовыми сущностями `conversation`, `response/run`, `conversation item`, `required action`;
- зафиксировать минимальный внешний набор операций:
  - `POST /api/rest/conversations/` — создать conversation;
  - `GET /api/rest/conversations/{conversation_id}/` — получить conversation и активный run;
  - `GET /api/rest/conversations/{conversation_id}/items/` — получить persisted timeline items;
  - `GET /api/rest/conversations/{conversation_id}/stream/` — единый SSE stream по conversation;
  - `POST /api/rest/responses/` — создать новый workflow run внутри conversation;
  - `GET /api/rest/responses/{response_id}/` — получить статус run, required actions и terminal result;
  - `POST /api/rest/responses/{response_id}/actions/` — отправить action (`resume`, `answer_question`, `cancel`, в будущем `pause/restart`);
- перенести `init_arch`, `update_arch` и `query` на единый способ запуска через `POST /responses/`, где тип workflow задаётся в typed payload, а не отдельной ручкой;
- перенести user-facing required actions и технические workflow events в общую conversation timeline как typed items, чтобы transport не строился вокруг `workflow_id` как отдельной сущности;
- обновить transport-level SSE так, чтобы события стримились из conversation timeline, а не из отдельных workflow endpoints.

**Результат этапа:** внешний продуктовый контракт становится `conversation-first`, а все workflow-specific HTTP endpoints удалены.

**Статус выполнения:** выполнено

**Мини-отчёт:**
- введён единый REST transport `app/api/rest/conversations.py` с contract `conversations/responses`: `POST /api/rest/conversations/`, `GET /api/rest/conversations/{conversation_id}/`, `GET /api/rest/conversations/{conversation_id}/items/`, `GET /api/rest/conversations/{conversation_id}/stream/`, `POST /api/rest/responses/`, `GET /api/rest/responses/{response_id}/`, `POST /api/rest/responses/{response_id}/actions/`;
- `POST /responses/` теперь запускает не только `init_arch`, но и `update_arch` / `query` через typed `workflow_type`, а `GET /responses/{response_id}/` возвращает единый status/read-model c `required_actions` и `terminal_result`;
- task-backed responses получили `conversation_id` и `response_type`, поэтому `update_arch/query` живут в том же conversation-first contract, что и workflow-backed `init_arch`; stream и items для них синтезируются из task runtime и persisted task metadata;
- legacy workflow-specific transport удалён из публичного HTTP-контура: `app/api/rest/workflows.py`, `app/api/rpc/workflows.py` и `app/api/rpc/arch_ops.py` убраны, router registration переведён на новый conversation-first REST слой;
- verification: `11 passed` в `tests/api/rest/test_conversations.py`, затем `71 passed` в regression-срезе `tests/api/rest/test_conversations.py`, `tests/api/rest/test_tasks.py`, `tests/services/test_init_arch_workflow.py`, `tests/services/test_task_runner.py`, `tests/db/test_task_repo.py`.

### Этап 10. [x] OpenAI compatibility facade

**Задача:** дать внешним клиентам и UI вроде LibreChat / OpenWebUI стабильный OpenAI-compatible вход, не раскрывая им внутренний `conversation-first` контракт напрямую.

**Что сделать:**
- добавить отдельный transport/facade слой с OpenAI-compatible surface;
- реализовать как минимум:
  - `GET /v1/models`;
  - `POST /v1/chat/completions` и/или `POST /v1/responses`;
  - streaming-ответы в OpenAI-compatible SSE формате;
- внутри facade транслировать OpenAI-compatible запросы в новый backend contract:
  - создать `conversation`;
  - создать `response/run`;
  - читать `conversation items`;
  - отправлять `response actions`;
- зафиксировать mapping workflow-типов:
  - `init_arch` → workflow run с typed `init_arch` input;
  - `update_arch` → workflow run с typed `update_arch` input;
  - `query` → workflow run с typed `query` input;
- описать ограничения facade:
  - facade не является source of truth;
  - внутренний persisted execution dialog живёт только в conversation-first модели;
  - не все внутренние workflow events обязаны быть напрямую видимы в OpenAI-compatible stream;
- подготовить facade к подключению LibreChat и OpenWebUI как к обычному OpenAI-compatible provider.

**Результат этапа:** внешние OpenAI-compatible клиенты подключаются через facade, а внутренний backend остаётся conversation-first.

**Статус выполнения:** выполнено

**Мини-отчёт:**
- добавлен отдельный facade-transport [app/api/openai.py](/Users/aanekraso2/github.com/znbiz/sdlc/arch-docs/app/api/openai.py) и router `/v1/*`, не меняющий внутренний conversation-first backend contract;
- реализованы `GET /v1/models`, `POST /v1/responses`, `GET /v1/responses/{response_id}` и `POST /v1/chat/completions`, при этом `/v1/responses` покрывает `init_arch`, `update_arch` и `query` через model-to-workflow mapping, а `chat/completions` пока сознательно ограничен `arch-docs-query`;
- добавлен OpenAI-compatible SSE surface: facade транслирует backend `stream_response_events_async()` в `response.created` / `response.output_text.delta` / terminal events и в `chat.completion.chunk`;
- conversation id и typed workflow input теперь проходят через facade metadata, а source of truth по-прежнему остаётся внутренний `conversations/responses` runtime;
- verification: `4 passed` в `tests/api/rest/test_openai_facade.py`; затем `15 passed` в совместном transport-срезе `tests/api/rest/test_openai_facade.py` и `tests/api/rest/test_conversations.py`.

### Этап 11. Тестирование на parity и регрессии

**Задача:** доказать, что gateway действительно реализует механику skill сам, а не только проксирует её во внешний LLM-run.

**Что сделать:**
- перенести критичные сценарии из `init-repo-arch-skill/tests/test_analysis_guard_knowledge.py`;
- добавить integration tests для полного happy path и для отрицательных сценариев: broken historical order, missing snapshot commit, compile drift, unresolved references;
- проверить transport-слой: REST, RPC, MCP, SSE/conversation stream;
- ввести smoke тест на реальный arch-repo fixture.
- добавить отдельные тесты на границу orchestrator/worker: сервис выбирает шаг, формирует prompt, валидирует ответ, принимает решение о retry/advance.
- добавить tests на audit persistence: ни один step transition и ни один CLI LLM call не теряется и корректно восстанавливается по workflow session.

**Результат этапа:** регрессии ловятся тестами раньше, чем в рабочих запусках.

**Статус выполнения:** выполнено

**Мини-отчёт:**
- добавлены regression tests на persistence LLM-call metadata и causal link в audit trail: `tests/services/test_task_runner.py`, `tests/db/test_task_repo.py`, `tests/workflows/init_arch/test_llm_worker.py`, `tests/db/test_workflow_repo.py`;
- red-green цикл зафиксировал новую гарантию: `LlmCliService` обязан привязывать `workflow_id/step_id/expected_schema_name` к persisted `cli_task` и публиковать `llm_call_id` в workflow events независимо от реализации `_build_cli_task`;
- добавлены regression tests на отдельную persistence шагов и knowledge-artifacts: `tests/db/test_workflow_repo.py` теперь проверяет запись `WorkflowStepTransitionModel` и `ArtifactEventModel`, а заодно поймал и зафиксировал корректный storage format для `EventType/AuditActor` (`.value`, а не `EnumName.MEMBER`);
- добавлены service-level workflow regression tests для `run_workflow`: happy path, interrupt path и failure path теперь проверяют, что orchestrator сам двигает шаги, персистит промежуточные состояния и корректно выставляет terminal status без делегирования этого решения worker-у;
- добавлены parity tests на historical gate: несортированный `ordered_repository_names` и непропагированный `current_snapshot_at` теперь отдельно ловятся как invalid historical prep state на уровне domain-операций;
- добавлен smoke test на реальном fixture `init-repo-arch-skill/tests/fixtures/valid_arch_repo`, который прогоняет service-owned knowledge pipeline `bootstrap -> compile -> lint` и подтверждает отсутствие blocking `ERROR:` в knowledge lint;
- transport/read-model regression дополнительно перепроверен на текущем conversation-first контуре: REST conversation API, MCP facade и DB persistence проходят зелёный срез вместе с новыми workflow tests;
- verification: `40 passed` в targeted workflow/domain/knowledge срезе (`tests/services/test_init_arch_workflow.py`, `tests/workflows/init_arch/domain/test_operations.py`, `tests/workflows/init_arch/test_knowledge.py`) и ещё `40 passed` в transport/db срезе (`tests/api/rest/test_conversations.py`, `tests/mcp/test_mcp_server.py`, `tests/db/test_workflow_repo.py`).

### Этап 12. [x] Hardening и вывод в эксплуатацию

**Задача:** подготовить реализацию к реальному использованию в контейнере с Codex/Claude.

**Что сделать:**
- ограничить таймауты и параллелизм для тяжелых analysis шагов;
- развести workspace для raw layer `.temp/` и synthesis layer `arch-doc`;
- описать env vars, volume layout и запуск в Docker Compose;
- описать retention/masking policy для audit trail: что можно хранить целиком, что нужно редактировать или ограничивать по размеру;
- обновить пользовательскую документацию проекта.

**Результат этапа:** `init_arch` можно запускать как штатную capability gateway-сервиса.

**Статус выполнения:** выполнено

**Мини-отчёт:**
- введены typed hardening-настройки в `GatewaySettings`: `WORKFLOWS__INIT__MAX_STEP_TIMEOUT_SECONDS`, `WORKFLOWS__INIT__RAW_WORKSPACE_SUBDIR`, `WORKFLOWS__INIT__ARCH_REPO_DIRNAME`, а также audit-limits `AUDIT__MAX_PROMPT_CHARS`, `AUDIT__MAX_OUTPUT_CHARS`, `AUDIT__MAX_ERROR_CHARS`;
- `LlmCliService` теперь жёстко ограничивает timeout для `init_arch` worker-задач через workflow-level cap, а `start_init_arch_workflow()` валидирует runtime layout и запрещает класть `arch_repo_dir` внутрь raw-layer;
- runtime prompt разделяет raw `.temp` layer и synthesis `arch-doc` layer, что устраняет двусмысленность для Codex/Claude при тяжёлых analysis шагах;
- persisted audit trail для `cli_tasks` теперь маскирует bearer tokens / inline secrets и ограничивает размер prompt/stdout/stderr/error payload before DB write;
- `docker-compose.yml` обновлён новыми env vars hardening-контура, а пользовательская документация расширена в [docs/workflows/init.md](/Users/aanekraso2/github.com/znbiz/sdlc/arch-docs/docs/workflows/init.md);
- verification: `66 passed` в focused hardening-срезе (`tests/test_settings.py`, `tests/services/test_task_runner.py`, `tests/services/test_init_arch_workflow.py`, `tests/db/test_task_repo.py`) и `185 passed` в расширенном regression-срезе workflow/transport/db.

## 6. Рекомендуемая последовательность выполнения

1. Этапы 1-3: зафиксировать контракт и вынести доменную логику из shell-обёрток.
2. Этапы 4-6: реализовать core workflow parity с исходным skill.
3. Этапы 7-8: вывести workflow в transport и persistence.
4. Этап 9: убрать legacy workflow transport и перейти на conversation-first API.
5. Этап 10: добавить OpenAI compatibility facade для внешних клиентов.
6. Этапы 11-12: закрыть quality gates, нагрузочные риски и документацию.

## 7. Критерий готовности

Реализацию можно считать завершённой, когда:

- `init_arch`, `update_arch` и `query` запускаются через единый conversation-first backend contract;
- legacy `/workflows/*` REST/RPC endpoints удалены из публичного transport-слоя;
- LibreChat / OpenWebUI и другие OpenAI-compatible клиенты подключаются через отдельный compatibility facade;
- progress, status-file semantics и historical prep управляются сервисом, а не внешним `analysis_guard.py` и не самой LLM;
- knowledge-artifacts создаются и валидируются в соответствии с `init-repo-arch-skill`;
- пользователь может отвечать на open questions и безопасно резюмировать workflow;
- CLI LLM используется только как execution worker и не определяет самостоятельно следующий этап процесса;
- вся работа skill, включая шаги orchestrator и все CLI-вызовы LLM, сохраняется в БД как целостный execution dialog;
- parity подтверждён integration/regression тестами.
