# Навигация по архитектурному репозиторию <название системы>

Этот файл — путеводитель для AI-агентов. Читай его первым, чтобы сразу открыть нужный файл, а не сканировать репозиторий целиком.

## Структура репозитория

```
AGENTS.md                              # этот файл — точка входа для любого агента
features-index.md                      # реестр всех фич (индекс → feature-файлы)
glossary.md                            # термины и определения платформы
open-questions.md                      # открытые вопросы, требующие ответа команды

features/
  <NNNN>-<slug>.md                     # детальное описание конкретной фичи

architecture/
  hld.md                               # общий обзор архитектуры + контекстная диаграмма
  tech-stack.md                        # технологии и зависимости по сервисам
  integrations-overview.md             # карта всех интеграций (индекс → detail-файлы)
  roles-and-permissions.md             # роли пользователей и матрица доступов
  security.md                          # аутентификация и границы доверия
  risks.md                             # известные риски и технический долг
  landscape.yaml                       # machine-readable реестр всех сервисов

  integrations/<service>.md            # детали интеграций конкретного сервиса
  contracts/<service>-sync.yml         # синхронные API-контракты сервиса (OpenAPI/REST)
  contracts/<service>-async.yml        # асинхронные контракты сервиса (Kafka/events)
  storage/<service>.yml                # схемы хранилищ сервиса (БД, S3, Redis)
```

## С чего начинать по типу задачи

| Вопрос / задача | Открой сначала | Затем при необходимости |
| --- | --- | --- |
| Как устроена система в целом | `architecture/hld.md` | `architecture/integrations-overview.md` |
| Что умеет платформа (список фич) | `features-index.md` | `features/<id>-<slug>.md` |
| Детали конкретной фичи | `features-index.md` → нужный файл | интеграции задействованных сервисов |
| Кто с кем интегрируется | `architecture/integrations-overview.md` | `architecture/integrations/<service>.md` |
| API-контракт сервиса | `architecture/contracts/<service>-sync.yml` | |
| Событийный контракт (Kafka/events) | `architecture/contracts/<service>-async.yml` | |
| Схема БД или хранилища | `architecture/storage/<service>.yml` | |
| Технологии конкретного сервиса | `architecture/tech-stack.md` | |
| Роли и права пользователей | `architecture/roles-and-permissions.md` | |
| Аутентификация, JWT, SSO | `architecture/security.md` | |
| Технический долг и риски | `architecture/risks.md` | |
| Термин или аббревиатура | `glossary.md` | |
| Что ещё не выяснено | `open-questions.md` | |
| Список всех сервисов | `architecture/landscape.yaml` | |

## Текущие сервисы

<!-- Заполни по итогам анализа, сгруппировав по типу -->

**Frontend:** `<service>`, `<service>`

**Backend:** `<service>`, `<service>`

**Инфраструктура:** `<service>`

## Как добавить новую фичу

1. Добавь строку в `features-index.md`
2. Создай `features/<следующий-номер>-<slug>.md` по образцу существующих файлов
3. Обнови `architecture/integrations/<service>.md` для затронутых сервисов
4. Если появился новый API или event — добавь/обнови `architecture/contracts/<service>-*.yml`

## Как добавить новый сервис

1. Добавь запись в `architecture/landscape.yaml`
2. Создай `architecture/integrations/<service>.md`
3. Добавь строки в `architecture/tech-stack.md`
4. Обнови карту в `architecture/integrations-overview.md`
5. Обнови диаграмму в `architecture/hld.md`
6. При наличии хранилища — создай `architecture/storage/<service>.yml`
7. При наличии контрактов — создай `architecture/contracts/<service>-sync.yml` и/или `<service>-async.yml`
8. Обнови раздел «Текущие сервисы» в этом файле (`AGENTS.md`)
