# Knowledge Workflow: raw -> synthesis -> navigation -> lint

**Текущий статус в сервисе**: обе ноды (`build_navigation_index` → `knowledge_service.compile_navigation()`,
`run_knowledge_lint` → `knowledge_service.lint_knowledge()`) остаются детерминированным Python по умолчанию —
никакого LLM-вызова, пока проверка ничего не нашла. Но если проверка находит хотя бы один `ERROR:`-issue
(unresolved related reference, frontmatter/related coverage ниже порога — для `build_navigation_index`; любой
`ERROR:`-issue из полного `run_knowledge_lint()` — для `run_knowledge_lint`), нода один раз вызывает LLM-агента
с `task_kind=knowledge_lint_autofix` и **именно этот файл** попадает в его промпт как reference-чеклист — см.
[init-graph-reference.md](../../../../../docs/workflows/init-graph-reference.md), ноды 11/12. Раздел «Автофикс
knowledge-issues» ниже — единственная часть этого файла, которая реально читается агентом; остальные разделы
(«Слои», «Frontmatter metadata model» и т.д.) — концептуальное описание knowledge-модели для людей, готовящих
контент на предыдущих шагах (`refine_features`/`interview_user`).

Этот reference фиксирует целевую knowledge-модель skill без требования немедленной миграции структуры репозитория.

Для `init-repo-arch-skill` knowledge workflow начинается не сразу с synthesis-артефактов, а только после стандартного historical prep:

1. `.temp/<repo>/` должен содержать checkout нужного временного среза, а не произвольный HEAD.
2. `historical_analysis.anchor_repository`, `anchor_created_at` и `current_snapshot_at` должны быть зафиксированы в progress.
3. Для каждого репозитория должен быть заполнен `analysis_target_commit_status`.

Пока historical prep не завершён, raw layer считается неготовым, и дальнейший compile/synthesis workflow не должен считаться standard happy path.

## Слои

### 1. Raw layer

Что входит:

- `.temp/<repo>/` checkout'ы репозиториев;
- исходный код, конфиги, тесты, OpenAPI/AsyncAPI/protobuf, миграции, manifests;
- внешние источники фактов, которые агент нашёл и явно сохранил как ссылку или цитируемый источник.

Правила:

- raw layer читается как исходный материал, а не как место для knowledge-правок;
- нельзя трактовать `.temp/` как произвольную mutable папку агента;
- любой наблюдаемый факт в synthesis layer должен быть восстанавливаем по raw layer или по явно указанному внешнему источнику.

### 2. Synthesis layer

Что входит:

- `features/`;
- `architecture/`;
- `glossary.md`;
- `open-questions.md`;
- `features-index.md` и другие артефакты, где фиксируется уже синтезированное знание.

Роль:

- собрать подтверждённые факты;
- явно отделить косвенные выводы от наблюдаемых фактов;
- вынести gaps и противоречия, которые нельзя закрыть из raw layer.

### 3. Navigation layer

Что входит:

- `AGENTS.md`;
- `wiki/index.md`;
- `wiki/log.md`;
- `wiki/maps/compile-report.md`;
- обзорные индексы вроде `features-index.md` и `architecture/integrations-overview.md`.

Роль:

- давать короткую точку входа;
- маршрутизировать к нужным артефактам;
- не подменять собой synthesis layer и не становиться местом для длинных аналитических описаний.

### 4. Knowledge lint

Knowledge lint проверяет, что:

- navigation layer не содержит битых ссылок;
- synthesis layer не потерял обязательные артефакты и связь с источниками;
- open questions, features, integrations, contracts и storage не противоречат друг другу на уровне базовой структуры.

Knowledge lint выполняется backend'ом автоматически как отдельный шаг графа (`run_knowledge_lint` →
`knowledge_service.lint_knowledge()`), а не по команде агента — здесь фиксируется, каким проверкам он должен
соответствовать, а не как его вызвать.

## Где фиксировать трассировку источников

В первой версии skill используй два уровня детализации:

