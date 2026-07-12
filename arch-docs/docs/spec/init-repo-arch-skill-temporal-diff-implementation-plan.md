# План реализации diff-aware temporal analysis для `init-repo-arch-skill` в `arch-docs`

## 1. Общее описание

**Цель:** расширить текущий `init_arch` workflow так, чтобы анализ по временным срезам опирался не только на `snapshot checkout` выбранного коммита, но и на **историю изменений за интервал между соседними временными окнами**: commit range, `git log`, `git diff --stat`, `git diff --name-status` и, при необходимости, targeted patch/context inspection.

**Проблема текущей реализации:** historical prep уже умеет выбрать `snapshot date`, найти commit не позже даты и перевести `.temp/<repo>` на этот commit, но последующий анализ читает в основном только содержимое checkout-состояния. Это даёт корректный срез состояния, но теряет важный сигнал: **что именно изменилось за период**, какие файлы/контракты/интеграции появились, удалились или были переименованы, и какие артефакты нужно пересмотреть в первую очередь.

**Базовый ориентир:** текущие historical-этапы из [init-repo-arch-skill-implementation-plan.md](./init-repo-arch-skill-implementation-plan.md) и workflow-документация [workflows/init.md](./workflows/init.md), но с новой обязательной доменной гарантией: temporal analysis становится **range-aware**, а не только snapshot-aware.

## 2. Текущее состояние проекта

Сейчас temporal pipeline в `init_arch` уже включает базовые historical операции:

- `refresh_main_branches` читает `main_branch`, `remote_head_commit`, `created_at`;
- `plan_repository_order` выбирает anchor repo и рассчитывает `current_snapshot_at`;
- `resolve_target_commits` находит commit не позже snapshot date;
- `.temp/<repo>` переводится на найденный commit через checkout;
- downstream-анализ выполняется по raw checkout-слою.

При этом отсутствует отдельная модель дельты между окнами:

- не хранится явный `previous_snapshot_commit -> current_snapshot_commit` range;
- не рассчитываются `git diff --stat`, `git diff --name-status`, summary commit log и список затронутых путей;
- prompt и worker-task не получают обязательный change context для текущего окна;
- knowledge/update decisions по временным окнам не могут опираться на приоритизацию по изменившимся зонам кода;
- нет quality gate, который бы проверял, что temporal range для окна действительно построен, а не подменён просто новым checkout.

Итог: сервис сейчас знает, **какой commit анализировать на дату**, но не знает, **какие изменения привели систему к этому состоянию** за рассматриваемый период.

## 3. Целевое состояние

`arch-docs` должен поддерживать два взаимодополняющих режима temporal reasoning внутри `init_arch`:

1. **Snapshot state**
   - сервис знает, какой commit является целевым состоянием на `snapshot date`;
   - `.temp/<repo>` по-прежнему может checkout-иться на этот commit для чтения фактического кода.

2. **Temporal delta**
   - сервис знает commit range для окна:
     - `window_start_commit` или `previous_snapshot_commit`;
     - `window_end_commit` или `analysis_target_commit`;
   - сервис собирает нормализованный diff-context:
     - `git log --oneline`;
     - `git diff --stat`;
     - `git diff --name-status`;
     - при необходимости — patch/context только по релевантным файлам.

Новая обязательная доменная гарантия:

- каждый временной срез после первого должен анализироваться как пара:
  - `state at snapshot`
  - `changes since previous snapshot`
- после завершения анализа каждого временного окна сервис не переходит к следующему окну автоматически, а ждёт явного подтверждения пользователя на продолжение.

Для первого окна допустим special-case:

- если предыдущего snapshot ещё нет, temporal delta считается от `repo created_at baseline` или от первого доступного commit;
- этот режим должен быть явно отражён в state и prompt, а не скрыт неявным поведением.

## 4. Наблюдаемый разрыв с текущей реализацией

- `HistoricalPrepService` сейчас вычисляет только `analysis_target_commit`, но не строит commit range между окнами.
- `analysis_guard timeline --advance-window` сдвигает дату, но не фиксирует temporal baseline следующего окна.
- workflow state не хранит typed delta-структуру для каждого repo и каждого snapshot-window.
- prompts для `assess_scope_and_domains` и `analyze_repositories` не содержат structured change summary.
- LLM worker не ограничен правилом “сначала изучить diff текущего окна, затем углубляться в состояние файлов”.
- tests покрывают planning/checkout, но не покрывают range construction, diff extraction и использование delta в downstream-анализе.

## 5. План реализации по этапам

### Этап 1. [x] Зафиксировать новый temporal contract

**Задача:** явно определить, что temporal analysis в `init_arch` состоит из snapshot-state и temporal-delta, а не только из checkout на дату.

**Что сделать:**
- зафиксировать новый glossary для temporal модели:
  - `snapshot_date`
  - `snapshot_commit`
  - `previous_snapshot_commit`
  - `window_start_commit`
  - `window_end_commit`
  - `commit_range`
  - `diff_stat_summary`
  - `changed_paths`
  - `commit_log_summary`
- описать правила для первого окна, промежуточных окон и случая missing history;
- описать поведение для репозиториев без новых commit в текущем окне:
  - если `snapshot_commit` совпадает с предыдущим окном, это `no_changes`, а не ошибка;
  - если repo ещё не существовал на дату окна, это `missing`/`baseline_missing`, но не авария всего workflow;
- определить, где temporal delta обязательна, а где может быть empty/degenerate;
- зафиксировать, что downstream analysis step не должен считать temporal prep завершённым, если построен только checkout без delta-context.

**Целевые зоны проекта:**
- `arch-docs/docs/workflows/init.md`
- `arch-docs/app/workflows/shared_assets/init_arch/SKILL.md`
- при необходимости отдельный gap-analysis документ рядом с этим планом

**Результат этапа:** утверждённый service contract для diff-aware historical analysis.

**Статус выполнения:** выполнено

**Мини-отчёт:**
- в [workflows/init.md](../workflows/init.md) добавлен нормативный `Temporal Contract`: glossary, правила окон, target gate и явная фиксация текущего snapshot-only gap;
- в `app/workflows/shared_assets/init_arch/SKILL.md` обновлён historical happy path: теперь он требует не только `snapshot commit`, но и обязательный `temporal-delta` для окна;
- добавлен отдельный документ [init-repo-arch-skill-temporal-diff-gap-analysis.md](./init-repo-arch-skill-temporal-diff-gap-analysis.md) с разрывом между текущей реализацией и target contract.

