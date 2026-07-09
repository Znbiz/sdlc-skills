# Пункт checklist: tech_stack_collection

Собрать технологический стек сервиса: только архитектурно значимые зависимости, не полный список пакетов.

## Что фиксировать

Фиксируй только то, что влияет на архитектуру, интеграции или эксплуатацию:

| Категория | Примеры |
|---|---|
| Язык и runtime | Python 3.11, Node.js 20, Go 1.22, JDK 21 |
| Основной framework | FastAPI, NestJS, Spring Boot, Gin, Django |
| ORM / database driver | SQLAlchemy, TypeORM, GORM, Hibernate |
| Transport / RPC | gRPC, Axios, RestTemplate, Feign |
| Broker clients | kafka-python, confluent-kafka, amqplib, spring-kafka |
| Observability | OpenTelemetry, Prometheus client, Micrometer, Sentry |
| Auth / security | python-jose, passport.js, spring-security, golang-jwt |
| Архитектурно значимые SDK | AWS SDK, Firebase Admin, Stripe, Twilio |

Не вноси в `tech-stack.md` все пакеты из `requirements.txt` / `package.json` подряд.

## Где искать

**Основные источники:**

- `package.json` → `dependencies` (runtime) vs `devDependencies`; **точные версии — из `package-lock.json` или `yarn.lock` / `pnpm-lock.yaml`**
- `pyproject.toml` / `requirements.txt` / `Pipfile` → зависимости; **точные версии — из `poetry.lock` или `Pipfile.lock`**
- `go.mod` → `require` блок; **точные версии — из `go.sum`**
- `pom.xml` / `build.gradle` → `dependencies`; **точные версии — из `gradle.lockfile` или Maven dependency:resolve**
- `Dockerfile` → базовый образ (`FROM python:3.11`, `FROM node:20-alpine`) — даёт runtime и версию
- `docker-compose.yml` / `helm/values.yaml` → образы сервисов-зависимостей (БД, брокер, кэш)

## Шаги выполнения

1. Определить ЯП и версию runtime из `Dockerfile` или корневого манифеста.
2. Найти основной framework — обычно первая крупная зависимость в манифесте.
3. Пройти по категориям из таблицы выше и выписать кандидатов. Версии брать из lock-файлов (`package-lock.json`, `poetry.lock`, `go.sum`, `gradle.lockfile` и т.п.) — они точнее, чем диапазоны в манифестах.
4. Для каждого кандидата зафиксировать источник подтверждения (конкретный файл).
5. Добавить записи в `architecture/tech-stack.md` по шаблону `assets/architecture/tech-stack-template.md`.

## Обязательные выходы

- Записи в `architecture/tech-stack.md` для текущего сервиса: категория, зависимость, версия, источник.
- Поле `technology` в `architecture/landscape.yaml` для сервиса в формате `<runtime> / <framework>`.

## Проверка согласованности и правка артефактов

Перед тем как пометить пункт `completed`:

- Для каждой категории из таблицы выше: либо есть запись, либо явно отмечено "не используется".
- Версии взяты из lock-файлов, не из диапазонов манифестов и не из памяти.
- Поле `technology` в `landscape.yaml` заполнено и согласуется с записями в `tech-stack.md`.
- Если найдена EOL-версия языка или критичного фреймворка — отметить для пункта `risks_and_tech_debt_updates`.
