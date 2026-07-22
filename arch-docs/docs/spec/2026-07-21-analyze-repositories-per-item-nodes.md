# Разбить `analyze_repositories` на пер-item графовые ноды с resume на уровне одного checklist item

**Цель:** сейчас нода `node_analyze_repositories` — один физический узел LangGraph с вложенным Python-циклом
`for repository in session.repositories: for item_id in routed_item_ids: ...`, внутри которого на каждый
пункт чек-листа запускается отдельная LLM-агентная сессия (`_run_step_worker`). Persist состояния (Postgres
`AsyncPostgresSaver` + YAML progress-снепшот) срабатывает только на границах графовых узлов — а значит, весь
прогресс внутри этого цикла невидим для восстановления: падение на 5-м пункте 2-го репозитория откатывает
всю ноду целиком, а не только незавершённый пункт. Нужно поднять цикл на уровень графа, чтобы каждый LLM-вызов
на один checklist item был отдельным чекпоинтом.

**Статус:** done. Все фазы 0-4 реализованы, покрыты тестами (582 → 606 тестов в сьюте, 0 регрессий),
документация актуализирована.

## Проблема

`node_analyze_repositories` ([nodes.py:551-646](../../back/app/workflows/init_arch/nodes.py#L551-L646)):

```python
for repository in session.repositories:
    start_result = await guard_service.start_repository(...)
    session = start_result.session
    routed_item_ids = route_checklist_items(repository, all_checklist_item_ids=list(CHECKLIST_ITEM_TO_REFERENCE))
    for item_id in routed_item_ids:
        llm_result = await _run_step_worker(..., checklist_item_id=item_id, repository_name=repository.repository_name)
        item_result = await guard_service.complete_repository_item(session, repository_name=..., item_id=item_id, ...)
        session = item_result.session
        if llm_result.open_questions_found:
            question_result = await guard_service.register_open_questions(...)
            session = question_result.session
    complete_result = await guard_service.complete_repository(session, repository_name=..., ...)
    session = complete_result.session
```

Это единственный физический узел графа. Persist срабатывает по схеме `_drive_graph_stream()`
([init_arch_workflow.py:730-765](../../back/app/services/init_arch_workflow.py#L730-L765)):

```python
async for event in graph.astream(stream_input, config=config):
    for node_name, node_output in event.items():
        ...
        apply_node_output(record, node_output)
        await persist_workflow_record(record)       # Postgres: workflow_runs.session_payload
        await _write_progress_snapshot(graph, config)  # YAML progress-снепшот
```

— то есть один раз **на весь выход `graph.astream`**, который для `analyze_repositories` наступает только
после того, как отработали **все** репозитории и **все** их пункты чек-листа. Если процесс упадёт (краш
контейнера, OOM, LLM CLI подвис дольше timeout) на середине цикла:

- Исключение ловится в `except Exception` ([nodes.py:628](../../back/app/workflows/init_arch/nodes.py#L628)),
  нода возвращает `{"step_error": ..., "retry_count": ...}` **без `"session"`** — партиальный прогресс цикла
  (уже вызванные `complete_repository_item`/`register_open_questions` для части пунктов) существует только в
  локальной переменной `session` внутри функции и теряется, как и было исправлено для отдельного случая
  `assess_scope_and_domains` в [2026-07-21-assess-scope-domain-persistence.md](2026-07-21-assess-scope-domain-persistence.md#дополнение-2026-07-21-идемпотентный-retry-вместо-повтора-всего-цикла)
  (см. «Дополнение»).
- Даже если это дополнение сделать и здесь (вернуть `"session"` в except-ветке) — это не решает основную
  проблему: если процесс убьют **между** двумя итерациями item-цикла (не exception, а SIGKILL/restart),
  накопленный в локальной переменной `session` вообще не долетает до `apply_node_output`/чекпоинтера,
  потому что нода физически не успела `return`. LangGraph/Postgres checkpointer restart начинает **весь**
  узел заново с состояния, каким оно было на входе в ноду.
- При большом количестве репозиториев (реалистично — десятки) и ~15 пунктов чек-листа на каждый это означает
  повторный запуск LLM-агента на уже честно обработанные пары `(repository, item_id)` — дорого по времени и
  деньгам, и практически не восстанавливаемо после сбоя на позднем репозитории.

## Принятые решения по архитектуре

- **Гранулярность чекпоинта = один checklist item одного репозитория.** Достигается не новым хранилищем, а
  переносом внутреннего Python-цикла на уровень графовых рёбер LangGraph — ровно тот же паттерн, что уже
  используется для `confirm_next_temporal_window`/`refresh_main_branches`
  ([graph.py:74-81](../../back/app/workflows/init_arch/graph.py#L74-L81)): отдельная conditional-routing
  функция вместо generic `_route_after_node`, self-loop и loop-back edges.
- **Персист не меняется.** `_drive_graph_stream()` уже пишет Postgres-чекпоинт и YAML-снепшот после **каждого**
  физического узла графа — значит, как только цикл станет графовыми рёбрами, per-item persist получаем
  бесплатно, без изменений в `init_arch_workflow.py`/`checkpointer.py`/`snapshot.py`.
- **Прогресс — не новое эфемерное состояние, а то, что уже есть в `session`.** Не заводим отдельную "очередь
  оставшихся item_id" в `InitArchState`. Вместо этого — две чистые доменные функции, которые на каждом входе
  в ноду **заново вычисляют**, что осталось сделать, читая только персистентные поля `RepositoryExecution`
  (`analysis_status`, `checklist_items_completed`) и `route_checklist_items()`:
  - `next_pending_repository(session) -> RepositoryExecution | None` — первый репозиторий с
    `analysis_status != "completed"`.
  - `next_pending_checklist_item(repository, *, all_checklist_item_ids) -> str | None` — первый элемент
    `route_checklist_items(repository, all_checklist_item_ids=...)`, которого нет в
    `repository.checklist_items_completed`.

  Это даёт идемпотентность "бесплатно": повторный вход в любую из двух нод после произвольного рестарта
  всегда пересчитывает актуальный "следующий шаг" от факта в `session`, а не от локальной переменной —
  никакого отдельного recovery-пути писать не нужно.
- **`StepId`/`STEP_DEFINITIONS` не меняются.** `ANALYZE_REPOSITORIES` остаётся одним логическим шагом
  (`session.current_step`, `completed_steps`, `required_previous_steps` у соседних шагов, отображение
  прогресса пользователю) — расщепляется только физическая топология графа для этого шага, аналогично тому,
  как `confirm_next_temporal_window`/`refresh_main_branches` физически являются двумя узлами, но логически
  одним "окном". Новый узел `analyze_repositories_item` не получает свой `StepId` и не попадает в
  `_LINEAR_NODES`/`STEP_DEFINITIONS` — добавляется в граф вручную.
- **Один узел = один checklist item.** Не "один узел = один репозиторий" — иначе внутри узла остаётся
  Python-цикл по items с той же проблемой на другом уровне вложенности. Оба уровня (repo/item) нужно поднять
  в граф.
- **БД:** отдельное структурированное хранилище для результатов по item здесь не заводим. Postgres-чекпоинтер
  (`AsyncPostgresSaver`, `workflow_runs.session_payload`) уже сериализует весь `WorkflowSessionRecord`
  целиком, включая `checklist_items_completed`/`analysis_status` по каждому репозиторию — как только эти
  поля обновляются построчно (per-item), они автоматически попадают в БД на каждом чекпоинте без единой
  миграции, тем же путём, что описан в
  [2026-07-21-assess-scope-domain-persistence.md](2026-07-21-assess-scope-domain-persistence.md#проблема).
  Отдельная queryable-таблица по item — возможное будущее улучшение для отчётности/observability, но не
  требуется для решения задачи восстановления, поэтому вынесена в Out of scope.

## Целевая топология графа

Было (один физический узел на StepId):

```
assess_scope_and_domains -> analyze_repositories -> interview_user
```

Станет:

```
                                   ┌─────────────────────────────┐
                                   │                              │
assess_scope_and_domains -> analyze_repositories ──(нет pending   │
                                   │   repo)──> interview_user     │
                                   │                              │
                                   └─(есть pending repo)──> analyze_repositories_item ──┐
                                                                    ▲                    │
                                                                    │(есть pending item)  │
                                                                    └────────────────────┘
                                            │(нет pending item в текущем репо — repo
                                             завершён, назад к analyze_repositories)
                                            ▼
                                    analyze_repositories
```

Оба узла разделяют стандартный error-routing паттерн `_route_after_node`/`_MAX_RETRY` (self-loop на retry,
`handle_error` после исчерпания попыток) — как и все остальные ноды графа.

## Фазы

### Фаза 0 — доменные функции выбора следующего шага `[x]`

В `domain/operations.py` (рядом с `historical_prep_is_complete`/`domain_assessment_is_complete`, по тому же
стилю — чистые функции без побочных эффектов):

```python
def next_pending_repository(session: WorkflowSessionRecord) -> RepositoryExecution | None:
    return next((repo for repo in session.repositories if repo.analysis_status != "completed"), None)


def next_pending_checklist_item(
    repository: RepositoryExecution, *, all_checklist_item_ids: list[str]
) -> str | None:
    routed_item_ids = route_checklist_items(repository, all_checklist_item_ids=all_checklist_item_ids)
    return next((item_id for item_id in routed_item_ids if item_id not in repository.checklist_items_completed), None)
```

Экспортировать через `domain/__init__.py` рядом с `route_checklist_items`.

Тесты в `test_operations.py`: `next_pending_repository` — пустой список репозиториев, все `completed`, есть
один `pending`/`in_progress` в середине списка. `next_pending_checklist_item` — пустой routed-список
(`NO_SIGNAL` severity), все routed-пункты уже в `checklist_items_completed`, часть пунктов ещё не
выполнена (порядок должен совпадать с порядком `route_checklist_items`, не с порядком
`checklist_items_completed`).

**Мини-отчёт**: реализовано как задумано, обе функции — в `domain/operations.py` рядом с
`mark_checklist_item`/перед `set_domain_assessment`, экспортированы через `domain/__init__.py`. Единственное
уточнение против плана: `operations.py` до этой фазы не импортировал ничего из `signal_routing.py` — добавлен
прямой импорт `route_checklist_items`; циклической зависимости нет (`signal_routing.py` импортирует только из
`models.py`). Тесты: `test_next_pending_repository_returns_none_without_repositories`,
`test_next_pending_repository_skips_completed_and_returns_first_pending`,
`test_next_pending_repository_returns_none_when_all_completed`,
`test_next_pending_checklist_item_returns_first_routed_item_not_yet_completed`,
`test_next_pending_checklist_item_returns_none_when_all_routed_items_completed`,
`test_next_pending_checklist_item_narrows_to_routed_subset_on_no_signal_repository` (проверяет, что при
`NO_SIGNAL`-severity функция не возвращает пункты вне узкого routed-подмножества) — все зелёные, 35 тестов в
`test_operations.py` (было 29), 0 регрессий. `ruff check`/`ruff format --check` на изменённых файлах чисты.

### Фаза 1 — разбить `node_analyze_repositories` на две ноды `[x]`

В `nodes.py` заменить текущее тело функции на две функции.

**`node_analyze_repositories`** (repo-loop entry; сохраняет имя = `StepId.ANALYZE_REPOSITORIES.value`, остаётся
точкой входа в шаг и точкой возврата после завершения каждого репозитория):

```python
async def node_analyze_repositories(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.analyze_repositories", workflow_id=state["session"].session_id)
    guard_service = get_guard_service()
    knowledge_service = get_knowledge_artifact_service()
    session = state["session"]
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.ANALYZE_REPOSITORIES)
    try:
        repository = next_pending_repository(session)
        if repository is None:
            if session.open_questions:
                sync_result = await knowledge_service.sync_open_questions(session, arch_repo_dir=state["arch_repo_dir"])
                session = sync_result.session
            advance_result = await guard_service.advance_step(
                session, StepId.INTERVIEW_USER, progress_file_path=state["progress_file_path"]
            )
            _record_workflow_event(
                state,
                EventType.WORKFLOW_STEP_COMPLETED,
                step_id=StepId.ANALYZE_REPOSITORIES,
                next_step=advance_result.session.current_step.value,
            )
            return _session_update_payload(advance_result.session, last_guard_output=advance_result.bridge_output)
        if repository.analysis_status == "pending":
            start_result = await guard_service.start_repository(
                session, repository_name=repository.repository_name, progress_file_path=state["progress_file_path"]
            )
            session = start_result.session
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(state, EventType.WORKFLOW_STEP_FAILED, step_id=StepId.ANALYZE_REPOSITORIES, error=str(exc))
        return {"session": session, "step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    return _session_update_payload(session)
```

**`node_analyze_repositories_item`** (обрабатывает ровно один checklist item текущего `in_progress`
репозитория; при отсутствии оставшихся пунктов — закрывает репозиторий):

```python
async def node_analyze_repositories_item(state: InitArchState) -> dict[str, typing.Any]:
    guard_service = get_guard_service()
    session = state["session"]
    repository = next((repo for repo in session.repositories if repo.analysis_status == "in_progress"), None)
    if repository is None:
        raise DomainOperationError("analyze_repositories_item: no in-progress repository in session")
    llm_result = None
    try:
        item_id = next_pending_checklist_item(repository, all_checklist_item_ids=list(CHECKLIST_ITEM_TO_REFERENCE))
        if item_id is None:
            complete_result = await guard_service.complete_repository(
                session, repository_name=repository.repository_name, progress_file_path=state["progress_file_path"]
            )
            return _session_update_payload(complete_result.session, last_guard_output=complete_result.bridge_output)

        _record_workflow_event(
            state,
            EventType.DIFF_SIGNAL_ROUTED,
            step_id=StepId.ANALYZE_REPOSITORIES,
            repository_name=repository.repository_name,
            diff_severity=classify_diff_severity(repository).value,
            routed_items="1",
            total_items=str(len(CHECKLIST_ITEM_TO_REFERENCE)),
        )
        llm_result = await _run_step_worker(
            {**state, "session": session},
            StepId.ANALYZE_REPOSITORIES,
            task_kind=LlmTaskKind.REPOSITORY_CHECKLIST_ITEM,
            checklist_item_id=item_id,
            repository_name=repository.repository_name,
        )
        item_result = await guard_service.complete_repository_item(
            session, repository_name=repository.repository_name, item_id=item_id, progress_file_path=state["progress_file_path"]
        )
        session = item_result.session
        if llm_result.open_questions_found:
            question_result = await guard_service.register_open_questions(
                session,
                question_texts=llm_result.open_questions_found,
                repository_name=repository.repository_name,
                progress_file_path=state["progress_file_path"],
            )
            session = question_result.session
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(state, EventType.WORKFLOW_STEP_FAILED, step_id=StepId.ANALYZE_REPOSITORIES, error=str(exc))
        return {"session": session, "step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    return _session_update_payload(session, last_llm_result=llm_result, last_guard_output=item_result.bridge_output)
```

Замечания к реализации (проверить по месту, не додумывать молча, если реальный код разойдётся):

- `_session_update_payload` уже сама вычисляет `current_repo_name` по `analysis_status == "in_progress"`
  ([nodes.py:46-67](../../back/app/workflows/init_arch/nodes.py#L46-L67)) — переиспользуется без изменений
  в обеих новых нодах.
- В except-ветке обеих нод возвращаем `"session"` (партиальный прогресс) по аналогии с фиксом из
  [2026-07-21-assess-scope-domain-persistence.md](2026-07-21-assess-scope-domain-persistence.md#дополнение-2026-07-21-идемпотентный-retry-вместо-повтора-всего-цикла) —
  здесь это менее критично (узел обрабатывает один item), но `start_repository`/`complete_repository_item`/
  `register_open_questions` внутри одного вызова узла всё ещё могут произойти частично до эксепшена, и
  теперь это дёшево сохранить.
- Старый импорт `route_checklist_items` в `nodes.py` заменяется на `next_pending_checklist_item`/
  `next_pending_repository`; сам `route_checklist_items` остаётся в `signal_routing.py` без изменений —
  используется только внутри новой доменной функции.

Тесты в `test_nodes.py`:

- `node_analyze_repositories`: нет pending-репозиториев → advance к `interview_user` (+ sync open questions,
  если есть); есть pending `pending`-репозиторий → `start_repository` вызван, `session` возвращён без
  advance; есть `in_progress`-репозиторий (resume после падения item-ноды) → `start_repository` **не**
  вызывается повторно.
- `node_analyze_repositories_item`: happy path на одном item (LLM вызван с правильным `checklist_item_id`/
  `repository_name`, `complete_repository_item` вызван, `open_questions_found` регистрируются); последний
  item репозитория → `complete_repository` вызван вместо LLM-вызова; отсутствие `in_progress`-репозитория в
  `session` → `DomainOperationError`; retry сохраняет частичный `session`.

**Мини-отчёт**: реализовано с одним отклонением от черновика в спеке. Проверку "нет in-progress репозитория"
(`_require_in_progress_repository`) пришлось вынести в отдельную функцию и вызывать **внутри** `try`, а не
`raise` до входа в `try` (как было в черновике псевдокода этой фазы) — иначе исключение вылетало бы наружу
необработанным, а не попадало в стандартный путь `step_error`/`retry_count`, как у всех остальных нод файла
(включая уже существующий `_require_domain_assessment_complete` в `node_assess_scope_and_domains`, который
именно поэтому тоже вызывается внутри `try`, а не до него). Без этого падение репо-луп ноды с багом (например,
переход в item-ноду без предварительного `start_repository`) уронило бы весь граф хардкрашем вместо
стандартного retry/`handle_error`. Остальное — как задумано: `next_pending_repository`/
`next_pending_checklist_item` из Фазы 0 используются вместо старого прямого импорта `route_checklist_items`
(сам `route_checklist_items` больше не импортируется в `nodes.py`). Тесты (13 новых взамен 2 старых, которые
тестировали цикл целиком): 5 на `node_analyze_repositories` (advance без pending, sync open questions перед
advance, старт `pending`-репозитория без advance, resume `in_progress`-репозитория без повторного
`start_repository`, partial-session на ошибке), 8 на `node_analyze_repositories_item` (happy path на одном
item, регистрация `open_questions_found`, `NO_SIGNAL`-роутинг сузивший чек-лист до одного пункта, завершение
репозитория при пустом остатке пунктов, `step_error` вместо raise при отсутствии in-progress репозитория,
partial-session на ошибке). Полный сьют: 597 passed, 1 xfailed, 0 регрессий. `ruff check`/`ruff format --check`
чисты на изменённых файлах.

### Фаза 2 — топология графа `[x]`

В `graph.py`:

- Добавить `node_analyze_repositories_item` в импорт из `nodes.py`.
- В `build_graph()`: для `node_name == "analyze_repositories"` в основном цикле по `_LINEAR_NODES[:-1]`
  использовать не generic `_route_after_node`, а новую `_route_after_analyze_repositories` — по тому же
  паттерну, что уже есть для `_CONFIRM_NEXT_WINDOW_NODE_NAME`
  ([graph.py:99-104](../../back/app/workflows/init_arch/graph.py#L99-L104)).
- После основного цикла — вручную добавить узел `analyze_repositories_item` (`graph.add_node(...)`) и его
  conditional edges (`_route_after_analyze_repositories_item`). Этот узел **не входит** в `_LINEAR_NODES`.

```python
_ANALYZE_REPOSITORIES_NODE_NAME: typing.Final[str] = StepId.ANALYZE_REPOSITORIES.value
_ANALYZE_REPOSITORIES_ITEM_NODE_NAME: typing.Final[str] = "analyze_repositories_item"


def _route_after_analyze_repositories(state: InitArchState) -> str:
    if state.get("step_error"):
        if state.get("retry_count", 0) < _MAX_RETRY:
            return _ANALYZE_REPOSITORIES_NODE_NAME
        return "handle_error"
    if state["session"].current_step is StepId.INTERVIEW_USER:
        return StepId.INTERVIEW_USER.value
    return _ANALYZE_REPOSITORIES_ITEM_NODE_NAME


def _route_after_analyze_repositories_item(state: InitArchState) -> str:
    if state.get("step_error"):
        if state.get("retry_count", 0) < _MAX_RETRY:
            return _ANALYZE_REPOSITORIES_ITEM_NODE_NAME
        return "handle_error"
    return _ANALYZE_REPOSITORIES_NODE_NAME
```

В `build_graph()`:

```python
for node_name, node_fn in _LINEAR_NODES:
    graph.add_node(node_name, node_fn)
graph.add_node(_ANALYZE_REPOSITORIES_ITEM_NODE_NAME, node_analyze_repositories_item)
graph.add_node("handle_error", node_handle_error)

...

for node_name, _ in _LINEAR_NODES[:-1]:
    if node_name == _CONFIRM_NEXT_WINDOW_NODE_NAME:
        graph.add_conditional_edges(node_name, _route_after_confirm_next_temporal_window)
    elif node_name == _ANALYZE_REPOSITORIES_NODE_NAME:
        graph.add_conditional_edges(node_name, _route_after_analyze_repositories)
    else:
        graph.add_conditional_edges(node_name, _route_after_node(node_name))

graph.add_conditional_edges(_ANALYZE_REPOSITORIES_ITEM_NODE_NAME, _route_after_analyze_repositories_item)
```

Важно: `_route_after_node` строится по индексу узла в `_LINEAR_NODES` (`node_idx + 1`) — так как
`analyze_repositories` больше не роутится через неё, ничего пересчитывать для соседних узлов не требуется;
`assess_scope_and_domains -> analyze_repositories` (вход) и `interview_user` как следующий шаг после generic
`_route_after_node("assess_scope_and_domains")` остаются как есть — они смотрят только на позицию
`analyze_repositories` в списке, а не на его внутреннюю routing-функцию.

Тесты в `test_graph.py` (или создать, если для этого файла ещё нет отдельного теста топологии — проверить
по факту): граф компилируется без ошибок (`compile_graph()`), у `analyze_repositories`/
`analyze_repositories_item` есть узлы с ожидаемыми именами.

**Мини-отчёт**: реализовано без отклонений от плана. `test_graph.py` уже существовал (топология уже
покрывалась тестами `test_build_graph_has_all_nodes`/`test_route_after_*`) — добавлена
`"analyze_repositories_item"` в список `expected_nodes` и 7 новых тестов на обе новые routing-функции:
`_route_after_analyze_repositories` (переход в item-ноду, когда `current_step` остаётся
`ANALYZE_REPOSITORIES`; переход в `interview_user`, когда шаг продвинулся; retry/`handle_error` на ошибке) и
`_route_after_analyze_repositories_item` (loop-back в repo-loop ноду; retry/`handle_error` на ошибке). Полный
сьют: 604 passed, 1 xfailed, 0 регрессий (было 597 после Фазы 1). `ruff check`/`ruff format --check` чисты.

### Фаза 3 — интеграционная проверка сквозного сценария `[x]`

Через `graph.astream`/`graph.ainvoke` (или существующий гарнесс для end-to-end тестов workflow, если он уже
есть в `tests/api/rpc/test_execute.py` или `tests/workflows/init_arch/` — проверить перед написанием, не
дублировать инфраструктуру):

- Сессия с 2 репозиториями × 3 routed checklist items. Прогнать до конца `analyze_repositories` (до входа в
  `interview_user`). Убедиться, что граф реально проходит через 2×3 = 6 отдельных вызовов
  `analyze_repositories_item` + 2 входа в `analyze_repositories` между репозиториями (через мокнутый
  `_run_step_worker`/`LlmWorkerService`, считающий количество вызовов и полученные `checklist_item_id`).
- Проверить, что `graph.aget_state(config)` (или прямой доступ к чекпоинтам) после **каждого** отдельного
  `analyze_repositories_item`-вызова содержит уже обновлённый `checklist_items_completed` — то есть per-item
  чекпоинт реально происходит, а не только по завершении всего шага.
- Смоделировать падение на 4-м из 6 item-вызовов (мок бросает исключение на конкретном вызове) → после этого
  запустить граф заново с того же `thread_id`/чекпоинта → убедиться, что LLM-вызовы для первых 3 item
  **не повторяются** (мок фиксирует уникальные `(repository_name, item_id)`, для которых был вызван), а
  повторяется только 4-й.

**Мини-отчёт**: реализовано в новом файле `tests/workflows/init_arch/test_analyze_repositories_integration.py`,
с одним сознательным отклонением от черновика сценария падения. Вместо симуляции падения через "мок бросает
исключение на 4-м вызове" (это тестировало бы retry/self-loop `_route_after_analyze_repositories_item`, что
уже покрыто юнит-тестами Фазы 1/2) — падение смоделировано как **обрыв потребления `graph.astream`** после
2 из 3 item-вызовов первого репозитория (`svc-a`), с последующим повторным вызовом `graph.astream(None,
config=config)` на том же `MemorySaver`/`thread_id`. Это точнее моделирует реальный краш процесса: реальный
`_drive_graph_stream()` не оборачивает каждый `astream`-тик в try/except с ретраем изнутри одного вызова —
краш процесса просто обрывает генератор, а новый процесс переподключается к чекпоинтеру и вызывает
`astream(None, config)` заново (ровно так же, как делает `run_workflow()`). Тест `astream_after_crash`
подтверждает: до обрыва — 2 LLM-вызова, `svc-a.checklist_items_completed` длиной 2 в состоянии графа сразу
после обрыва; после «рестарта» — ещё 4 вызова (item3 `svc-a` + все 3 `svc-b`), итого ровно 6, а не 8 —
означает, что первые 2 пункта `svc-a` не переигрываются. Второй тест (`checkpoints_after_every_single_item`)
проверяет саму гранулярность: после каждого из первых 3 `analyze_repositories_item`-эвентов (все относятся к
`svc-a`, т.к. репозитории обрабатываются по очереди) чекпоинт уже содержит 1, затем 2, затем 3 завершённых
пункта — то есть прогресс виден графу «по одному пункту», а не «по репозиторию целиком». Оба теста запускают
**настоящий** `compile_graph()` + `MemorySaver` и настоящие domain/guard-операции; мокается только
`LlmWorkerService.run_task` (внешний LLM CLI) и `CHECKLIST_ITEM_TO_REFERENCE` сужен до 3 пунктов, чтобы не
плодить лишние вызовы. Вход в граф — через связку `graph.aupdate_state(config, values,
as_node="assess_scope_and_domains")` и `astream(None, ...)`, тот же приём, что использует production
`run_workflow(..., as_node=...)` для resume — не пришлось гонять реальные
`define_scope`/`clone_repositories`/`historical_prep` и т.п. Оба теста
намеренно останавливают потребление `astream`, как только `session.current_step` становится
`INTERVIEW_USER` — иначе граф продолжает реально исполнять `refine_features`/`run_knowledge_lint`/etc, для
которых пришлось бы мокать ещё несколько сервисов, не относящихся к предмету этой спеки. Побочный эффект:
`WorkflowAuditService.record()` в фоне честно пытается персистить события в Postgres и получает
`ForeignKeyViolationError` (нет строки в `conversations` для тестового `session_id`) — это ловится
существующим `except Exception` внутри `_persist_event` и только логируется предупреждением, тесты не падают;
отдельно не подавлялось, т.к. это pre-existing поведение audit-сервиса, не относящееся к этой задаче. Полный
сьют: 606 passed, 1 xfailed, 0 регрессий (было 604 после Фазы 2). `ruff check`/`ruff format --check` чисты.

### Фаза 4 — актуализация документации `[x]`

- `init-graph-reference.md` — нода 8 (`analyze_repositories`): переписать топологию (repo-loop node + item
  node, conditional edges, per-item чекпоинт), убрать описание как единого Python-цикла внутри одной ноды.
- Эта спека — статус `done` после Фаз 0-4.

**Мини-отчёт**: `init-graph-reference.md` обновлён в нескольких местах. (1) mermaid-диаграмма (строки 28-29
исходного файла) — вместо одного узла `analyze[analyze_repositories\nLLM x N]` теперь два узла с явными
рёбрами self-loop/loop-back (`analyzeRepo`/`analyzeItem`), отражающими реальную топологию из Фазы 2. (2)
Раздел «Нода 8» переписан целиком: заголовок теперь называет оба физических узла, добавлен абзац с ссылкой на
эту спеку и кратким изложением исходной проблемы (persist только на границах узлов), отдельные абзацы на
`analyze_repositories` (repo-loop entry) и `analyze_repositories_item` (обработка одного пункта). (3)
Обновлены «Файлы» (`collect_worker_artifacts` теперь не вызывается именно в `analyze_repositories_item`),
«В базе» (`DIFF_SIGNAL_ROUTED` эмитится из item-ноды), «На выходе» (advance на `interview_user` делает только
repo-loop нода), «При ошибке» (переписан целиком — вместо "один try/except на весь цикл, retry повторяет всё"
теперь "свой try/except и свой retry-бюджет на каждый узел, соседние уже зачекпоинченные пункты/репозитории
не переигрываются", со ссылкой на интеграционные тесты Фазы 3) и «Логи и что видит пользователь». (4) Заодно
поправлена соседняя устаревшая формулировка в ноде 7 (`assess_scope_and_domains`): фраза «В отличие от
`analyze_repositories`, retry здесь идемпотентен» была верна только до этой задачи — теперь `analyze_repositories`
идемпотентен ещё более гранулярно (на уровне графового чекпоинта, а не только за счёт партиального `session`
внутри одного узла), поэтому сравнение переформулировано как «идемпотентен на уровне репозитория внутри
одного узла, но не на уровне графового чекпоинта» с явной отсылкой к ноде 8. (5) В «Известные несостыковки»
пункт 4 — `analyze_repositories` заменён на `analyze_repositories_item` (это теперь физическое имя ноды, где
реально живёт LLM-вызов и где `collect_worker_artifacts` по-прежнему не вызывается). Полный сьют после всех
правок кода (без изменений в этой фазе, только документация): 606 passed, 1 xfailed, 0 регрессий.

## Тестирование (сквозной критерий)

Дельта покрывается тестами не хуже соседних доменных функций/нод (`historical_prep_is_complete`,
`assess_scope_and_domains` — см. [2026-07-21-assess-scope-domain-persistence.md](2026-07-21-assess-scope-domain-persistence.md#тестирование-сквозной-критерий)):
happy path, retry на частичном прогрессе, resume после симулированного падения по чекпоинту, 0 регрессий в
существующем сьюте. Цель по покрытию дельты — 100% (`pylines`-гайдлайн проекта).

## Критерии готовности

- `node_analyze_repositories`/`node_analyze_repositories_item` — два отдельных узла графа; каждый вызов LLM
  на один checklist item происходит в отдельном узле, после которого граф обязательно возвращает управление
  `_drive_graph_stream()`.
- После каждого `analyze_repositories_item` Postgres-чекпоинт и YAML progress-снепшот содержат обновлённый
  `checklist_items_completed` для соответствующего репозитория (без изменений в `checkpointer.py`/
  `snapshot.py` — только за счёт того, что это теперь отдельные узлы).
- Симулированный краш между двумя item-вызовами → рестарт с чекпоинта повторяет только необработанные пары
  `(repository, item_id)`, не весь шаг заново.
- `StepId.ANALYZE_REPOSITORIES`/`STEP_DEFINITIONS`/`session.current_step` ведут себя как раньше извне шага —
  расщепление не видно снаружи (progress bridge, `required_previous_steps` соседних шагов).
- Все существующие тесты на `analyze_repositories` (`test_nodes.py`) переписаны под новую пару нод, зелёные,
  0 регрессий в остальном сьюте.

## Out of scope

- Отдельная queryable-таблица в БД для результатов по checklist item (сверх того, что уже даёт Postgres
  checkpointer через `session_payload`) — возможное будущее улучшение для отчётности/observability, не
  требуется для решения задачи восстановления.
- Аналогичное расщепление других шагов с внутренними циклами по репозиториям (`refresh_main_branches`,
  `plan_repository_order`, `assess_scope_and_domains`) — вне скоупа этой задачи; каждый может требовать
  отдельного разбора (`assess_scope_and_domains` уже частично идемпотентен на уровне репозитория, см.
  «Дополнение» в [2026-07-21-assess-scope-domain-persistence.md](2026-07-21-assess-scope-domain-persistence.md#дополнение-2026-07-21-идемпотентный-retry-вместо-повтора-всего-цикла),
  но не на уровне отдельного LLM-вызова внутри репозитория, т.к. там он ровно один).
- Параллельное выполнение репозиториев/items (`Send`-API LangGraph для map-reduce) — эта спека делает цикл
  последовательным на уровне графа (как и был последовательным Python-цикл), не меняя порядок выполнения;
  распараллеливание — отдельная задача с отдельными компромиссами (rate-limit LLM CLI, порядок in `notes`).
