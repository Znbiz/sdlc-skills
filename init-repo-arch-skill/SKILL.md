---
name: init-repo-arch-skill
description: Инициализация и первичное наполнение архитектурного репозитория по уже существующему продукту или системе. Use when the user wants to reconstruct the current architecture from code and configuration, describe current features, integrations, contracts, storages, and populate an architecture repository for the as-is state. Suitable for reverse engineering, brownfield analysis, architecture audit, and first-pass arch repo filling. Do not use for designing a new target solution or planning a feature change from scratch; use `new-feature-arch-skill` for to-be design.
license: MIT
metadata:
  author: Nekrasov ALeksei
  version: "2.0"
---

# Навык анализа существующего продукта

Используй этот навык, когда система уже существует, а задача состоит не в проектировании новой фичи с нуля, а в восстановлении и структурировании текущего состояния продукта и архитектуры.

## Граница применения

Используй этот skill, когда нужно описать `as-is` состояние.

Не используй его как основной skill для проектирования нового поведения системы. Если текущее состояние уже восстановлено и дальше нужно спроектировать изменение, переходи к `new-feature-arch-skill`.

## Шаблоны и структура репозитория

Если нужно наполнить архитектурный репозиторий, используй шаблоны из `assets/` этого skill.

Не копируй каталог `assets/` в продуктовый репозиторий. Шаблоны нужны skill как источник для создания артефактов, а не как часть целевой структуры `architecture`-репозитория.

Для временных клонов репозиториев используй локальный каталог `.temp/` в текущем workspace. Если каталога нет, создай его. Эту папку нужно держать в `.gitignore`, чтобы временные checkout'ы не попадали в git.

Для обязательного пошагового исполнения workflow используй `scripts/analysis_guard.py`. Это не опциональная утилита, а основной механизм управления прогрессом анализа и защиты от пропуска этапов.

Шаблон progress-файла: `assets/repo-initialization-progress-template.yaml`.

Структура репозитория и соответствие шаблонов артефактам — в [references/repository-layout.md](references/repository-layout.md).

## Обязательный guard workflow

Этот skill нужно исполнять в режиме `low freedom`: переход между этапами анализа должен идти через `scripts/analysis_guard.py`, а не только через текстовые инструкции в голове агента.

Минимальный цикл работы:

1. Создай progress-файл через `python .agents/skills/init-repo-arch-skill/scripts/analysis_guard.py init ...`.
2. Перед началом каждого нового этапа вызывай `... status` или `... validate` и сверяй текущий шаг.
3. Не переходи к следующему этапу, пока текущий не завершен в progress-файле.
4. После завершения этапа переводи workflow дальше через `... advance`.
5. Если скрипт показывает ошибку консистентности или нарушение обязательных предусловий, сначала исправь progress-файл или артефакты, и только потом продолжай анализ.

Рекомендуемый CLI минимален. По умолчанию агент должен использовать только 4 команды:

- `python .agents/skills/init-repo-arch-skill/scripts/analysis_guard.py init --output <path> --product <name> --scope <scope>`
- `python .agents/skills/init-repo-arch-skill/scripts/analysis_guard.py status --progress <path>`
- `python .agents/skills/init-repo-arch-skill/scripts/analysis_guard.py repo ...`
- `python .agents/skills/init-repo-arch-skill/scripts/analysis_guard.py advance --progress <path> --note "<что завершено>"`

Перед первым вызовом `status`, `validate`, `repo` или `advance` агент обязан определить фактический путь к progress-файлу в текущем workspace.

Если progress-файл уже существует, нужно использовать именно его фактическое имя и путь. По умолчанию progress-файл с работой скилла это `repo-initialization-progress.yaml`.

Команда `validate` и низкоуровневые `register-repo`, `start-repo`, `update-repo-checklist`, `complete-repo` допустимы как служебные или для отладки, но не должны быть основным интерфейсом skill.

Если workflow в progress-файле и фактические действия расходятся, источником истины считается не память агента, а проверяемый progress-файл и результаты `validate`.

## Петля исполнения: один шаг за раз

Скилл работает в режиме **одного шага за раз**. Не читай весь checklist заранее. Не переходи к следующему шагу, пока текущий не закрыт в progress-файле.

**Для шагов верхнего уровня** (`workflow.steps`):
```
status → загрузить reference → выполнить один шаг → advance → повторить
```