- **уровень секции** для markdown-документов с обзорным содержанием, где один блок текста агрегирует несколько наблюдений;
- **уровень записи/объекта** для YAML-артефактов и табличных markdown-фрагментов, где знание естественно выражается как отдельные сущности.

Практическое правило:

- для `hld.md`, `feature.md`, `security.md`, `risks.md`, `integration.md`, `tech-stack.md`, `domain-entities.md` добавляй секции или таблицы `Тип утверждения` / `Источники`;
- для `contract.yml`, `async-contract.yml`, `storage.yml`, `repo-structure-map.yml` добавляй поля `assertion_type` и `sources` на верхнем уровне и на уровне ключевых объектов, если объект может жить независимо;
- если весь документ целиком основан на одном типе подтверждения, допустим общий `assertion_type` на уровне документа, но критичные исключения всё равно нужно маркировать рядом с соответствующей записью.

Минимальный словарь типов утверждений:

- `наблюдаемый факт`
- `выведено косвенно`
- `требует подтверждения`

## Frontmatter metadata model

Для markdown-артефактов допустим и рекомендован YAML frontmatter.

Базовая schema:

- `title`
- `type`
- `sources`
- `related`
- `created`
- `updated`
- `confidence`
- `domain`
- `repositories`

Практические правила:

- `sources`, `related`, `repositories` — списки строк;
- `created`, `updated` — даты `YYYY-MM-DD`;
- `confidence` — одно из `high`, `medium`, `low`, `unknown`;
- секции `Источники` и табличная трассировка остаются допустимыми;
- lint должен понимать и frontmatter, и секции `Источники`.

## Как это соотносится с LLM-Wiki паттерном

В терминах LLM-Wiki этот skill движется к модели, где:

- raw layer соответствует исходному корпусу документов и кода;
- synthesis layer соответствует compiled wiki pages;
- navigation layer соответствует короткому graph/navigation entrypoint;
- knowledge lint соответствует compile/evaluate/refine циклу, где ошибки структуры и пропуски фиксируются отдельно и устраняются итеративно.

## Примеры knowledge lint

Blocking (`ERROR`):

- `wiki/index.md` ссылается на отсутствующий файл;
- `features-index.md` ведёт на несуществующий `features/*.md`;
- `architecture/contracts/*.yml`, `architecture/storage/*.yml` или
  `architecture/integrations/*.md` не содержат явной трассировки источников;
- resolved-запись в `open-questions.md` не указывает, в каком артефакте
  зафиксировано закрытие вопроса;
- `wiki/log.md` содержит пустую запись `## Запись: ...`.

Non-blocking (`WARN`):

- feature-файл существует, но не внесён в `features-index.md`;
- `wiki/log.md` отсутствует или не содержит ни одной корректной записи;
- markdown-документ содержит кодовый путь без префикса репозитория, например
  `src/app/page.tsx` вместо `gateway-web/src/app/page.tsx`.

Ожидаемый remediation path:

1. `run_knowledge_lint` (`knowledge_service.lint_knowledge()`) считает `ERROR:`-issues без исключения.
2. Если blocking issues есть — backend один раз вызывает тебя (`task_kind=knowledge_lint_autofix`) с этим
   файлом как reference и списком найденных issues в разделе «Найденные проблемы для исправления» промпта
   выше. Почини именно перечисленные knowledge-артефакты (см. «Автофикс knowledge-issues» ниже) — не жди
   более раннего шага, чинить нужно сейчас, прямо в этом вызове.
3. Backend перекомпилирует навигацию (`compile_navigation()`) и перезапускает `lint_knowledge()` заново над
   исправленными файлами — без нового вызова агента, если issues исчезли.
4. Если `ERROR` остался после твоей правки — нода завершится ошибкой
   (`KNOWLEDGE_LINT_BLOCKED_AFTER_AUTOFIX: ...`), граф повторит всю ноду (включая новый автофикс-вызов) до 3
   раз, прежде чем уйти в `handle_error`.
5. Только после исчезновения `ERROR` граф продвигается на `validate_final`.

Knowledge lint сочетает file-level и graph-aware проверки: он ловит потерю
ссылочной целостности, базовой трассируемости и drift в wiki-navigation layer.

## Compile loop для wiki-режима