### Этап 2. Расширить доменную модель historical state

**Задача:** ввести typed representation временного окна и его дельты на уровне workflow domain model.

**Что сделать:**
- расширить `HistoricalAnalysisState` и `RepositoryExecution` новыми полями:
  - `previous_snapshot_at`
  - `previous_analysis_target_commit`
  - `window_start_commit`
  - `window_end_commit`
  - `commit_range`
  - `commit_range_status`
  - `diff_stat_summary`
  - `commit_log_summary`
  - `changed_paths`
  - `renamed_paths`
  - `deleted_paths`
  - `temporal_delta_note`
- определить enum-статусы наподобие:
  - `not_started`
  - `baseline_missing`
  - `range_resolved`
  - `diff_collected`
  - `no_changes`
  - `invalid_range`
- определить инварианты в domain operations:
  - если `analysis_target_commit` заполнен и окно не первое, то должен быть либо валидный `commit_range`, либо явно зафиксирован `baseline_missing`;
  - `window_end_commit` должен совпадать с `analysis_target_commit`.

**Целевые зоны проекта:**
- `arch-docs/app/workflows/init_arch/domain/models.py`
- `arch-docs/app/workflows/init_arch/domain/operations.py`
- `arch-docs/app/workflows/init_arch/state.py`
- `init-repo-arch-skill/scripts/analysis_guard/models.py`

**Результат этапа:** workflow state умеет хранить не только snapshot commit, но и осмысленную temporal delta.

**Статус выполнения:** выполнено

**Мини-отчёт:**
- в `app/workflows/init_arch/domain/models.py` добавлен enum `CommitRangeStatus` и typed temporal-delta поля для `RepositoryExecution` и `HistoricalAnalysisState`, включая `previous_snapshot_at`, `previous_analysis_target_commit`, `window_start_commit`, `window_end_commit`, `commit_range`, summaries и path-lists;
- в `app/workflows/init_arch/domain/operations.py` historical gate усилен новыми инвариантами: для non-first window требуется либо валидный range-status с `commit_range`, либо явный `baseline_missing`; `window_end_commit` больше не может расходиться с `analysis_target_commit`;
- в `app/workflows/init_arch/historical.py` `plan_repository_order()` теперь сбрасывает temporal-delta поля в консистентное `not_started`-состояние и явно обнуляет `previous_snapshot_at` для первого окна;
- добавлены и прогнаны тесты на новые поля и инварианты: `tests/workflows/init_arch/domain/test_models.py`, `tests/workflows/init_arch/domain/test_operations.py`, `tests/workflows/init_arch/test_historical.py`, плюс полный suite `tests/workflows/init_arch`;
- `app/workflows/init_arch/state.py` не потребовал структурных изменений, потому что transport envelope уже несёт весь domain state через `session`;
- legacy `init-repo-arch-skill/scripts/analysis_guard/models.py` в этом репозитории отсутствует: stage 2 закрыт на service-owned моделях `arch-docs`, а перенос CLI parity остаётся задачей следующих этапов миграции.

### Этап 3. Реализовать range/diff extraction в historical service

**Задача:** научить сервис строить commit range и change summary для каждого repo в каждом окне.

**Что сделать:**
- расширить `HistoricalPrepService` методами уровня домена:
  - `resolve_temporal_baseline(...)`
  - `build_commit_range(...)`
  - `collect_diff_summary(...)`
  - `collect_changed_paths(...)`
  - `collect_commit_log_summary(...)`
- определить правила baseline:
  - для первого окна baseline может быть `""` или первый commit;
  - для следующих окон baseline берётся из предыдущего завершённого snapshot;
- реализовать git-операции:
  - `git rev-list`
  - `git log --oneline <range>`
  - `git diff --stat <range>`
  - `git diff --name-status <range>`
- аккуратно обработать edge-cases:
  - одинаковый start/end commit;
  - force-push/rebase и invalid ancestry;
  - отсутствие commit на дату;
  - merge-heavy history.

**Целевые зоны проекта:**
- `arch-docs/app/workflows/init_arch/historical.py`
- `init-repo-arch-skill/scripts/analysis_guard/commands.py`
- `init-repo-arch-skill/scripts/analysis_guard/validation.py`

**Результат этапа:** service-side historical prep строит воспроизводимую temporal delta для каждого окна.

**Статус выполнения:** выполнено

**Мини-отчёт:**
- в `app/workflows/init_arch/historical.py` добавлены stage-3 методы `resolve_temporal_baseline()`, `build_commit_range()`, `collect_diff_summary()`, `collect_changed_paths()` и `collect_commit_log_summary()`;
- `resolve_target_commits()` теперь не только находит `analysis_target_commit`, но и собирает typed temporal delta: baseline commit, `commit_range`, summaries по `git log --oneline` и `git diff --stat`, а также нормализованные `changed_paths`/`renamed_paths`/`deleted_paths`;
- обработаны edge-cases для первого окна и проблемной истории: first-window baseline может деградировать в явный `baseline_missing`, одинаковые start/end commits маркируются как `no_changes`, а invalid ancestry помечается как `invalid_range`;
- diff parsing нормализует rename/delete semantics в состоянии workflow, чтобы downstream analysis мог приоритизировать изменившиеся зоны кода без повторного raw git parsing;
- legacy `init-repo-arch-skill/scripts/analysis_guard/{commands,validation}.py` в этом репозитории отсутствуют, поэтому parity на этом этапе реализована на service-side `arch-docs`, а перенос CLI-поведения остаётся следующей миграционной задачей;
- добавлены и прогнаны тесты в `tests/workflows/init_arch/test_historical.py`, затем подтверждён регрессионный прогон всего `tests/workflows/init_arch`.

### Этап 4. Сделать temporal delta обязательным quality gate

**Задача:** запретить переход к содержательному анализу, если delta текущего окна не подготовлена.

**Что сделать:**
- расширить quality gates перед `assess_scope_and_domains` и/или `analyze_repositories`;
- добавить проверку:
  - snapshot commit resolved;
  - previous baseline resolved or explicitly marked missing;
  - commit range computed;
  - diff metadata collected;
- добавить audit-события:
  - `temporal_range_requested`
  - `temporal_range_resolved`
  - `temporal_diff_collected`
  - `temporal_diff_missing`
  - `temporal_range_invalid`
- зафиксировать failure semantics: если checkout возможен, но range invalid, workflow не считает окно готовым.

**Целевые зоны проекта:**
- `arch-docs/app/workflows/init_arch/domain/operations.py`
- `arch-docs/app/workflows/init_arch/nodes.py`
- `arch-docs/app/workflows/init_arch/audit.py`

