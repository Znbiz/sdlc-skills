# Индекс знаний по системе <название системы>

Этот файл — короткая точка входа в knowledge-слой. Он не дублирует детали из `features/` и `architecture/`, а показывает, где искать нужный артефакт.

## Что читать первым

1. `AGENTS.md` — operational entrypoint и правила работы с knowledge-слоем.
2. `wiki/index.md` — навигация по уже собранным артефактам.
3. Нужный детальный артефакт из разделов ниже.

## Обзор системы

- Краткое описание продукта: `<1-2 предложения>`
- Текущий статус покрытия: `<что уже восстановлено, что ещё в работе>`
- Основные репозитории в scope: `<repo-1>`, `<repo-2>`

## Фичи

- [Реестр фич](../features-index.md) — короткий список всех выделенных capability.
- Ключевые фичи:
  - `[<feature-1>](../features/<file>.md)` — `<1 предложение о назначении>`
  - `[<feature-2>](../features/<file>.md)` — `<1 предложение о назначении>`

## Архитектура

- [HLD](../architecture/hld.md) — общий обзор системы и основных потоков.
- [Ландшафт сервисов](../architecture/landscape.yaml) — машиночитаемая карта сервисов и зависимостей.
- [Технологический стек](../architecture/tech-stack.md) — ЯП, фреймворки, transport, observability.
- [Роли и доступы](../architecture/roles-and-permissions.md) — роли пользователей и границы функционала.
- [Безопасность](../architecture/security.md) — auth, trust boundaries, чувствительные данные.
- [Риски](../architecture/risks.md) — известные architectural gaps и техдолг.

## Интеграции, контракты и данные

- [Обзор интеграций](../architecture/integrations-overview.md) — входящие и исходящие интеграции по сервисам.
- Интеграции по сервисам:
  - `[<service>](../architecture/integrations/<service>.md)` — `<какие внешние или внутренние связи описаны>`
- Контракты:
  - `../architecture/contracts/<service>-sync.yml`
  - `../architecture/contracts/<service>-async.yml`
- Хранилища:
  - `../architecture/storage/<service>.yml`

## Термины и открытые вопросы

- [Глоссарий](../glossary.md) — продуктовые и технические термины.
- [Открытые вопросы](../open-questions.md) — gaps, которые не удалось закрыть из кода.

## Support-репозитории

- [Support repositories](../architecture/support-repositories.md) — библиотеки, infra и test-repo, которые не оформляются как продуктовые фичи.

## Артефакты по типам

- `<тип документа>`:
  - `[<артефакт>](../<path>.md)` — `<короткое пояснение>`

## Related Artifacts

- `features/<file>.md` -> `architecture/<artifact>.md`

## Graph Gaps

- Missing related references: `не собраны`
- Weakly linked pages: `не собраны`

## Quality Gates

- Required sections gate: `pending`
- Frontmatter coverage gate: `pending`
- Related coverage gate: `pending`

## Knowledge log

- [Журнал knowledge-обновлений](./log.md) — когда и почему менялся knowledge-слой, какие противоречия и follow-up остались.

## Compile Rules

- Navigation layer должен пересобираться через `analysis_guard compile` после существенных изменений knowledge graph.
- `wiki/index.md` и `wiki/maps/compile-report.md` должны оставаться синхронизированными.

## Правило обновления

Обновляй `wiki/index.md`, когда появляется хотя бы один новый или существенно изменённый артефакт в одной из групп:

- `features/` или `features-index.md`;
- `architecture/integrations/`, `architecture/contracts/`, `architecture/storage/`;
- `architecture/support-repositories.md`;
- `glossary.md` или `open-questions.md`, если появился новый существенный пробел или термин.
