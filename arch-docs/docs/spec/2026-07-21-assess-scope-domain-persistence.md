# Persist domain assessment (`assess_scope_and_domains`)

**Цель:** результат шага `assess_scope_and_domains` (объём репозитория + бизнес-домены) должен реально
сохраняться в `session` (а значит — автоматически в `workflow_runs.session_payload` и в progress-снепшот
YAML) и быть пригодным для переиспользования на следующих шагах, вместо того чтобы бесследно растворяться в
свободном тексте LLM-ответа.

**Статус:** done. Все фазы 0-8, включая Фазу 6 (переиспользование в `analyze_repositories`), реализованы,
покрыты тестами (574 → 582 теста в сьюте, 0 регрессий), документация актуализирована. См. также «Дополнение»
ниже — retry сделан идемпотентным на уровне одного репозитория.

## Проблема

`RepositoryExecution` в [models.py:124-125](../../back/app/workflows/init_arch/domain/models.py#L124-L125)
уже содержит поля `domain_strategy: DomainStrategy | None` и `domains: list[DomainDefinition]` — они были
задуманы именно под результат этого шага, но ни один модуль backend'а их не заполняет (см. известную
несостыковку №5 в [init-graph-reference.md](../workflows/init-graph-reference.md#известные-несостыковки-найденные-при-разборе)).

`node_assess_scope_and_domains` ([nodes.py:457](../../back/app/workflows/init_arch/nodes.py#L457)) — это
голый `_simple_llm_step`: один LLM-вызов на весь список репозиториев сразу, без парсинга структурированного
результата (кроме generic `completed_actions`/`notes` — свободный текст) и без вызова
`collect_worker_artifacts`. Итог: даже если агент честно проанализировал домены, это нигде не оседает — ни в
`session`, ни в артефактах, ни в чём, что мог бы прочитать `analyze_repositories` дальше.

При этом хранилище — не проблема: `workflow_runs.session_payload` в
[db/models.py:79](../../back/app/db/models.py#L79) — это `sa.JSON`-колонка, сериализующая весь
`WorkflowSessionRecord` целиком; progress-снепшот YAML — та же сериализация того же `session`
(`_drive_graph_stream()` пишет его после каждой ноды). Как только `domain_strategy`/`domains` окажутся
заполнены на `RepositoryExecution`, они автоматически попадут в оба хранилища без единой миграции.
Настоящая работа — в контракте между LLM и этими полями.

## Принятые решения по архитектуре

- **Топология LLM-вызова**: цикл, один вызов на репозиторий (как в `analyze_repositories`/
  `refresh_main_branches`), а не один общий вызов на весь список. Дороже по числу LLM-вызовов, но надёжнее
  при большом количестве репозиториев и переиспользует существующий `repository_name`-параметр
  `LlmTaskRequest`/`_run_step_worker` без новых полей контракта.
- **Quality gate**: блокирующий. Если LLM не вернул валидный `domain_assessment` для репозитория — нода
  роняет `DomainOperationError` и уходит в стандартный retry/`handle_error` путь, как уже делает
  `plan_repository_order` при неполном `historical_prep_is_complete()`. Молча проходить дальше без
  структурного результата шаг не должен.
- **Кто пишет артефакт**: backend детерминированно сериализует уже заполненный `session.repositories[*]` в
  `architecture/domain-map.yaml` (тем же способом, что `compile_navigation()` пишет `wiki/index.md`) — не
  полагаемся на то, что LLM аккуратно продублирует те же данные в файл руками.

## Фазы

### Фаза 0 — контракт ответа LLM `[x]`

Расширить универсальный JSON-контракт в `build_step_prompt()`
([prompts.py:269-277](../../back/app/workflows/init_arch/prompts.py#L269-L277)) необязательным полем
`domain_assessment` — используется только на шаге `assess_scope_and_domains`, на остальных шагах агент его
не заполняет (парсится как `None`, что безопасно). Формат:

```json
{
  "domain_assessment": {
    "volume_class": "small|medium|large|xlarge",
    "strategy": "per_module|per_domain",
    "domains": [
      {"domain_id": "billing", "name": "Биллинг", "paths": ["apps/billing/", "apps/payments/"], "signal": "...", "subdomains": []}
    ]
  }
}
```

Инструкцию описать явно только для этого шага (аналог существующего спецблока для
`_RELEASE_NOTES_STEP_VALUE`), чтобы не путать остальные шаги лишним полем в промпте.

**Мини-отчёт**: реализовано как задумано — `_DOMAIN_ASSESSMENT_STEP_VALUE`/`_DOMAIN_ASSESSMENT_CONTRACT_BLOCK`
в [prompts.py](../../back/app/workflows/init_arch/prompts.py), подмешивается в эпилог `build_step_prompt()`
только когда `step_value == "assess_scope_and_domains"`. Тесты:
`test_build_step_prompt_includes_domain_assessment_contract_for_its_step`,
`test_build_step_prompt_omits_domain_assessment_contract_for_other_steps` в `test_prompts.py`.

### Фаза 1 — модель и парсинг `[x]`

- Новая pydantic-модель `RepositoryDomainAssessment` (`volume_class`, `strategy: DomainStrategy`,
  `domains: list[DomainDefinition] = []`) в `domain/models.py`.
- `LlmTaskResult` получает поле `domain_assessment: RepositoryDomainAssessment | None = None`.
- `task_runner._parse_result()`/`run_task()` ([task_runner.py:318-328](../../back/app/services/task_runner.py#L318-L328))
  прокидывают `parsed_result.get("domain_assessment")` в `LlmTaskResult(...)` — как и остальные поля, без
  дополнительной защиты: если LLM прислал невалидную структуру, pydantic сам поднимет `ValidationError`,
  что попадёт в тот же `try/except` ноды и уйдёт в retry (согласуется с блокирующим gate).

**Мини-отчёт**: `RepositoryDomainAssessment`/`VolumeClass` добавлены в `domain/models.py`; заодно пришлось
добавить `RepositoryExecution.volume_class: VolumeClass | None = None` — в спеке этого поля не было явно
названо, но без него негде было бы хранить volume вместе со strategy/domains на самом репозитории.
`LlmTaskResult.domain_assessment` и прокидывание в `task_runner.py` — как и планировалось, без
дополнительной защиты сверх стандартного `pydantic.ValidationError`.

### Фаза 2 — доменная операция + guard-метод `[x]`

- `set_domain_assessment(session, *, repository_name, volume_class, strategy, domains)` в
  `domain/operations.py` — копирует список репозиториев, обновляет нужный через `model_copy`, по образцу
  `mark_checklist_item` ([operations.py:124-140](../../back/app/workflows/init_arch/domain/operations.py#L124-L140)).
- `domain_assessment_is_complete(session) -> bool` — по образцу `historical_prep_is_complete()`
  ([operations.py:225](../../back/app/workflows/init_arch/domain/operations.py#L225)): `True`, только если
  каждый repository имеет непустой `domain_strategy`.
- `GuardService.assess_repository_domains(session, *, repository_name, volume_class, strategy, domains,
  progress_file_path)` в `guard.py` — вызывает `set_domain_assessment`, пишет
  `GUARD_COMMAND_REQUESTED`/`APPLIED(command="domain_assess")`, возвращает `GuardOperationResult`.

**Мини-отчёт**: `set_domain_assessment`/`domain_assessment_is_complete` реализованы точно по плану (образцы
`mark_checklist_item`/`historical_prep_is_complete`). Отклонение от плана в guard-методе: сигнатура с 5
раздельными keyword-параметрами (`repository_name`/`volume_class`/`strategy`/`domains`/`progress_file_path`)
триггерила `ruff PLR0913` (`self` + 5 = 6 аргументов); заменил три доменных поля на один параметр
`assessment: RepositoryDomainAssessment` — тот же pydantic-объект, что уже приходит из `LlmTaskResult`, так
что это не лишняя обёртка, а устранение дублирования. Тесты: `test_set_domain_assessment_*`,
`test_domain_assessment_is_complete_*` в `test_operations.py`;
`test_guard_service_assess_repository_domains_updates_session_and_emits_events` в `test_guard.py`.

### Фаза 3 — переписать `node_assess_scope_and_domains` `[x]`

Убрать `_simple_llm_step`, сделать явную ноду по образцу `node_analyze_repositories`
([nodes.py:466](../../back/app/workflows/init_arch/nodes.py#L466)):

```python
session = state["session"]
for repository in session.repositories:
    start_result = await guard_service.start_repository(...)  # scoping для build_step_prompt (current_repo)
    session = start_result.session
    llm_result = await _run_step_worker(
        {**state, "session": session},
        StepId.ASSESS_SCOPE_AND_DOMAINS,
        repository_name=repository.repository_name,
    )
    assessment = _require_domain_assessment(llm_result, repository.repository_name)  # raise вынесен наружу
    assess_result = await guard_service.assess_repository_domains(
        session, repository_name=repository.repository_name, assessment=assessment,
        progress_file_path=state["progress_file_path"],
    )
    session = assess_result.session
```

**Мини-отчёт**: реализовано с двумя дополнениями к плану. (1) Добавлен вызов `guard_service.start_repository(...)`
перед каждым LLM-вызовом — без него `build_step_prompt()` не знает, какой repository "текущий"
(`current_repository`/`temporal_delta_block` там определяются по `analysis_status == "in_progress"`, который
больше нигде на этом шаге не выставляется). Не ломает `analyze_repositories`: та нода сама вызывает
`start_repository` заново на каждый свой repository, так что промежуточное значение `in_progress` от этого
шага просто перезаписывается. (2) Оба `raise DomainOperationError` вынесены в отдельные функции
(`_require_domain_assessment`, `_require_domain_assessment_complete`) — прямой `raise` внутри `try`-блока
ловит `ruff TRY301`; вынос в функцию — стандартный способ обойти это в остальном коде репозитория (raise
внутри `operations.advance_step()`/`historical_prep_is_complete()`, а не в теле ноды). Тесты:
`test_node_assess_scope_and_domains_persists_assessment_per_repository`,
`test_node_assess_scope_and_domains_blocks_when_llm_omits_assessment`,
`test_require_domain_assessment_complete_raises_on_incomplete_session` в `test_nodes.py`.

### Фаза 4 — quality gate перед advance `[x]`

Перед `guard_service.advance_step(..., StepId.ANALYZE_REPOSITORIES, ...)` — явная проверка
`domain_assessment_is_complete(session)`, иначе `raise DomainOperationError(...)`. Дублирует защиту цикла из
Фазы 3 (там уже нельзя выйти из цикла без assessment на каждый repository), но добавляет симметрию с
`plan_repository_order` и защищает от будущих рефакторингов цикла.

**Мини-отчёт**: реализовано как `_require_domain_assessment_complete(session)`, вызывается после цикла, до
`write_domain_map`/`advance_step`. Эта ветка недостижима через обычный ход ноды (цикл уже гарантирует полноту
через Фазу 3) — чисто защитный код на случай будущего рефакторинга цикла; покрыт отдельным прямым unit-тестом
на саму функцию (`test_require_domain_assessment_complete_raises_on_incomplete_session`), а не через ноду.

### Фаза 5 — читаемый артефакт `domain-map.yaml` `[x]`

Новый метод `KnowledgeArtifactService.write_domain_map(session, *, arch_repo_dir)` в `knowledge.py`, по
образцу `compile_navigation()` ([knowledge.py:135-167](../../back/app/workflows/init_arch/knowledge.py#L135-L167)):
детерминированно сериализует `session.repositories[*].domain_strategy/.domains` через
`yaml.safe_dump(..., sort_keys=False, allow_unicode=True)` (тот же вызов, что уже используется в
`snapshot.py:44`) в `architecture/domain-map.yaml`, регистрирует артефакт через `_register_artifacts(...,
step_id=StepId.ASSESS_SCOPE_AND_DOMAINS, source_refs=["service:domain_assessment"])` — это даёт
`ARTIFACT_WRITTEN` и попадание в `session.artifacts`/`wiki/index.md` тем же путём, что и у остальных
knowledge-артефактов. Вызывается из ноды после цикла Фазы 3, перед `advance_step`.

**Мини-отчёт**: реализовано как задумано — `write_domain_map()` в `knowledge.py`, `yaml.safe_dump(...,
sort_keys=False, allow_unicode=True)`, добавлена запись `"architecture/domain-map.yaml": "domain_map"` в
`_ARTIFACT_KINDS` для точного kind вместо общего `architecture_artifact`. Тест:
`test_write_domain_map_serializes_repository_assessments` в `test_knowledge.py` — проверяет и содержимое
YAML, и регистрацию артефакта с правильным `artifact_kind`/`last_updated_step`.

### Фаза 6 — переиспользование в `analyze_repositories` `[x]`

Прокинуть в контекстный блок `build_step_prompt()` для `analyze_repositories` домены текущего репозитория
(`repository.domains`), чтобы агент и `route_checklist_items` видели границы доменов явно, а не открывали их
заново.

**Мини-отчёт**: реализовано как новая секция промпта «Домены репозитория»
(`_build_domain_context_block()` в [prompts.py](../../back/app/workflows/init_arch/prompts.py)), рендерится
только для `step_value == "analyze_repositories"` (константа `_ANALYZE_REPOSITORIES_STEP_VALUE`), для
остальных шагов — общий `_NOT_APPLICABLE_BLOCK` (переименовал `_NOT_APPLICABLE_RELEASE_NOTES_BLOCK`, т.к.
текст `"(не применимо для этого шага)"` теперь переиспользуется двумя независимыми блоками — release notes и
domain context). Блок показывает `volume_class`/`strategy` и список доменов (`domain_id`, `name`, `paths`,
`signal`, `subdomains`) для текущего репозитория, с явными fallback-текстами на случай, если репозитория нет
(`current_repository is None`) или `assess_scope_and_domains` для него ещё не прошёл
(`domain_strategy is None`). Добавлена отдельная строка в «Инструкции» (`domain_context_instruction`),
явно говорящая агенту не пере-открывать домены через `find`/`ls`, а использовать уже показанные.

**Осознанное сужение скоупа относительно исходной формулировки фазы**: `route_checklist_items()`
([signal_routing.py:99](../../back/app/workflows/init_arch/domain/signal_routing.py#L99)) технически уже
получает полный `RepositoryExecution` (включая `.domains`) первым аргументом — структурно "видеть" домены
ему для этого ничего дополнительно передавать не нужно. Но сама функция — чистый path-based роутер по
diff severity (`FULL_REQUIRED`/`NO_SIGNAL`/`LOCAL`/`BROAD` + категории по паттернам путей), и в исходной
формулировке фазы не было конкретики, *как именно* домены должны влиять на её решение — домены это
ортогональная ось ("какая часть кода — про биллинг"), а не категория чеклиста ("про контракты"/"про тесты").
Реализация правила "домен X → роутить чеклист-пункт Y" — отдельное архитектурное решение (потребовало бы
либо per-domain цикла в `analyze_repositories`, либо доменной фильтрации путей внутри роутера), которое не
было зафиксировано ни в одном критерии готовности спеки. Оставляю как явный открытый пункт, а не додумываю
поведение молча. Тесты: `test_build_step_prompt_domain_context_*` (5 штук) в `test_prompts.py`.

### Фаза 7 — тесты `[x]`

- `test_operations.py` (или соответствующий файл): `set_domain_assessment`, `domain_assessment_is_complete`.
- `test_guard.py`: `assess_repository_domains` — audit-события, обновлённый `session`.
- `test_nodes.py`: новый `test_node_assess_scope_and_domains_*` — успешный цикл по нескольким репозиториям,
  блокировка при отсутствующем `domain_assessment` у одного из них (retry/`step_error`), артефакт
  зарегистрирован.
- `test_knowledge.py`: `write_domain_map` — содержимое YAML, регистрация артефакта.
- `test_prompts.py`: JSON-контракт содержит описание `domain_assessment` только для нужного шага.

**Мини-отчёт**: все пункты покрыты, плюс тесты сверх плана —
`test_require_domain_assessment_complete_raises_on_incomplete_session` (прямой unit-тест на defensive-gate
Фазы 4, т.к. через ноду эта ветка недостижима) и 5 тестов на domain-context блок Фазы 6
(`test_build_step_prompt_domain_context_not_applicable_for_other_steps`,
`_no_active_repository`, `_not_yet_assessed`, `_per_module_repository`,
`_per_domain_repository_lists_domains`). Итог после Фазы 6: 580 тестов в сьюте (было 574 до задачи), 0
упавших, 0 регрессий. `ruff check .`/`ruff format --check .` — на изменённых файлах чисто; оставшиеся
замечания (`task_runner.py` `PLR0915`, `architecture_lint.py`/`historical.py` форматирование,
`conftest.py` `E402`) — подтверждённый pre-existing baseline (сверено через `git stash` до/после). Coverage
дельты (`nodes.py`/`guard.py`/`knowledge.py`/`operations.py`/`prompts.py`/`task_runner.py` в части моих
новых строк) — 100%, проверено построчно по `--cov-report=term-missing`: ни одна "Missing"-строка не
принадлежит новому коду (в `prompts.py` непокрытые строки 216/230 — предсуществующая функция
`_build_release_notes_context_block`, не тронутая этой задачей).

### Фаза 8 — актуализация документации `[x]`

- `checklist-scope-and-domain-assessment.md` — переписать раздел «шаг 3» под настоящий JSON-контракт
  (текущая версия там временная, я поставил её заплаткой в рамках предыдущей задачи про мёртвый
  `analysis_guard.py`; теперь появляется реальный структурированный формат, и текст должен описывать именно
  его, а не просто "пиши текстом в notes").
- `init-graph-reference.md` — снять известную несостыковку №5 (поля `domain_strategy`/`domains` теперь
  реально заполняются) и обновить описание ноды 7 (`assess_scope_and_domains`) под новую топологию
  (цикл по репозиториям, guard-метод, артефакт, quality gate) — по аналогии с тем, как уже описана нода 8
  (`analyze_repositories`).
- Эта спека (текущий файл) — статус проставляется в `done` по завершении всех фаз 0-7.

**Мини-отчёт (первый проход, после Фаз 0-5,7)**: оба документа обновлены.
`checklist-scope-and-domain-assessment.md`: вступление про "текущее состояние сервиса" переписано с описания
временной заплатки (текст в `notes`) на реальный протокол — вызов per-repository, `domain_assessment` в JSON
как единственный канал; шаг 3 переписан под точную JSON-схему на один репозиторий (не батч); "Обязательные
выходы" теперь явно говорят, что это блокирующая проверка, а не "никакой автоматической проверки нет" (как
было в моей предыдущей временной правке).
`init-graph-reference.md`: нода 7 переписана целиком (топология цикла, роль `write_domain_map`, реальный
блокирующий `try/except`, ссылка на эту спеку); известная несостыковка №5 помечена как исправленная (с
оговоркой про Фазу 6 как открытый пункт); несостыковка №4 сужена — `assess_scope_and_domains` из неё убран
(теперь единственная нода из тройки, которая реально регистрирует свой артефакт, хоть и не через
`collect_worker_artifacts`, а через отдельный детерминированный путь).

**Мини-отчёт (повторный проход, после Фазы 6)**: доп. правки в `init-graph-reference.md` — нода 8
(`analyze_repositories`) дополнена описанием новой секции промпта «Домены репозитория»
(`_build_domain_context_block()`/`domain_context_instruction`) и явной оговоркой про сужение скоупа
(`route_checklist_items` домены не использует — см. мини-отчёт Фазы 6 выше); известная несостыковка №5 —
убрана оговорка "Фаза 6 — открытый пункт" (Фаза 6 реализована), вместо неё зафиксировано новое, более узкое
открытое расхождение: `route_checklist_items` по-прежнему не учитывает домены при роутинге чеклиста, хотя
контекст для агента уже показывается.

## Дополнение (2026-07-21): идемпотентный retry вместо повтора всего цикла

После первого прохода Фаз 0-8 `node_assess_scope_and_domains` при падении на любом репозитории (например,
LLM не вернул `domain_assessment` для второго из трёх) ретраил **весь** цикл заново — включая уже успешно
провалидированные репозитории, тратя на них лишние LLM-вызовы. Причина: except-ветка возвращала только
`{"step_error": ..., "retry_count": ...}` без `"session"` — точно тот же паттерн, что и во всех остальных
нодах файла (`grep` подтвердил: ни одна нода не возвращает `session` при ошибке). Раз `InitArchState` —
обычный `TypedDict` без reducer'ов, отсутствующий в возвращаемом dict ключ означает "не трогать" — значит
локальный прогресс цикла (`session`, накопленный внутри функции) при исключении просто терялся, и следующая
попытка узла стартовала с `state["session"]`, каким он был до начала этого захода.

Исправлено двумя изменениями в `node_assess_scope_and_domains`
([nodes.py:474](../../back/app/workflows/init_arch/nodes.py#L474)):

1. Цикл в начале каждой итерации пропускает уже провалидированные репозитории:
   `if repository.domain_strategy is not None: continue` — не тратит LLM-вызов повторно.
2. except-ветка возвращает `{"session": session, "step_error": ..., "retry_count": ...}` — партиальный
   прогресс (уже назначенные `domain_strategy`/`domains` на успешно обработанных репозиториях) реально
   долетает до graph state через `apply_node_output()` (которая, увидев ключ `"session"`, сама выводит
   `current_step_id`/`completed_steps` — отдельно их передавать не нужно).

Это делает `assess_scope_and_domains` первой нодой в файле с по-настоящему идемпотентным retry на уровне
одного репозитория, а не всего шага — сознательно локальный фикс только для этой ноды (не трогал
`analyze_repositories`/остальные ноды с тем же паттерном, т.к. явно попросили именно эту).

Тесты: `test_node_assess_scope_and_domains_preserves_partial_progress_on_failure` (падение на втором
репозитории не стирает `domain_strategy` первого) и
`test_node_assess_scope_and_domains_skips_already_assessed_repository_on_retry` (при уже заполненном
`domain_strategy` LLM/`start_repository`/`assess_repository_domains` вызываются только для непровалидированного
репозитория) в `test_nodes.py`. Итог: 582 теста в сьюте (было 580), 0 регрессий, 100% покрытие новой логики.
`init-graph-reference.md` (нода 7, раздел «При ошибке») актуализирован под новое поведение.

## Тестирование (сквозной критерий)

`assess_scope_and_domains` должен быть покрыт тестами не хуже, чем `analyze_repositories`/
`plan_repository_order` — happy path, retry при частичном отказе LLM, содержимое итогового `session` и
артефакта. Цель по покрытию для дельты этой задачи — 100%, как требует `pylines`-гайдлайн проекта.

## Критерии готовности

- После прогона шага `session.repositories[*].domain_strategy`/`.domains` заполнены для каждого репозитория.
- `architecture/domain-map.yaml` существует в `arch_repo_dir`, зарегистрирован в `session.artifacts`.
- Если LLM не вернул assessment хотя бы для одного репозитория — шаг уходит в retry/`handle_error`, а не
  проходит дальше молча.
- Retry повторяет только тот репозиторий, на котором упало, а не весь цикл заново (см. «Дополнение»).
- Все новые unit-тесты зелёные, `just agent-check` (или эквивалент) проходит.

## Out of scope

- `route_checklist_items()` не учитывает домены при роутинге чеклиста — агент видит домены в промпте, но
  сам роутер по-прежнему чисто path/diff-based (см. мини-отчёт Фазы 6 про сужение скоупа).
- Миграция БД — не требуется, `session_payload` уже `sa.JSON`.
- Изменение топологии графа (число нод, edges) — не требуется, меняется только содержимое существующей
  ноды.