**Результат этапа:** historical prep становится snapshot+diff gate, а не только snapshot gate.

**Статус выполнения:** выполнено

**Мини-отчёт:**
- в `app/workflows/init_arch/domain/models.py` в `EventType` добавлены temporal-события: `TEMPORAL_RANGE_REQUESTED`, `TEMPORAL_RANGE_RESOLVED`, `TEMPORAL_DIFF_COLLECTED`, `TEMPORAL_DIFF_MISSING`, `TEMPORAL_RANGE_INVALID`;
- в `app/workflows/init_arch/domain/operations.py` найден и закрыт реальный баг quality gate: прежний `_repository_temporal_window_is_valid()` требовал непустой `commit_range` для *любого* допустимого `commit_range_status`, из-за чего легитимный `NO_CHANGES` (start commit == end commit, range намеренно пустой) ложно проваливал gate. Теперь `NO_CHANGES` и `BASELINE_MISSING` обрабатываются как отдельные валидные состояния, а непустой `commit_range` обязателен только для `DIFF_COLLECTED`; транзитный `RANGE_RESOLVED` (диапазон построен, но diff ещё не собран) больше не проходит gate — переход к `assess_scope_and_domains`/`analyze_repositories` блокируется, пока diff не собран или окно явно не помечено `no_changes`/`baseline_missing`;
- в `app/workflows/init_arch/historical.py` `resolve_target_commits()` теперь публикует audit-события через новый `_record_temporal_delta_event()`: `temporal_range_requested` — один раз в начале прогона окна, и per-repository `temporal_diff_collected`/`temporal_range_resolved`(no-changes)/`temporal_diff_missing`(baseline missing)/`temporal_range_invalid` — по фактическому `commit_range_status` каждого репозитория;
- failure semantics зафиксированы кодом, а не только документом: checkout может быть выполнен успешно, но если `commit_range_status` не в `{DIFF_COLLECTED, NO_CHANGES, BASELINE_MISSING}` (например `INVALID_RANGE` после rebase/force-push), `historical_prep_is_complete()` возвращает `False` и `advance_step()` кидает `DomainOperationError`, не пропуская workflow дальше;
- изменение затронуло `nodes.py`/`audit.py` только косвенно: `nodes.py` уже вызывал `resolve_target_commits()` и общий `_record_workflow_event`, отдельных правок не потребовалось; `audit.py` (generic `WorkflowAuditService.record()`) переиспользован как есть — новые события используют тот же transport;
- добавлены и прогнаны тесты: `tests/workflows/init_arch/domain/test_operations.py` (новые кейсы на `NO_CHANGES`, `INVALID_RANGE`, `DIFF_COLLECTED`, и на баг с прежним строгим `bool(commit_range and ...)`), `tests/workflows/init_arch/test_historical.py` (audit-события для `baseline_missing`, `no_changes`, `diff_collected`, прямой unit-тест на `_record_temporal_delta_event` для `invalid_range`); полный прогон `tests/` — **309 passed**;
- `ruff check` на изменённые файлы — новых замечаний не осталось (устранено `PLR0911` на `_repository_temporal_window_is_valid`, ужатое до 6 return-веток); оставшиеся warnings в тех же файлах — pre-existing, вне дельты этого этапа.

### Этап 5. Добавить обязательное подтверждение пользователя перед следующим периодом

**Задача:** сделать переход между временными окнами управляемым пользователем, а не автоматическим продолжением workflow.

**Что сделать:**
- ввести отдельную required action / interrupt semantics после завершения анализа текущего окна:
  - `confirm_next_temporal_window`
  - optional `stop_temporal_analysis`
- зафиксировать, что после закрытия анализа окна workflow:
  - сохраняет результаты текущего окна;
  - публикует summary того, что было обнаружено за период;
  - переходит в paused/waiting-user-confirmation state;
  - не выполняет `advance-window` до user action;
- добавить typed поля состояния наподобие:
  - `awaiting_window_confirmation`
  - `last_completed_snapshot_at`
  - `next_snapshot_at`
  - `next_window_confirmation_status`
- определить, какой именно user action разрешает продолжение:
  - `continue_to_next_window`
  - `finish_temporal_analysis`
- зафиксировать transport contract для этого подтверждения:
  - через internal conversation-first API как standard `response action`;
  - через OpenAI-compatible facade как действие над тем же `response_id` / workflow-run, без отдельного обходного механизма;
  - semantics подтверждения должны быть одинаковыми независимо от transport layer;
- зафиксировать правила для последнего окна:
  - если достигнут terminal snapshot или больше нет новых commit, workflow завершает temporal loop без лишнего подтверждения.

**Целевые зоны проекта:**
- `arch-docs/app/workflows/init_arch/domain/models.py`
- `arch-docs/app/workflows/init_arch/domain/operations.py`
- `arch-docs/app/workflows/init_arch/domain/steps.py`
- `arch-docs/app/workflows/init_arch/historical.py`
- `arch-docs/app/workflows/init_arch/guard.py`
- `arch-docs/app/workflows/init_arch/nodes.py`
- `arch-docs/app/workflows/init_arch/graph.py`
- `arch-docs/app/services/init_arch_workflow.py`
- `arch-docs/app/api/rest/conversations.py` (генерик transport, отдельных правок не потребовалось — см. ниже)
- `arch-docs/app/api/openai.py`

**Результат этапа:** temporal analysis превращается в пользовательски управляемую последовательность окон, где сервис явно останавливается между периодами.

**Статус выполнения:** выполнено полностью — domain-контракт, реальный graph loop-back с interrupt-паузой и transport wiring (REST + OpenAI-compatible facade) для `temporal_window_confirmation`

