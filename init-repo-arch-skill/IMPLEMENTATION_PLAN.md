# План развития `init-repo-arch-skill`

Документ основан на:

- [SKILL.md](/Users/aanekraso2/github.com/znbiz/sdlc/init-repo-arch-skill/SKILL.md)
- [references/repository-layout.md](/Users/aanekraso2/github.com/znbiz/sdlc/init-repo-arch-skill/references/repository-layout.md)
- [references/knowledge-workflow.md](/Users/aanekraso2/github.com/znbiz/sdlc/init-repo-arch-skill/references/knowledge-workflow.md)
- [assets/AGENTS-template.md](/Users/aanekraso2/github.com/znbiz/sdlc/init-repo-arch-skill/assets/AGENTS-template.md)
- [assets/repo-initialization-progress-template.yaml](/Users/aanekraso2/github.com/znbiz/sdlc/init-repo-arch-skill/assets/repo-initialization-progress-template.yaml)
- [scripts/analysis_guard/definitions.py](/Users/aanekraso2/github.com/znbiz/sdlc/init-repo-arch-skill/scripts/analysis_guard/definitions.py)

## Цель

Развить skill из набора checklist-инструкций в управляемый wiki workflow для первичного восстановления `as-is` архитектуры:

- `.temp/` остаётся raw layer;
- markdown/yaml артефакты образуют synthesis layer;
- `AGENTS.md`, `wiki/index.md`, `wiki/log.md`, `wiki/maps/compile-report.md` образуют navigation layer;
- `analysis_guard` управляет шагами, индексом, lint и compile;
- knowledge lint проверяет не только наличие файлов, но и связность knowledge graph.

## Принципы

- Одна схема без параллельных режимов: skill работает в едином wiki layout.
- Navigation over lookup: агент начинает с `AGENTS.md` и `wiki/index.md`, а не со случайного поиска по репозиторию.
- Compile/evaluate/refine loop: knowledge-слой пересобирается и проверяется через `index`, `lint`, `compile`.
- Traceability first: значимые утверждения должны иметь источники или явную пометку уверенности.

## Завершённые этапы

### Этап 1. Зафиксировать целевую концепцию в skill-документации [выполнено]

- В `SKILL.md` зафиксированы `raw layer`, `synthesis layer`, `navigation layer`, `knowledge lint`.
- В `repository-layout.md` описана связь `.temp/` -> knowledge-артефакты.
- Workflow закреплён как обязательный guard-процесс, а не как набор пожеланий.

### Этап 2. Добавить навигационный слой [выполнено]

- Добавлены шаблоны `assets/index-template.md` и `assets/knowledge-log-template.md`.
- Navigation entrypoint перенесён в `wiki/index.md`.
- Append-only журнал закреплён в `wiki/log.md`.

### Этап 3. Расширить `AGENTS-template.md` до operational entrypoint [выполнено]

- `AGENTS-template.md` описывает `Source of Truth`, режимы `Ingest`, `Query`, `Lint`.
- Зафиксирован порядок чтения `AGENTS.md -> wiki/index.md -> целевые артефакты`.
- Добавлены правила по gaps и трассировке.

### Этап 4. Добавить трассируемость источников в шаблоны артефактов [выполнено]

- Обновлены markdown и yaml шаблоны артефактов.
- Добавлены секции и поля для источников, уверенности и related-связей.
- Поддержаны категории: `наблюдаемый факт`, `выведено косвенно`, `требует подтверждения`.

### Этап 5. Расширить schema progress-файла под knowledge workflow [выполнено]

- В progress schema добавлены шаги `build_navigation_index` и `run_knowledge_lint`.
- `knowledge_layout` закреплён как `wiki`.
- Validation и artifact tracking синхронизированы с новым workflow.

### Этап 6. Добавить команды `index` и `lint` в `analysis_guard` [выполнено]

- CLI расширен командами `index` и `lint`.
- `index` генерирует navigation layer.
- `lint` запускает базовые проверки knowledge-слоя.

### Этап 7. Реализовать knowledge lint [выполнено]

- В `scripts/analysis_guard/knowledge.py` добавлены проверки для `features-index.md`, `wiki/index.md`, `wiki/log.md`, `open-questions.md`, трассировки источников и путей к коду без имени репозитория.
- Severity-модель сведена к `ERROR`, `WARN`, `DEBT`.
- В references добавлены правила remediation.

### Этап 8. Провести сквозную обкатку skill на тестовом сценарии [выполнено]

- Добавлен synthetic fixture `tests/fixtures/valid_arch_repo`.
- Добавлены smoke/regression tests для сценариев `init -> index -> lint` и `compile`.
- Поведение `analysis_guard` синхронизировано с шаблонами и references.

### Этап 9. Закрепить единый каталог `wiki/` [выполнено]

- Layout закреплён в [wiki-layout.md](/Users/aanekraso2/github.com/znbiz/sdlc/init-repo-arch-skill/references/wiki-layout.md).
- `analysis_guard` теперь работает только в wiki-схеме.
- Убраны shim-файлы и логика параллельных layout-схем.

