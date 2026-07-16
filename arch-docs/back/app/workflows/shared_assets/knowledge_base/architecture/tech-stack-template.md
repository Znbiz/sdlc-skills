# Технологический стек

Этот документ фиксирует ключевые технологии и архитектурно значимые зависимости по сервисам.

Не включай сюда все пакеты подряд. Добавляй только то, что влияет на понимание архитектуры, интеграций, сопровождения и ограничений системы.

## Правила заполнения

- Фиксируй язык, runtime, основной framework и другие ключевые зависимости.
- Не перечисляй транзитивные или незначимые utility-зависимости.
- Добавляй короткие `Источники`, но не превращай таблицу в сырой лог всех файлов.
- Если версия не найдена, так и помечай (`not pinned`), не выдумывай.

## Таблица

| Service | Dependency | Version | Role | Assertion Type | Sources |
| --- | --- | --- | --- | --- | --- |
| `<service-name>` | `<python>` | `<3.12>` | `runtime` | `наблюдаемый факт` | `<repo-name/pyproject.toml>` |
| `<service-name>` | `<fastapi>` | `<0.115.x>` | `web framework` | `наблюдаемый факт` | `<repo-name/pyproject.toml>` |
| `<service-name>` | `<sqlalchemy>` | `<2.x>` | `orm` | `наблюдаемый факт` | `<repo-name/pyproject.toml>` |

## Примечания

- `Role` используй для краткой классификации: `runtime`, `web framework`, `orm`, `broker client`, `observability`, `security`, `internal sdk`, `build`, `transport`, `routing`, `openapi codegen`.
- Если строка выведена не напрямую из lock/package manifest, а из кода или runtime wiring, помечай `Assertion Type` как `выведено косвенно`.
