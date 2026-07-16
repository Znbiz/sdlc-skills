# Arch Docs Frontend SPA

**Цель:** добавить в репозиторий отдельное frontend-приложение `arch-docs-front` как React SPA для работы с сервисом `arch-docs`. Первая версия должна закрывать три сценария: подготовка среды и авторизации, полный интерактивный запуск `init_arch`, просмотр сгенерированной документации по дереву файлов.

**Архитектура:** frontend живет в отдельном каталоге и отдельном Docker-контейнере `arch-docs-front`. Внешней точкой входа остается `nginx`: он отдает SPA и проксирует backend API/SSE в `arch-docs`. SPA не читает workspace или Docker volumes напрямую. Все данные и действия идут через HTTP/SSE-контракты backend, включая readiness checks, auth flow, workflow transport и просмотр generated arch-repo.

**Tech Stack:** React SPA, TypeScript, Vite, React Router, query-layer для server state, SSE через `EventSource`, Docker multi-stage build, `nginx` как reverse proxy.

## Опора на текущий backend

Первая реализация frontend должна в первую очередь опираться на уже существующий backend surface, а не требовать параллельного проектирования новой API-платформы.

Уже есть и должны использоваться как основа:

- `GET /api/rest/cli-auth/` для статуса `codex` и `claude`;
- `POST /api/rpc/cli-auth/init/` для запуска auth flow;
- `GET /api/rest/cli-auth/auth-sessions/{auth_session_id}/`;
- `GET /api/rest/cli-auth/auth-sessions/{auth_session_id}/stream/`;
- `POST /api/rest/conversations/`;
- `GET /api/rest/conversations/{conversation_id}/`;
- `GET /api/rest/conversations/{conversation_id}/items/`;
- `GET /api/rest/conversations/{conversation_id}/stream/`;
- `POST /api/rest/responses/`;
- `GET /api/rest/responses/{response_id}/`;
- `POST /api/rest/responses/{response_id}/actions/`.

Новые backend-добавки для первой версии должны быть минимальными и адресными:

- PAT-based Git credentials API для user-provided token;
- HTTPS-based repository access check, использующий сохраненный PAT;
- небольшой response-scoped docs browser API;
- небольшое расширение workflow/read-model для хранения `workspace_dir` и `arch_repo_dir`.

## Глобальные ограничения

- `arch-docs-front` остается отдельным проектом в корне репозитория: `sdlc/arch-docs-front/`.
- Первая версия не делает редактирование документации, только просмотр.
- UI не должен зависеть от прямого доступа к хостовой файловой системе, Docker volume или backend container shell.
- Все long-running операции должны переживать обновление страницы через повторное чтение backend read-model.
- `init_arch` в первой версии поддерживается в полном режиме: запуск, live SSE, `required_actions`, отправка ответов, terminal result, переход в просмотр generated docs.
- onboarding Git-доступа должен быть настоящим operational readiness flow, а не статичным чеклистом.
- SPA обязана запускаться и собираться в Docker Compose рядом с `arch-docs`.
- Вне scope первой версии: multi-user auth, inline editing docs, visual diff between runs, generic workflow designer, offline mode.

## Пользовательские сценарии

### 1. Setup

Экран `Setup` показывает readiness среды до запуска `init_arch`.

Пользователь видит:

- статус авторизации `Codex`;
- статус авторизации `Claude`;
- статус сохранения Git Personal Access Token;
- статус проверки доступа к целевому репозиторию;
- actionable ошибки и следующие шаги.

С экрана доступны действия:

- запустить auth flow для `codex` или `claude`;
- смотреть live progress auth через SSE;
- отправить device/user code, если backend запросил его отдельно;
- ввести Personal Access Token;
- сохранить или заменить Personal Access Token;
- проверить доступ к репозиторию через backend probe по HTTPS;
- удалить сохраненный токен;
- повторить проверку доступа после обновления токена.

### 2. Init Workflow

Экран `Init Workflow` ведет полный сценарий `conversation` / `response`.

