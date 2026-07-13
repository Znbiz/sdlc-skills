---
name: init-repo-arch-skill
description: Инициализация и первичное наполнение архитектурного репозитория по уже существующему продукту или системе. Use when the user wants to reconstruct the current architecture from code and configuration, describe current features, integrations, contracts, storages, and populate an architecture repository for the as-is state. Suitable for reverse engineering, brownfield analysis, architecture audit, and first-pass arch repo filling. Do not use for designing a new target solution or planning a feature change from scratch; use `new-feature-arch-skill` for to-be design.
license: MIT
metadata:
  author: Nekrasov ALeksei
  version: "2.1"
---

# Навык анализа существующего продукта

Используй этот навык, когда система уже существует, а задача состоит не в проектировании новой фичи с нуля, а в восстановлении и структурировании текущего состояния продукта и архитектуры.

## Граница применения

Используй этот skill, когда нужно описать `as-is` состояние.

Не используй его как основной skill для проектирования нового поведения системы. Если текущее состояние уже восстановлено и дальше нужно спроектировать изменение, переходи к `new-feature-arch-skill`.

## Структура репозитория

Структура и обязательные секции каждого артефакта описаны прямо в reference-чеклисте соответствующего шага (`references/checklist-*.md`) — читай их оттуда. Отдельного каталога с шаблонами (`assets/`) в этом окружении нет: не пытайся его открыть.

Для временных клонов репозиториев используй локальный каталог `.temp/` в текущем workspace. Если каталога нет, создай его. Эту папку нужно держать в `.gitignore`, чтобы временные checkout'ы не попадали в git.

В knowledge workflow этого skill каталог `.temp/` является **raw layer**: он хранит исходные checkout'ы, конфиги, контракты, тесты и другие первичные источники фактов. Этот слой рассматривается как **immutable source of truth для наблюдаемых фактов**. Агент может читать `.temp/`, индексировать его и ссылаться на файлы, но не должен использовать его как место для редактирования knowledge-артефактов.

Markdown/YAML артефакты, создаваемые в архитектурном репозитории (`features/`, `architecture/`, `glossary.md`, `open-questions.md` и связанные wiki-файлы), образуют **synthesis layer**: это слой синтезированного знания, где агент собирает факты, выводы, пробелы и трассировку источников.

Файлы `AGENTS.md`, `wiki/index.md`, `features-index.md`, `integrations-overview.md` и аналогичные короткие входные документы образуют **navigation layer**: он нужен, чтобы агент и человек быстро находили нужные knowledge-артефакты, не перечитывая весь репозиторий целиком.

Проверки консистентности между raw/synthesis/navigation слоями относятся к **knowledge lint**. Knowledge lint не заменяет `analysis_guard` и не ослабляет обязательный workflow; это дополнительный контроль качества knowledge-слоя.

Прогресс workflow отслеживает сам сервис, а не агент: текущий шаг, завершённые шаги и зарегистрированные артефакты хранятся в состоянии сессии и обновляются автоматически по структурированному JSON-отчёту, который агент возвращает в конце каждого шага (`completed_actions`, `created_artifacts`, `open_questions_found`, `notes`). Агенту не нужно вызывать какой-либо CLI progress-guard самому и не нужен шаблон progress-файла — если промпт шага сообщает путь к progress-файлу, это только informational bridge, а не источник решений.

## Обязательная дисциплина workflow

Этот skill нужно исполнять в режиме `low freedom`: переход между этапами анализа определяется текущим шагом сессии и reference-чеклистом из промпта, а не памятью агента и не ручным CLI-guard.

Минимальный цикл работы:

