# Пункт checklist: contracts_and_schemas

Восстановить публичные контракты сервиса: синхронные API и асинхронные события.

## Что искать

- **OpenAPI / Swagger** — `openapi.yaml`, `swagger.json`, `@ApiOperation`, автогенерация через `springdoc`, `fastapi`, `drf-spectacular`
- **gRPC / Protobuf** — `.proto`-файлы, generated stubs
- **GraphQL** — `.graphql`-схемы, resolver definitions
- **AsyncAPI** — `asyncapi.yaml`, описания топиков
- **DTO / request-response модели** — классы с суффиксами `*Request`, `*Response`, `*Dto`, `*Schema`, `*Payload`
- **Serializers** — Django REST Framework serializers, Pydantic models, Jackson, protobuf message classes
- **Message payloads** — структуры Kafka/RabbitMQ сообщений, event-классы

## Когда пропустить

Если репозиторий является **фронтенд-приложением** (SPA, мобильное приложение, UI-библиотека) — шаг пропустить полностью: фронтенд потребляет контракты бекенда, но не публикует собственные. Зафиксировать в notes: `"frontend — нет публичных контрактов"`.

## Шаги выполнения

1. Найти и прочитать все OpenAPI/AsyncAPI/proto файлы.
2. **Обойти все вьюхи и роуты вручную** — прочитать все файлы с определениями маршрутов (router, urls, routes, controller, handler) и составить полный список API-эндпоинтов. Ни один эндпоинт не должен быть пропущен: даже если Swagger есть, сверить его с реальными роутами — автогенерация часто упускает internal-хендлеры, webhook-приёмники и служебные эндпоинты.
3. **Попробовать получить живую спецификацию**: если сервис можно запустить локально — запустить его и обратиться к `/swagger.json`, `/openapi.json`, `/v3/api-docs`, `/api-docs`, `/swagger/doc.json` или аналогичному URL. Полученный JSON/YAML сохранить как основной источник контракта и **сверить с перечнем из шага 2** — расхождения задокументировать.
4. Если автогенерации нет и сервис не запускается — восстановить контракт по DTO и handler-сигнатурам для каждого найденного в шаге 2 эндпоинта.
5. Для каждого HTTP/gRPC endpoint зафиксировать: метод, путь, request schema, response schema, auth.
6. Для каждого Kafka/AMQP топика зафиксировать: topic name, direction (publisher/subscriber), payload schema.
7. Создать артефакты.

## Обязательные выходы

- **Если есть HTTP/REST/gRPC API**: создать `architecture/contracts/<service>-sync.yml` по шаблону `assets/architecture/contract-template.yml`.
  - Нет API → написать `"нет sync контракта"` в notes.
- **Если есть Kafka/AMQP топики**: создать `architecture/contracts/<service>-async.yml` по шаблону `assets/architecture/async-contract-template.yml`.
  - Нет топиков → написать `"нет async контракта"` в notes.
- Kafka-топики **не попадают** в `architecture/storage/` — только в contracts.

## Проверка согласованности и правка артефактов

Перед тем как пометить пункт `completed`:

- Проверить, что все endpoints из пункта `entrypoints_and_interfaces` покрыты контрактом (или явно помечены как "нет контракта").
- Если контракт содержит auth-параметры (`Authorization`, `X-API-Key`, OAuth scopes) — отметить для пункта `security_and_auth_updates`.
- Если топики совпадают с топиками других уже проанализированных сервисов — проверить согласованность схем payload (должны совпадать между publisher и subscriber).
- Обновить `architecture/hld.md` — добавить информацию о публичных интерфейсах сервиса в соответствующий компонент.

## Подводные камни

- Не объявляй контракт восстановленным, если у него нет подтверждения в хендлерах, DTO, схемах или тестах.
- Результат не готов, если контракты не выделены в отдельные артефакты, хотя они читаются из кода.