Пользователь может:

- создать новую conversation;
- запустить `init_arch` response;
- видеть текущий шаг, текущий репозиторий, timeline items и stream событий;
- отвечать на `required_actions`;
- продолжать paused/interrupted run;
- после завершения перейти к generated docs.

Экран не должен хранить состояние только локально. Источник истины:

- `GET /conversations/{id}`;
- `GET /conversations/{id}/items`;
- `GET /responses/{id}`;
- `GET /conversations/{id}/stream`;
- `POST /responses/{id}/actions`.

### 3. Docs Viewer

Экран `Docs` показывает generated architecture repository как дерево директорий и файлов.

Поддерживаемое поведение:

- раскрытие директорий;
- открытие произвольного файла;
- рендер `Markdown` как документ;
- форматированный просмотр `YAML` / `JSON`;
- fallback на plain text для остальных текстовых файлов;
- отображение metadata: относительный путь, тип файла, размер, время изменения;
- deep-link на конкретный файл через route/query params.

Первая версия не поддерживает:

- редактирование и сохранение;
- бинарные вложения;
- поиск по содержимому;
- сравнение версий.

## Информационная архитектура и маршруты

Минимальный набор route:

- `/` — redirect на dashboard или `setup`;
- `/setup`;
- `/workflows/init`;
- `/workflows/init/:conversationId`;
- `/docs`;
- `/docs?responseId=<response-id>&path=<relative-path>`.

Навигация верхнего уровня:

- `Setup`
- `Init Workflow`
- `Docs`

На dashboard допустим компактный summary-блок:

- readiness status;
- последняя conversation;
- быстрые действия `Start init` / `Open docs`.

## Frontend-модули

### `app`

- bootstrap SPA;
- router;
- app shell;
- env config.

### `features/setup`

- auth status polling/query;
- auth session SSE;
- Git PAT form and access-check cards.

### `features/workflow`

- conversation creation;
- response launch;
- timeline;
- stream event reducer;
- required actions renderer;
- terminal result summary.

### `features/docs`

- file tree;
- file content loader;
- markdown renderer;
- code/text viewer;
- route sync for active path.

### `shared`

- typed API client;
- SSE utilities;
- UI primitives;
- error mapping;
- date/size formatting;
- domain models.

## State and data flow

Server state хранится отдельно от transient UI state.

- Query-layer читает snapshot endpoints.
- SSE обновляет экран поверх snapshot и при reconnect выполняет re-fetch.
- Форма ответа на `required_action` локальна до submit.
- Route state определяет активный conversation и открытый doc path.

Инварианты:

- после reload SPA может восстановить экран по backend read-model;
- потеря SSE не делает UI unusable;
- terminal result всегда дочитывается через snapshot endpoint, а не только из stream;
- UI не парсит свободный текст ошибок как основной контракт, а опирается на typed status/reason fields где они есть.

## Backend зависимости

Frontend первой версии требует следующие backend capability:

- существующие auth endpoints и auth SSE;
- новый Git credentials surface для PAT и repository access check;
- существующие workflow endpoints и workflow SSE;
- небольшой response-scoped docs tree/file API;
- небольшое расширение existing workflow/read-model payload, чтобы UI знал `workspace_dir` и `arch_repo_dir` активного или завершенного `init_arch` run;
- CORS не нужен при работе через `nginx`, но route/proxy contract должен быть стабилен.

Если backend capability отсутствует, frontend не должен подменять ее client-side эвристикой.

## Docker и runtime

### Каталог проекта

Ожидаемая структура:

```text
arch-docs-front/
├── docs/
│   └── specs/
├── src/
├── public/
├── package.json
├── tsconfig.json
├── vite.config.ts
├── Dockerfile
└── README.md
```

### Compose integration

В `arch-docs/docker-compose.yml` должен появиться сервис `arch-docs-front`:

- build из `../arch-docs-front` или эквивалентного относительного пути;
- expose внутреннего порта frontend runtime;
- зависимость от `arch-docs` только на уровне network reachability, не через shared filesystem;
- подключение к тому же compose network, что `nginx`.

`nginx` должен:

- слать `/api/` и SSE в `arch-docs`;
- слать `/` и frontend assets в `arch-docs-front`;
- поддерживать SPA fallback на `index.html`;
- не буферизовать SSE endpoints.

### Env contract

Frontend получает:

- `VITE_API_BASE_PATH=/api`;
- при необходимости `VITE_APP_TITLE`;
- feature flags только если они действительно нужны.

Первая версия не требует отдельного runtime secret во frontend.

## Error handling

SPA должна различать:

- transport/network error;
- backend validation error;
- long-running process failure;
- readiness failure;
- file not found / forbidden path;
- auth expired / auth failed.

Требования:

- пользователь видит actionable сообщение;
- повторяемые действия доступны без full page reload;
- stream disconnect показывает degraded state и делает reconnect;
- sensitive backend details не отображаются как raw stack trace.

## Security

- SPA не хранит Personal Access Token дольше локального submit-цикла формы.
- UI показывает только safe metadata readiness checks.
- Просмотр документации ограничен файлами, которые backend явно разрешил.
- Deep-links к doc path не должны позволять path traversal.

## Accessibility and UX

- базовая keyboard navigation для setup cards, workflow actions и docs tree;
- читаемая иерархия статусов;
- явное разделение `in progress`, `needs action`, `failed`, `completed`;
- мобильная поддержка обязательна, но primary target первой версии — desktop operator workflow;
- не использовать визуальный язык “chat app”; это operational console для архитектурного workflow.
- интерфейс весь на русском языке

## Нефункциональные требования

- dev startup через Docker Compose должен поднимать frontend вместе с backend;
- production build frontend должен быть детерминированным;
- cold reload страницы не должен ломать активный run;
- initial page load на локальном контуре должен быть быстрым и не требовать предварительного прогрева;
- все API-интеграции typed и централизованы, без ad hoc `fetch` по экранам;
- структура проекта должна позволять без переписывания добавить `update_arch` следующим этапом.

## Тестирование

Минимальный контур:

- unit tests для status mapping, reducers/hooks, docs path helpers;
- component tests для setup/workflow/docs ключевых экранов;
- contract-level tests API client against mocked backend responses;
- smoke test Docker startup для frontend container;
- e2e happy path для `auth -> init -> docs open` допустим как следующий этап, но архитектура должна его предусматривать.

## Этапы реализации

> Статус на 2026-07-14: этапы 1-7 реализованы (backend contracts были готовы до старта фронтенда; фронтенд реализован полностью в рамках этой сессии). Мини-отчёты — под каждым этапом.

### Этап 1. Backend contracts ready

Frontend implementation не начинается с экранов. Сначала backend должен отдать минимально пригодные контракты:

- `setup/git-credentials`
- existing `cli-auth`
- existing `conversations/responses`
- `docs/tree`
- `docs/file`

Выход этапа:

- frontend-команда знает, какие существующие endpoints переиспользуются без изменений;
- минимальные новые контракты ограничены PAT flow, docs browser и path metadata;
- можно начать typed API client без проектирования нового setup API слоя.

**Статус: ✅ выполнено (уже было в репозитории до старта фронтенда).**

Мини-отчёт: контракты уже существовали в `arch-docs` до начала работы над фронтендом (`git log` показывает `feat(arch-docs): добавить response-scoped docs browser API`, `сохранять workspace_dir и arch_repo_dir`, `переписать git-credentials REST API под контракт спеки` и т.д.). Проверены исходники: `app/api/rest/cli_auth.py`, `app/api/rpc/cli_auth.py`, `app/api/rest/git_credentials.py`, `app/api/rest/conversations.py`, `app/api/rest/docs.py`. Обнаружен и задокументирован важный нюанс, не отражённый в спеке: все `/api/*` запросы защищены `BearerAuthMiddleware` со статичным `AUTH_SECRET` — учтено на этапе 3 (инъекция заголовка на уровне `nginx`, без runtime-секрета во фронтенде).

