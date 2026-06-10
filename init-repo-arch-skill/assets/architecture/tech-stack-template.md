# Технологический стек

Этот документ фиксирует ключевые технологии и архитектурно значимые зависимости по сервисам.

Не включай сюда все пакеты подряд. Добавляй только то, что влияет на понимание архитектуры, интеграций, сопровождения и ограничений системы.

## Правила заполнения

- Фиксируй язык, runtime, основной framework и другие ключевые зависимости.
- Не перечисляй транзитивные или незначимые utility-зависимости.
- Для каждой строки указывай источник подтверждения: manifest, lockfile, Dockerfile, конфиг, код или иной артефакт.
- Если версия не найдена, так и помечай, не выдумывай.

## Таблица

| Service | Dependency | Version | Role | Evidence | Confidence |
| --- | --- | --- | --- | --- | --- |
| `<service-name>` | `<python>` | `<3.12>` | `runtime` | `<Dockerfile / pyproject.toml>` | `fact` |
| `<service-name>` | `<fastapi>` | `<0.115.x>` | `web framework` | `<pyproject.toml>` | `fact` |
| `<service-name>` | `<sqlalchemy>` | `<2.x>` | `orm` | `<poetry.lock>` | `fact` |

## Примечания

- `Role` используй для краткой классификации: `runtime`, `web framework`, `orm`, `broker client`, `observability`, `security`, `sdk`, `build`, `transport`.
- `Confidence` используй как `fact` или `inferred`.