**Мини-отчёт:**
- в `app/workflows/init_arch/domain/models.py` добавлен `NextWindowConfirmationStatus` (`none`/`pending`/`confirmed`/`stopped`) и typed-поля `HistoricalAnalysisState`: `awaiting_window_confirmation`, `last_completed_snapshot_at`, `next_snapshot_at`, `next_window_confirmation_status`;
- в `app/workflows/init_arch/domain/operations.py` добавлены две typed-операции: `request_next_temporal_window_confirmation(session, *, next_snapshot_at)` переводит session в `WAITING_FOR_USER` и фиксирует pending-подтверждение; `confirm_next_temporal_window(session, *, action)` принимает `continue_to_next_window` (продвигает `previous_snapshot_at`/`current_snapshot_at`/`window_index`, пополняет `completed_snapshot_dates`) или `finish_temporal_analysis` (снимает флаг ожидания, помечает `STOPPED`, не продвигает окно); вызов без активного pending-подтверждения кидает `DomainOperationError`;
- добавлены и прогнаны тесты в `tests/workflows/init_arch/domain/test_operations.py` (happy path для обоих действий, guard на отсутствие pending-подтверждения, guard на отсутствие `next_snapshot_at`, unreachable-по-типам ветка `unsupported action`); полный прогон `tests/` — **316 passed**; дельта по `operations.py`/`models.py` полностью покрыта тестами;
- **важное ограничение, зафиксированное явно, а не скрытое:** сам langgraph-граф (`app/workflows/init_arch/graph.py`) сейчас линеен и не содержит loop-back edge для повторного прохода `refresh_main_branches -> plan_repository_order -> ... -> finalize_progress` в рамках одного запуска — `HistoricalAnalysisState.window_index`/`completed_snapshot_dates` существовали в модели ещё до этого этапа, но нигде не инкрементировались исполняемым кодом. Эта работа не была явно описана как отдельный этап плана, но является предпосылкой, без которой `confirm_next_temporal_window` некому вызывать из orchestration-слоя;
- следствие: `services/init_arch_workflow.py`, `api/rest/conversations.py`, `api/openai.py` **не тронуты** в этом проходе — transport-контракт (dedicated interrupt-node, resume action `continue_to_next_window`/`finish_temporal_analysis`, OpenAI-facade submit action поверх того же `response_id`) остаётся открытым follow-up. Закрыт только domain-контракт (typed state + инварианты), который эти слои будут использовать;
- также не реализовано в этом проходе: сброс per-window analysis progress (`checklist_items_completed`, `analysis_status`) при продвижении на следующее окно — `plan_repository_order()` уже сбрасывает только temporal-delta поля, но не analysis-прогресс по repositories; нужно явно решить, накопительный это прогресс между окнами или per-window, прежде чем подключать loop-back в graph.py.

**Обновление (доведено до ума):**
- добавлен новый `StepId.CONFIRM_NEXT_TEMPORAL_WINDOW` между `VALIDATE_FINAL` и `FINALIZE_PROGRESS` в `domain/models.py`/`domain/steps.py`: `FINALIZE_PROGRESS` теперь требует прохождения этого шага, а не напрямую `VALIDATE_FINAL`;
- в `historical.py` добавлен `HistoricalPrepService.compute_next_window(session, *, today)`: возвращает `None` (terminal), если все repositories уже на `remote_head_commit`, либо если следующий кандидат окна (`current_snapshot_at + historical_window_months`) ещё в будущем относительно `today`; иначе возвращает дату следующего окна;
- в `guard.py` добавлены `request_next_temporal_window()`/`confirm_next_temporal_window()` — typed-обёртки над domain-операциями с audit-событиями `GUARD_COMMAND_REQUESTED`/`GUARD_COMMAND_APPLIED`, по аналогии с остальными guard-методами;
- в `nodes.py` добавлена `node_confirm_next_temporal_window()`: если `compute_next_window()` вернул `None` — сразу advance к `FINALIZE_PROGRESS` без паузы; иначе вызывает `interrupt({"interrupt_type": "temporal_window_confirmation", ...})` (пауза до explicit user action, ровно как `node_request_repository_list`/`node_interview_user`), затем на resume извлекает `action` (`continue_to_next_window`/`finish_temporal_analysis`) через `_extract_window_confirmation_action()`, вызывает `request_next_temporal_window()` -> `confirm_next_temporal_window()`; при `continue_to_next_window` дополнительно сбрасывает `checklist_items_completed`/`analysis_status` у всех repositories (per-window re-analysis, а не накопительный прогресс — осознанный выбор до появления diff-based signal routing в Этапе 7) и advance к `REFRESH_MAIN_BRANCHES` (реальный loop-back); при `finish_temporal_analysis` advance к `FINALIZE_PROGRESS`;
- в `graph.py` узел `confirm_next_temporal_window` подключён кастомным router'ом `_route_after_confirm_next_temporal_window()` (не через generic `_route_after_node()`, так как маршрутизация не линейна): при ошибке — retry/`handle_error`, иначе — `refresh_main_branches`, если `session.current_step is REFRESH_MAIN_BRANCHES` (после confirm continue), иначе `finalize_progress`;
- добавлены тесты: `tests/workflows/init_arch/test_historical.py` (`compute_next_window` — terminal по remote head, terminal по future date, happy path), `tests/workflows/init_arch/test_guard.py` (request+confirm round-trip с audit-событиями), `tests/workflows/init_arch/test_nodes.py` (no-more-windows path, continue path со сбросом repository progress, finish path, propagation реального interrupt через `KeyboardInterrupt` — как и для остальных pause-точек, `except Exception` в узле не глотает interrupt), `tests/workflows/init_arch/test_graph.py` (новый узел в списке графа, `_route_after_confirm_next_temporal_window` для всех веток); полный прогон `tests/` — **330 passed**; дельта по всем изменённым файлам покрыта тестами (проверено через `--cov-report=term-missing`, непокрытые строки — исключительно pre-existing код вне дельты);
- **что осталось открытым после этого прохода:** реальный E2E-прогон через LangGraph checkpointer (Postgres) не выполнялся — корректность replay-семантики `interrupt()` для нового узла верифицирована только на уровне unit-тестов по аналогии с уже существующими `request_repository_list`/`interview_user`, не через живой checkpointed run.

