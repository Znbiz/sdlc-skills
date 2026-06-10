# Технологический стек изменения

Этот документ фиксирует технологии и зависимости, которые затрагиваются новым решением или становятся архитектурно значимыми из-за изменения.

Не включай сюда все пакеты подряд. Добавляй только то, что влияет на понимание решения, ограничений, rollout или сопровождения.

## Правила заполнения

- Фиксируй только новые или существенно меняющиеся технологии и зависимости.
- Для каждой строки указывай, что именно меняется: добавляется, обновляется, переиспользуется или остается без изменений, но является критичным для решения.
- Указывай источник подтверждения: код, manifest, RFC, инфраструктурный артефакт или проектное решение.
- Если версия пока не определена, так и помечай, не выдумывай.

## Таблица

| Component | Dependency | Version | Role | Change Type | Evidence | Confidence |
| --- | --- | --- | --- | --- | --- | --- |
| `<service-name>` | `<python>` | `<3.12>` | `runtime` | `unchanged` | `<Dockerfile / pyproject.toml>` | `fact` |
| `<service-name>` | `<fastapi>` | `<0.115.x>` | `web framework` | `reused` | `<pyproject.toml>` | `fact` |
| `<service-name>` | `<temporal-sdk>` | `<TBD>` | `workflow engine` | `planned_addition` | `<HLD / decision record>` | `decision` |

## Примечания

- `Role` используй для краткой классификации: `runtime`, `web framework`, `orm`, `broker client`, `observability`, `security`, `sdk`, `build`, `transport`.
- `Change Type` используй как `planned_addition`, `planned_upgrade`, `reused`, `unchanged`, `planned_removal`.
- `Confidence` используй как `fact`, `inferred` или `decision`.