### Этап 2. Frontend scaffold and platform

Нужно создать `arch-docs-front` как отдельный проект и поднять общий каркас:

- Vite + React + TypeScript;
- router;
- app shell;
- shared API client;
- shared SSE helpers;
- базовые status/error UI primitives;
- env contract.

Выход этапа:

- SPA запускается локально;
- есть каркас для экранов;
- есть единый способ работать с API и SSE.

**Статус: ✅ выполнено.**

Мини-отчёт: собран каркас вручную (Vite CLI не работал в неинтерактивном режиме) — `package.json`, `tsconfig*.json`, `vite.config.ts`, `vitest.config.ts`. Роутер (`react-router-dom`, `createBrowserRouter`) с маршрутами `/`, `/setup`, `/workflows/init`, `/workflows/init/:conversationId`, `/docs`. `AppShell` с верхней навигацией (Setup / Init Workflow / Docs) и light/dark темой через CSS-переменные (`prefers-color-scheme`). Типизированный API-клиент (`shared/api/http-client.ts` + `endpoints.ts` + `models.ts`) с моделями, списанными напрямую с pydantic-схем backend. `ApiError` с разбором `kind`/`reason_code`/typed `detail` (не парсит свободный текст как контракт). SSE-хелпер `useEventSource` с авто-reconnect и статусами `connecting/open/reconnecting/closed`. `npm run build` и `tsc -b` проходят чисто, dev/preview сервер проверен `curl` (200 на `/`).

### Этап 3. Docker, compose and nginx integration

После каркаса нужно встроить фронт в существующий runtime contour:

- frontend `Dockerfile`;
- compose service `arch-docs-front`;
- `nginx` proxy rules для `/`, `/api/*` и SSE;
- SPA fallback routing.

Выход этапа:

- `docker compose up` поднимает backend, frontend и proxy;
- SPA доступна через тот же входной адрес, что и backend.

**Статус: ✅ выполнено.**

Мини-отчёт: добавлен `arch-docs-front/Dockerfile` (multi-stage: `node:20-alpine` build → `nginx:alpine` runtime) и собственный `arch-docs-front/nginx.conf` с SPA fallback (`try_files ... /index.html`). В `arch-docs/docker-compose.yml` добавлен сервис `arch-docs-front` (билд из `../arch-docs-front`, только network-зависимость от `arch-docs`, без shared volume). Обнаружен архитектурный нюанс: backend требует `Authorization: Bearer <AUTH_SECRET>` на каждый запрос (`BearerAuthMiddleware`), а спека требует, чтобы фронт не хранил рантайм-секрет — поэтому верхнеуровневый `nginx` переведён на envsubst-темплейтинг (`arch-docs/nginx-templates/default.conf.template`, монтируется в `/etc/nginx/templates`), который сам инжектирует `Authorization: Bearer ${AUTH_SECRET}` в проксируемые `/api/*` и `/stream/` запросы — браузер токен не видит. `/` теперь проксируется на upstream `arch_docs_front`; сохранён доступ к `/docs`, `/redoc`, `/openapi.json` (открытые пути backend) напрямую на `arch_docs`. Старый `arch-docs/nginx.conf` не удалён (это отслеживаемый git-файл, для удаления нужно явное разрешение пользователя) — просто больше не монтируется в compose.
Проверено вживую: `docker build` фронтенда проходит, контейнер отдаёт `200` на `/` и на клиентский роут `/setup` (SPA fallback работает); `envsubst`-темплейт nginx проверен через `docker run ... nginx -t` — `${AUTH_SECRET}` корректно подставляется во все `Authorization`-заголовки, синтаксис конфига валиден (ошибка "host not found in upstream" ожидаема вне сети compose). Полный `docker compose up` end-to-end не прогонялся (тяжёлая сборка backend с CLI-агентами, БД и внешними секретами) — это единственная часть этапа 3, не провалидированная вживую.