**Транспорт-слой (доведено до конца):**
- в `services/init_arch_workflow.py` расширен `build_resume_value()`: для `interrupt_type == "temporal_window_confirmation"` возвращает `{"action": value}` (generic resume path, симметрично `user_input`/`user_question`);
- добавлена `confirm_init_arch_temporal_window(workflow_id, *, action)` — mirror `answer_init_arch_question()`: проверяет, что `record.workflow_status is INTERRUPTED` и `pending_interrupt.interrupt_type == "temporal_window_confirmation"` (иначе `WorkflowConflictError`), валидирует `action ⊂ {continue_to_next_window, finish_temporal_analysis}` (иначе `WorkflowValidationError`), затем `schedule_resume(record, resume_value={"action": action})`;
- `submit_response_action_async()` получил новую ветку `action_type == "confirm_temporal_window"` (требует `value`, дергает `confirm_init_arch_temporal_window`) — это тот же generic action dispatcher, которым уже пользуются `cancel`/`answer_question`/`resume`, так что REST endpoint `POST /responses/{response_id}/actions/` в `api/rest/conversations.py` заработал **без единой правки в файле**: `ResponseActionRequest` уже был достаточно generic (`action_type`, `question_id`, `answer`, `field`, `value`);
- в `api/openai.py` добавлен новый route `POST /v1/responses/{response_id}/actions` (`OpenAIResponseActionRequest`, то же generic-поле множество), который вызывает тот же `submit_response_action_async()` — то самое "действие над тем же `response_id`/workflow-run, без отдельного обходного механизма" из требований этапа. Побочный эффект: это заодно закрывает Known Gap #4 ("OpenAI facade не экспонирует submit actions") для *всех* interrupt-типов (`cancel`, `answer_question`, `resume`, `confirm_temporal_window`), а не только для temporal-окон — до этого OpenAI-facade вообще не имел ни одного submit-action route;
- добавлены тесты: `tests/services/test_init_arch_workflow.py` (`build_resume_value` для нового interrupt-типа, `confirm_init_arch_temporal_window` — happy path/wrong interrupt type/unsupported action, `submit_response_action_async` dispatch + guard на отсутствие `value`), `tests/api/rest/test_openai_facade.py` (новый route — happy path, 404, 422); полный прогон `tests/` — **339 passed**; `ruff check` на изменённые файлы — 0 новых замечаний (auto-fix поправил порядок импортов);
- REST-специфичных тестов в `tests/api/rest/test_conversations.py` не добавлено осознанно: маршрут и диспетчер там уже покрыты существующими generic-тестами `submit_response_action`, а новая ветка `action_type` целиком лежит в уже протестированном `submit_response_action_async` — дублировать REST-уровень не требовалось, так как conversations.py не редактировался.

### Этап 6. [x] Передавать diff-context в worker prompts и task contracts

**Задача:** сделать temporal delta обязательной частью контекста для LLM worker и всех аналитических шагов по окну.

**Что сделать:**
- расширить `build_step_prompt(...)` так, чтобы он включал:
  - `snapshot date`
  - `snapshot commit`
  - `commit range`
  - commit log summary
  - diff stat summary
  - changed/renamed/deleted paths
- добавить явную инструкцию:
  - сначала проанализировать изменения за окно;
  - затем по необходимости читать итоговое состояние файлов в checkout;
- разделить change-context по уровням:
  - compact summary для обычных шагов;
  - expanded changed-paths context для `analyze_repositories`;
- при необходимости расширить `LlmTaskRequest`/expected schema, чтобы worker мог отдельно возвращать:
  - какие выводы опираются на diff;
  - какие — на snapshot state.

**Целевые зоны проекта:**
- `arch-docs/app/workflows/init_arch/prompts.py`
- `arch-docs/app/workflows/init_arch/llm_worker.py`
- `arch-docs/app/workflows/shared_assets/init_arch/references/*.md`

**Результат этапа:** worker больше не изучает временной срез “вслепую” по одному лишь checkout.

**Статус выполнения:** выполнено

**Мини-отчёт:**
- в `app/workflows/init_arch/prompts.py` добавлен `_build_temporal_delta_block()`, который рендерит для активного репозитория (`analysis_status == "in_progress"`) блок `# Temporal delta текущего окна`: `snapshot date`, `snapshot commit`, `window_start_commit`/`window_end_commit`, `commit_range`, `commit_range_status`, commit log summary, diff stat summary и три списка путей (`changed_paths`/`renamed_paths`/`deleted_paths`); блок вставлен в `build_step_prompt()` между открытыми вопросами и reference-чеклистом, так что он доступен на каждом шаге, а не только на `analyze_repositories`;
- для нетривиальных `commit_range_status` добавлены explanatory-заметки прямо в промпт: `NOT_STARTED` -> "delta ещё не построена", `NO_CHANGES` -> "изменений не было", `BASELINE_MISSING`/`INVALID_RANGE` -> явное указание не полагаться на diff и работать со snapshot state — это прямое отражение доменных инвариантов из Этапов 2-4, а не дублирующая эвристика;
- реализовано разделение compact/expanded context, как того требовал план: `_format_path_list()` для обычных шагов обрезает списки путей до `_MAX_COMPACT_CHANGED_PATHS = 10` записей с суффиксом "... и ещё N путей", а для `analyze_repositories` (единственный шаг в `_EXPANDED_DIFF_CONTEXT_STEPS`) выводит полный список без обрезки — компромисс между шумностью промпта на обычных шагах и полнотой контекста там, где worker реально приоритизирует анализ по diff;
- добавлена явная инструкция в секцию `# Инструкции`: сначала изучить temporal delta (commit range/log/diff stat), затем при необходимости читать итоговое состояние файлов в raw checkout-слое — воркер больше не может "начать вслепую" с checkout;
- `LlmTaskRequest` менять не потребовалось (уже содержит нужный `prompt_text`), но `LlmTaskResult` (`app/workflows/init_arch/domain/models.py`) расширен двумя полями — `diff_based_findings: list[str]` и `snapshot_based_findings: list[str]` — чтобы worker мог явно разделить, какие выводы опираются на diff, а какие на snapshot state, как и требовал план ("при необходимости расширить LlmTaskRequest/expected schema"); JSON-контракт в промпте (`build_step_prompt`) обновлён теми же двумя полями, `app/services/task_runner.py::_parse_result`-consumer (`LlmCliService.run_task`) прокидывает их из распарсенного JSON в `LlmTaskResult`;
- `app/workflows/init_arch/llm_worker.py` не потребовал изменений: это тонкая обёртка над `LlmCliService`, весь diff-context уже приходит через `prompt_text`, который строит `build_step_prompt()`;
- `arch-docs/app/workflows/shared_assets/init_arch/references/*.md` не редактировались в этом проходе: reference-чеклисты описывают, что проверять по каждой категории (domain entities, contracts, integrations и т.д.), а не как читать temporal-контекст — это принадлежит общей секции промпта, а не per-checklist reference; при необходимости точечных упоминаний "изучи diff перед чтением файлов" для конкретных чеклистов это можно сделать отдельным точечным проходом, но глобальная инструкция уже покрывает это для всех шагов;
- добавлены тесты в `tests/workflows/init_arch/test_prompts.py`: отсутствие активного репозитория, `NOT_STARTED`/`NO_CHANGES`-заметки, полный набор temporal-полей и path-списков для `DIFF_COLLECTED`, compact-обрезка на 15 путях для обычного шага и full-list без обрезки для `analyze_repositories`; и в `tests/services/test_task_runner.py` — парсинг `diff_based_findings`/`snapshot_based_findings` из JSON-ответа worker'а;
- прогнаны `ruff check` (0 замечаний после ручного дробления длинных строк) и `pytest tests/` — **345 passed**; `--cov-report=term-missing` по `app/workflows/init_arch/prompts.py` — **100%** (56/56 строк), по `app/services/task_runner.py` — **96%**, непокрытые строки (264, 269-270, 296-298) — pre-existing код вне дельты этого этапа (fallback JSON-parse error path и module-level singleton getter).