1. В начале шага сверяй блоки `Шаг`, `Завершённые шаги`, `Текущий репозиторий`, `Открытые вопросы` и `Temporal delta` из промпта.
2. Выполняй только текущий шаг и только по reference-чеклисту, который инжектирован сервисом в этот prompt.
3. Не переходи к следующему этапу, пока текущий шаг не отражён в артефактах и в JSON-отчёте (`completed_actions`, `created_artifacts`, `open_questions_found`, `notes`).
4. Если промпт показывает путь к progress-файлу, используй его только как informational bridge и compatibility-след, а не как источник решений о том, что делать дальше.
5. Если обнаружена ошибка консистентности или нарушение обязательных предусловий, сначала исправь артефакты и верни корректный структурированный отчёт, и только потом считай шаг завершённым.

Стандартный happy path для `init-repo-arch-skill` всегда включает historical prep до первого содержательного анализа репозиториев:

1. Зарегистрировать все репозитории с `created_at`.
2. Зафиксировать `main_branch` и доступный `remote_head_commit`.
3. Найти самый старый репозиторий.
4. Вычислить первый `snapshot date` как `created_at + historical_window_months` для workflow `init` (`3` месяца по умолчанию, но параметр конфигурируется).
5. Для каждого репозитория найти `snapshot commit` не позже общего `snapshot date`.
6. Для каждого репозитория подготовить temporal delta текущего окна: baseline, `commit_range`, `git log`, `git diff --stat`, `git diff --name-status`.
7. Только после этого переходить к `assess_scope_and_domains` и `analyze_repositories`.

Это не дополнительный режим и не optional prep-ветка. Для `init-repo-arch-skill` это обязательная линейная часть стандартного workflow.

## Temporal contract

Для `init-repo-arch-skill` temporal analysis всегда трактуется как пара:

- `snapshot-state` — код в состоянии на `snapshot date`;
- `temporal-delta` — изменения, которые привели систему к этому состоянию с прошлого окна.

Обязательный glossary:

- `snapshot_date`
- `snapshot_commit`
- `previous_snapshot_commit`
- `window_start_commit`
- `window_end_commit`
- `commit_range`
- `diff_stat_summary`
- `changed_paths`
- `commit_log_summary`

Правила окна:

- Для любого окна после первого `window_start_commit` обычно совпадает с `previous_snapshot_commit`, а `window_end_commit` должен совпадать с `snapshot_commit`.
- Для первого окна допустим special-case: baseline берётся от `created_at`/первого доступного commit и помечается явно, а не скрывается пустым diff.
- Репозиторий не обязан иметь коммиты внутри каждого окна. Если его последний доступный commit старше текущего окна, workflow всё равно должен отработать:
  - `snapshot_commit` выбирается как последний commit не позже `snapshot_date`;
  - если в предыдущем окне уже был выбран тот же commit, delta текущего окна фиксируется как `no_changes`;
  - это нормальный сценарий для редко меняющихся или временно неактивных репозиториев, а не ошибка historical prep.
- Если на дату окна репозиторий ещё не существовал или для него вообще нет commit не позже `snapshot_date`, это отдельный случай `baseline_missing` / `missing`, но он не должен ломать весь `init` workflow.
- Если история неполная, ancestry не строится или baseline отсутствует, это нужно фиксировать отдельным статусом temporal delta, а не считать historical prep завершённым автоматически.
- Empty/degenerate delta допустима только как явно помеченный случай: `no_changes`, `baseline_missing` или `window_start_commit == window_end_commit`.
- Downstream analysis не должен считать historical prep завершённым, если подготовлен только checkout на дату без delta-context.

Ниже приведены legacy CLI-мнемоники из исходного standalone skill. В `arch-docs` это не обязательные команды, а лишь короткие имена операций, чтобы не терять терминологическое соответствие с историческими reference-материалами:

- `init --output <path> --product <name> --scope <scope>`
- `status --progress <path>`
- `domain ...`
- `repo ...`
- `advance --progress <path> --note "<что завершено>"`

Для knowledge workflow тем же образом могут упоминаться операции:

- `bootstrap --progress <path> --arch-repo-path <arch-repo>`
- `index --progress <path> --arch-repo-path <arch-repo>`
- `lint --progress <path> --arch-repo-path <arch-repo>`
- `compile --progress <path> --arch-repo-path <arch-repo>`
- `timeline --progress <path> --plan|--resolve-local|--advance-window [--checkout]`

Skill работает в единой wiki-схеме:

- `wiki/index.md` — основной navigation entrypoint;
- `wiki/log.md` — append-only журнал обновлений knowledge-слоя;
- `wiki/maps/compile-report.md` — диагностический compile-report.

Если промпт сообщает путь к progress-файлу, считай его compatibility bridge для человека и внешних инструментов.
По умолчанию такой bridge-файл может называться `repo-initialization-progress.yaml`, но decisions о переходе между шагами принимает не он, а сервисное состояние сессии.

Команда `validate` и низкоуровневые `register-repo`, `start-repo`, `update-repo-checklist`, `complete-repo` допустимы как служебные или для отладки, но не должны быть основным интерфейсом skill.

Если содержимое progress bridge расходится с текущим шагом в промпте или фактическими артефактами, источником истины считается не память агента и не bridge-файл, а состояние сессии, reference-чеклист и реальные файлы knowledge-слоя.

## Петля исполнения: один шаг за раз

Скилл работает в режиме **одного шага за раз**. Не читай весь checklist заранее. Не переходи к следующему шагу, пока текущий не закрыт в артефактах и сервисном состоянии шага.

**Для шагов верхнего уровня** (`workflow.steps`):
```
status → загрузить reference → выполнить один шаг → advance → повторить
```

Для `init-repo-arch-skill` исторический анализ по временным срезам включён всегда. Это и есть стандартный путь выполнения:

1. Найти репозиторий с самой ранней `created_at`.
2. Взять дату этого репозитория и прибавить `historical_window_months` workflow `init` (`3` месяца по умолчанию).
3. Использовать эту дату как общий `snapshot date` для всех in-scope репозиториев.
4. Для каждого репозитория попытаться найти `snapshot commit` не позже `snapshot date`.
5. Для каждого репозитория построить temporal delta от предыдущего окна: `commit_range`, commit log, `diff --stat`, `name-status`.
   Если commit не менялся с прошлого окна, зафиксировать `no_changes` и продолжить анализ без ошибки.
6. Анализировать репозитории в порядке `created_at` от старых к новым, опираясь и на snapshot-state, и на delta текущего окна.
7. После завершения прохода по всем репозиториям на текущем срезе перевести окно на следующий шаг `historical_window_months` workflow `init` (`3` месяца по умолчанию) и повторить цикл.

Historical prep и его результаты должны отражаться в сервисном состоянии сессии, связанных артефактах и итоговом JSON-отчёте шага, а не только в заметках агента.

### Standard Happy Path

Нормальный линейный прогон `init-repo-arch-skill` выглядит так:

```text
define_scope
  → request_repository_list
  → prepare_temp_workspace
  → clone_repositories
  → refresh_main_branches
      → для каждого repo зафиксировать main branch, remote HEAD, created_at
  → plan_repository_order
      → timeline --progress <path> --plan
      → timeline --progress <path> --resolve-local --checkout
      → проверить anchor_repository, anchor_created_at, current_snapshot_at
      → проверить, что ordered_repository_names отсортирован по created_at
  → assess_scope_and_domains
  → analyze_repositories
  → interview_user
  → refine_features
  → build_navigation_index
  → run_knowledge_lint
  → validate_final
  → finalize_progress
```

Если historical prep не завершён, skill считается не дошедшим до standard happy path и не должен начинать `assess_scope_and_domains` или `analyze_repositories`.

Для шагов knowledge workflow порядок такой:

```text
refine_features
  → index --progress <path> --arch-repo-path <arch-repo>
  → advance
run_knowledge_lint
  → lint --progress <path> --arch-repo-path <arch-repo>
  → исправить ERROR
  → advance
```

