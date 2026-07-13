# Postgres-only test harness для arch-docs

**Цель:** перевести весь тестовый контур `arch-docs` на обязательную работу с реальной PostgreSQL БД в Docker, отдельной test database и схемой, создаваемой только через Alembic-миграции. Любой запуск `pytest` должен зависеть от доступного Docker Postgres и подготовленной тестовой БД; SQLite и моки DB-session слоя больше не считаются допустимым путём выполнения тестов.

**Архитектура:** тестовый контур делится на два слоя orchestration. Внешний слой отвечает только за наличие Docker Postgres-контейнера. Внутренний слой находится в `pytest`: session-scoped bootstrap создаёт/пересоздаёт отдельную test database, направляет `DATABASE_URL` на неё, накатывает `alembic upgrade head`, инициализирует application engine и предоставляет тестам только реальные `AsyncSession`. Если Docker Postgres недоступен, `pytest` падает сразу и явно. Таким образом, инвариант "все тесты идут против реальной Postgres-схемы из миграций" enforced на уровне самого test runner, а не только через `just`.

**Tech Stack:** Python 3.14, pytest/pytest-asyncio, PostgreSQL 16, Docker Compose, SQLAlchemy async, Alembic.

## Глобальные ограничения

- `pytest` без доступного Docker Postgres должен завершаться ошибкой preflight, а не silently fallback на SQLite/in-memory режим.
- Тестовая схема создаётся только через `alembic upgrade head`; `Base.metadata.create_all()` не используется как путь подготовки БД.
- Отдельная test database должна быть изолирована от dev/runtime БД `arch-docs`.
- Unit-тесты, которые сейчас мокают `AsyncSession`, `get_session()` или используют `sqlite+aiosqlite:///:memory:`, переводятся на реальные SQL-запросы к Postgres либо удаляются как дублирующие поведение ORM/SQLAlchemy.
- Моки остаются допустимы для внешних систем, не относящихся к БД: subprocess/CLI, network, LLM worker, auth side effects, filesystem edge cases.
- Новый контур не должен требовать ручного создания таблиц, ручного SQL bootstrap или ad hoc schema drift-логики.
- Поведение `just test`, `just agent-check` и прямого `uv run pytest` должно быть согласованным: все три пути используют один и тот же DB-backed bootstrap.

---

## Целевое поведение

После внедрения любой локальный или CI-запуск тестов в `arch-docs` работает по одному сценарию:

1. Запущен Docker Postgres-контейнер тестового контура.
2. `pytest` preflight проверяет соединение с server-level database.
3. Session bootstrap создаёт fresh test database `arch_docs_test` или эквивалентное имя.
4. На test database выполняется `alembic upgrade head`.
5. Приложение и тестовые fixtures работают только через `DATABASE_URL`, указывающий на эту test database.
6. Каждый тест получает чистое состояние данных через cleanup strategy, не нарушающую миграционную схему.
7. По завершении suite test database может либо очищаться, либо пересоздаваться на следующем запуске.

Прямой вызов `pytest` без Docker Postgres считается некорректным использованием и должен падать с сообщением, которое объясняет, какой compose/just entrypoint нужно поднять.

---

## Рекомендованный подход

Выбран гибридный orchestration:

- Docker lifecycle остаётся снаружи `pytest`, потому что управлять контейнерами изнутри Python менее надёжно и хуже диагностируется.
- Обязательность БД enforced внутри `pytest`, чтобы прямой вызов test runner не обходил требования.
- Подготовка test database и миграций выполняется внутри `pytest` session fixture, потому что это даёт единый source of truth для локального запуска, CI и IDE.

Почему не полный Docker lifecycle внутри `pytest`:

- выше вероятность flaky cleanup;
- выше связность test harness с Docker CLI API;
- хуже debuggability при падении контейнера, healthcheck или port binding.

Почему не только внешний `just` orchestration:

- пользователь может запустить прямой `pytest` и обойти подготовку;
- инвариант оказывается договорённостью, а не enforced механизмом.

---

## Тестовая БД и lifecycle

Нужны два уровня подключения:

- server/admin URL: подключение к уже существующему database entrypoint Postgres без привязки к конкретной app DB; используется для `CREATE DATABASE`/`DROP DATABASE` или equivalent reset;
- app/test URL: `DATABASE_URL` приложения, всегда указывающий на test database.

Ожидаемый lifecycle session bootstrap:

1. Прочитать test settings/env.
2. Проверить, что Postgres reachable.
3. Завершить активные соединения к старой test database при необходимости.
4. Пересоздать test database с нуля.
5. Выполнить `alembic upgrade head` на новой test database.
6. Инициализировать SQLAlchemy engine приложения на test URL.
7. Отдать тестам session factory / helpers.

Стратегия очистки между тестами:

- по умолчанию truncate всех прикладных таблиц между тестами, с `RESTART IDENTITY CASCADE`, если это совместимо с моделью;
- fallback: rollback вложенной транзакции для узких тестов, но не как единственная глобальная стратегия;
- выбор должен быть единым и прозрачным для всего suite.