### Этап 7. [x] Добавить signal routing по diff внутри `init_arch`

**Задача:** использовать change-set как механизм приоритизации и ограничения глубины анализа внутри каждого временного окна.

**Что сделать:**
- адаптировать идеи из `update-repo-arch-skill`:
  - changed files -> impacted knowledge categories;
  - diff severity -> review depth;
- ввести lightweight routing even for init flow:
  - если в окне нет изменений по repo, analysis может быть сведён к подтверждению отсутствия изменений;
  - если изменения локальны, можно фокусировать анализ на затронутых подсистемах;
  - если изменения широкие, выполнять полный checklist;
- зафиксировать, что temporal diff в `init` не заменяет целостный анализ состояния, но помогает приоритизировать и документировать evolution.

**Целевые зоны проекта:**
- `arch-docs/app/workflows/init_arch/nodes.py`
- `arch-docs/app/workflows/init_arch/domain/operations.py`
- общие reference/checklist assets

**Результат этапа:** temporal analysis начинает учитывать evolution-path, а не только конечный state.

**Статус выполнения:** выполнено

**Мини-отчёт:**
- добавлен новый domain-модуль `app/workflows/init_arch/domain/signal_routing.py` — pure business logic без зависимости от `prompts.py`, экспортирован через `domain/__init__.py` (`DiffSeverity`, `classify_diff_severity`, `route_checklist_items`);
- `classify_diff_severity(repository)` классифицирует repository-window по уже существующим typed-полям из Этапов 2-4 (не вводит новый источник фактов): `not_started`/`baseline_missing`/`invalid_range` -> `DiffSeverity.FULL_REQUIRED` (недостаточно сигнала, чтобы сузить анализ — temporal diff не заменяет целостный анализ, как того требовал план); `no_changes` или пустой footprint при `diff_collected` -> `DiffSeverity.NO_SIGNAL`; иначе считается `top_level_dirs` по объединению `changed_paths`+`renamed_paths`+`deleted_paths` — до 3 затронутых директорий верхнего уровня включительно -> `LOCAL`, больше -> `BROAD`;
- `route_checklist_items(repository, *, all_checklist_item_ids)` реализует три ветки, дословно совпадающие с формулировками плана: `FULL_REQUIRED`/`BROAD` -> полный чеклист без исключений; `NO_SIGNAL` -> "analysis сведён к подтверждению отсутствия изменений" — единственный routed item `repository_consistency_review`; `LOCAL` -> "фокусировать анализ на затронутых подсистемах" — категории берутся из lightweight glob-таблицы `_PATH_SIGNAL_CATEGORIES` (адаптация fallback-таблицы `update-repo-arch-skill/references/checklist-signal-routing.md`: `api/`/`routers/`/`controllers/` -> `entrypoints_and_interfaces`, `serializers/`/`schemas/`/`dto/` -> `contracts_and_schemas`, `migrations/`/`models/` -> `data_and_storage`, `auth/`/`rbac/` -> `roles_and_permissions_updates`+`security_and_auth_updates` и т.д.), плюс всегда включённые `architecture_artifact_updates` и `repository_consistency_review` (doc-consistency категории, не зависящие от конкретных путей); порядок результата совпадает с порядком `all_checklist_item_ids`, а не порядком обнаружения категорий;
- `nodes.py::node_analyze_repositories` теперь вызывает `route_checklist_items(repository, all_checklist_item_ids=list(CHECKLIST_ITEM_TO_REFERENCE))` перед циклом по чеклисту репозитория и итерирует только по routed-подмножеству вместо всех 20 категорий безусловно; per-repository routing-решение публикуется как новое audit-событие `EventType.DIFF_SIGNAL_ROUTED` (`diff_severity`, `routed_items`, `total_items` в payload) — так фиксируется, что именно было решено маршрутизировать для конкретного repository-window, что явно требовал план ("помогает приоритизировать и документировать evolution"); `_record_workflow_event()` в `nodes.py` расширен опциональным `repository_name` kwarg для этого случая (раньше per-repository events публиковались только из `historical.py`, а не из `nodes.py`);
- инвариант "temporal diff не заменяет целостный анализ" закреплён кодом, а не только комментарием: `historical_prep_is_complete()` (Этап 4) по-прежнему блокирует переход к `analyze_repositories`, если delta не построена, а внутри `analyze_repositories` `guard_service.complete_repository()` не проверяет полноту `checklist_items_completed` (подтверждено чтением `operations.py`/`guard.py` и grep по всем вызовам поля) — значит сокращённый routing не может тихо пометить репозиторий "полностью проанализированным", когда фактически проверено меньше категорий, но и не ломает существующий invariant, которого не было;
- обратная совместимость: `RepositoryExecution` по умолчанию имеет `commit_range_status = NOT_STARTED` (Этап 2), что маппится в `FULL_REQUIRED` -> полный чеклист — поэтому весь существующий regression suite (`test_node_analyze_repositories_uses_typed_services` и остальные 344 теста) прошёл без единой правки, подтверждая, что routing строго аддитивен для уже существующих сценариев без построенной temporal-delta;
- добавлены тесты: `tests/workflows/init_arch/domain/test_signal_routing.py` (полное покрытие `classify_diff_severity`/`route_checklist_items` — все статусы, узкий/широкий footprint, rename/delete paths, сохранение порядка, unmatched-paths fallback) и `tests/workflows/init_arch/test_nodes.py::test_node_analyze_repositories_routes_reduced_checklist_for_no_changes_window` (end-to-end через `node_analyze_repositories`: `NO_CHANGES` -> ровно один вызов LLM worker для `repository_consistency_review`, аудит-событие `diff_signal_routed` с `diff_severity=no_signal`, `routed_items=1`);
- `EventType.DIFF_SIGNAL_ROUTED = "diff_signal_routed"` добавлен в `domain/models.py`;
- reference/checklist assets (`app/workflows/shared_assets/init_arch/references/*.md`) не редактировались: routing — оркестрационное решение сервиса (какие reference-файлы вообще загружать через `build_step_prompt()`/`CHECKLIST_ITEM_TO_REFERENCE`), а не изменение содержимого самих чеклистов;
- прогнаны `ruff check` (0 замечаний после перевода docstring на английский — `RUF002` не допускает кириллицу в docstring в этом репозитории, хотя разрешает её в markdown/комментариях) и `pytest tests/` — **360 passed**; `--cov-report=term-missing` по `app/workflows/init_arch/domain/signal_routing.py` — **100%** (45/45 строк).