Для wiki knowledge graph допустим дополнительный compile-цикл:

```text
build_navigation_index
  → bootstrap --progress <path> --arch-repo-path <arch-repo>   # если wiki-структура ещё не создана
  → compile --progress <path> --arch-repo-path <arch-repo>
  → проверить wiki/index.md и wiki/maps/compile-report.md
  → при необходимости исправить metadata/frontmatter/links
```

**Для шага `interview_user`** — выполняется строго по одному открытому вопросу за раз. Нельзя задавать следующий вопрос, пока текущий не закрыт не только в `open-questions.md`, но и во всех связанных артефактах:
```
status → выбрать один open question со статусом open и "Нужен ответ пользователя" = yes
       → кратко показать: что подтверждено кодом, какой пробел остался, сам вопрос
       → дождаться одного ответа пользователя
       → сопоставить ответ с уже найденными артефактами и отметить расхождения, если они есть
       → обновить основной артефакт из колонки "Контекст" (feature / security / roles / risk / integration / contract / storage / glossary / hld)
       → обновить другие затронутые артефакты, если знание влияет более чем на один документ
       → обновить open-questions.md: статус, `Follow-up ID`, `Целевые артефакты`, `Обновление knowledge graph`, "Что уже известно", "Как закрыт"
       → только после этого задать следующий один вопрос
```

Минимальный пост-ответ цикл обязателен:
1. Получить ответ пользователя на один вопрос.
2. Проверить, не противоречит ли он уже найденному коду и конфигам.
3. Обновить все целевые документы, на которые влияет ответ.
4. Убедиться, что в целевых документах появился явный `Q-...` reference.
5. Обновить `open-questions.md`.
6. Лишь после сохранения правок переходить к следующему вопросу.

Если ответ пользователя влияет на несколько артефактов, агент обязан обновить их в том же цикле, а не откладывать "на потом". Оставлять знание только в `open-questions.md` запрещено.

**Для шага `assess_scope_and_domains`** — это первый шаг после обязательного historical prep. Он выполняется по каждому репозиторию в отдельности, в порядке `ordered_repository_names`. Результат хранится в `repo.domain_map`, не глобально:
```
status → загрузить reference checklist-scope-and-domain-assessment.md
       → для каждого репозитория:
           оценить объём (find + wc по .temp/<repo>)
           domain --repo <repo> --assess --volume-class <class> --total-files <N> --strategy <per_module|per_domain>
           (если per_domain) domain --repo <repo> --register ... для каждого домена
       → advance --note "repo1: per_domain 2 домена; repo2: per_module"
```

Historical prep перед `assess_scope_and_domains` и `analyze_repositories` обязателен:

```text
refresh_main_branches
  → для каждого repo зафиксировать main branch, remote HEAD и created_at
plan_repository_order
  → timeline --progress <path> --plan
  → timeline --progress <path> --resolve-local --checkout
  → проверить, что ordered_repository_names отсортирован по created_at
  → проверить, что у каждого repo заполнены analysis_target_date и analysis_target_commit_status
  → проверить, что для текущего окна подготовлены snapshot-state и temporal-delta либо явно зафиксирован baseline_missing/no_changes
  → advance --note "historical snapshot YYYY-MM-DD и temporal delta подготовлены"
```

**Для шага `analyze_repositories`** — вложенная петля, форма зависит от стратегии:

*Стратегия `per_repository` (малые продукты или нет явных доменных границ):*
```
status → получить текущий checklist-пункт → загрузить reference → выполнить
       → checklist-item completed → повторить
```

*Стратегия `per_domain` (явные бизнес-домены выявлены на предыдущем шаге):*
```
domain --start --domain-id <id>
  → для каждого репозитория домена: полный checklist (см. ниже)
  → зафиксировать находки с тегом домена в features и артефактах
domain --complete --domain-id <id> --notes "<итог домена>"
→ следующий домен
```

