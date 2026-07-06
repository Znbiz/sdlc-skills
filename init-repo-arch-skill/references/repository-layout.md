# Как раскладывать файлы в репозитории

Используй эту структуру, если в репозитории нужно хранить продуктовую и архитектурную документацию по существующему продукту.

## Базовая структура

```text
repo/
├── AGENTS.md                        # Навигационный путеводитель для AI-агентов (Claude, Codex и др.)
├── CLAUDE.md                        # Точка входа для Claude Code: содержит только @AGENTS.md
├── features-index.md                # Плоский реестр текущих фич с кратким описанием и ссылками
├── glossary.md                      # Термины и определения системы
├── open-questions.md                # Открытые вопросы и пробелы, требующие закрытия
├── wiki/
│   ├── index.md                     # Короткий navigation hub по knowledge-артефактам репозитория
│   ├── log.md                       # Append-only журнал knowledge-обновлений, противоречий и follow-up
│   ├── concepts/                    # Cross-cutting knowledge pages
│   ├── summaries/                   # Короткие compiled summaries
│   └── maps/
│       └── compile-report.md        # Диагностика knowledge graph
├── release-notes/                   # Один файл на каждый завершённый прогон update-repo-arch-skill (не создаётся на этом этапе)
│   └── <YYYY-MM-DD>.md              # Дата прогона и ссылки на обновлённые файлы — заполняется только update-repo-arch-skill
├── features/                        # Продуктовые и бизнесовые описания текущих фич
│   └── 0001-example-feature.md      # Одна фича или capability в одном файле
├── architecture/                    # Архитектурные артефакты по текущему состоянию системы
│   ├── constraints.md               # Ограничения системы и реализации
│   ├── requirements.md              # Наблюдаемые или выведенные ФТ и НФТ
│   ├── hld.md                       # High-level design текущего решения
│   ├── landscape.yaml               # Карта сервисов, хранилищ и связей
│   ├── roles-and-permissions.md     # Роли и матрица функционала
│   ├── security.md                  # Модель аутентификации, границы доверия, чувствительные данные
│   ├── risks.md                     # Известные риски и технический долг
│   ├── domain-entities.md           # Ключевые бизнес-сущности: поля видимые пользователю и backend_only
│   ├── tech-stack.md                # Ключевые технологии и архитектурно значимые зависимости
│   ├── support-repositories.md      # Реестр library/test-repo/infra репозиториев, отдельно от продуктовых
│   ├── structure/                   # Карта структуры каждого репозитория: путь → техническая категория
│   │   └── <repo>.yml               # API/UI-экраны, контракты, БД/очереди, интеграции, безопасность, конфиги, деплой, техстек
│   ├── integrations-overview.md     # Обзор всех интеграций
│   ├── integrations/                # Детализация интеграций по сервисам
│   │   └── <service>.md             # Один файл на сервис со всеми входящими и исходящими интеграциями
│   ├── contracts/                   # Машиночитаемые контракты интерфейсов
│   │   ├── <sync-api>.yml           # OpenAPI для синхронного API
│   │   └── <async-events>.yml       # AsyncAPI для событий и асинхронных взаимодействий
│   └── storage/                     # Описание БД, кэшей, топиков и других хранилищ
│       └── <storage>.yml            # Один файл на одно хранилище или логическую схему
```

## Шаблоны и соответствующие артефакты

Шаблоны хранятся в `assets/` skill и используются только для генерации целевых файлов. В продуктовый репозиторий попадают только заполненные артефакты, сами шаблоны туда не копируются.