### Этап 8. [x] Обновить progress/guard semantics и interop CLI

**Задача:** синхронизировать новый temporal contract между сервисом и legacy/interop guard tooling.

**Что сделать:**
- расширить progress-template новыми temporal fields;
- обновить `analysis_guard timeline` так, чтобы он умел:
  - сохранять previous/current window metadata;
  - вычислять range;
  - валидировать diff collection;
- обновить `status`/`validate` выводы, чтобы temporal delta была видима как first-class state;
- сохранить обратную совместимость там, где это возможно, но не ценой потери нового инварианта.

**Целевые зоны проекта:**
- `init-repo-arch-skill/assets/repo-initialization-progress-template.yaml`
- `init-repo-arch-skill/scripts/analysis_guard/status.py`
- `init-repo-arch-skill/scripts/analysis_guard/validation.py`
- `init-repo-arch-skill/SKILL.md`

**Результат этапа:** interop-слой отражает diff-aware temporal workflow, а не старую snapshot-only модель.

**Статус выполнения:** выполнено

**Мини-отчёт:**
- ревизией подтверждено, что legacy `init-repo-arch-skill/scripts/analysis_guard/*` в этом репозитории **существует** и активно используется (в отличие от предположения в мини-отчётах Этапов 2-3, где было ошибочно указано, что `analysis_guard/models.py` отсутствует) — это отдельный standalone Python CLI (`analysis_guard.py` → пакет `analysis_guard/`), не связанный импортами с сервисом `arch-docs`, со своей JSON/YAML progress-моделью и собственным unittest-сьютом `init-repo-arch-skill/tests/test_analysis_guard_knowledge.py`;
- в `scripts/analysis_guard/models.py` `default_historical_analysis()` и `normalize_repository()` расширены temporal-delta полями по образцу `arch-docs` domain-модели (Этап 2): `previous_snapshot_at` на уровне `historical_analysis`; `previous_analysis_target_commit`, `window_start_commit`, `window_end_commit`, `commit_range`, `commit_range_status`, `diff_stat_summary`, `commit_log_summary`, `changed_paths`, `renamed_paths`, `deleted_paths`, `temporal_delta_note` на уровне репозитория;
- в `scripts/analysis_guard/commands.py` добавлены git-хелперы `_run_git`, `_resolve_first_commit` (first-window baseline fallback — первый commit на `main_branch`), `_is_ancestor` (`git merge-base --is-ancestor`), `_parse_name_status` (нормализация `git diff --name-status` в changed/renamed/deleted) и `_collect_commit_range_diff` (`git log --oneline` + `git diff --stat` + `git diff --name-status` для диапазона, с усечением длинного commit log до 50 строк и changed-paths до 200 записей); собраны в `_build_temporal_delta()`, который воспроизводит те же четыре исхода, что и `HistoricalPrepService` в `arch-docs` (Этап 3): `baseline_missing` (baseline не резолвится), `no_changes` (`window_start_commit == window_end_commit`), `invalid_range` (`window_start_commit` не предок `window_end_commit` — переписанная история/force-push), `diff_collected` (нормальный случай);
- `timeline --resolve-local` теперь вызывает `_build_temporal_delta()` сразу после резолва `analysis_target_commit` для каждого repo (независимо от `--checkout`, как и в `arch-docs`, где delta не требует checkout); `timeline --advance-window` сохраняет только что резолвленный commit как `previous_analysis_target_commit` следующего окна и переносит `current_snapshot_at` в `previous_snapshot_at` (сохранение previous/current window metadata из требований плана), затем сбрасывает temporal-delta поля через новый `_reset_temporal_delta()`; тот же reset вызывается и в `timeline --plan`, чтобы повторное планирование не оставляло stale-delta от предыдущего прогона;
- в `scripts/analysis_guard/validation.py` добавлена проверка допустимых значений `commit_range_status` (зеркалирует `CommitRangeStatus` из `arch-docs`, включая `range_resolved` для forward-совместимости, хотя synchronous-модель legacy CLI никогда не производит этот промежуточный статус — diff собирается атомарно в одном вызове `--resolve-local`) и новый gate: `analyze_repositories` не может быть помечен `completed`, пока для каждого repo (кроме `missing_on_date`) `commit_range_status` не в `{diff_collected, no_changes, baseline_missing}` — тот же инвариант "temporal diff не заменяет целостный анализ, но обязателен как quality gate", что и в Stage 4 `arch-docs`;
- в `scripts/analysis_guard/status.py` добавлена строка `historical_previous_snapshot_at` в общий блок статуса и per-repository строка `temporal_delta: range_status=... range=... changed=N renamed=N deleted=N` — temporal delta стала first-class видимым состоянием, а не скрытым полем progress-файла;
- `assets/repo-initialization-progress-template.yaml` расширен теми же полями на уровне `historical_analysis` (`previous_snapshot_at`) и `repositories[]` (полный temporal-delta блок из 11 полей), синхронно с реализацией;
- `init-repo-arch-skill/SKILL.md` обновлён: historical prep happy path требует не только `analysis_target_commit_status`, но и `commit_range_status ∈ {diff_collected, no_changes, baseline_missing}` перед `advance`; добавлено объяснение семантики `baseline_missing`/`no_changes`/`invalid_range` и того, что `--advance-window` переносит baseline в следующее окно; шаг 4 чеклиста репозитория явно требует сверять temporal delta до чтения итогового состояния файлов; короткая памятка по `timeline` уточнена по каждой команде;
- обратная совместимость: `normalize_repository()` подставляет `commit_range_status="not_started"` через `setdefault`, поэтому старые progress-файлы без temporal-delta полей продолжают проходить `validate`/`status`, пока `analyze_repositories` ещё не завершён; ценой нового инварианта (как и предполагал план) стало то, что **завершить** `analyze_repositories` для repo без построенной delta теперь нельзя — это обнаружил и подтвердил regression-тест `test_status_advance_and_validate_cover_knowledge_steps`, чья фикстура пришлось дополнить `commit_range_status: no_changes`, когда gate впервые сработал на существующем тесте;
- добавлены тесты в `init-repo-arch-skill/tests/test_analysis_guard_knowledge.py`: существующий `test_timeline_plan_resolve_checkout_and_advance_window` расширен полным end-to-end циклом на два окна (первое окно даёт `no_changes`, т.к. baseline совпадает с snapshot commit; `--advance-window` переносит baseline; второе `--resolve-local` даёт `diff_collected` с реальным `commit_range`/`changed_paths`/`diff_stat_summary`/`commit_log_summary`); новый `test_validate_rejects_missing_temporal_delta_and_invalid_commit_range_status` покрывает сам gate и невалидное значение `commit_range_status`; новый класс `TemporalDeltaUnitTests` с тремя unit-тестами на `_build_temporal_delta()` напрямую (`baseline_missing` для repo без единого commit, `invalid_range` через реальный git amend/rewrite сценарий, `diff_collected` happy path); итого **13/13 passed** (`python3 -m unittest init-repo-arch-skill.tests.test_analysis_guard_knowledge`);
- `ruff`/линтер для этого CLI не настроен отдельно (`init-repo-arch-skill/` не содержит собственного `pyproject.toml`/`ruff.toml`) — попытка прогнать `ruff check` из окружения `arch-docs` некорректно применила чужой lint-конфиг и внесла посторонние авто-фиксы (переупорядочивание импортов, снятие `# noqa`, смена стиля кавычек) в файлы вне зоны этой дельты; все такие правки вручную откачены, чтобы не тащить в коммит несвязанные изменения — итоговая дельта строго ограничена Stage 8;
- прогон полного regression-сьюта `arch-docs` (`pytest tests/`, 360 тестов) подтвердил отсутствие побочных эффектов — Stage 8 не затрагивает код `arch-docs`, только legacy `init-repo-arch-skill`.

