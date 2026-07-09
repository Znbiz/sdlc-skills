# AGENTS.md для архитектурного репозитория <название системы>

Этот файл — operational entrypoint для AI-агентов. Читай его первым. Он объясняет, где лежит source of truth, что открывать дальше и как работать с knowledge-слоем, не сканируя репозиторий вслепую.

## Что читать первым

1. `AGENTS.md` — правила работы и режимы операций.
2. `wiki/index.md` — короткий navigation hub по knowledge-артефактам.
3. Нужные детальные артефакты из `features/`, `architecture/`, `glossary.md`, `open-questions.md`.

Если `wiki/index.md` ещё не создан, используй `features-index.md` и `architecture/hld.md` как временные точки входа.

## Source of Truth

### Raw layer

- `.temp/<repo>/` и другие checkout'ы исходных репозиториев;
- код, конфиги, контракты, тесты, миграции, deployment manifests;
- внешние источники, если они явно сохранены как ссылки или отмечены в knowledge-артефактах.

Правило:

- raw layer читается как исходный материал;
- `.temp/` не редактируется как knowledge-слой;
- наблюдаемые факты должны быть восстанавливаемы по raw layer или по явно указанному внешнему источнику.

### Synthesis layer

- `features/`
- `architecture/`
- `glossary.md`
- `open-questions.md`
- `features-index.md`

Здесь фиксируется уже синтезированное знание: подтверждённые факты, косвенные выводы, пробелы и трассировка.

### Navigation layer

- `AGENTS.md`
- `wiki/index.md`
- `wiki/log.md`
- `wiki/maps/compile-report.md`
- `architecture/integrations-overview.md`

Navigation layer не дублирует полные описания, а только помогает быстро найти нужный synthesis-артефакт.

## Структура репозитория

```text
AGENTS.md                              # этот файл
CLAUDE.md                              # ссылается на AGENTS.md
wiki/index.md                          # короткий навигационный индекс knowledge-слоя
wiki/log.md                            # append-only журнал knowledge-изменений
wiki/maps/compile-report.md            # диагностика связности knowledge graph
features-index.md                      # реестр всех фич (индекс -> feature-файлы)
glossary.md                            # термины и определения платформы
open-questions.md                      # открытые вопросы, требующие ответа команды

features/
  <NNNN>-<slug>.md                     # детальное описание конкретной фичи

architecture/
  hld.md                               # общий обзор архитектуры + контекстная диаграмма
  tech-stack.md                        # технологии и зависимости по сервисам
  integrations-overview.md             # карта всех интеграций (индекс -> detail-файлы)
  roles-and-permissions.md             # роли пользователей и матрица доступов
  security.md                          # аутентификация и границы доверия
  risks.md                             # известные риски и технический долг
  landscape.yaml                       # machine-readable реестр всех сервисов

  integrations/<service>.md            # детали интеграций конкретного сервиса
  contracts/<service>-sync.yml         # синхронные API-контракты сервиса
  contracts/<service>-async.yml        # асинхронные контракты сервиса
  storage/<service>.yml                # схемы хранилищ сервиса
```

## Operations

### Ingest

Используй этот режим, когда нужно пополнить или уточнить knowledge-слой по коду и конфигам.

Порядок:

1. Читать raw layer.
2. Обновлять synthesis layer.
3. Обновлять `wiki/index.md`, если появился новый важный артефакт.
4. Добавлять запись в `wiki/log.md`, если были значимые изменения, противоречия или новые gaps.

### Query

Используй этот режим, когда нужно ответить на вопрос по уже собранной базе знаний.

Порядок:

1. Начать с `wiki/index.md`.
2. Перейти в нужный synthesis-артефакт.
3. При недостатке уверенности спуститься до raw layer и перепроверить факт.

### Lint

Используй этот режим, когда нужно проверить консистентность knowledge-слоя.

Минимальные проверки:

- ссылки из `wiki/index.md` и обзорных файлов ведут на существующие артефакты;
- фичи отражены в `features-index.md`;
- открытые вопросы не потеряны и не противоречат уже зафиксированным фактам;
- описания в synthesis layer не ссылаются на кодовые пути без имени репозитория.

## Правила трассировки и gaps

- Каждое значимое утверждение должно быть либо наблюдаемым фактом, либо помеченным косвенным выводом, либо явным предположением.
- Если факт не подтверждается кодом или конфигами, не поднимай его до наблюдаемого факта.
- Если пробел нельзя закрыть из raw layer, фиксируй его в `open-questions.md`.
- Если был существенный сдвиг в knowledge-слое, отражай его в `wiki/log.md`.

## С чего начинать по типу задачи

| Вопрос / задача | Открой сначала | Затем при необходимости |
| --- | --- | --- |
| Как устроена система в целом | `wiki/index.md` | `architecture/hld.md`, `architecture/integrations-overview.md` |
| Что умеет платформа | `wiki/index.md` | `features-index.md`, `features/<id>-<slug>.md` |
| Кто с кем интегрируется | `wiki/index.md` | `architecture/integrations-overview.md`, `architecture/integrations/<service>.md` |
| API-контракт сервиса | `wiki/index.md` | `architecture/contracts/<service>-sync.yml` |
| Событийный контракт | `wiki/index.md` | `architecture/contracts/<service>-async.yml` |
| Схема БД или хранилища | `wiki/index.md` | `architecture/storage/<service>.yml` |
| Технологии сервиса | `wiki/index.md` | `architecture/tech-stack.md` |
| Роли и права | `wiki/index.md` | `architecture/roles-and-permissions.md` |
| Аутентификация и доверие | `wiki/index.md` | `architecture/security.md` |
| Технический долг и риски | `wiki/index.md` | `architecture/risks.md` |
| Термин или аббревиатура | `wiki/index.md` | `glossary.md` |
| Что ещё не выяснено | `wiki/index.md` | `open-questions.md` |

## Текущие сервисы

<!-- Заполни по итогам анализа, сгруппировав по типу -->

**Frontend:** `<service>`, `<service>`

**Backend:** `<service>`, `<service>`

**Инфраструктура:** `<service>`

## Как добавлять изменения

### Новая фича

1. Добавь строку в `features-index.md`.
2. Создай `features/<следующий-номер>-<slug>.md`.
3. Обнови связанные интеграции, контракты, storage и HLD.
4. Обнови `wiki/index.md`, если фича меняет карту знаний.
5. Добавь запись в `wiki/log.md`, если появились новые gaps, противоречия или важные выводы.

### Новый сервис

1. Добавь запись в `architecture/landscape.yaml`.
2. Создай `architecture/integrations/<service>.md`.
3. Обнови `architecture/tech-stack.md`.
4. Обнови `architecture/integrations-overview.md` и `architecture/hld.md`.
5. При наличии хранилища создай `architecture/storage/<service>.yml`.
6. При наличии контрактов создай `architecture/contracts/<service>-sync.yml` и/или `<service>-async.yml`.
7. Обнови `wiki/index.md` и раздел «Текущие сервисы».