| Артефакт в репозитории | Шаблон | Когда создавать |
| --- | --- | --- |
| `AGENTS.md` | `assets/AGENTS-template.md` | После завершения анализа — заполни название системы и раздел «Текущие сервисы» |
| `CLAUDE.md` | `assets/CLAUDE-template.md` | Один раз при инициализации — содержит только `@AGENTS.md`, редактировать не нужно |
| `wiki/index.md` | `assets/index-template.md` | После появления первых knowledge-артефактов; затем обновляется как короткая точка входа |
| `wiki/log.md` | `assets/knowledge-log-template.md` | После первого значимого прогона анализа; затем обновляется append-only записями |
| `wiki/maps/compile-report.md` | создаётся через `analysis_guard bootstrap` или `analysis_guard compile` | При инициализации wiki-слоя как stub, затем пересобирается compile-командой |
| `features-index.md` | `assets/features-index-template.md` | При выделении первой фичи, затем обновляется при каждом новом репозитории |
| `open-questions.md` | `assets/open-questions-template.md` | При первом же пробеле, который нельзя закрыть из кода |
| `release-notes/<YYYY-MM-DD>.md` | `assets/release-note-template.md` в `update-repo-arch-skill` | Не создаётся этим skill — папку и первый файл заводит `update-repo-arch-skill` на шаге `finalize_update` после первого прогона обновления |
| `features/<name>.md` | `assets/feature-template.md` | Один файл на каждую выделенную capability |
| `architecture/hld.md` | `assets/architecture/hld-template.md` | При первом репозитории, затем дополняется |
| `architecture/landscape.yaml` | `assets/architecture/landscape-template.yaml` | При первом репозитории — сервис, technology, зависимости |
| `architecture/tech-stack.md` | `assets/architecture/tech-stack-template.md` | После сбора стека каждого сервиса |
| `architecture/support-repositories.md` | `assets/architecture/support-repositories-template.md` | Когда классифицирован первый репозиторий категории `support` (`library`/`test-repo`/`infra`) |
| `architecture/structure/<repo>.yml` | `assets/architecture/repo-structure-map-template.yml` | На пункте `repository_structure_mapping`, сразу после `repository_classification`, до глубокого анализа репозитория |
| `architecture/constraints.md` | `assets/architecture/constraints-template.md` | Когда обнаружены технические или организационные ограничения |
| `architecture/requirements.md` | `assets/architecture/requirements-template.md` | Когда подтверждены ФТ или НФТ из кода, конфигурации или тестов |
| `architecture/glossary.md` | `assets/architecture/glossary-template.md` | При первом специфичном или переопределённом термине |
| `architecture/roles-and-permissions.md` | `assets/architecture/roles-and-permissions-template.md` | Когда обнаружены роли, RBAC/ABAC или auth middleware |
| `architecture/security.md` | `assets/architecture/security-template.md` | Когда определены auth-механизмы или границы доверия |
| `architecture/domain-entities.md` | `assets/architecture/domain-entities-template.md` | После прохода по всем репозиториям — ключевые бизнес-сущности с разметкой видимости полей |
| `architecture/risks.md` | `assets/architecture/risks-template.md` | Когда найден технический долг, уязвимость или архитектурный риск |
| `architecture/integrations-overview.md` | `assets/architecture/integrations-overview-template.md` | После первой интеграции, затем обновляется |
| `architecture/integrations/<service>.md` | `assets/architecture/integration-template.md` | Один файл на сервис со всеми входящими и исходящими интеграциями |
| `architecture/contracts/<service>-sync.yml` | `assets/architecture/contract-template.yml` | Когда восстановлен синхронный (HTTP/gRPC) контракт |
| `architecture/contracts/<service>-async.yml` | `assets/architecture/async-contract-template.yml` | Когда восстановлены события или Kafka-топики |
| `architecture/storage/<service>.yml` | `assets/architecture/storage-template.yml` | Когда найдены БД, кэши, файловые хранилища |

## Слои знания

Структура репозитория семантически делится на четыре слоя:

- **Raw layer**: `.temp/<repo>/` и другие первичные источники фактов.
- **Synthesis layer**: `features/`, `architecture/`, `glossary.md`, `open-questions.md`, `features-index.md`.
- **Navigation layer**: `AGENTS.md`, `wiki/index.md`, `wiki/log.md`, `wiki/maps/compile-report.md`, `architecture/integrations-overview.md`.
- **Knowledge lint**: проверки, которые подтверждают связность этих слоёв.