Для каждого репозитория строгий порядок (независимо от стратегии):
1. Добавить в очередь через `repo --register`
2. Начать через `repo --start`
3. По одному пункту checklist: загрузить reference → выполнить → `repo --checklist-item ... --checklist-status completed --notes "<findings>"`
4. Зафиксировать `main_branch`, `analyzed_commit`, `remote_head_commit`; отдельно проверить `analysis_target_date`, `analysis_target_commit`, `analysis_target_commit_status`
5. Закрыть через `repo --complete`
6. **Остановиться.** Вывести пользователю итог по репозиторию и явно попросить открыть новый чат для продолжения со следующим репозиторием. Не переходить к следующему репозиторию в текущем контексте. Пример сообщения:

   > Репозиторий `<repo>` проанализирован и зафиксирован в knowledge-артефактах и состоянии сессии.
   > Чтобы продолжить анализ следующего репозитория (`<next-repo>`), откройте новый чат и продолжайте workflow с тем же session context; если промпт показывает progress bridge path, используйте его только как вспомогательную ссылку.

7. Следующий репозиторий начинается только в новом чате.

Короткая памятка по `repo`:
- `repo --register --name <repo> --role <role> --repository-url <url> [--created-at <YYYY-MM-DD>]`
- `repo --start --name <repo>`
- `repo --checklist-item <item> --checklist-status completed --name <repo> --notes "<findings>"`
- `repo --complete --name <repo>`

Короткая памятка по `timeline`:
- `timeline --progress <path> --plan`
- `timeline --progress <path> --resolve-local`
- `timeline --progress <path> --resolve-local --checkout`
- `timeline --progress <path> --advance-window`

Короткая памятка по `domain` (все команды требуют `--repo <имя-репозитория>`):
- `domain --repo <repo> --assess --volume-class <class> --total-files <N> --strategy <per_module|per_domain>`
- `domain --repo <repo> --register --domain-id <id> --name <name> --paths "<path1,path2>" [--signal "<сигнал>"]`
- `domain --repo <repo> --add-subdomain --domain-id <id> --subdomain-id <sid> --subdomain-name <name>`
- `domain --repo <repo> --start --domain-id <id>`
- `domain --repo <repo> --complete --domain-id <id> [--notes "<итог>"]`

Нельзя завершать шаг `analyze_repositories`, пока хотя бы один `in_scope` репозиторий не имеет `analysis_status=completed`.
Нельзя завершать отдельный репозиторий, пока хотя бы один пункт его `analysis_checklist` не имеет `status=completed`.
Если `domain_map.strategy=per_domain`, нельзя завершать `analyze_repositories`, пока хотя бы один зарегистрированный домен не имеет `analysis_status=completed`.

### Маппинг: шаг workflow → reference

| Шаг `workflow` | Reference-файл |
|---|---|
| `assess_scope_and_domains` | [checklist-scope-and-domain-assessment.md](references/checklist-scope-and-domain-assessment.md) |

### Маппинг: пункт analysis_checklist → reference

