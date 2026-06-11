# Пункты checklist: roles_and_permissions_updates + security_and_auth_updates + deployment_and_operability + risks_and_tech_debt_updates

Четыре связанных пункта: роли, безопасность, операционность и технический долг.

---

## Часть 1: roles_and_permissions_updates

### Что искать

- Роли пользователей и сервисов: `ROLE_ADMIN`, `ROLE_USER`, scopes, permissions
- Middleware авторизации, `@PreAuthorize`, `permission_required`, RBAC/ABAC
- ACL-правила, матрицы доступа

### Шаги выполнения

1. Найти все middleware и декораторы авторизации.
2. Зафиксировать роли и что они разрешают или запрещают.
3. Обновить `architecture/roles-and-permissions.md` — добавить новые роли и строки матрицы.

---

## Часть 2: security_and_auth_updates

### Что искать

- **Аутентификация пользователей** — JWT, session, OAuth2, SAML, API Key
- **M2M аутентификация** — service tokens, mTLS, shared secret, внутренние JWT
- **Границы доверия** — что сервис считает доверенным (заголовки, сети, сертификаты)
- **Управление секретами** — Vault, AWS Secrets Manager, Kubernetes Secrets, хардкод (риск!)
- **Чувствительные данные** — где хранятся PII, payment data, credentials
- **Шифрование** — data at rest (encrypted columns, disk encryption), data in transit (TLS)

### Шаги выполнения

1. Найти auth middleware и проследить, как валидируется токен или сессия.
2. Определить механизм M2M аутентификации (если есть).
3. Найти все места работы с секретами.
4. Обновить `architecture/security.md` по шаблону `assets/architecture/security-template.md`.
   - Нет данных → написать `"не удалось восстановить"` в notes.

---

## Часть 3: deployment_and_operability

### Что искать

- **CI/CD** — `.github/workflows/`, `.gitlab-ci.yml`, Jenkinsfile — что запускается на PR и на merge
- **Манифесты** — Kubernetes Deployment, StatefulSet, HPA, PDB, resource limits
- **Health checks** — `/health`, `/ready`, liveness/readiness probes
- **Observability** — метрики (Prometheus, Micrometer), логирование (structured, correlation-id), tracing (OpenTelemetry, Jaeger)
- **Scaling** — горизонтальное (replica count, HPA), вертикальное (resource requests/limits)
- **Startup dependencies** — initContainers, wait-for-it, зависимости при старте

### Шаги выполнения

1. Прочитать CI/CD конфигурацию — зафиксировать pipeline stages.
2. Прочитать Kubernetes manifests — зафиксировать replica count, resource limits, probes.
3. Найти метрики и логирование — какой формат, есть ли correlation-id.
4. Зафиксировать в notes.

---

## Часть 4: risks_and_tech_debt_updates

### Что фиксировать

- Отсутствующие retry/circuit breakers для критичных интеграций
- EOL-зависимости или давно не обновлённые пакеты
- Незащищённые внутренние endpoints (нет auth)
- Проблемы с хранением чувствительных данных (plaintext, хардкод секретов)
- Shared database anti-pattern
- Большие транзакции или N+1 запросы
- Отсутствие health checks или observability
- Технический долг с известной причиной (TODO/FIXME-комментарии с контекстом)

### Шаги выполнения

1. По итогам всех предыдущих пунктов собрать список рисков и долга.
2. Добавить в `architecture/risks.md` по шаблону `assets/architecture/risks-template.md`.
   - Нет рисков → написать `"рисков не выявлено"` в notes.

---

## Обязательные выходы

- `architecture/roles-and-permissions.md` — роли и матрица функционала (или явная пометка "нет ролевой модели").
- `architecture/security.md` — модель аутентификации и границы доверия (или "не удалось восстановить").
- `architecture/risks.md` — известные риски и технический долг (или "рисков не выявлено").
- `notes` пункта `deployment_and_operability` — pipeline stages, resource limits, observability.

## Проверка согласованности и правка артефактов

Перед тем как пометить все четыре пункта `completed`:

- `architecture/security.md` содержит запись для этого сервиса или явно помечен как "не удалось восстановить".
- `architecture/risks.md` содержит записи из этого репозитория или явно помечен как "рисков не выявлено".
- `architecture/roles-and-permissions.md` отражает роли, найденные в этом репозитории.
- Если обнаружен хардкод секретов — создать запись в `open-questions.md` с `ask_user=false` и отметить как HIGH приоритет.
- Если отсутствует observability (нет метрик, нет structured logging) — зафиксировать в рисках.

## Подводные камни

- Результат не готов, если `architecture/security.md` отсутствует или не заполнен, хотя auth-механизмы видны в коде.
- Результат не готов, если `architecture/risks.md` отсутствует без явной пометки "рисков не выявлено".