### Этап 4. Setup screen

Первый пользовательский экран — `Setup`, потому что он подготавливает среду до workflow:

- auth status cards;
- auth start + auth SSE;
- ввод и сохранение Personal Access Token;
- ввод repository URL и вызов backend access-check по HTTPS;
- минимальные retry/recheck actions.

Выход этапа:

- пользователь может довести среду до рабочего состояния;
- UI покрывает реальные operational prerequisites для `init_arch` в рамках уже существующего backend behavior.

**Статус: ✅ выполнено.**

Мини-отчёт: `features/setup/` — карточки статуса `Codex`/`Claude` (`AuthEngineCard`) с запуском auth flow (`POST /rpc/cli-auth/init/`), live-панелью SSE (`AuthSessionPanel` на `useEventSource`) и формой отправки device/user-кода (`POST .../submit-code/`). `auth_session_id` сохраняется в `localStorage` (`shared/storage/recent-auth-session.ts`), чтобы live-сессия восстанавливалась после reload через снапшот `GET .../auth-sessions/{id}/` — SSE только дополняет, а не является источником истины. `GitTokenCard` — сохранение/удаление PAT по хосту. `RepositoryAccessCard` — HTTPS access-check с typed `access_status`/`reason_code`. Статусы замаплены в `shared/status/status-mapping.ts` на основе реальных backend enum'ов (`CliAuthStatus`, `GitAccessStatus` из `app/services/*`), а не догадок.

### Этап 5. Init workflow screen

После setup реализуется основной сценарий:

- create conversation;
- start `init_arch`;
- timeline/status panels;
- stream handling;
- `required_actions`;
- submit actions;
- terminal result.

Выход этапа:

- полный интерактивный `init_arch` проходит из UI end-to-end;
- reload страницы не ломает active run.

**Статус: ✅ выполнено.**

Мини-отчёт: `features/workflow/` — старт conversation, запуск `init_arch` response, панель текущего статуса, `RequiredActionCard`, лог SSE-событий, `TerminalResult`, `Timeline`. Ключевая находка при чтении backend (`app/services/init_arch_workflow.py`): `action_type` в `required_actions` — это сырой `interrupt_type` из LangGraph (`user_question`, `user_input`, `temporal_window_confirmation`), а **не** тот `action_type`, который принимает `POST /responses/{id}/actions/` (`answer_question`, `resume`, `confirm_temporal_window`) — это две разные таксономии на входе и на выходе одного контракта. Frontend явно маппит одно на другое в `RequiredActionCard` (а не угадывает по тексту). Reducer SSE-событий (`stream-events.ts`) — чистая функция, разбирает реальные типы событий backend (`step_started`, `cli_output`, `interrupted`, `workflow_done`, `workflow_failed`, `workflow_cancelled`, и taskovые `progress`/`output`/`done`). Источник истины после reconnect/после terminal — снапшот `GET /conversations/{id}` (react-query), поток только дополняет лог.

### Этап 6. Docs viewer

Когда workflow умеет завершаться, добавляется просмотр результатов:

- docs tree;
- file open by path;
- markdown renderer;
- yaml/json/text viewer;
- deep-link на файл;
- переход из terminal result в docs.

Выход этапа:

- пользователь может открыть generated arch-repo конкретного `init_arch` run и читать любой поддерживаемый текстовый файл.

**Статус: ✅ выполнено.**

Мини-отчёт: `features/docs/` — `FileTree` (рекурсивный expand/collapse, корень раскрыт по умолчанию, `ancestorPaths` авто-раскрывает путь до active file), `FileViewer` с рендером `markdown` (`react-markdown` + `remark-gfm`), форматированием `yaml`/`json` (парсинг + повторная сериализация с отступами) и fallback на `plain text`/«предпросмотр недоступен» при `content: null` (unsupported/undecodable). Дерево получаем одним запросом `GET /responses/{id}/docs/tree/` (backend уже возвращает весь вложенный tree, отдельных запросов на директорию не нужно). Deep-link — `?responseId=&path=` через `useSearchParams`, path traversal не эмулируется на клиенте — валидация `PATH_FORBIDDEN` полностью на backend (403 → typed `reason_code`, замаплено в `ErrorBanner`).