Связь слоёв должна быть однонаправленной:

`raw layer -> synthesis layer -> navigation layer`

Navigation-файлы не заменяют synthesis-артефакты и не должны хранить длинные аналитические описания, которые уже есть в `features/` или `architecture/`.
Детали wiki-структуры описаны в [wiki-layout.md](wiki-layout.md).

## Frontmatter и compile-ready metadata

Для markdown-артефактов используй YAML frontmatter с полями:

- `title`
- `type`
- `sources`
- `related`
- `created`
- `updated`
- `confidence`
- `domain`
- `repositories`

Этот frontmatter не заменяет читаемое markdown-содержимое, а делает артефакты
машиночитаемыми для `analysis_guard compile`, который собирает `wiki/index.md`
и `wiki/maps/compile-report.md`.

## Как ссылаться на исходный код

Если в документации, feature-описаниях, HLD, glossary, ролях, интеграциях или вопросах на уточнение ты ссылаешься на исходный код, всегда указывай путь вместе с репозиторием-источником.

Правильно:

- `frontend-web/src/app/[locale]/news/[id]/page.tsx`
- `billing-service/internal/app/usecases/create_invoice.go`

Неправильно:

- `src/app/[locale]/news/[id]/page.tsx`
- `internal/app/usecases/create_invoice.go`

Это обязательное требование, потому что архитектурный репозиторий собирается по нескольким репозиториям, и путь без имени репозитория не позволяет надежно перейти к источнику факта.

## Порядок наполнения

1. Сначала собери список репозиториев в scope и зафиксируй предполагаемую роль каждого.
2. Для каждого репозитория сразу после классификации построй карту структуры — `architecture/structure/<repo>.yml`: какие пути отвечают за API/UI-экраны, контракты, БД/очереди, интеграции, безопасность, конфиги, деплой, техстек. Эта карта — основной источник точного дельта-анализа в `update-repo-arch-skill`.
3. Затем проходи репозитории по одному и после каждого прохода обновляй `architecture/hld.md`, `architecture/landscape.yaml`, `architecture/tech-stack.md`, `glossary.md`, `open-questions.md`, `architecture/roles-and-permissions.md` и `features-index.md`.
4. После появления первых артефактов создай или обнови `wiki/index.md`, чтобы у knowledge-слоя появилась короткая navigation entrypoint.
   Для первичного scaffold используй `analysis_guard bootstrap`, а не ручное создание каталогов.
5. После каждого существенного пополнения knowledge-слоя добавляй запись в `wiki/log.md`: что создано, что изменено, какие противоречия или gaps остались.
6. По мере появления фактов выноси интеграции в `architecture/integrations/`.
7. По мере появления подтверждений собирай контракты в `architecture/contracts/`.
8. По мере появления структуры данных описывай хранилища в `architecture/storage/`.
9. По мере появления новых capability создавай или уточняй документы в `features/`.
10. После прохода по доступным репозиториям провалидируй согласованность артефактов между собой и с исходными репозиториями.
11. Затем собери список открытых вопросов и пробелов.
12. Затем уточни пробелы у пользователя.
13. Перед завершением еще раз провалидируй итоговую картину.

## Quality Gates compile output

Если в репозитории уже создан `wiki/maps/compile-report.md`, то knowledge lint рассматривает compile output как обязательный артефакт качества:

- `wiki/index.md` должен содержать секции `Что читать первым`, `Артефакты по типам`, `Related Artifacts`, `Graph Gaps`, `Quality Gates`, `Compile Rules`;
- `wiki/maps/compile-report.md` должен содержать секции `Summary`, `Coverage`, `Quality Gates`, `Unresolved References`, `Weakly Linked Pages`, `Link Graph`, `Document Metadata`;
- покрытие frontmatter по compile-участвующим markdown-документам должно быть не ниже 50%;
- покрытие `related` среди документов с frontmatter должно быть не ниже 50%.
