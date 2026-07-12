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
- `arch-docs/app/services/init_arch_workflow.py`
- `arch-docs/app/api/rest/conversations.py`
- `arch-docs/app/api/openai.py`

**Результат этапа:** temporal analysis превращается в пользовательски управляемую последовательность окон, где сервис явно останавливается между периодами.

### Этап 6. Передавать diff-context в worker prompts и task contracts

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

### Этап 7. Добавить signal routing по diff внутри `init_arch`

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

### Этап 8. Обновить progress/guard semantics и interop CLI

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
