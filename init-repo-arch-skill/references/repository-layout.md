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
| `features-index.md` | `assets/features-index-template.md` | При выделении первой фичи, затем обновляется при каждом новом репозитории |
| `open-questions.md` | `assets/open-questions-template.md` | При первом же пробеле, который нельзя закрыть из кода |
| `features/<name>.md` | `assets/feature-template.md` | Один файл на каждую выделенную capability |
| `architecture/hld.md` | `assets/architecture/hld-template.md` | При первом репозитории, затем дополняется |
| `architecture/landscape.yaml` | `assets/architecture/landscape-template.yaml` | При первом репозитории — сервис, technology, зависимости |
| `architecture/tech-stack.md` | `assets/architecture/tech-stack-template.md` | После сбора стека каждого сервиса |
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
2. Затем проходи репозитории по одному и после каждого прохода обновляй `architecture/hld.md`, `architecture/landscape.yaml`, `architecture/tech-stack.md`, `glossary.md`, `open-questions.md`, `architecture/roles-and-permissions.md` и `features-index.md`.
3. По мере появления фактов выноси интеграции в `architecture/integrations/`.
4. По мере появления подтверждений собирай контракты в `architecture/contracts/`.
5. По мере появления структуры данных описывай хранилища в `architecture/storage/`.
6. По мере появления новых capability создавай или уточняй документы в `features/`.
7. После прохода по доступным репозиториям провалидируй согласованность артефактов между собой и с исходными репозиториями.
8. Затем собери список открытых вопросов и пробелов.
9. Затем уточни пробелы у пользователя.
10. Перед завершением еще раз провалидируй итоговую картину.