Knowledge graph не только проверяется, но и компилируется — отдельным шагом графа (`build_navigation_index` →
`knowledge_service.compile_navigation()`):

1. Backend сканирует markdown-артефакты, уже написанные предыдущими шагами (`refine_features` и т.д.).
2. Из frontmatter, markdown links, wikilinks и metadata `related` строится
   `wiki/index.md`.
3. Диагностика weak links и missing related refs пишется в
   `wiki/maps/compile-report.md`.
4. Если среди найденного есть `ERROR:` (missing related reference или frontmatter/related coverage ниже
   порога — `graph_blocking_issues()`) — backend один раз вызывает тебя (`task_kind=knowledge_lint_autofix`)
   так же, как на шаге 12 (см. выше), с тем же самым списком issues в промпте. Почини `related`/frontmatter в
   затронутых `features/*.md`/`architecture/*.md` — не трогай `wiki/index.md`/`compile-report.md` напрямую,
   backend перекомпилирует их сам над твоей правкой.
5. Если после этого `ERROR` остался — нода завершится ошибкой
   (`KNOWLEDGE_COMPILE_BLOCKED_AFTER_AUTOFIX: ...`), граф повторит ноду (включая новый автофикс-вызов) до 3
   раз.

## Автофикс knowledge-issues

Этот раздел — единственная часть файла, которая пишется как прямая инструкция для вызова автофикса (шаги 11 и
12). Если ты видишь непустой раздел «Найденные проблемы для исправления» в промпте выше — это значит,
детерминированная проверка (`compile_navigation`/`lint_knowledge`) нашла blocking issue, и тебя вызвали именно
чтобы его починить, а не для обычного синтеза новых артефактов.

Правила:

- Правь только файлы, явно упомянутые в перечисленных issues (например, `features/auth.md -> features/missing.md`
  — значит правь `features/auth.md`, а не создавай `features/missing.md` из ничего, если это не то, что
  реально имелось в виду — сверься с контекстом соседних фич). Не переписывай файлы, не упомянутые ни в одном
  issue, даже если заметил в них что-то ещё требующее правки — заведи это как отдельное наблюдение в
  `open-questions.md`, не смешивай с текущим автофиксом.
- Не редактируй `wiki/index.md`, `wiki/maps/compile-report.md` напрямую — они перезаписываются backend'ом
  механически после твоего вызова; ручная правка в них потеряется и будет означать, что автофикс не сработал.
- Типовые blocking issues и как их чинить:
  - `missing related reference X -> Y` — в файле `X` либо исправь `related`/markdown-ссылку на существующий
    файл, либо, если `Y` действительно должен существовать как отдельный knowledge-артефакт, создай его с
    минимально необходимым содержимым (frontmatter + краткое описание), а не удаляй саму ссылку молча.
  - `frontmatter coverage`/`related coverage ниже порога` (`quality gate`) — добавь недостающий YAML
    frontmatter (`title`/`type`/`sources`/`related`/`confidence`/`domain`) в документы, которые требуют
    метаданных (`features/*`, `architecture/integrations/*`, `architecture/hld.md`, `architecture/requirements.md`,
    `architecture/security.md`, `architecture/risks.md`, `wiki/concepts/*`, `wiki/summaries/*`), не выдумывая
    факты — если конкретное значение неизвестно, используй `confidence: unknown` и зафиксируй gap в
    `open-questions.md`, а не оставляй frontmatter пустым.
  - Остальные `ERROR:` от `run_knowledge_lint` (отсутствующая трассировка источников, `features-index.md`
    рассинхронизирован с `features/*.md`, resolved-вопрос без указания артефакта закрытия, пустая запись в
    `wiki/log.md`) — правь по тому же принципу «Примеры knowledge lint» выше: добавь недостающую секцию
    `Источники`/строку в `features-index.md`/описание закрытия, не переписывая остальное содержимое файла.
- Верни стандартный JSON-отчёт (`completed_actions`/`created_artifacts`/`notes`) — `created_artifacts` должен
  содержать реально изменённые тобой файлы, чтобы backend корректно записал их в audit-лог.
