# Knowledge Workflow: raw -> synthesis -> navigation -> lint

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

Knowledge lint не отменяет `analysis_guard`, а расширяет его проверками качества knowledge-слоя.

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

1. Исправить blocking-проблемы в knowledge-артефактах.
2. Снова запустить `analysis_guard lint`.
3. Только после исчезновения `ERROR` продвигать шаг `run_knowledge_lint`.

Knowledge lint сочетает file-level и graph-aware проверки: он ловит потерю
ссылочной целостности, базовой трассируемости и drift в wiki-navigation layer.

## Compile loop для wiki-режима

Knowledge graph не только проверяется, но и компилируется:

1. `analysis_guard compile` сканирует markdown-артефакты.
2. Из frontmatter, markdown links, wikilinks и metadata `related` строится
   `wiki/index.md`.
3. Диагностика weak links и missing related refs пишется в
   `wiki/maps/compile-report.md`.
4. Агент исправляет metadata / links и повторяет compile при необходимости.