| Пункт `analysis_checklist` | Reference-файл |
|---|---|
| `repository_classification` | [checklist-repository-classification.md](references/checklist-repository-classification.md) |
| `repository_structure_mapping` | [checklist-repository-structure-mapping.md](references/checklist-repository-structure-mapping.md) |
| `entrypoints_and_interfaces` | [checklist-entrypoints-and-interfaces.md](references/checklist-entrypoints-and-interfaces.md) |
| `business_flow_orchestration` | [checklist-business-flow-orchestration.md](references/checklist-business-flow-orchestration.md) |
| `configs_and_runtime` | [checklist-configs-and-runtime.md](references/checklist-configs-and-runtime.md) |
| `tech_stack_collection` | [checklist-tech-stack.md](references/checklist-tech-stack.md) |
| `contracts_and_schemas` | [checklist-contracts-and-schemas.md](references/checklist-contracts-and-schemas.md) |
| `data_and_storage` | [checklist-data-and-storage.md](references/checklist-data-and-storage.md) |
| `domain_entities` | [checklist-domain-entities.md](references/checklist-domain-entities.md) |
| `integrations_and_dependencies` | [checklist-integrations-and-dependencies.md](references/checklist-integrations-and-dependencies.md) |
| `tests_and_behavior_evidence` | [checklist-tests-and-behavior-evidence.md](references/checklist-tests-and-behavior-evidence.md) |
| `glossary_updates` + `open_questions_review_and_updates` | [checklist-glossary-and-open-questions.md](references/checklist-glossary-and-open-questions.md) |
| `feature_discovery_and_updates` + `features_index_updates` | [checklist-features-and-index.md](references/checklist-features-and-index.md) |
| `roles_and_permissions_updates` + `security_and_auth_updates` + `deployment_and_operability` + `risks_and_tech_debt_updates` | [checklist-roles-security-operability-risks.md](references/checklist-roles-security-operability-risks.md) |
| `architecture_artifact_updates` | [checklist-architecture-artifact-updates.md](references/checklist-architecture-artifact-updates.md) |
| `repository_consistency_review` | [checklist-repository-consistency-review.md](references/checklist-repository-consistency-review.md) |

## Источники фактов

**Сильные** — доверяй без дополнительной перепроверки: маршруты API / gRPC handlers / consumers / producers, интеграционные и e2e-тесты, миграции БД и схемы таблиц, OpenAPI / AsyncAPI / protobuf, Helm / Terraform / Compose / k8s manifests, код оркестрации бизнес-процесса.

**Средние** — полезны, требуют перепроверки по коду: README, `.env.example`, unit-тесты, диаграммы без признаков актуальности.

**Слабые** — только вспомогательный сигнал: названия папок без кода, комментарии без подтверждения в логике, wiki без привязки к коду.

Каждое утверждение в артефактах — одна из трёх категорий: **наблюдаемый факт** (сильный источник), **обоснованный вывод** (косвенно; помечай `выведено косвенно`), **предположение** (нет подтверждения; помечай `требует подтверждения` или `не найдено в коде`). Не оставляй утверждения без категории.

Для knowledge workflow это означает следующее:

- raw layer хранит первичные доказательства;
- synthesis layer обязан ссылаться на raw layer или явно помечать косвенный вывод;
- navigation layer не дублирует подробное содержание synthesis layer, а только указывает, где лежит знание;
- knowledge lint проверяет, что навигация не указывает на отсутствующие артефакты, а synthesis не теряет связь с источниками.
- После появления `wiki/maps/compile-report.md` knowledge lint также рассматривает compile output как quality gate: обязательные секции `wiki/index.md` и `wiki/maps/compile-report.md`, а также минимальное покрытие frontmatter и `related`-связей должны быть соблюдены до закрытия шага `run_knowledge_lint`.


## Правила работы