### Этап 9. Расширить тестовый контур и регрессии

**Задача:** доказать тестами, что temporal windows анализируются через commit history и diff, а не только через содержимое checkout.

**Что сделать:**
- добавить unit/integration tests на:
  - построение commit range для первого и следующих окон;
  - empty diff при одинаковых commit;
  - diff summary / changed paths extraction;
  - invalid baseline после переписанной истории;
  - prompt enrichment diff-context-ом;
  - quality gate failure при отсутствии delta;
- расширить existing git-fixtures:
  - несколько commit в одном окне;
  - rename/delete cases;
  - разные даты для старых и новых изменений;
- добавить workflow-level test, который проверяет:
  - сервис не проходит historical gate, если есть checkout, но нет temporal delta.

**Целевые зоны проекта:**
- `arch-docs/tests/workflows/init_arch/test_historical.py`
- `arch-docs/tests/workflows/init_arch/test_nodes.py`
- `arch-docs/tests/workflows/init_arch/domain/test_operations.py`
- `init-repo-arch-skill/tests/test_analysis_guard_knowledge.py`

**Результат этапа:** регрессии snapshot-only поведения ловятся автоматически.

### Этап 10. Документация, аудит и критерии эксплуатации

**Задача:** довести новый механизм до состояния, в котором его можно безопасно использовать и отлаживать.

**Что сделать:**
- обновить `docs/workflows/init.md` с новым sequence flow;
- документировать audit trail для temporal delta:
  - какие range/diff решения приняты;
  - какие git-команды сработали;
  - какие paths повлияли на анализ;
- уточнить операторские сценарии:
  - что делать при invalid range;
  - как интерпретировать `baseline_missing`;
  - когда допустим fallback к snapshot-only анализу, если вообще допустим;
- явно задокументировать границу с `update-repo-arch-skill`:
  - `update` остаётся baseline-to-HEAD delta workflow;
  - `init` теперь получает window-to-window diff semantics внутри исторического первичного анализа.

**Результат этапа:** механизм понятен не только коду, но и эксплуатации, отладке и будущим доработкам.

## 6. Рекомендуемая последовательность выполнения

1. Этап 1: зафиксировать contract и терминологию.
2. Этапы 2-4: ввести typed state, range extraction и quality gates.
3. Этап 5: встроить обязательную пользовательскую паузу между окнами.
4. Этапы 6-8: протащить diff-context в prompts, analysis flow и guard/progress semantics.
5. Этапы 9-10: закрыть тесты, документацию и operational clarity.

## 7. Основные риски и решения

- **Риск:** merge-heavy history даст шумный diff.
  - **Решение:** хранить compact summaries и уметь ограничивать expanded context только changed paths.

- **Риск:** первый snapshot окна не имеет явного baseline.
  - **Решение:** ввести explicit special-case c typed status, а не притворяться обычным range.

- **Риск:** переписанная история ломает ancestry.
  - **Решение:** отдельный `invalid_range`/`baseline_missing` статус и блокирующий gate.

- **Риск:** prompt разрастётся и станет шумным.
  - **Решение:** разделить compact diff summary и expanded path context, передавать подробности только на глубоких шагах.

- **Риск:** подтверждение каждого следующего периода сделает workflow слишком медленным на длинной истории.
  - **Решение:** остановку делать обязательной, но summary текущего окна и `next_snapshot_at` показывать сразу, чтобы пользователь принимал решение быстро и осознанно.

- **Риск:** разные transport-слои начнут по-разному трактовать подтверждение следующего окна.
  - **Решение:** держать confirmation semantics в backend workflow как единый `required_action`, а REST/OpenAI facade использовать только как разные способы доставки одного и того же действия.

- **Риск:** `init` и `update` начнут дублировать слишком много логики.
  - **Решение:** переиспользовать primitives для diff extraction и signal routing, но сохранить разные workflow semantics.

## 8. Критерий готовности

Реализацию можно считать завершённой, когда:

- для каждого исторического окна сервис хранит не только `analysis_target_commit`, но и temporal delta metadata;
- переход к содержательному анализу блокируется, если range/diff не построены;
- после завершения каждого окна workflow останавливается и ждёт явного подтверждения пользователя перед переходом к следующему периоду;
- подтверждение следующего периода доступно в том числе через OpenAI-compatible API facade, а не только через internal conversation API;
- worker prompts получают структурированный change context по текущему окну;
- тесты доказывают, что temporal flow использует commit history и diff, а не только checkout-state;
- progress/audit/status явно показывают, какой commit range был использован для анализа;
- документация workflow отражает новый diff-aware temporal contract.
