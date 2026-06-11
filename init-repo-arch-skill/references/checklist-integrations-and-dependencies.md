# Пункт checklist: integrations_and_dependencies

Найти все внешние и внутренние интеграции сервиса: с кем он общается, как и зачем.

## Что искать

- **Исходящие HTTP-вызовы** — `axios`, `httpx`, `requests`, `RestTemplate`, `fetch`, gRPC stubs к другим сервисам
- **Внутренние сервисные вызовы** — вызовы других микросервисов по имени / через service discovery
- **Брокеры** — Kafka producer, RabbitMQ publisher, SQS sender
- **Внешние API** — платёжные системы, SMS/email провайдеры, OAuth провайдеры, карты, аналитика
- **SDK** — сторонние SDK (Stripe, Twilio, SendGrid, AWS SDK, Firebase)
- **Resilience** — retry-логика, circuit breakers (`resilience4j`, `pybreaker`, `go-circuit-breaker`), timeouts, bulkhead
- **Service discovery** — Consul, Kubernetes DNS, env-based endpoints

## Шаги выполнения

1. Найти HTTP-клиенты и проследить, какие URL они вызывают.
2. Найти gRPC-stub вызовы — к каким сервисам.
3. Найти Kafka/RabbitMQ producer вызовы — в какие топики.
4. Найти использование SDK внешних сервисов.
5. Для каждой интеграции зафиксировать: направление (входящая/исходящая), с кем, назначение, протокол, есть ли retry/timeout.
6. Создать артефакт.

## Обязательные выходы

- Создать или обновить `architecture/integrations/<service>.md` по шаблону `assets/architecture/integration-template.md` — таблицы входящих и исходящих интеграций. Путь зафиксировать в notes.

## Проверка согласованности и правка артефактов

Перед тем как пометить пункт `completed`:

- Обновить `architecture/integrations-overview.md` — добавить строки для сервиса в раздел "Карта интеграций" (входящие и исходящие). Обновить раздел "Разрез по направлению".
- Проверить `architecture/landscape.yaml` — связи (`dependencies`) у сервиса должны отражать найденные интеграции.
- Если найдены интеграции без retry/timeout — отметить как риск для пункта `risks_and_tech_debt_updates`.
- Если внешний сервис ещё не упомянут в системе — добавить его в `landscape.yaml` как внешний компонент.
- Если у интеграции нет явного circuit breaker и она критичная — отметить как риск.

## Подводные камни

- Результат не готов, если интеграции описаны общими словами без направления и назначения: для каждой интеграции должны быть указаны direction (in/out), с кем, зачем и по какому протоколу.