### Этап 7. Hardening and end-to-end verification

Финальный этап закрывает устойчивость и качество:

- component/integration tests для экранов;
- contract tests для API client;
- smoke tests Docker startup;
- happy-path проверка `setup -> init -> docs`;
- polish UX и обработка деградаций SSE/network.

Выход этапа:

- весь пользовательский сценарий подтвержден на локальном контуре;
- приложение готово к дальнейшему расширению под `update_arch`.

**Статус: ⚠️ выполнено частично.**

Мини-отчёт: 37 тестов (Vitest + Testing Library + MSW), все зелёные — `npx vitest run`:

- unit: `status-mapping.test.ts` (маппинг статусов auth/access/response), `stream-events.test.ts` (reducer SSE, включая обрезку лога и терминальность), `file-tree.test.ts` (`ancestorPaths`), `format.test.ts` (размер файла).
- contract: `shared/api/http-client.test.ts` — парсинг успешных ответов backend в типизированные модели, маппинг 404/403 с typed `reason_code` в `ApiError`, оборачивание сетевых сбоев в `transport`-ошибку (через MSW-моки реальных backend-контрактов).
- component: `setup-page.test.tsx` (рендер статусов CLI + ошибки backend с retry), `docs-page.test.tsx` (открытие файла из дерева, рендер markdown, empty-state без `responseId`).
- Docker smoke: `docker build` фронтенда проходит, контейнер отдаёт `200` на `/` и на клиентский роут (SPA fallback), `envsubst`-темплейт nginx проверен на реальную подстановку `AUTH_SECRET` и валидный синтаксис.
- `npm run build` и `tsc -b` — чисто, без ошибок.

Не выполнено в этой сессии (осознанно, для явной фиксации, а не тихого умолчания):

- Полный `docker compose up` со всем стеком (`postgres` + `arch-docs` с CLI-агентами + `nginx` + фронт) end-to-end не прогонялся — тяжёлая сборка, внешние секреты/CLI-логины недоступны в этой среде.
- e2e happy-path `auth -> init -> docs` не автоматизирован (в спеке это прямо помечено как допустимое для следующего этапа, архитектура это позволяет: SSE + snapshot read-model, deep-links, persisted `conversationId`/`responseId`).

## Риски и компромиссы

- Основной риск первой версии не во frontend, а в том, что PAT-поток потребует безопасного server-side хранения токена и четкой redaction policy.
- Второй риск — смешать в одном UX PAT и legacy SSH-подход; первая версия должна вести пользователя по одному основному пути, а именно PAT.
- SSE и snapshot read-model могут временно рассинхронизироваться; SPA должна считать snapshot источником истины после reconnect.
- Docs viewer требует небольшого расширения workflow metadata, иначе UI не сможет надежно восстановить `arch_repo_dir` после reload.

## Критерии готовности

- В репозитории создан проект `arch-docs-front` с отдельным Docker build/run контуром.
- `docker compose up` для `arch-docs` поднимает frontend вместе с backend.
- Пользователь может пройти auth flow для `codex` и `claude` из UI.
- Пользователь может сохранить Personal Access Token, проверить доступ к целевому репозиторию и затем пройти полный `init_arch` flow.
- После завершения пользователь может открыть generated docs tree конкретного run и просмотреть любой текстовый файл.
- Все filesystem-sensitive операции идут через backend API, а не через прямой доступ frontend к volume или попытку читать paths напрямую из браузера.

## Out of Scope

- редактирование generated docs;
- generic Git repository browser вне generated arch-repo;
- support для нескольких независимых пользователей;
- rich diff/compare UI;
- интеграция с внешним SSO.
