# Autofix-цикл для шагов 11 (`build_navigation_index`) и 12 (`run_knowledge_lint`)

**Цель:** сейчас обе ноды — чистый детерминированный Python
(`knowledge_service.compile_navigation()`/`knowledge_service.lint_knowledge()`), они никогда не строят промпт
и не вызывают LLM-агента (подтверждено по коду: `node_build_navigation_index`/`node_run_knowledge_lint` в
[nodes.py:821-892](../../back/app/workflows/init_arch/nodes.py#L821-L892) не вызывают `_run_step_worker` ни
разу). Из-за этого retry на blocking-проблему в `run_knowledge_lint` сегодня бесполезен: `lint_knowledge()`
кидает `ValueError` при `ERROR:`-issues, нода уходит в `step_error` → граф перезапускает **ту же самую** ноду
до 3 раз ([graph.py:63-75](../../back/app/workflows/init_arch/graph.py#L63-L75)), но между попытками ничего не
меняется в файлах — три попытки гарантированно дают три одинаковых провала, после чего `handle_error`. Нужно:
подключить реальный LLM-вызов к обеим нодам так, чтобы (1) сначала выполнялась существующая детерминированная
проверка, (2) если она находит blocking-проблему — LLM чинил конкретно найденные проблемы в исходных
knowledge-артефактах, (3) проверка перезапускалась над обновлёнными файлами, и только если проблема осталась —
шаг считался реально упавшим (с текстом ошибки, отличимым от инфраструктурного сбоя).

**Статус:** done. Все фазы 1-5 реализованы, документация обновлена.

## Проблема

### 1. Retry на `run_knowledge_lint` сегодня — гарантированный тройной провал без шанса на исправление

`KnowledgeArtifactService.lint_knowledge()` ([knowledge.py:223-245](../../back/app/workflows/init_arch/knowledge.py#L223-L245)):

```python
issues = run_knowledge_lint(pathlib.Path(arch_repo_dir))
blocking_issues = [issue for issue in issues if issue.startswith("ERROR:")]
if blocking_issues:
    raise ValueError("knowledge lint failed: " + "; ".join(blocking_issues))
```

`node_run_knowledge_lint` оборачивает это в общий `try/except Exception` →
`{"step_error": str(exc), "retry_count": ... + 1}` — тот же паттерн, что и во всех остальных нодах
([nodes.py:858-892](../../back/app/workflows/init_arch/nodes.py#L858-L892)). `_route_after_node`
([graph.py:63-75](../../back/app/workflows/init_arch/graph.py#L63-L75)) на `step_error` возвращает **то же имя
ноды** (не следующий шаг), пока `retry_count < 3`. Но `run_knowledge_lint()` — чистая функция от содержимого
`arch_repo_dir`: если содержимое не менялось между вызовами (а оно не меняется — никто не пишет файлы между
retry), три повторных вызова дают идентичный список issues и идентичный `ValueError`. Единственный сегодняшний
способ починить blocking-проблему — вручную вернуться на более ранний LLM-шаг (`refine_features`/
`interview_user`), что реально и предполагается текстом
[knowledge-workflow.md](../../back/app/workflows/shared_assets/init_arch/references/knowledge-workflow.md#L152-L158)
(«Ожидаемый remediation path» пункт 1), но граф не даёт для этого автоматического пути назад — только ручное
вмешательство после `handle_error`.

### 2. `STEP_TO_REFERENCE` для обеих нод формально не пуст, но мёртв

`STEP_TO_REFERENCE["build_navigation_index"]` и `STEP_TO_REFERENCE["run_knowledge_lint"]`
([prompts.py:48-49](../../back/app/workflows/init_arch/prompts.py#L48-L49)) указывают на
[knowledge-workflow.md](../../back/app/workflows/shared_assets/init_arch/references/knowledge-workflow.md), но
`build_step_prompt()` для этих шагов никогда не вызывается — сам файл прямо документирует свою мёртвость
(«этот текст сейчас никогда не попадает в контекст агента», строки 3-9). Файл уже содержит целевую модель
(«Compile loop для wiki-режима», «Как это соотносится с LLM-Wiki паттерном» — раздел, который, по всей
видимости, и имел в виду пользователь под «wiki llm»): compile/evaluate/refine цикл, где «ошибки структуры и
пропуски фиксируются отдельно и устраняются итеративно». Сегодня это описание будущего, не текущее поведение.

### 3. У `build_navigation_index` вообще нет понятия «ошибка»

`compile_navigation()` ([knowledge.py:145-178](../../back/app/workflows/init_arch/knowledge.py#L145-L178))
считает `compile_knowledge_graph()`, пишет `wiki/index.md`/`wiki/maps/compile-report.md` и **всегда** успешно
завершается (кроме IO-ошибок) — даже если `compile_result.unresolved_references` не пуст или frontmatter/
related coverage ниже порога (`MIN_FRONTMATTER_COVERAGE`/`MIN_RELATED_COVERAGE` в
[knowledge_runtime.py:86-87](../../back/app/workflows/init_arch/knowledge_runtime.py#L86-L87)). Эти же самые
метрики уже дают `ERROR:`-issues в `_lint_compile_quality_gates`/`_lint_missing_related_references`
([knowledge_runtime.py:826-830](../../back/app/workflows/init_arch/knowledge_runtime.py#L826-L830),
[knowledge_runtime.py:918-943](../../back/app/workflows/init_arch/knowledge_runtime.py#L918-L943)), но только
когда их считает `run_knowledge_lint()` на шаге 12 — шаг 11 их вычисляет (внутри `compile_knowledge_graph`),
но не смотрит на них.

## Принятые решения по архитектуре

- **Не создавать новые физические узлы графа.** Обе ноды остаются `build_navigation_index`/
  `run_knowledge_lint` в текущих позициях графа; меняется только их внутреннее тело (`nodes.py`) — по аналогии
  с тем, как в предыдущей задаче
  ([2026-07-22-mandatory-per-repo-feature-sync-and-final-feature-review.md](2026-07-22-mandatory-per-repo-feature-sync-and-final-feature-review.md))
  расширение поведения решалось без изменения топологии `graph.py`.
- **Единая точка вычисления «blocking-подмножества» для графового уровня, переиспользуемая обеими нодами.**
  Новая публичная функция в `knowledge_runtime.py`, например `graph_blocking_issues(compile_result:
  CompileResult) -> list[str]`, реализованная как объединение уже существующих `_lint_missing_related_references`
  и `_lint_compile_quality_gates` (обе уже `ERROR:`-only, без переименования порогов). И `compile_navigation()`
  (шаг 11), и `lint_knowledge()` (шаг 12, через `_lint_graph_awareness`) вызывают её через один и тот же путь —
  пороги (`MIN_FRONTMATTER_COVERAGE`/`MIN_RELATED_COVERAGE`) не дублируются в двух местах.
- **`KnowledgeArtifactResult.lint_issues` (уже существует, сейчас используется только `lint_knowledge()`)
  становится общим каналом для обеих нод.** `compile_navigation()` дополнительно возвращает в этом поле
  blocking-подмножество, вычисленное по своему `compile_result`, не вводя новых полей модели.
- **`lint_knowledge()` больше не кидает `ValueError` сама.** Раньше это был единственный вызывающий код
  (проверено — единственный продакшн-вызов в [nodes.py:868](../../back/app/workflows/init_arch/nodes.py#L868)),
  так что смена контракта безопасна и локальна. Метод возвращает `KnowledgeArtifactResult(lint_issues=issues,
  ...)` всегда (blocking и non-blocking вперемешку, как и весь список `run_knowledge_lint()` сегодня); решение
  «raise или нет» переезжает в `node_run_knowledge_lint`, где оно и должно приниматься — там же, где будет
  решение «звать LLM или нет».
- **Одна попытка автофикса на один вызов ноды; переиспользуем существующий retry графа (`_MAX_RETRY=3`,
  [graph.py:30](../../back/app/workflows/init_arch/graph.py#L30)) вместо нового счётчика.** Внутри одного
  вызова ноды: проверка → (если blocking) один LLM-вызов на исправление → одна повторная проверка. Если после
  этого всё ещё blocking — нода поднимает исключение как раньше, и `_route_after_node` перезапускает **всю**
  ноду целиком (проверка → фикс → проверка заново) до 3 раз суммарно. В отличие от сегодняшнего поведения, при
  каждом таком графовом retry файлы уже реально меняются между попытками (LLM что-то поправил), поэтому retry
  перестаёт быть гарантированно бесполезным — это устраняет проблему №1 без единой новой structure в графе.
- **Новый `LlmTaskKind.KNOWLEDGE_LINT_AUTOFIX`**, а не переиспользование существующего (но фактически нигде не
  используемого в проде) `LlmTaskKind.KNOWLEDGE_SYNTHESIS` — чтобы `LLM_TASK_*` audit-события автофикса были
  однозначно отличимы в логах/SSE от обычных шаговых LLM-вызовов и от `INTERVIEW_RECONCILIATION`/
  `REPOSITORY_CHECKLIST_ITEM`.
- **Данные о найденных issues передаются в промпт явным параметром, а не через `InitArchState`.** Расширяются
  сигнатуры `_build_task_request`/`_run_step_worker`/`build_step_prompt` необязательным параметром (например,
  `autofix_findings: list[str] | None = None`), по аналогии с тем, как уже передаются `checklist_item_id`/
  `repository_name` — не персистентные, транзитные для одного вызова данные. `InitArchState`
  ([state.py](../../back/app/workflows/init_arch/state.py)) не меняется — избегаем вопроса совместимости
  чекпоинтов LangGraph при добавлении нового persisted-поля состояния для того, что по сути является
  одноразовым runtime-контекстом одного вызова.
- **В промпт автофикса передаётся только blocking-подмножество (issues, начинающиеся с `ERROR:`), не
  `WARN:`/`DEBT:`.** Non-blocking сигналы (orphan pages, stale low-confidence pages, repository/domain
  conflicts, отсутствие фичи в индексе) остаются информационными, как сегодня — LLM их не трогает
  автоматически. Это осознанное ограничение blast radius автофикса: `WARN:`/`DEBT:` часто требуют человеческого
  суждения (например, «эта страница осознанно не связана ни с чем» — не баг), а не текстового фикса.
- **`STEP_TO_REFERENCE["build_navigation_index"]`/`["run_knowledge_lint"]` не меняются** (по-прежнему указывают
  на `knowledge-workflow.md`) — вместо удаления мёртвой записи (что предлагалось как альтернатива в прошлом
  анализе) файл наконец получает реальное содержимое промпта: новый раздел с конкретной инструкцией для
  автофикс-вызова (какие файлы трогать, чего не трогать, как оформить `completed_actions`/`created_artifacts`
  в стандартном JSON-отчёте). Существующие разделы файла («Compile loop», «LLM-Wiki паттерн», «Ожидаемый
  remediation path») переписываются so as to отражать, что автофикс теперь реально существует, а не только
  «на предыдущих шагах».
- **Явно различимое сообщение об ошибке для «issue пережила автофикс».** Раньше `ValueError("knowledge lint
  failed: ...")` неотличим на уровне графа от инфраструктурного сбоя (эта проблема отдельно зафиксирована в
  [init-graph-reference.md](../workflows/init-graph-reference.md#L711-L715) для шага 12). В рамках этой задачи
  вводится отдельный префикс для этого конкретного случая, например
  `"KNOWLEDGE_LINT_BLOCKED_AFTER_AUTOFIX: ..."`/`"KNOWLEDGE_COMPILE_BLOCKED_AFTER_AUTOFIX: ..."`, чтобы в
  audit-логе и в SSE `step_failed` было видно: это content-проблема, которую LLM не смог решить, а не
  инфраструктурная ошибка. Общий механизм `try/except → step_error → retry` не меняется — меняется только
  текст сообщения в этом одном конкретном пути.
- **`StepDefinition.uses_llm_worker` для `BUILD_NAVIGATION_INDEX`/`RUN_KNOWLEDGE_LINT`
  ([steps.py](../../back/app/workflows/init_arch/domain/steps.py)) отражает новую реальность.** Сегодня
  `BUILD_NAVIGATION_INDEX` уже задекларирован как `uses_llm_worker=True` (значение по умолчанию, не
  переопределено) — расходится с фактическим поведением (LLM не вызывается никогда). После этой задачи оба шага
  реально **иногда** используют LLM-воркер — `uses_llm_worker=True` для обоих становится точным (не
  переопределяем в `False`), с явным комментарием в коде, что вызов условный (только при blocking-issues).
  Никаких мест в проде, читающих это поле рантаймом, не найдено (grep по `arch-docs/back` и по TS/TSX в
  `arch-docs/e2e`/фронтенде — 0 совпадений вне `steps.py`/тестов), так что смена значения не меняет поведение
  графа, только точность метаданных.

## Последствия и граничные кейсы

1. **Дрифт `wiki/index.md`/`wiki/maps/compile-report.md` после автофикса на шаге 12 — критично.**
   `_lint_wiki_compile_drift` ([knowledge_runtime.py:877-897](../../back/app/workflows/init_arch/knowledge_runtime.py#L877-L897))
   сравнивает то, что уже лежит в `wiki/index.md`/`compile-report.md`, с тем, что дал бы повторный
   `compile_knowledge_graph()`. Если автофикс шага 12 поправил `related`/frontmatter/ссылки в
   `features/*.md`/`architecture/*.md`, а `wiki/index.md` при этом не перезаписан — второй проход
   `lint_knowledge()` внутри той же ноды увидит **новую** blocking-проблему (drift), которой не было в первом
   проходе, и результат будет выглядеть как «автофикс не помог», хотя исходная проблема на самом деле решена.
   **Решение**: автофикс-путь `node_run_knowledge_lint` обязан вызвать `knowledge_service.compile_navigation()`
   заново (перезаписать оба wiki-файла) между LLM-фиксом и повторным `lint_knowledge()`. Это единственное
   жёсткое требование к порядку операций в этой задаче — тест на этот сценарий обязателен (см. «Тестирование»).
2. **Симметричный, но более лёгкий вариант того же самого — на шаге 11.** Если автофикс шага 11 поправил
   `related`/frontmatter, `compile_result` нужно пересчитать (`compile_knowledge_graph()` заново) перед вторым
   вычислением blocking-подмножества и перед финальной записью `wiki/index.md`/`compile-report.md` — иначе
   записанные файлы будут отражать **старое**, до-фикса состояние графа, и на следующем шаге `run_knowledge_lint`
   тут же поймает drift между только что записанными (устаревшими) wiki-файлами и актуальным содержимым.
3. **Стоимость и латентность там, где их раньше не было вообще.** Оба шага сегодня — чистый Python, ноль
   LLM-вызовов, доли секунды. После задачи: в худшем случае (blocking-issue не чинится с первой попытки)
   — до 3 графовых retry × (1 LLM-вызов на попытку) = до 3 дополнительных LLM CLI-вызовов на шаг на temporal-
   окно. В счастливом пути (нет blocking-issues, самый частый случай для уже линтованного репозитория) —
   стоимость не меняется: LLM не вызывается вовсе, как и сегодня. Никаких новых конфигов/лимитов на стоимость
   не вводится — переиспользуется существующий `timeout_seconds`/`_MAX_RETRY` бюджет, как у любого другого шага.
4. **Не-blocking issues намеренно не эскалируются в LLM.** См. «Принятые решения» — `WARN:`/`DEBT:` остаются
   видимыми только в compile-report/audit, не передаются в промпт автофикса. Если впоследствии понадобится
   чинить и их — это отдельная задача с отдельным риском (LLM может «почистить» то, что было осознанным
   архитектурным решением, например одиночную orphan-страницу).
5. **Незачёт при исключении, не связанном с содержимым (IO/encoding/permissions).** Новая логика проверки
   blocking-issues должна остаться строго внутри существующего `try/except Exception` каждой ноды — если
   `compile_knowledge_graph()`/`run_knowledge_lint()` бросит исключение по инфраструктурной причине (не
   `ValueError` с текстом lint-issues, а, например, `UnicodeDecodeError` на битом файле), это исключение не
   должно попадать в автофикс-ветку («issue есть — зовём LLM») — оно должно сразу уйти в стандартный
   `step_error`/retry, как и сегодня. Автофикс запускается только когда детерминированная проверка **успешно
   завершилась** и вернула непустой blocking-список, а не когда сама проверка упала.
6. **Сбой самого LLM-вызова автофикса (timeout, исчерпанный failover, невалидный JSON-ответ) не получает
   специальной обработки** — он проваливается в тот же общий `try/except`, что и всё остальное в ноде, и
   считается обычным `step_error` (без специального `..._BLOCKED_AFTER_AUTOFIX`-префикса, т.к. это не «issue
   пережила фикс», а «сам фикс не выполнился»). Различимость нужна только для случая «фикс отработал, issue
   осталась», не для «фикс не смог отработать».
7. **LLM может задеть больше файлов, чем перечислено в blocking-issues.** Промпт указывает работать только с
   файлами, упомянутыми в списке проблем, но это соглашение на уровне текста промпта, не enforced кодом (как и
   для всех остальных LLM-шагов в этом графе — нет sandboxing на уровне файловой системы сверх
   `state["arch_repo_dir"]`). Риск фиксируется как известный, митигируется только формулировкой промпта;
   `collect_worker_artifacts` всё равно зарегистрирует все реально изменённые файлы, которые вернёт агент, так
   что случайные правки не останутся невидимыми в audit-логе (`ARTIFACT_WRITTEN` на каждый).
8. **Отдельный, несинхронизированный `analysis_guard.py` в `init-repo-arch-skill/scripts/`.** Обнаружен при
   поиске параллельная реализация похожих проверок (`init-repo-arch-skill/scripts/analysis_guard.py`,
   `analysis_guard/knowledge.py`) — судя по всему, самостоятельный CLI для случаев, когда skill используется
   вне backend-оркестрации `arch-docs/back`. Эта задача её не трогает (не входит в `arch-docs/back`, вне
   области действия AGENTS.md для этого репозитория) — фиксируется как известное расхождение, аналогичное
   уже задокументированному в
   [2026-07-22-mandatory-per-repo-feature-sync-and-final-feature-review.md](2026-07-22-mandatory-per-repo-feature-sync-and-final-feature-review.md)
   для `checklist-features-and-index.md`: копии/параллельные реализации одной и той же концепции не
   синхронизированы между `arch-docs/back` и `init-repo-arch-skill`/`update-repo-arch-skill`.
9. **`lint_knowledge()` перестаёт кидать исключение — контрактное изменение публичного метода сервиса.**
   Проверено: единственный продакшн-вызывающий код — `node_run_knowledge_lint`
   ([nodes.py:868](../../back/app/workflows/init_arch/nodes.py#L868)); других вызовов в `arch-docs/back` нет.
   Существующие тесты, которые полагаются на `pytest.raises(ValueError)` вокруг `lint_knowledge()` (если такие
   есть в `test_knowledge.py`), потребуют переписывания на «возвращает `lint_issues`, включая ERROR-строки», а
   не «кидает исключение» — это ожидаемая часть Фазы 2, не побочная регрессия.
10. **Наблюдаемость: у шагов 11/12 впервые появятся `LLM_TASK_REQUESTED`/`COMPLETED`/`FAILED` события.**
    Реалтайм SSE-наблюдаемость воркфлоу (см. недавний коммит `feat(arch-docs): realtime SSE observability +
    pause/resume`) стримит эти события по мере их появления — пользователь, ранее не видевший LLM-активности на
    шагах 11/12 (они были мгновенными), при наличии blocking-issues увидит новую SSE-активность и заметную
    задержку на этих шагах. Изменений в самом SSE/observability-слое эта задача не требует (события уже
    поддержаны общей инфраструктурой `_record_workflow_event`/`LlmWorkerService`), но стоит упомянуть
    пользователю/фронтенду, что шаги 11/12 больше не гарантированно мгновенны.

## Фазы

### Фаза 1 — переиспользуемая функция blocking-подмножества графового уровня `[x]`

В `knowledge_runtime.py`: новая публичная функция (например, `graph_blocking_issues(compile_result:
CompileResult) -> list[str]`), реализованная как `_lint_missing_related_references(compile_result.unresolved_references)
+ _lint_compile_quality_gates(compile_result)` — без изменения порогов/семантики самих проверок. `_lint_graph_awareness`
(используется `run_knowledge_lint`) обновляется на вызов этой функции вместо дублирования тех же двух вызовов
inline, чтобы не было двух источников истины.

Тесты в `test_knowledge_runtime.py`: `graph_blocking_issues` возвращает те же issues, что раньше давала
inline-комбинация в `_lint_graph_awareness`, для существующих fixture-сценариев (missing related reference,
coverage ниже порога, оба случая одновременно, случай без issues).

**Мини-отчёт**: добавлена публичная функция `graph_blocking_issues(compile_result)` в
[knowledge_runtime.py](../../back/app/workflows/init_arch/knowledge_runtime.py) — объединяет
`_lint_missing_related_references(compile_result.unresolved_references)` и `_lint_compile_quality_gates(compile_result)`
без изменения порогов/текста issues. `_lint_graph_awareness` переписан на вызов `graph_blocking_issues(compile_result)`
вместо прежних двух inline-вызовов — порядок issues в общем списке изменился (blocking-подмножество теперь идёт
первым блоком, `_lint_orphan_pages`/`_lint_stale_low_confidence_pages`/`_lint_repository_domain_conflicts`/
`_lint_wiki_compile_drift` — следом), но ни один существующий тест не проверял порядок (только вхождение
подстрок через `"\n".join(issues)`), проверено явным grep по `issues[0]`/`issues[-1]` в тестовой директории —
такие проверки относятся к другим функциям, не к `_lint_graph_awareness`. В `test_knowledge_runtime.py`
добавлены два новых теста: `test_graph_blocking_issues_combines_missing_references_and_quality_gates`
(unresolved reference → issue с `missing related reference`, и quality gate ниже порога → issue с
`quality gate`, оба с префиксом `ERROR:`) и `test_graph_blocking_issues_empty_when_graph_is_clean` (пустой
`CompileResult` без документов → `[]`). Понадобился реальный (не только `TYPE_CHECKING`) импорт `pathlib.Path`
в тестовом файле — раньше он был только в `if TYPE_CHECKING` для type hints параметра `tmp_path`, новым тестам
нужен настоящий конструктор `Path("arch")`.
`pytest tests/workflows/init_arch/test_knowledge_runtime.py`: 14 passed, 0 регрессий; `ruff check`/`ruff format --check`
чисты после форматирования тестового файла.

### Фаза 2 — `KnowledgeArtifactService`: обе проверки возвращают issues вместо raise `[x]`

- `lint_knowledge()`: убрать `raise ValueError`, всегда возвращать `KnowledgeArtifactResult(lint_issues=issues,
  session=updated_session, summary=...)`. `_register_artifacts`/audit-запись (сегодня она происходит только в
  happy path, до `raise`) должна писаться независимо от наличия blocking issues — реши, пишем ли audit ДО
  проверки на blocking (текущий порядок кода делает это после), чтобы `ARTIFACT_WRITTEN`/session-обновление не
  терялось, когда есть issues, которые нода решит чинить.
- `compile_navigation()`: дополнительно вычисляет `graph_blocking_issues(compile_result)` (Фаза 1) и кладёт в
  `lint_issues` возвращаемого `KnowledgeArtifactResult` — не влияет на то, что файлы всё равно пишутся
  (сегодняшнее поведение «всегда пишем» сохраняется, blocking-issues — дополнительная информация для вызывающей
  ноды, не блокировка записи).

Тесты в `test_knowledge.py`: `lint_knowledge()` с фикстурой, дающей `ERROR:`-issue — раньше `pytest.raises`,
теперь `result.lint_issues` содержит issue, исключения нет. `compile_navigation()` с фикстурой без issues
(`lint_issues == []`) и с фикстурой, дающей unresolved reference/coverage ниже порога (`lint_issues` содержит
соответствующий `ERROR:`).

**Мини-отчёт**: `lint_knowledge()` в [knowledge.py](../../back/app/workflows/init_arch/knowledge.py) больше не
вычисляет `blocking_issues`/не кидает `ValueError` — просто возвращает `KnowledgeArtifactResult(lint_issues=issues,
...)` всегда; `summary` изменён с `"Knowledge lint passed with N issues"` на `"Knowledge lint completed with N
issues"` (текст "passed" был неточным, когда список содержит `ERROR:`). Решение raise/не raise теперь целиком у
вызывающей стороны (`node_run_knowledge_lint`, Фаза 4). `compile_navigation()` дополнительно кладёт
`lint_issues=graph_blocking_issues(compile_result)` (Фаза 1) в возвращаемый результат — запись файлов
(`wiki/index.md`/`compile-report.md`) не меняется, происходит всегда, как и раньше. В `test_knowledge.py`:
переименован `test_lint_knowledge_raises_on_blocking_issues` →
`test_lint_knowledge_returns_blocking_issues_without_raising` (тот же fixture-сценарий — пустой arch-repo без
обязательных файлов, — но теперь проверяет `result.lint_issues` вместо `pytest.raises`); обновлена проверка
текста summary в `test_valid_arch_repo_smoke_bootstrap_compile_and_lint` и
`test_lint_knowledge_returns_non_blocking_issues` (`"Knowledge lint passed"` → `"Knowledge lint completed"`);
добавлен `test_compile_navigation_surfaces_graph_blocking_issues` (feature-файл с `related` на несуществующий
файл → `compiled.lint_issues` содержит `ERROR: missing related reference ...`) и явный `assert compiled.lint_issues
== []` в существующем `test_compile_navigation_writes_compiled_index_and_report` (happy path). Единственный
продакшн-вызывающий код `lint_knowledge()` — `node_run_knowledge_lint` (подтверждено и grep'ом, и
`trace_path(function_name="lint_knowledge", direction="inbound")` через Codebase Memory) — смена контракта не
задевает никакой другой код.
`pytest tests/workflows/init_arch/test_knowledge.py`: 18 passed, 1 xfailed (тот же pre-existing xfail из
Фазы, не связанный с этой задачей). Полный `pytest tests/workflows/init_arch`: 269 passed, 1 xfailed, 0
регрессий. `ruff check`/`ruff format --check` на `knowledge.py`/`test_knowledge.py` чисты.

### Фаза 3 — промпт автофикса: `LlmTaskKind`, сигнатуры, reference-контент `[x]`

- Новый `LlmTaskKind.KNOWLEDGE_LINT_AUTOFIX = "knowledge_lint_autofix"` в
  [domain/models.py](../../back/app/workflows/init_arch/domain/models.py).
- `_build_task_request`/`_run_step_worker`/`build_step_prompt`
  ([prompts.py](../../back/app/workflows/init_arch/prompts.py)) получают необязательный параметр
  `autofix_findings: list[str] | None = None`. В `build_step_prompt` — новый блок промпта (по аналогии с
  `release_notes_block`/`domain_context_block`), например «# Найденные проблемы для исправления», рендерящий
  список issues построчно, если параметр непуст, иначе `_NOT_APPLICABLE_BLOCK`.
- [knowledge-workflow.md](../../back/app/workflows/shared_assets/init_arch/references/knowledge-workflow.md):
  обновить «Ожидаемый remediation path» и «Compile loop для wiki-режима» — они сегодня буквально говорят, что
  почини на предыдущих шагах, а compile/lint себя не запускают повторно с фиксом; заменить на описание нового
  фактического поведения (автофикс внутри самих шагов 11/12). Добавить новый раздел с конкретной инструкцией
  для LLM-вызова автофикса: работать только с файлами, упомянутыми в переданных issues; не трогать
  `wiki/index.md`/`wiki/maps/compile-report.md` напрямую (они перезаписываются механически после фикса, ручная
  правка потеряется); вернуть стандартный JSON-отчёт с `created_artifacts` = реально изменённые файлы.

Тесты: `test_models.py`/`test_prompts.py` (если есть) — новый `LlmTaskKind`, `build_step_prompt` с
`autofix_findings` рендерит блок; без параметра — `_NOT_APPLICABLE_BLOCK`.

**Мини-отчёт**: `LlmTaskKind.KNOWLEDGE_LINT_AUTOFIX = "knowledge_lint_autofix"` добавлен в
[domain/models.py](../../back/app/workflows/init_arch/domain/models.py) (уже реэкспортирован из
`domain/__init__.py` — отдельного экспорта не потребовалось, там уже есть общий `__all__` со всеми
`LlmTaskKind`-именами). В [prompts.py](../../back/app/workflows/init_arch/prompts.py): `build_step_prompt`
получил keyword-only `autofix_findings: list[str] | None = None`; новый приватный `_build_autofix_findings_block`
рендерит issues построчно (`- {finding}`) или `_NOT_APPLICABLE_BLOCK`, если параметр пуст/`None` — использован
тот же паттерн, что и у `release_notes_block`/`domain_context_block`. Новый блок промпта «# Найденные проблемы
для исправления» вставлен между «Контекст release notes» и «Reference-чеклист» (после — не до — reference,
чтобы issues шли ближе к инструкциям). Добавлена условная инструкция `autofix_instruction` (только когда
`autofix_findings` непуст) — три правила: править только упомянутые файлы, не трогать
`wiki/index.md`/`compile-report.md` напрямую. В [nodes.py](../../back/app/workflows/init_arch/nodes.py):
`_build_task_request`/`_run_step_worker` получили тот же keyword-only параметр и пробрасывают его в
`build_step_prompt` — оба потребовали `# noqa: PLR0913` (стало 6 параметров, ruff-порог 5; прецедент такого
noqa для сигнатур с keyword-only параметрами уже есть в тестовом хелпере `_doc` в `test_knowledge_runtime.py`).
[knowledge-workflow.md](../../back/app/workflows/shared_assets/init_arch/references/knowledge-workflow.md)
переписан: вводный абзац больше не утверждает, что шаги 11/12 никогда не вызывают LLM — описывает условный
вызов; «Ожидаемый remediation path» и «Compile loop для wiki-режима» переписаны под реальный автофикс-цикл
(включая упоминание `KNOWLEDGE_LINT_BLOCKED_AFTER_AUTOFIX:`/`KNOWLEDGE_COMPILE_BLOCKED_AFTER_AUTOFIX:` как
результата исчерпанных попыток — забегая вперёд на Фазу 4, т.к. текст reference и код должны говорить об одном
и том же); добавлен новый раздел «Автофикс knowledge-issues» с конкретными правилами (что трогать/не трогать,
типовые blocking issues и как их чинить, формат JSON-отчёта) — единственная часть файла, которая теперь
задумана как прямая инструкция агенту, а не описание модели для людей.
В `test_prompts.py` — два новых теста: `test_build_step_prompt_autofix_findings_not_applicable_when_absent`
(без параметра → `_NOT_APPLICABLE_BLOCK`, инструкция про «правь только упомянутые файлы» отсутствует) и
`test_build_step_prompt_autofix_findings_rendered_as_list` (issues рендерятся построчно, инструкция
присутствует). В `test_models.py` — `test_llm_task_kind_has_knowledge_lint_autofix_variant`.
`pytest tests/workflows/init_arch`: 272 passed, 1 xfailed, 0 регрессий (было 269 до этой фазы, +3 новых теста).
`ruff check`/`ruff format --check` на всех изменённых файлах чисты (потребовались `# noqa: PLR0913` на двух
функциях в `nodes.py` и перенос части текста промпта на новую строку из-за `E501`).

### Фаза 4 — `nodes.py`: цикл проверка → фикс → повторная проверка в обеих нодах `[x]`

`node_build_navigation_index`:

1. `compile_result = await knowledge_service.compile_navigation(...)`.
2. `blocking = compile_result.lint_issues`.
3. Если `blocking` непуст: `llm_result = await _run_step_worker(state, StepId.BUILD_NAVIGATION_INDEX,
   task_kind=LlmTaskKind.KNOWLEDGE_LINT_AUTOFIX, autofix_findings=blocking)` → `collect_worker_artifacts` →
   `compile_result = await knowledge_service.compile_navigation(...)` (пересчёт и перезапись файлов над
   исправленным состоянием, см. «Последствия», п. 2) → `blocking = compile_result.lint_issues`.
4. Если `blocking` всё ещё непуст — `raise ValueError("KNOWLEDGE_COMPILE_BLOCKED_AFTER_AUTOFIX: " +
   "; ".join(blocking))` (попадает в существующий `except` → `step_error`/retry).
5. Иначе — `advance_step` на `RUN_KNOWLEDGE_LINT`, как сегодня.

`node_run_knowledge_lint` — симметрично, с обязательным вызовом `compile_navigation()` между фиксом и повторным
`lint_knowledge()` (см. «Последствия», п. 1):

1. `lint_result = await knowledge_service.lint_knowledge(...)`.
2. `blocking = [issue for issue in lint_result.lint_issues if issue.startswith("ERROR:")]`.
3. Если `blocking` непуст: LLM-автофикс (`KNOWLEDGE_LINT_AUTOFIX`) → `collect_worker_artifacts` →
   `await knowledge_service.compile_navigation(...)` (обязательный ресинк wiki-файлов) →
   `lint_result = await knowledge_service.lint_knowledge(...)` заново → `blocking` пересчитывается.
4. Если `blocking` всё ещё непуст — `raise ValueError("KNOWLEDGE_LINT_BLOCKED_AFTER_AUTOFIX: " +
   "; ".join(blocking))`.
5. Иначе — `advance_step` на `VALIDATE_FINAL`, как сегодня.

`StepDefinition` для обоих шагов — комментарий, что `uses_llm_worker=True` теперь означает «условно, только
при blocking-issues», без изменения самого значения (уже `True` по умолчанию для обоих — см. «Принятые
решения»).

**Мини-отчёт**: обе ноды в [nodes.py](../../back/app/workflows/init_arch/nodes.py) переписаны точно по плану.
`node_build_navigation_index`: `compile_navigation()` → если `compile_result.lint_issues` непуст → один
`_run_step_worker(..., task_kind=KNOWLEDGE_LINT_AUTOFIX, autofix_findings=blocking_issues)` →
`collect_worker_artifacts` → повторный `compile_navigation()` (пересчёт и перезапись wiki-файлов над
исправленным состоянием) → пересчёт `blocking_issues`. `node_run_knowledge_lint`: `lint_knowledge()` → если
есть issues с `ERROR:` → тот же автофикс-вызов → `collect_worker_artifacts` → **обязательный**
`compile_navigation()` (ресинк `wiki/index.md`/`compile-report.md`, защита от drift-кейса из «Последствия»,
п. 1) → повторный `lint_knowledge()` → пересчёт `blocking_issues`. В обеих нодах решение "raise или нет"
вынесено в новую общую приватную функцию `_raise_if_blocking(prefix, blocking_issues)` — потребовалась из-за
`ruff TRY301` («abstract raise to an inner function», raise напрямую внутри `try` не приветствуется линтером);
она формирует `f"{prefix}: " + "; ".join(blocking_issues)` — `KNOWLEDGE_COMPILE_BLOCKED_AFTER_AUTOFIX`/
`KNOWLEDGE_LINT_BLOCKED_AFTER_AUTOFIX` как и планировалось. Обе ноды теперь передают `last_llm_result=llm_result`
в `_session_update_payload` (раньше не передавали, т.к. никогда не имели LLM-результата) — `llm_result`
инициализируется `None` перед `try`, чтобы happy path (без автофикса) отправлял `None`, как и весь остальной
код ожидает. `_build_task_request`/`_run_step_worker` потребовали `# noqa: PLR0913` (см. Фазу 3). В
[domain/steps.py](../../back/app/workflows/init_arch/domain/steps.py): `RUN_KNOWLEDGE_LINT` лишился
`uses_llm_worker=False` (значение стало `True` по умолчанию, как и у `BUILD_NAVIGATION_INDEX`) — оба шага
получили комментарий-пояснение, что вызов условный. Проверено (`grep`/`test_steps.py`) — ни один существующий
тест не фиксировал `uses_llm_worker is False` для `RUN_KNOWLEDGE_LINT`, регрессии нет.
Полный `pytest tests/workflows/init_arch` после этой фазы: 272 passed, 1 xfailed, 0 регрессий — все
существующие моки на `compile_navigation`/`lint_knowledge` по умолчанию возвращают `lint_issues=[]`
(`pydantic.Field(default_factory=list)`), поэтому автофикс-ветка нигде не активируется случайно, и
`llm_service.assert_not_called()` в старых тестах по-прежнему проходит. `ruff check`/`ruff format --check`
чисты после добавления `_raise_if_blocking`.

### Фаза 5 — тесты нод `[x]`

- Переписать `test_node_build_navigation_index_uses_knowledge_service_without_llm`/
  `test_node_run_knowledge_lint_uses_knowledge_service_without_llm` в `test_nodes.py` — сохранить happy-path
  вариант (`lint_issues == []` → `llm_service` не вызывается ни разу, имя теста уточнить, например `..._skips_llm_when_no_blocking_issues`).
- Новый тест «автофикс успешен»: первый `compile_navigation`/`lint_knowledge` возвращает blocking issue,
  `_run_step_worker`/`collect_worker_artifacts` мокнуты на успех, второй вызов
  `compile_navigation`/`lint_knowledge` возвращает пустой `lint_issues` → нода продвигается на следующий шаг,
  `llm_service.run_task` вызван ровно один раз с `task_kind=LlmTaskKind.KNOWLEDGE_LINT_AUTOFIX`.
- Новый тест «автофикс не решил проблему»: второй вызов проверки всё ещё возвращает blocking issue → нода
  возвращает `step_error`, начинающийся с `KNOWLEDGE_COMPILE_BLOCKED_AFTER_AUTOFIX:`/
  `KNOWLEDGE_LINT_BLOCKED_AFTER_AUTOFIX:` соответственно.
- Новый тест на порядок операций для `run_knowledge_lint`: явно проверить, что `knowledge_service.compile_navigation`
  вызывается **после** `collect_worker_artifacts` и **до** второго `lint_knowledge` (через `Mock.mock_calls`
  порядок или отдельные side_effect-счётчики) — это прямая проверка защиты от drift-кейса из «Последствия», п. 1.
- Тест на то, что исключение из самой проверки (не `ValueError` с issues, а произвольное исключение) не
  вызывает автофикс-ветку, а сразу уходит в `step_error` без вызова `llm_service` — защита от кейса №5 из
  «Последствия».

**Мини-отчёт**: в [test_nodes.py](../../back/tests/workflows/init_arch/test_nodes.py) два старых теста
(`..._uses_knowledge_service_without_llm`) переименованы в `test_node_build_navigation_index_skips_llm_when_no_blocking_issues`/
`test_node_run_knowledge_lint_skips_llm_when_no_blocking_issues` — тело не изменилось, только явный
`lint_issues=[]` в фикстуре `KnowledgeArtifactResult` для наглядности. Добавлено 6 новых тестов:
`test_node_build_navigation_index_autofix_success` (первый `compile_navigation` → blocking issue, автофикс,
`collect_worker_artifacts`, второй `compile_navigation` → чисто → шаг продвигается; проверено
`compile_navigation.await_count == 2`, `task_kind` переданного `LlmTaskRequest` — `KNOWLEDGE_LINT_AUTOFIX`);
`test_node_build_navigation_index_autofix_failure_blocks_step` (issue переживает автофикс → `step_error`
начинается с `KNOWLEDGE_COMPILE_BLOCKED_AFTER_AUTOFIX:`, `retry_count == 1`, `guard_service.advance_step` не
вызван); симметричные `test_node_run_knowledge_lint_autofix_success`/`test_node_run_knowledge_lint_autofix_failure_blocks_step`
для `run_knowledge_lint`; `test_node_run_knowledge_lint_infra_exception_skips_autofix` (не-content исключение
— `RuntimeError` — не запускает автофикс-ветку: `llm_service`/`collect_worker_artifacts` не вызваны,
`step_error` не содержит `KNOWLEDGE_LINT_BLOCKED_AFTER_AUTOFIX:` префикс, т.к. это провал самой проверки, а не
«issue пережила фикс» — прямая проверка кейса №5 и №6 из «Последствия»).
Отдельно в `test_node_run_knowledge_lint_autofix_success` — обязательная проверка порядка операций
(кейс №1 из «Последствия», drift-защита): `knowledge_service.mock_calls` должен идти строго
`["lint_knowledge", "collect_worker_artifacts", "compile_navigation", "lint_knowledge"]` — `compile_navigation`
обязан произойти между сбором артефактов автофикса и вторым lint-проходом, иначе тест падает. Также в этом
тесте проверено, что в `prompt_text` переданного `LlmTaskRequest` попадает только `ERROR:`-issue
(`features-index.md ссылается на отсутствующий файл...`), а `WARN: gap` из того же `lint_issues`-списка —
нет (фильтрация `issue.startswith("ERROR:")` в `node_run_knowledge_lint` работает как задумано).
`pytest tests/workflows/init_arch/test_nodes.py`: 50 passed (было 44 до этой фазы, +6 новых тестов, 2
переименованы). Полный `pytest tests/workflows/init_arch`: 277 passed, 1 xfailed, 0 регрессий. `ruff check`
чист сразу; `ruff format` потребовал одного автоформатирования файла (длинные строки в конструкторах
`KnowledgeArtifactResult` с длинными issue-текстами).

### Фаза 6 — актуализация документации `[x]`

[init-graph-reference.md](../workflows/init-graph-reference.md), ноды 11/12: заголовки `— не LLM` → `—
условно LLM (автофикс)`; описания «Что делает»/«LLM»/«Файлы»/«В базе»/«При ошибке»/«Логи» переписаны под
реальный check→fix→recompile→recheck цикл, со ссылкой на эту спеку. Раздел «Известные несостыковки, найденные
при разборе» — пункты 1 и 3 отмечены как (частично) исправленные (зачёркнутый текст + пояснение), пункт 1
(мёртвый `STEP_TO_REFERENCE`) закрыт полностью, пункт 3 (неотличимость lint-fail от инфра-сбоя) — частично
(текст исключения теперь с отличимым префиксом, но механизм передачи через общий `try/except` не менялся).
Эта спека — статус `done`.

**Мини-отчёт**: обновления внесены без отклонений от плана. Оба заголовка нод (11, 12) и весь описательный
текст под ними переписаны с указанием актуальных номеров строк (`nodes.py:831`/`nodes.py:891` вместо старых
`:696`/`:733`, сдвинувшихся из-за вставленного в Фазе 4 кода). В «Известные несостыковки» — пункты 1 и 3
зачёркнуты по тому же паттерну, что уже использован там для пункта 5 (`~~старый текст~~ — исправлено: ...`).
Пункт 2 (`uses_llm_worker=False` для `validate_final`, не связан с этой задачей) — не тронут, вне скоупа.
Дополнительно проверено (`grep`) — mermaid-диаграмма графа (строки 35-36) не содержит меток LLM/не-LLM по
нодам, менять её не потребовалось.

## Тестирование (сквозной критерий)

- Фаза 1 — новые/обновлённые юнит-тесты `test_knowledge_runtime.py` для `graph_blocking_issues` и то, что
  `_lint_graph_awareness` даёт идентичный результат до/после рефакторинга (регрессионный тест на неизменность
  поведения существующего полного lint).
- Фаза 2 — `test_knowledge.py`: `lint_knowledge()`/`compile_navigation()` без `pytest.raises`, проверка полей
  `lint_issues` напрямую.
- Фазы 3-4 — `test_nodes.py`/`test_prompts.py`/`test_models.py`, сценарии из Фазы 5 выше. Обязательно —
  сквозной happy-path прогон (нет blocking issues → 0 LLM-вызовов, как и сегодня) и обязательный тест на
  порядок `compile_navigation` относительно повторного `lint_knowledge`.
- Цель по покрытию дельты — 100% для изменённого Python-кода (`pylines`-гайдлайн проекта); markdown-контент
  (`knowledge-workflow.md`) не покрывается coverage-метрикой по построению.
- Прогнать полный `pytest tests/workflows/init_arch` после каждой фазы — 0 регрессий, особое внимание к
  существующим тестам, которые сегодня явно проверяют `llm_service.assert_not_called()` для этих двух нод (они
  либо переименовываются под новый happy-path сценарий, либо остаются с уточнением «когда нет blocking
  issues»).

## Критерии готовности

- `node_build_navigation_index`/`node_run_knowledge_lint` вызывают LLM-воркер **только** когда детерминированная
  проверка нашла хотя бы один `ERROR:`-issue, и не более одного раза за вызов ноды (retry сверх этого — только
  через существующий графовый `_route_after_node`, без нового счётчика).
- При успешном автофиксе wiki-навигационные файлы (`wiki/index.md`, `wiki/maps/compile-report.md`) всегда
  синхронизированы с фактическим содержимым `features/*`/`architecture/*` после фикса — drift-проверка не
  падает как побочный эффект автофикса (см. обязательный тест на порядок операций).
- Сообщение об ошибке для «blocking issue пережила автофикс» начинается с `KNOWLEDGE_COMPILE_BLOCKED_AFTER_AUTOFIX:`/
  `KNOWLEDGE_LINT_BLOCKED_AFTER_AUTOFIX:` и отличимо в audit-логе от прочих исключений в этих нодах.
- `STEP_TO_REFERENCE`-записи для обеих нод больше не мёртвые — `knowledge-workflow.md` реально попадает в
  промпт LLM-вызова автофикса, когда он происходит.
- Happy path (нет blocking issues, самый частый случай) не меняется по стоимости/латентности — 0 LLM-вызовов,
  как и сегодня; подтверждается тестом.
- `pytest tests/workflows/init_arch` — 0 регрессий; `ruff check`/`ruff format --check` чисты на изменённых
  файлах.

**Подтверждено фактическим прогоном**: все пункты выше проверены. `pytest tests/workflows/init_arch` — 277
passed, 1 xfailed (pre-existing, не связан с этой задачей), 0 регрессий (было 269 до начала работы). Полный
`pytest` по всему backend-репозиторию (`arch-docs/back`) — 677 passed, 1 xfailed, 0 регрессий. `ruff check`/
`ruff format --check` чисты на всех 11 изменённых Python-файлах (`knowledge.py`, `knowledge_runtime.py`,
`nodes.py`, `prompts.py`, `domain/models.py`, `domain/steps.py` и соответствующие тестовые файлы) — pre-existing
lint-долг в других, не тронутых этой задачей файлах репозитория (`architecture_lint.py`, `historical.py`,
`test_conversations.py`, `conftest.py`) не в скоупе и не трогался. Delta-coverage (pylines-требование 100% для
изменённого кода) подтверждён явным прогоном `pytest --cov` по всем шести изменённым модулям — единственные
непокрытые строки относятся к коду, который эта задача не меняла (проверено построчно: новые/изменённые
функции — `graph_blocking_issues`, `_lint_graph_awareness`, `compile_navigation`/`lint_knowledge` в
`knowledge.py`, оба переписанных нода, `_build_autofix_findings_block`/`build_step_prompt`-расширение,
`_build_task_request`/`_run_step_worker`-расширение, новый `LlmTaskKind` — все входят в покрытые строки).

## Out of scope

- Автофикс `WARN:`/`DEBT:`-уровня issues (orphan pages, stale low-confidence, repository/domain conflicts,
  фича не в индексе) — остаются информационными, не эскалируются в LLM (см. «Последствия», п. 4).
- Изменение `init-repo-arch-skill/scripts/analysis_guard.py` и его копии knowledge-логики — отдельная,
  несинхронизированная реализация вне `arch-docs/back`, вне области действия AGENTS.md этого репозитория (см.
  «Последствия», п. 8).
- Новый глобальный лимит стоимости/латентности на автофикс сверх уже существующих `timeout_seconds`/
  `_MAX_RETRY=3` — не вводится; если на практике окажется недостаточно (например, автофикс систематически не
  сходится за 3 графовых retry), это отдельная задача по тюнингу, не эта спека.
- Изменения во фронтенде/SSE-наблюдаемости для явного отображения «идёт автофикс» на шагах 11/12 — события
  `LLM_TASK_*` уже стримятся общей инфраструктурой без изменений; UI-индикация конкретно для автофикса (если
  потребуется отличать её от обычного шагового LLM-вызова в интерфейсе) — вне скоупа этой backend-задачи.
- Изменение `STEP_TO_REFERENCE` для любых других шагов графа, кроме `build_navigation_index`/
  `run_knowledge_lint`.
