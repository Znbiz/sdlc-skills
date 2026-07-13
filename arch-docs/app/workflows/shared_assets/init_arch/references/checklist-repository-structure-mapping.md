# Пункт checklist: repository_structure_mapping

Построить карту структуры репозитория: какие пути/паттерны отвечают за какую техническую категорию. Эта карта — отдельная ось от `domain_map` (бизнес-домены, см. `checklist-scope-and-domain-assessment.md`). `domain_map` отвечает на вопрос "какая часть кода относится к биллингу/авторизации/уведомлениям", `architecture/structure/<repo>.yml` отвечает на вопрос "какая часть кода отвечает за API, какая за БД, какая за интеграции" — независимо от бизнес-домена.

Один репозиторий — один файл: `architecture/structure/<repo>.yml`. Не своди карты всех репозиториев в общий файл — это удорожает каждое точечное обновление карты при дельта-анализе в `update-repo-arch-skill`.

Выполняется сразу после `repository_classification`, **до** детального прохода по остальным пунктам чеклиста — карта структуры — это разведка, а не результат глубокого анализа. Детали внутри найденных путей уточняются позже, при выполнении соответствующих пунктов (`entrypoints_and_interfaces`, `data_and_storage`, `contracts_and_schemas` и т.д.) — этот пункт фиксирует только **где искать**, не **что там происходит**.

## Категории карты

Используй ровно эти идентификаторы категорий (это важно для дальнейшей работы других скиллов):

| Категория | Что туда попадает |
| --- | --- |
| `entrypoints_and_interfaces` | HTTP/gRPC routes, controllers, handlers, CLI-команды, admin UI |
| `ui_screens_and_navigation` | **Только для frontend-репозиториев (web/mobile).** Экраны, страницы, роуты, навигация между ними: file-based routing (Next.js `app/`/`pages/`), React Router/Vue Router конфиги, мобильные screens/navigators. Для чисто backend-репозитория — `not_applicable` |
| `contracts_and_schemas` | OpenAPI/AsyncAPI/proto-файлы (если коммитятся руками), а также **слой-источник** контракта: serializers, DTO, request/response модели, decorator-аннотации схемы |
| `data_and_storage` | ORM-модели, миграции, схемы БД, кэш, описание Kafka/AMQP-топиков как структур данных |
| `integrations_and_dependencies` | HTTP/gRPC-клиенты к внешним сервисам, SDK-обёртки, consumers/producers как код, а не как схема данных. **Для frontend-репозиториев** — сюда же относятся зависимости от backend API: API-клиенты, сгенерированный SDK, GraphQL-операции, React Query/SWR/RTK Query хуки |
| `business_flow_orchestration` | Use cases, application services, оркестрация, фичи и бизнес-сценарии |
| `roles_and_permissions_updates` | Роли, RBAC/ABAC, матрица доступа |
| `security_and_auth_updates` | Auth middleware, проверка токенов, границы доверия, работа с секретами |
| `configs_and_runtime` | `.env`-файлы, конфиг-модули, `docker-compose`, runtime-настройки |
| `deployment_and_operability` | Dockerfile, Helm, Terraform, CI/CD пайплайны, healthchecks |
| `tech_stack_collection` | Manifest-файлы зависимостей (`package.json`, `go.mod`, `pyproject.toml`, lock-файлы) |
| `tests_and_behavior_evidence` | Integration/e2e тесты — где они лежат и что покрывают |

Не пытайся найти путь для каждой категории — если категория в этом репозитории не выражена отдельным путём (например, нет интеграций), явно зафиксируй это в карте как `paths: []` с комментарием `not_found`, а не пропускай категорию молча.

## Шаги выполнения

1. Построить дерево каталогов верхнего уровня (`find .temp/<repo> -maxdepth 3 -type d`), без чтения содержимого файлов.
2. Для каждой категории определить покрывающие её пути/паттерны по структурным сигналам — именам папок/файлов, фреймворк-конвенциям (Django `apps/*/models.py`, FastAPI `routers/`, NestJS `*.controller.ts`, Go `internal/handler/`), а не по чтению бизнес-логики.
3. Если один путь покрывает несколько категорий одновременно (например, `internal/users/` содержит и handler, и model, и use case) — указать его в карте под каждой подходящей категорией с уточнением (`internal/users/handler.go → entrypoints_and_interfaces`, `internal/users/model.go → data_and_storage`).
4. Заполнить `architecture/structure/<repo>.yml` в следующей структуре (`repo_structure_map.analyzed_commit` обязателен — его сверяет с `landscape.yaml` автоматическая проверка на шаге `run_knowledge_lint`):

   ```yaml
   repo_structure_map:
     repository: <название-репозитория>
     analyzed_commit: <commit-sha-на-момент-построения-карты>
     built_at: <дата-время>
     assertion_type: <наблюдаемый факт|выведено косвенно|требует подтверждения>
     sources:
       - <repo-name/path/to/root-or-structure-signal>
     categories:
       entrypoints_and_interfaces:
         status: <found|not_found|not_applicable>
         paths:
           - path: <например, internal/api/handlers/>
             signal: <например, "HTTP-хендлеры, Go net/http">
             assertion_type: <наблюдаемый факт|выведено косвенно|требует подтверждения>
             sources:
               - <repo-name/path/to/file-or-dir>
       # остальные категории из таблицы выше — по той же схеме: status + paths[] (path/signal/assertion_type/sources)
   ```
5. Зафиксировать `analyzed_commit`, по которому построена карта — карта валидна только для этого коммита и более новых, если структура не менялась.

## Обязательные выходы

- `architecture/structure/<repo>.yml` создан и содержит запись для каждой категории из таблицы выше (включая явные `paths: []` / `not_found` там, где категория не выражена).
- Поле `notes` пункта `repository_structure_mapping` содержит краткую сводку: сколько категорий покрыто путями, какие явно отсутствуют.

## Если категория репозитория `support` (library / test-repo / infra)

Карту всё равно строить нужно — структура важна и для support-репозиториев (например, чтобы при обновлении понимать, что изменение в `charts/` — это `deployment_and_operability`, а не шум). Но включай в карту только категории, применимые к этому типу репозитория (см. таблицу применимости в `checklist-repository-classification.md`); остальные явно отмечай `not_applicable`, а не `not_found`.

## Подводные камни

- Поле `signal` пиши на русском, даже когда оно короткое: `"HTTP handlers, Go net/http"` — неверно, `"HTTP-хендлеры, Go net/http"` — верно. Английскими оставляй только сами имена технологий/фреймворков/протоколов, а не описательную часть фразы (см. SKILL.md → Правила работы).
- Не путай эту карту с `domain_map`: структура — про техническую категорию, домен — про бизнес-область. Один путь может относиться к одной категории и одному домену одновременно, это не конфликт.
- Не описывай поведение внутри путей — это задача последующих пунктов чеклиста. Здесь только "где искать".
- Не делай карту слишком дробной: если весь HTTP-слой лежит в одной папке `api/`, не разбивай её искусственно на под-категории без структурных оснований.
- Если структура репозитория позже меняется в ходе анализа (например, при `architecture_artifact_updates` обнаруживается путь, не учтённый в карте) — обновляй карту немедленно, не оставляй её устаревшей к моменту закрытия репозитория.