**Для шага `analyze_repositories`** — вложенная петля по `analysis_checklist`:
```
status → получить текущий checklist-пункт → загрузить reference для пункта → выполнить → checklist-item completed → повторить
```

Для каждого репозитория строгий порядок:
1. Добавить в очередь через `repo --register`
2. Начать через `repo --start`
3. По одному пункту checklist: загрузить reference → выполнить → `repo --checklist-item ... --checklist-status completed --notes "<findings>"`
4. Зафиксировать `main_branch`, `analyzed_commit`, `remote_head_commit`
5. Закрыть через `repo --complete`
6. Только потом — следующий репозиторий

Короткая памятка по `repo`:
- `repo --register --name <repo> --role <role> --repository-url <url>`
- `repo --start --name <repo>`
- `repo --checklist-item <item> --checklist-status completed --name <repo> --notes "<findings>"`
- `repo --complete --name <repo>`

Нельзя завершать шаг `analyze_repositories`, пока хотя бы один `in_scope` репозиторий не имеет `analysis_status=completed`.
Нельзя завершать отдельный репозиторий, пока хотя бы один пункт его `analysis_checklist` не имеет `status=completed`.

### Маппинг: пункт analysis_checklist → reference

| Пункт `analysis_checklist` | Reference-файл |
|---|---|
| `repository_characterization` | [checklist-repository-characterization.md](references/checklist-repository-characterization.md) |
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


## Правила работы

- Если ссылаешься на кодовый файл, всегда указывай путь вместе с репозиторием, а не только внутренний путь файла. Пиши в формате вроде `<repo-name>/src/app/[locale]/news/[id]/page.tsx`, чтобы по ссылке или пути можно было сразу перейти в нужный репозиторий.
- Это обязательное требование. Не пиши пути вида только `src/app/[locale]/news/[id]/page.tsx` без указания репозитория-источника.
- Не выдумывай поведение, если оно не подтверждается кодом, тестами или конфигурацией.
- Не считай ответы пользователя автоматическим источником истины для технической реализации: сопоставляй их с уже найденными артефактами и отмечай расхождения.
- Если пользователь говорит, что поведение уже реализовано, но подтверждение не находится в коде и артефактах, прямо укажи на это и попроси показать, где именно это реализовано. Если подтверждение так и не найдено, не включай это в `as-is`.
- Если логика размазана по нескольким сервисам, сначала собери end-to-end поток, а потом детализируй части.
- Если фактическое поведение расходится с имеющейся документацией, приоритет у фактического поведения, но расхождение нужно явно отметить.
- Для каждого значимого вывода старайся иметь хотя бы один источник подтверждения.
- Если контракт публичный, старайся зафиксировать его в машиночитаемом формате, а не только текстом.
- Если обнаружена внешняя интеграция, не оставляй ее только в HLD или feature-описании: выноси ее в `architecture/integrations/` в файл соответствующего сервиса с направлением вызова, назначением, ключевыми данными и способом взаимодействия.
- Если структура данных критична для потока, выноси ее в `architecture/storage/`, а не оставляй только в HLD.
- Если обнаружен термин, который агент трактует иначе, чем система, или который в продукте имеет специальный смысл, выноси его в glossary вместе с определением и источником подтверждения.
- Вопросы пользователю о функционале задавай после того, как уже собран базовый технический каркас системы и понятны конкретные пробелы, а не вместо анализа кода.
- Если в `open-questions.md` есть строки со статусом `open` и значением `yes` в колонке `Нужен ответ пользователя`, агент обязан явно вынести их в ответ пользователю и попросить ответить на них.
- Закрытый вопрос — это не только смена статуса в `open-questions.md`. Если колонка `Контекст` указывает на конкретный артефакт (фича, интеграция, контракт, хранилище, HLD и т.п.), обновляй тот артефакт новой подтвержденной информацией. Знание должно попасть в основной документ, а не остаться только в реестре вопросов.
- **Не обходи `scripts/analysis_guard.py`, если задача реально идет по полному workflow этого skill. Для длинного анализа отсутствие progress-guard считается ошибкой исполнения skill.**

## Чего не делать

- Не переписывай код в документацию построчно.
- Не смешивай текущее состояние и желаемое будущее состояние без явной пометки.
- Не объявляй систему понятой, если критичные части не подтверждены артефактами.
- Не ограничивайся одним README, если в коде есть более надежные источники фактов.
- Не подменяй пользовательский список репозиториев автоматическим анализом соседних папок в workspace.
