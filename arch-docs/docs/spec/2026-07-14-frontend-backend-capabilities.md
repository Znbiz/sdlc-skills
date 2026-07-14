# Backend Capabilities For Arch Docs Frontend

**Цель:** подготовить backend `arch-docs` к работе нового React SPA из `arch-docs-front`. Backend должен стать единственным trusted execution and data surface для setup/onboarding, workflow transport и просмотра generated documentation. Особый акцент первой версии: полноценная readiness-модель для Git-доступа через user-provided Personal Access Token, а также для `Codex`, `Claude`, workspace и generated arch-repo.

**Архитектура:** новый frontend не получает прямого доступа к Docker volumes или файловой системе. Все операции идут через backend API. Backend уже содержит существенную часть нужного surface: `cli-auth` и conversation-first workflow transport. При этом текущий `git_ssh` контур существует в коде, но для первой версии frontend считается secondary/legacy path. Основной onboarding-поток должен быть перестроен на Git over HTTPS с user-provided Personal Access Token, с минимальными дополнениями: Git credentials API, path metadata в workflow/read-model и response-scoped docs browser.

**Tech Stack:** FastAPI, Pydantic v2, existing `GatewaySettings`, existing workflow/read-model services, filesystem access внутри backend container, subprocess/system checks для `git`, secure server-side token storage, SSE only where long-running interaction already существует.

## Глобальные ограничения

- Backend остается source of truth для readiness и generated docs access.
- Нельзя отдавать frontend содержимое токенов, auth files или полный shell output без фильтрации.
- Все filesystem операции ограничены разрешенным workspace и generated arch-repo.
- Новые capability должны быть read-only, кроме явных actions типа `start auth`, `submit action`, `rerun readiness checks`.
- Новые API не должны ломать текущие consumers `open-webui` или существующие workflow transports.
- readiness первой версии для Git-доступа должен быть operationally meaningful: UI должен понимать, можно ли реально перейти к `init_arch`, а не просто видит “git установлен”.

## Текущая подтвержденная база

На момент обновления этой спеки backend уже умеет следующее:

- `GET /api/rest/cli-auth/` возвращает статусы `codex` и `claude` через `check_codex_auth()` и `check_claude_auth()`;
- `POST /api/rpc/cli-auth/init/` запускает auth session;
- `GET /api/rest/cli-auth/auth-sessions/{id}/` и `.../stream/` уже дают polling + SSE для auth flow;
- `POST /api/rest/conversations/`, `POST /api/rest/responses/`, `GET /api/rest/conversations/...`, `GET /api/rest/responses/...`, `POST /api/rest/responses/{id}/actions/` уже дают основной workflow transport для `init_arch`.

Дополнительно в коде уже есть SSH-ориентированный контур:

- `GET /api/rest/git-ssh/public-key/`;
- `POST /api/rpc/git-ssh/check-access/`;
- `app/services/git_ssh.py` с service-managed key generation и `git ls-remote` probe.

Этот контур считается подтвержденной существующей базой, но для первой версии frontend не является primary onboarding path.

## Почему нужны небольшие дополнения

Существующий backend уже умеет:

- auth flow для `codex` и `claude`;
- workflow conversation/response/read-model;
- SSE transport для auth и workflow.

Но frontend первой версии также требует:

- прием и безопасное хранение user-provided PAT;
- repository access check через HTTPS с использованием сохраненного PAT;
- способ привязать generated docs к конкретному `init_arch` run;
- просмотр дерева generated docs и чтение файлов;
- чуть более удобный HTTP surface для frontend поверх уже существующих endpoints там, где это действительно нужно.

## Capability 1: Reuse current auth and workflow endpoints

Для первой версии frontend должен по умолчанию переиспользовать текущие endpoints, а не требовать нового обязательного aggregate setup API.

Базовый setup flow уже может быть собран из:

- `GET /api/rest/cli-auth/`
- `POST /api/rpc/cli-auth/init/`
- `GET /api/rest/cli-auth/auth-sessions/{id}/`
- `GET /api/rest/cli-auth/auth-sessions/{id}/stream/`

Опционально, но не обязательно для первой итерации:

- легкий aggregate endpoint позже, если fan-out окажется неудобным.

Workflow flow уже может быть собран из существующих:

- `POST /api/rest/conversations/`
- `GET /api/rest/conversations/{id}/`
- `GET /api/rest/conversations/{id}/items/`
- `GET /api/rest/conversations/{id}/stream/`
- `POST /api/rest/responses/`
- `GET /api/rest/responses/{id}/`
- `POST /api/rest/responses/{id}/actions/`

## Capability 2: Git access via Personal Access Token

### Цель

Сделать основным onboarding-путем Git over HTTPS с user-provided Personal Access Token.

### Что меняется по сравнению с текущим кодом

- текущий `git_ssh` код остается в сервисе как secondary/legacy capability;
- frontend first-run flow больше не зависит от `public-key` и SSH key provisioning;
- новый путь строится вокруг token submission и HTTPS probe.

### Что нужно добавить минимально

