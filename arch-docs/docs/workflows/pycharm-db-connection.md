# PyCharm: подключение к локальной PostgreSQL

Этот `docker-compose` публикует PostgreSQL на локальный интерфейс:

- host: `127.0.0.1`
- port: `5432`
- database: `arch_docs`
- user: `arch_docs`
- password: `arch-docs-local-dev`

Готовая JDBC-строка для PyCharm:

```text
jdbc:postgresql://127.0.0.1:5432/arch_docs
```

Параметры взяты из:

- [arch-docs/docker-compose.yml](/Users/aanekraso2/github.com/znbiz/sdlc/arch-docs/docker-compose.yml)
- [arch-docs/.env](/Users/aanekraso2/github.com/znbiz/sdlc/arch-docs/.env)
- [arch-docs/back/app/settings.py](/Users/aanekraso2/github.com/znbiz/sdlc/arch-docs/back/app/settings.py)

Как заполнить Data Source в PyCharm:

1. `DataGrip / Database` -> `+` -> `PostgreSQL`
2. `Host`: `127.0.0.1`
3. `Port`: `5432`
4. `Database`: `arch_docs`
5. `User`: `arch_docs`
6. `Password`: `arch-docs-local-dev`
7. `URL` при ручном режиме: `jdbc:postgresql://127.0.0.1:5432/arch_docs`

Примечания:

- Контейнер `arch-docs-postgres-1` сейчас запущен и healthy.
- В коде backend использует async SQLAlchemy URL `postgresql+asyncpg://...`, но для PyCharm нужен обычный PostgreSQL JDBC URL без `+asyncpg`.
- `POSTGRES_DB` и `POSTGRES_USER` в `.env` не заданы, поэтому compose использует дефолты `arch_docs`.