- По умолчанию пиши артефакты архитектурного репозитория на русском языке. Английские термины оставляй только там, где это часть точного технического имени, протокола, библиотеки, endpoint, поля, enum, заголовка, env-переменной или другого кодового идентификатора.
- Это правило действует и для коротких полей вроде `signal`, `notes`, `description` в `.yml`-артефактах — даже однострочное значение пиши как русскую фразу, а не как полностью англоязычное описание (`"HTTP handlers, routing layer"` — неверно, `"HTTP-хендлеры, слой роутинга"` — верно). Англоязычными остаются только сами имена технологий/библиотек/протоколов внутри фразы.
- Если в исходном коде или старых артефактах встречаются англоязычные описательные фразы, при обновлении старайся переводить их на естественный русский язык, сохраняя точный технический смысл.
- Если ссылаешься на кодовый файл, всегда указывай путь вместе с репозиторием, а не только внутренний путь файла. Пиши в формате вроде `<repo-name>/src/app/[locale]/news/[id]/page.tsx`, чтобы по ссылке или пути можно было сразу перейти в нужный репозиторий.
- Это обязательное требование. Не пиши пути вида только `src/app/[locale]/news/[id]/page.tsx` без указания репозитория-источника.
- Не выдумывай поведение, если оно не подтверждается кодом, тестами или конфигурацией.
- Не считай ответы пользователя автоматическим источником истины для технической реализации: сопоставляй их с уже найденными артефактами и отмечай расхождения.
- Если пользователь говорит, что поведение уже реализовано, но подтверждение не находится в коде и артефактах, прямо укажи на это и попроси показать, где именно это реализовано. Если подтверждение так и не найдено, не включай это в `as-is`.
- Если логика размазана по нескольким сервисам, сначала собери end-to-end поток, а потом детализируй части.
- Если фактическое поведение расходится с имеющейся документацией, приоритет у фактического поведения, но расхождение нужно явно отметить.
- Для каждого значимого вывода старайся иметь хотя бы один источник подтверждения.
- Если контракт публичный, старайся зафиксировать его в машиночитаемом формате, а не только текстом.
- Если репозиторий относится к категории `support` (`library`, `test-repo`, `infra` — см. `repository_classification`), не заводи для него запись в `landscape.yaml` и не создавай `features/`. Документируй его в `architecture/support-repositories.md`, чтобы не смешивать инфраструктурную/тестовую документацию с продуктовой.
- Если обнаружена внешняя интеграция, не оставляй ее только в HLD или feature-описании: выноси ее в `architecture/integrations/` в файл соответствующего сервиса с направлением вызова, назначением, ключевыми данными и способом взаимодействия.
- Если структура данных критична для потока, выноси ее в `architecture/storage/`, а не оставляй только в HLD.
- Если обнаружен термин, который агент трактует иначе, чем система, или который в продукте имеет специальный смысл, выноси его в glossary вместе с определением и источником подтверждения.
- Вопросы пользователю о функционале задавай после того, как уже собран базовый технический каркас системы и понятны конкретные пробелы, а не вместо анализа кода.
- На шаге `interview_user` задавай только один вопрос за раз. Следующий вопрос можно задавать только после того, как текущий закрыт ответом пользователя и этот ответ внесен в основной артефакт(ы) и в `open-questions.md`.
- Если в `open-questions.md` есть строки со статусом `open` и значением `yes` в колонке `Нужен ответ пользователя`, агент обязан явно вынести их в ответ пользователю и попросить ответить на них.
- Закрытый вопрос — это не только смена статуса в `open-questions.md`. Если колонка `Контекст` указывает на конкретный артефакт (фича, интеграция, контракт, хранилище, HLD и т.п.), обновляй тот артефакт новой подтвержденной информацией. Знание должно попасть в основной документ, а не остаться только в реестре вопросов.
- После каждого ответа пользователя на открытый вопрос агент обязан сначала внести все документальные правки, а уже потом задавать следующий вопрос. Нельзя накапливать серию ответов без немедленного обновления файлов.
- **Не полагайся на память вместо фактического состояния артефактов.** Прогресс-guard в этом сервисе не CLI-утилита — это состояние сессии, которое сервис ведёт сам; агент должен строго следовать шагу и reference-чеклисту, которые получает в промпте, и не пропускать обязательные пункты checklist, даже если ничего не блокирует это технически на его стороне.

## Чего не делать

- Не переписывай код в документацию построчно.
- Не смешивай текущее состояние и желаемое будущее состояние без явной пометки.
- Не объявляй систему понятой, если критичные части не подтверждены артефактами.
- Не ограничивайся одним README, если в коде есть более надежные источники фактов.
- Не подменяй пользовательский список репозиториев автоматическим анализом соседних папок в workspace.