- endpoint для сохранения или обновления PAT;
- endpoint для удаления PAT;
- endpoint для masked PAT status, чтобы UI понимал, что токен уже задан;
- repository access-check endpoint, использующий сохраненный PAT для `git ls-remote` по HTTPS;
- нормализованные reason codes для UI поверх результатов probe;
- server-side storage policy для PAT.

### Предпочтительная модель первой версии

- UI отправляет PAT в backend один раз;
- backend сохраняет его server-side в single-user secret storage;
- UI передает `repository_url` в access-check;
- backend использует PAT для HTTPS-authenticated `git ls-remote`;
- успешный `git ls-remote` считается достаточным подтверждением readiness для первой версии.

### Минимальные endpoints

- `GET /api/rest/git-credentials/`
- `PUT /api/rest/git-credentials/personal-access-token/`
- `DELETE /api/rest/git-credentials/personal-access-token/`
- `POST /api/rest/git-credentials/check-access/`

### Storage policy

- token не возвращается из API после сохранения;
- backend хранит token только server-side;
- для первой версии допустим single-user storage в отдельном secret file или dedicated settings-backed secret storage с restrictive permissions;
- plaintext token не должен попадать в логи, exception text, SSE events или DB read-model;
- если later потребуется rotation/audit, это отдельный этап, не обязательный для первой версии.

## Capability 3: Path metadata in workflow/read-model

Чтобы frontend мог открыть generated docs после reload или повторного входа в conversation, backend должен сохранять и отдавать:

- `workspace_dir` конкретного run;
- `arch_repo_dir` конкретного run.

### Минимальное изменение

- расширить `WorkflowRecord` и его persistence/read-model;
- при старте `init_arch` сохранять `resolved_workspace_dir` и `resolved_arch_repo_dir`;
- включить эти поля в payload `GET /api/rest/responses/{response_id}/` и активного response в `GET /api/rest/conversations/{conversation_id}/`.

Это намного ближе к текущему коду, чем вводить отдельный глобальный workspace status API как обязательный первый шаг.

## Capability 4: Docs Browser API

### Цель

Дать frontend доступ к generated docs без прямого filesystem access, но не как глобальному файловому браузеру, а как viewer для конкретного workflow/result context.

### Требуемое поведение

Frontend должен уметь:

- запросить дерево директорий;
- открыть файл по относительному пути;
- получить metadata и content type;
- понимать, что файл текстовый и как его лучше рендерить.

### Предпочтительные минимальные endpoints

- `GET /api/rest/responses/{response_id}/docs/tree/`
- `GET /api/rest/responses/{response_id}/docs/file/?path=<relative-path>`

### Contract для tree

Нужны поля:

- `path`
- `name`
- `node_type: file | directory`
- `children` или lazy-loading contract
- `size`
- `modified_at`
- `media_kind: markdown | yaml | json | text | unsupported`

Для первой версии допустим вернуть полное дерево целиком, если размер умеренный. Если есть риск крупных репозиториев, лучше сразу проектировать lazy-loading по path.

### Contract для file

Нужны поля:

- `path`
- `name`
- `media_kind`
- `content`
- `encoding`
- `size`
- `modified_at`

### Ограничения безопасности

- backend получает `arch_repo_root` из сохраненного metadata конкретного `response_id`;
- backend нормализует path и запрещает выход выше `arch_repo_root`;
- backend не отдает бинарные файлы как есть;
- для unsupported/binary возвращается typed error или metadata-only response;
- backend не раскрывает абсолютные пути контейнера без необходимости.

## API surface and layering

Новые возможности стоит добавлять поверх существующих router-ов и сервисов, а не рядом с ними как параллельную платформу.

Рекомендуемые точки расширения:

- добавить `app/api/rest/git_credentials.py`;
- расширить `app/api/rest/conversations.py` / `app.services.init_arch_workflow.py`, чтобы response payload включал path metadata;
- добавить небольшой `app/api/rest/docs.py` только для response-scoped docs browsing.

Новая доменная логика нужна в сервисах:

- новый `services/git_credentials.py` для storage, masking и HTTPS probe;
- небольшой `services/docs_browser.py` или эквивалентный helper для path normalization и file reading.

Если логика filesystem/probe разрастается, ее надо держать вне router-layer.

## Data model and status taxonomy

Нужно ввести единый словарь статусов и reason codes.

Минимальный taxonomy:

- status: `ok`, `warning`, `failed`, `running`, `unknown`
- aggregate: `ready`, `degraded`, `blocked`

Примеры reason codes, которые стоит ввести поверх текущих реализаций:

- `codex_not_authenticated`
- `claude_not_authenticated`
- `git_binary_missing`
- `git_pat_missing`
- `git_pat_invalid`
- `git_access_auth_failed`
- `git_access_timeout`
- `git_access_error`
- `arch_repo_missing_for_response`
- `path_forbidden`
- `file_unsupported`

Frontend должен зависеть от этих reason codes, а не от текста сообщений.

## Docker and operational implications

### Compose

Если frontend должен делать нормальный Git PAT onboarding, backend container needs a stable policy for secret handling:

- persistence-механизм для server-side token storage;
- понятная документация, что token используется только для Git over HTTPS access-check и clone/fetch внутри workflow;
- redaction policy для логов и ошибок;
- отсутствие зависимости frontend UX от `~/.ssh`, `known_hosts` или `ssh-agent`.

Это должно быть отражено в `docker-compose.yml` и в accompanying docs.

### User model

Все проверки выполняются от имени того же runtime user, что и workflow. Иначе readiness будет ложноположительным.

### Logging

Логировать только:

- check id;
- status;
- reason code;
- safe metadata вроде host, exit code, duration;
- без секретов и без полного содержимого sensitive files.

## Error handling

Новые endpoints должны возвращать typed application errors:

- `404` для отсутствующего файла внутри разрешенного root;
- `403` для path traversal / forbidden path;
- `422` для invalid probe payload;
- `503` для временно недоступного workspace/runtime dependency при необходимости.

Ошибки probe/readiness должны быть пригодны для UI, а не только для журналов.

## Testing

Минимальный тестовый контур:

- unit tests для path normalization и media kind detection;
- unit tests для mapping current `cli_auth` and new Git PAT results в UI-friendly status/reason codes;
- unit tests для token storage and masking policy;
- unit tests для HTTPS git access policy;
- API tests для existing `cli-auth` integration points и новых `git-credentials` endpoints;
- API tests для docs tree/file;
- negative tests для path traversal и binary/unsupported files;
- tests на redaction/no-secret leakage in responses.

Если git access probe использует subprocess, нужны deterministic tests через controlled mocks/stubs.

## Этапы реализации

### Этап 1. Align spec with current backend surface

Сначала нужно зафиксировать, что именно уже переиспользуется без переписывания:

- existing `cli-auth` REST/SSE;
- existing conversation/response workflow transport.

Выход этапа:

- новые задачи ограничены только узкими gaps;
- frontend не требует нового “workflow platform” слоя, но Git onboarding меняется на PAT.

### Этап 2. Add Git PAT model

Дальше добавляется новый основной Git onboarding path:

- token storage;
- masked status endpoint;
- PUT/DELETE lifecycle;
- HTTPS access-check;
- deterministic tests вокруг PAT-модели.

Выход этапа:

- PAT onboarding становится primary path для UI и готов к использованию без SSH setup.

### Этап 3. Persist workflow path metadata

Небольшое расширение conversation-first модели:

- сохранить `workspace_dir` и `arch_repo_dir` в workflow record;
- отдать их через существующий response payload.

Выход этапа:

- frontend знает, где лежат generated docs конкретного run, не вводя отдельный global workspace API.

### Этап 4. Docs browser API

После фиксации allowed root добавляется read-only docs browser:

- `GET /api/rest/responses/{response_id}/docs/tree/`
- `GET /api/rest/responses/{response_id}/docs/file/`
- path normalization;
- media kind detection;
- safe content serving только для поддерживаемых текстовых файлов.

Выход этапа:

- frontend может строить дерево файлов и viewer для конкретного `init_arch` run без прямого filesystem access.

### Этап 5. Optional setup summary helpers

Только если после интеграции выяснится, что frontend слишком сложно собирать из fan-out запросов, добавить:

- тонкий setup summary endpoint;
- или дополнительные detail endpoints над PAT flow.

Выход этапа:

- backend улучшает DX frontend без архитектурного дублирования.

### Этап 6. Integration hardening

Финальный backend-этап:

- пройти API/integration tests;
- проверить отсутствие secret leakage;
- проверить negative scenarios для path traversal и failed `git ls-remote`;
- сверить contracts с frontend spec и убедиться, что reused endpoints покрывают основной UI flow.

Выход этапа:

- backend готов обслуживать frontend end-to-end;
- дальнейшая реализация UI может идти без возврата к фундаментальным контрактам.

## Риски и компромиссы

- Самый опасный риск: принять PAT от пользователя, но не обеспечить корректную server-side redaction и secret storage policy.
- Второй риск: docs browser API сделать глобальным по workspace вместо привязки к конкретному `response_id`.
- Третий риск: оставить одновременно равноправными PAT и SSH onboarding в первом UX и тем самым запутать пользователя.

## Критерии готовности

- Backend отдает агрегированный setup status для frontend.
- Backend переиспользует существующие auth endpoints как основу setup flow.
- Backend предоставляет PAT-based Git credentials flow как primary onboarding path.
- Backend сохраняет и отдает `workspace_dir` / `arch_repo_dir` для `init_arch` run.
- Backend отдает tree и file content для generated docs в пределах `arch_repo_dir`, привязанного к конкретному `response_id`.
- Все новые контракты typed, безопасны и покрыты тестами.
- Frontend может закрыть full onboarding/init/docs сценарий без filesystem access и без проектирования нового параллельного setup API слоя.

## Out of Scope

- редактирование docs через backend;
- произвольный файловый браузер по всему workspace;
- generic secret management UI;
- multi-tenant isolation;
- хранение PAT в открытом виде в response payload, read-model или UI state дольше submit-цикла.
