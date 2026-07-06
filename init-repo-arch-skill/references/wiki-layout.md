# Wiki Layout

Этот document фиксирует единственную рабочую структуру knowledge-слоя skill.

## Структура

```text
repo/
├── AGENTS.md
├── wiki/
│   ├── index.md
│   ├── log.md
│   ├── concepts/
│   ├── summaries/
│   └── maps/
│       └── compile-report.md
├── features/
├── architecture/
├── glossary.md
└── open-questions.md
```

## Роли каталогов

- `wiki/index.md` — primary navigation entrypoint для агента;
- `wiki/log.md` — append-only журнал изменений knowledge-слоя;
- `wiki/concepts/` — устойчивые cross-cutting страницы по доменам и терминам;
- `wiki/summaries/` — короткие compiled summaries по потокам или сервисам;
- `wiki/maps/compile-report.md` — диагностика качества knowledge graph.

## Compile workflow

- `analysis_guard bootstrap` создаёт `wiki/`, `wiki/maps/` и стартовые файлы navigation layer;
- `analysis_guard index` собирает короткий navigation hub в `wiki/index.md`;
- `analysis_guard compile` пересобирает `wiki/index.md` и
  `wiki/maps/compile-report.md` по frontmatter, markdown links, wikilinks и
  metadata `related`;
- `analysis_guard lint` проверяет связность wiki-слоя, unresolved references,
  orphan pages и knowledge debt.

## Quality Gates

После появления `wiki/maps/compile-report.md` compile output считается проверяемым артефактом:

- `wiki/index.md` обязан содержать секции `Что читать первым`, `Артефакты по типам`, `Related Artifacts`, `Graph Gaps`, `Quality Gates`, `Compile Rules`;
- `wiki/maps/compile-report.md` обязан содержать секции `Summary`, `Coverage`, `Quality Gates`, `Unresolved References`, `Weakly Linked Pages`, `Link Graph`, `Document Metadata`;
- frontmatter coverage по compile-участвующим markdown-страницам должен быть не ниже 50%;
- coverage `related` среди страниц с frontmatter должен быть не ниже 50%;
- нарушения этих правил считаются блокирующими `ERROR` для шага `run_knowledge_lint`.

## Metadata

Markdown-артефакты используют YAML frontmatter:

- `title`
- `type`
- `sources`
- `related`
- `created`
- `updated`
- `confidence`
- `domain`
- `repositories`
