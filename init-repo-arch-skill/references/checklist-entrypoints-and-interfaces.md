# Пункт checklist: entrypoints_and_interfaces

Найти все точки входа репозитория — публичные интерфейсы, через которые система принимает внешние запросы или инициирует работу.

## Что искать

- **HTTP/REST** — routing-файлы, контроллеры, `@app.route`, `router.get/post`, `@Controller`, FastAPI endpoints
- **gRPC** — `.proto`-файлы, server implementations, `grpc.Server`
- **Message consumers** — Kafka consumer groups, RabbitMQ consumers, SQS handlers, NATS subscribers
- **Message producers** — publisher-классы, event emitters, `send`/`publish` вызовы в entry-точках
- **CLI команды** — `argparse`, `click`, `cobra`, `commander` definitions
- **Cron / scheduled tasks** — `cron`, `APScheduler`, `@Scheduled`, Kubernetes CronJob, Celery beat
- **Batch processors** — bulk-обработка файлов, queue drains, ETL entry points
- **Admin / management endpoints** — `/admin`, `/internal`, `/management`, Django admin, Spring Actuator

## Шаги выполнения

1. Если сервис можно безопасно поднять локально через Docker или Docker Compose — сделай это перед или параллельно с анализом кода. Runtime-старт покажет фактические порты, реально работающие endpoints, consumers и скрытые фоновые процессы, которые сложно увидеть только в коде.
2. Найти routing/handler файлы по паттернам: `routes/`, `controllers/`, `handlers/`, `views/`, `api/`, `cmd/`.
3. Найти consumer и producer registration — где они инициализируются и запускаются.
4. Найти CLI entry points — `main.go`, `__main__.py`, `bin/`, `cmd/` с subcommand-структурой.
5. Найти cron и scheduler конфигурацию.
6. Для каждой точки входа записать: **тип**, **путь или topic**, **метод** (GET/POST/...), **краткое назначение**.

## Обязательные выходы

- В `notes` progress-файла: список точек входа с типами и путями.
- Если найдены HTTP/gRPC endpoints — это сигнал для обязательного прохода пункта `contracts_and_schemas`.
- Если найдены consumer/producer — это сигнал для обязательного прохода пункта `contracts_and_schemas` (async-контракт).

## Проверка согласованности и правка артефактов

Перед тем как пометить пункт `completed`:

- Если найдены точки входа, которых нет в `architecture/hld.md` — добавить компонент или обновить существующий раздел.
- Если сервис имеет публичный HTTP/gRPC API — проверить, что в `landscape.yaml` у него задано поле `technology` (runtime / framework).
- Если тип репозитория в предыдущем пункте `library` или `infra`, а здесь нашлись HTTP-handlers — пересмотреть тип и категорию (`support` → `product`) и обновить `notes` пункта `repository_classification`.
- Если найдены consumer/producer — проверить, упомянут ли broker в HLD. Если нет — добавить.