Для `arch-docs` предпочтителен truncate cleanup, потому что тесты смешивают repository layer, service layer, API layer и lifespan/startup поведение, где один глобальный rollback часто ломается на дополнительных commit внутри кода приложения.

---

## Изменения в структуре проекта

- **Изменить:** `arch-docs/tests/conftest.py` — добавить глобальный DB bootstrap, env wiring, cleanup fixtures, реальный async client поверх Postgres-backed app state.
- **Изменить:** `arch-docs/justfile` — ввести явные команды для test postgres lifecycle и сделать `test`/`agent-check` зависимыми от них.
- **Изменить:** `arch-docs/docker-compose.yml` или создать `arch-docs/docker-compose.test.yml` — описать test postgres service и его параметры.
- **Создать:** `arch-docs/tests/helpers/db.py` или аналогичный модуль — admin/test URL helpers, database reset, alembic runner, truncate helper.
- **Изменить:** `arch-docs/app/main.py` и связанный startup path только если потребуется убрать неявные допущения про runtime DB state.
- **Изменить:** `arch-docs/tests/db/test_session.py` — убрать SQLite path и переписать под реальный Postgres.
- **Изменить:** `arch-docs/tests/db/test_task_repo.py` — заменить `AsyncMock` session на реальные DB assertions.
- **Изменить:** `arch-docs/tests/db/test_workflow_repo.py` — заменить `AsyncMock` session на реальные DB assertions.
- **Изменить:** service/API тесты, которые патчат `get_session` или DB persistence path, если они проверяют именно интеграцию с persistence, а не чистую orchestration-логику.

---

## Классификация текущих тестов

Тесты `arch-docs` сейчас делятся на три класса:

1. DB-layer tests, которые прямо мокают `AsyncSession` или используют SQLite in-memory.
2. Service/API tests, которые формально тестируют higher-level поведение, но подменяют persistence path моками.
3. Pure non-DB tests, где БД не является предметом проверки.

Целевое правило:

- Класс 1 полностью переводится на реальный Postgres.
- Класс 2 переводится на реальный Postgres там, где результат зависит от чтения/записи persisted state.
- Класс 3 всё равно запускается в том же suite и под тем же DB bootstrap, даже если конкретный тест не пишет в БД. Это нужно не ради самого теста, а ради единого инварианта всего `pytest`.

---

## Blast Radius

Изменение затрагивает:

- developer workflow локального запуска тестов;
- CI pipeline `arch-docs`, если он существует вне этого репозитория;
- время выполнения test suite;
- стабильность startup/lifespan тестов;
- DB repository и API integration coverage.

Основные риски:

- suite станет медленнее;
- появятся race conditions при параллельном запуске нескольких `pytest`;
- cleanup может оказаться неполным и давать order-dependent failures;
- startup приложения может писать в БД раньше, чем fixture полностью подготовит engine/env.

Снижение рисков:

- запретить `xdist`/параллельный shared-DB запуск до появления явной multi-db стратегии;
- использовать одну test database на один pytest process;
- выполнять reset database на session start, а table cleanup на function scope;
- делать bootstrap idempotent и с понятными ошибками.

---

## Нефункциональные требования

- Ошибки preflight должны быть короткими и actionable: какой контейнер поднять, какой `just`/`docker compose` command ожидался.
- Harness должен работать из IDE, terminal и CI одинаково.
- Миграции должны быть единственным source of truth для структуры БД в тестах.
- Запуск одного теста по пути `uv run pytest tests/... -k ...` должен работать в том же контуре, без отдельной ручной подготовки схемы.

---

## Out of Scope

- Переписывание всех не-DB моков в проекте.
- Полный отказ от unit-тестирования как подхода для CLI/subprocess/LLM orchestration.
- Автоматический подъём Docker изнутри `pytest`.
- Одновременная поддержка SQLite test backend.
- Мульти-процессный запуск тестов с независимыми test databases.

---

## Критерии готовности

- Любой запуск `uv run pytest` в `arch-docs` падает без Docker Postgres и проходит с ним.
- В test suite больше нет `sqlite+aiosqlite:///:memory:` и DB-layer моков как основного способа проверки persistence.
- Test database создаётся автоматически и мигрируется автоматически.
- DB cleanup между тестами обеспечивает детерминированный прогон всего suite.
- `just test` и `just agent-check` используют тот же механизм и не содержат альтернативного пути подготовки схемы.

---

## Открытые решения, зафиксированные этим дизайном

- Использовать отдельную test database, а не отдельную schema внутри dev database.
- Использовать Alembic migration path, а не `metadata.create_all`.
- Делать DB bootstrap в `pytest`, а не только во внешнем shell wrapper.
- Оставить Docker container lifecycle внешним по отношению к `pytest`.
- Считать DB-backed execution обязательным для всего suite, даже для тестов, которые логически не используют persistence.