### Этап 10. Ввести frontmatter и richer metadata model [выполнено]

- Зафиксирована schema `title`, `type`, `sources`, `related`, `created`, `updated`, `confidence`, `domain`, `repositories`.
- Обновлены markdown-шаблоны, которые должны участвовать в compile/lint.
- Lint понимает как frontmatter, так и секции `Источники`.

### Этап 11. Добавить compile-операции и link graph [выполнено]

- Добавлена команда `compile`.
- `compile` собирает `wiki/index.md` и `wiki/maps/compile-report.md` по frontmatter, markdown links, wikilinks и `related`.
- Compile-report показывает unresolved references, weakly linked pages и adjacency list.

### Этап 12. Усилить knowledge lint до graph-aware режима [выполнено]

- Добавлены проверки на orphan pages, missing related references, stale low-confidence pages, domain conflicts и drift между фактическими wiki-файлами и compile output.
- Knowledge debt вынесен в отдельный префикс `DEBT:`.

### Этап 13. Развить open questions и user interview в knowledge closure loop [выполнено]

- `open-questions.md` расширен колонками `Follow-up ID`, `Целевые артефакты`, `Обновление knowledge graph`.
- Lint проверяет, что закрытые вопросы реально отражены в целевых артефактах.
- Post-answer cycle зафиксирован в `SKILL.md` и references.

### Этап 14. Упростить workflow до одной wiki-модели [выполнено]

- Убраны упоминания старой схемы из кода, шаблонов и references.
- `index`, `lint` и `compile` работают как единый wiki workflow.
- План и шаблоны синхронизированы с подходом «wiki без версий».

## Следующие 3 этапа

### Этап 15. Добавить regression coverage для самого skill [выполнено]

Цель: защитить knowledge workflow от регрессий при дальнейших изменениях.

Состав:

- покрыть `status`, `advance`, `validate` вместе с knowledge-этапами;
- добавить негативные fixture-сценарии для битых ссылок, drift и orphan pages;
- проверить шаблоны и CLI output на согласованность.

Критерий готовности:

- Добавлены regression tests для `bootstrap`, `status`, `advance`, `validate`, `compile` и `lint` вокруг knowledge-этапов.
- Негативные сценарии для битых секций compile output, drift, orphan pages и слабого metadata coverage воспроизводятся тестами.
- CLI output и шаблоны навигационного слоя проверяются на согласованность тестами.

### Этап 16. Добавить bootstrap-команду для wiki-артефактов [выполнено]

Цель: упростить первичное создание `wiki/index.md`, `wiki/log.md` и compile-report структуры.

Состав:

- добавить scaffold/init-команду для navigation layer;
- создавать `wiki/`, `wiki/maps/` и базовые файлы без ручной подготовки;
- проверить совместимость со строгим progress workflow.

Критерий готовности:

- Добавлена команда `analysis_guard bootstrap`, которая создаёт `wiki/`, `wiki/maps/`, `wiki/index.md`, `wiki/log.md` и stub для `wiki/maps/compile-report.md`.
- Bootstrap синхронизирует `progress`-артефакты и не подменяет `index`/`compile`, а только готовит стартовую структуру.
- Инициализация navigation layer больше не требует ручной подготовки каталогов.

### Этап 17. Добавить quality gates для compile output [выполнено]

Цель: сделать compile результат проверяемым артефактом, а не только побочным удобством.

Состав:

- формализовать обязательные секции `wiki/index.md` и `wiki/maps/compile-report.md`;
- добавить проверки на минимальное покрытие frontmatter и related-связей;
- описать, какие проблемы блокируют завершение шага `run_knowledge_lint`.

Критерий готовности:

- Формализованы обязательные секции для `wiki/index.md` и `wiki/maps/compile-report.md`.
- `compile` публикует coverage по frontmatter и `related`, а `lint` блокирует завершение при coverage ниже 50%.
- После появления compile-report `lint` и `compile` образуют единый quality gate для knowledge graph.

### Этап 18. Закрепить historical prep как standard happy path [выполнено]

Цель: убрать двусмысленность между “обычным” и “историческим” init-flow и сделать temporal prep обязательной линейной частью старта анализа.

Состав:

- закрепить в `SKILL.md`, что `refresh_main_branches` и `plan_repository_order` образуют обязательный historical prep-цикл;
- расширить progress-template полями `workflow_profile`, `workflow.happy_path`, `historical_analysis.status`, `prep_notes`, `analysis_target_commit_note`;
- зафиксировать в references, что raw layer для init должен быть подготовлен на snapshot-коммитах до начала synthesis workflow.

Критерий готовности:

- standard happy path в документации описан одной линейной цепочкой без альтернативного “обычного режима”;
- progress-template явно отражает состояние historical prep;
- у агента есть единая точка истины, когда init реально готов к первому содержательному анализу репозиториев.
