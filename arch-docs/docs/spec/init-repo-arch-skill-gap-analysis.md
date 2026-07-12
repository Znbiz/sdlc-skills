# Gap Analysis: `init_arch` vs `init-repo-arch-skill`

## Scope

Документ фиксирует Stage 1 для `arch-docs`: текущие разрывы между сервисной реализацией `init_arch` и исходным `init-repo-arch-skill`, а также целевой service/worker contract и инварианты parity.

## Source Matrix

| Source skill artifact | Current `arch-docs` implementation | Gap |
| --- | --- | --- |
| `init-repo-arch-skill/SKILL.md` | `app/workflows/init_arch/prompts.py`, `nodes.py`, `graph.py` | Сервис читает skill и reference как prompt-context, но не владеет доменной логикой шагов. |
| `init-repo-arch-skill/references/*` | `app/workflows/init_arch/prompts.py` | Reference используется только для генерации общего prompt, без typed step contracts и quality gates. |
| `init-repo-arch-skill/assets/*` | Не подключено как runtime resource | Нет artifact bootstrap, registry и source-traceability. |
| `init-repo-arch-skill/scripts/analysis_guard.py` и пакет `analysis_guard/*` | `app/workflows/init_arch/guard.py` | Сейчас только subprocess wrapper без service API, typed state и persisted audit. |
| Guard commands: `init`, `status`, `advance`, `repo`, `domain`, `timeline`, `bootstrap`, `index`, `lint`, `compile`, `validate` | Частично вызываются только `init`, `advance`, `repo`, `finalize` | Нет полного service-level контракта для остальных операций, нет resume/status semantics в API. |
| Progress YAML как source of truth | `InitArchState.progress_file_path` | Progress-файл пока остаётся внешним координирующим механизмом; сервис не ведёт собственное persisted workflow state. |
| Historical prep и timeline workflow | `refresh_main_branches`, `plan_repository_order` nodes | Отсутствуют typed historical models, commit resolution, ordering quality gate и decision logging. |
| One-open-question interview loop | `node_interview_user()` | Есть только interrupt по строке вопроса; нет open-question entity, post-answer cycle и persisted resume. |
| Knowledge workflow: `bootstrap/index/lint/compile` | `refine_features`, `build_navigation_index`, `run_knowledge_lint` nodes | Сервис не управляет knowledge artifacts и не валидирует synthesis outputs как отдельный pipeline. |
| Execution dialog / audit trail | Нет | Не сохраняются orchestrator decisions, prompts, stdout/stderr, retries, user answers и step transitions. |

## Current State Summary

1. `app/workflows/init_arch/graph.py` задаёт линейный `langgraph`, но не моделирует доменную state machine с persisted lifecycle.
2. `app/workflows/init_arch/nodes.py` вызывает CLI LLM почти на каждом шаге и делегирует ему содержательные решения.
3. `app/workflows/init_arch/guard.py` является shell adapter поверх `analysis_guard.py`, а не внутренним guard-service.
4. `app/api/rpc/arch_ops.py` и `app/mcp_server.py` до сих пор ориентированы на prompt-level запуск `/update-repo-arch-skill` и `/init-repo-arch-skill`.
5. База данных пока хранит только `cli_tasks`; workflow session, audit events и interview state отсутствуют.

## Target Service / Worker Contract

### Service responsibilities

- Владеть canonical workflow state, step transitions и quality gates.
- Выбирать активный шаг и проверять его предусловия.
- Управлять historical prep, repo ordering, snapshot window и knowledge pipeline.
- Хранить session state, open questions, artifact registry и audit trail.
- Формировать узкие worker-задачи с expected result schema.
- Валидировать ответы worker и решать `retry`, `reject`, `advance`, `pause_for_user`.

### Worker responsibilities

- Получать уже подготовленную сервисом подзадачу в пределах одного шага.
- Работать только в выделенном `cwd`, с явным `timeout` и expected output schema.
- Возвращать структурированный результат без самостоятельного выбора следующего шага workflow.
- Не менять progress/state напрямую вне разрешённых сервисом артефактов.

## Required Domain Operations

Сервисный слой должен предоставить typed операции для:

- `init_progress`
- `get_status`
- `validate_progress`
- `advance_step`
- `register_repo`
- `start_repo_analysis`
- `complete_repo_checklist_item`
- `complete_repo_analysis`
- `assess_repo_domains`
- `register_domain`
- `plan_timeline`
- `resolve_timeline_window`
- `advance_timeline_window`
- `bootstrap_knowledge_base`
- `compile_navigation`
- `index_knowledge`
- `lint_knowledge`
- `record_user_answer`
- `finalize_workflow`

## Event Model For Audit Trail

Обязательные типы событий:

- `workflow_step_started`
- `workflow_step_completed`
- `workflow_step_failed`
- `guard_command_requested`
- `guard_command_applied`
- `llm_task_requested`
- `llm_task_completed`
- `llm_task_failed`
- `worker_result_rejected`
- `user_question_opened`
- `user_answer_recorded`
- `artifact_written`
- `artifact_rejected`
- `workflow_paused`
- `workflow_resumed`

## Parity Invariants

1. Только сервис принимает решение о переходе между шагами.
2. `historical prep` обязателен перед `assess_scope_and_domains` и `analyze_repositories`.
3. Для каждого `repo` и `domain` существует typed lifecycle, а не только заметка в prompt.
4. В каждый момент времени может быть не более одного открытого пользовательского вопроса.
5. Knowledge artifacts создаются через сервисный pipeline с валидацией и traceability.
6. Каждый LLM CLI вызов сохраняется как отдельный audit record.
7. `status`, `resume` и transport APIs работают поверх одного backend workflow state.
8. Progress YAML может использоваться как миграционный/interop артефакт, но не как единственный owner состояния.

## Stage 1 Outcome

Stage 1 считается закрытым, когда:

- зафиксирован source matrix;
- описан service/worker contract;
- перечислены обязательные guard operations;
- зафиксирован event model audit trail;
- записаны parity invariants для дальнейшей реализации.
