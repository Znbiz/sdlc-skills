# Workflow Docs

Этот каталог хранит рабочую документацию по backend workflow и связанным transport-facade слоям в `arch-docs`.

## Правила ведения

- один файл на один workflow;
- имя файла совпадает с доменной операцией: `init.md`, `update.md`, `query.md`;
- документ описывает текущую фактическую реализацию, а не только целевую архитектуру;
- если реализация расходится с целевым дизайном, расхождение фиксируется явно в разделе `Known Gaps`;
- sequence diagrams и state machine обновляются вместе с изменением workflow-логики.

## Текущие документы

- [init.md](./init.md) — workflow первичной инициализации архитектурной документации, включая service-driven historical prep, knowledge pipeline и единый REST/RPC/MCP runtime path.
- [openai-facade.md](./openai-facade.md) — OpenAI-compatible facade поверх conversation-first backend contract для `init_arch`, `update_arch` и `query`.

## Рекомендуемый шаблон

Каждый workflow-файл должен содержать:

1. назначение;
2. entrypoints;
3. state machine;
4. sequence diagram;
5. ключевые компоненты;
6. state и артефакты;
7. pause/resume semantics;
8. quality gates;
9. audit/events;
10. known gaps;
11. ссылки на код и связанные документы.
