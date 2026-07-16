# Init Workflow: форма параметров запуска

**Цель:** добавить на экран `Init Workflow` форму ввода параметров `init_arch` перед запуском response, чтобы пользователь мог реально запустить workflow, а не получал `422` от backend из-за пустого `input`.

**Статус:** предложение, не реализовано. Задокументировано по факту найденного при живом прогоне бага.

## Проблема

`InitWorkflowPage` (`src/features/workflow/init-workflow-page.tsx`) рендерит кнопку «Запустить init_arch», которая вызывает `useCreateInitArchResponse().mutate(conversationId)`. Хук `useCreateInitArchResponse` (`src/features/workflow/hooks.ts:35-41`) всегда шлёт `POST /api/rest/responses/` с `input: {}` — без единого параметра запуска.

Backend (`app/services/init_arch_workflow.py`, `create_response_async`) для `workflow_type=init_arch` требует все 7 полей `start_init_arch_workflow`:

- `product_name`
- `analysis_scope`
- `workspace_dir`
- `arch_repo_dir`
- `repo_list`
- `engine_name`
- `timeout_seconds`

При пустом `input` backend отдаёт `422 init_arch requires fields: ...` (после фикса backend-валидации; до фикса — сырой `500 TypeError`). Ни один экран фронтенда не собирает эти значения — форма для них никогда не была реализована, хотя backend contract для `POST /api/rest/responses/` существует с самого начала (см. [2026-07-14-arch-docs-react-spa.md](./2026-07-14-arch-docs-react-spa.md), этап 5).

## Архитектура

Изменения полностью укладываются в существующую архитектуру SPA (см. базовую спеку). Новых backend-контрактов не требуется — `POST /api/rest/responses/` уже принимает произвольный `input: Record<string, unknown>` (`src/shared/api/endpoints.ts:39-44`), нужно только реально его заполнить.

Затрагиваемые модули:

- `features/workflow/init-workflow-page.tsx` — рендер формы перед стартом response.
- `features/workflow/hooks.ts` — `useCreateInitArchResponse` должен принимать `input`, а не только `conversationId`.
- `shared/api/endpoints.ts` — уже поддерживает `input`, изменений не требует.
- новый файл `features/workflow/init-arch-form.tsx` (или аналогичное имя) — сама форма и её локальный state/валидация.

## Backend-контракт полей (source of truth: `app/services/init_arch_workflow.py`, `app/settings.py`)

| Поле | Тип | Семантика | Дефолт/примечание |
| --- | --- | --- | --- |
| `product_name` | `string` | Название продукта/системы, свободный текст, попадает в `WorkflowSessionRecord.product_name` | Обязательное, без backend-дефолта |
| `analysis_scope` | `string` | Свободный текст, описывает объём анализа; подставляется напрямую в system prompt LLM-агента (`Контур анализа: {...}`, `app/workflows/init_arch/prompts.py:259`) | В форме не показывается (см. UX) — фронт всегда шлёт константу `"full"`, как дефолт у MCP-инструмента `init_arch` (`app/mcp_server.py:63`) |
| `workspace_dir` | `string` | Абсолютный путь workspace **внутри backend-контейнера** (примонтированный volume) | Backend `GatewaySettings.workspace_dir` дефолтится в `/workspace` (см. `docker-compose.yml`), но эндпоинта, отдающего этот дефолт фронту, нет — фронт хардкодит `/workspace` как placeholder |
| `arch_repo_dir` | `string` | Путь до генерируемого arch-repo; можно передать `""` — backend сам резолвит его как `workspace_dir/arch-doc` (`InitWorkflowSettings.arch_repo_dirname`) | Разрешено пустое значение — валидация backend это допускает |
| `repo_list` | `list[string]` | Список репозиториев для анализа: HTTPS/SSH URL (`https://...`, `git@...`) либо plain-имя. `_parse_repo_list_entry` сам вычисляет `repository_name` из URL | Минимум 1 элемент, иначе `init_arch` анализировать нечего |
| `engine_name` | `"claude" \| "codex"` | CLI-движок для запуска. Backend валидирует через `_validate_engine_name` только в ветке `update_arch` — для `init_arch` строгой серверной проверки допустимых значений нет, поэтому фронт обязан ограничить выбор сам (`<select>`) | Дефолт на форме: `claude` |
| `timeout_seconds` | `int` | Таймаут шага workflow в секундах | Backend `InitWorkflowSettings.max_step_timeout_seconds = 900` — фронт предзаполняет `900` |

Ограничение `arch_repo_dir` не должен жить внутри `raw_workspace_subdir` (`.temp`) и должен быть либо внутри `workspace_dir`, либо содержать его — проверяется backend'ом (`_resolve_init_arch_paths`), фронт не дублирует эту проверку клиентски, только показывает backend-ошибку как `422 WorkflowValidationError`.

## UX

Форма показывается в карточке «Запуск init_arch» (там же, где сейчас голая кнопка), до появления `activeResponse`.

Поля формы, в порядке отображения:

1. **Название продукта** (`product_name`) — текстовое поле, обязательное.
2. **Репозитории** (`repo_list`) — динамический список текстовых полей с add/remove (минимум одна строка), каждая строка — URL или имя репозитория. Плейсхолдер: `https://github.com/org/repo.git`.
3. **Движок** (`engine_name`) — `<select>` с двумя опциями `claude` / `codex`, дефолт `claude`.
4. **Таймаут шага, сек** (`timeout_seconds`) — числовое поле, дефолт `900`, минимум `1`.
5. Секция **Advanced** (свёрнута по умолчанию, т.к. это server-side paths, не то, с чем обычно работает пользователь):
   - **Workspace dir** (`workspace_dir`) — текстовое поле, дефолт `/workspace`.
   - **Arch repo dir** (`arch_repo_dir`) — текстовое поле, можно оставить пустым (backend сам резолвит).

`analysis_scope` в форме не показывается вообще — фронт молча отправляет константу `"full"` вместе с остальным `input`. Поле есть в API-контракте только потому, что backend требует его наличие в payload; для UI это не пользовательский ввод, а implementation detail запроса.

Валидация на клиенте (перед сабмитом, чтобы не тратить круг на заведомо невалидный запрос):

- `product_name` — не пустая строка после `trim()`.
- `repo_list` — хотя бы один непустой элемент после `trim()`.
- `timeout_seconds` — целое число `> 0`.
- `workspace_dir` — не пустая строка (дефолт есть, но поле нельзя стереть в пустоту).
- `engine_name` — ограничен `<select>`, инвалидное значение невозможно.
- `arch_repo_dir` — разрешена пустая строка, отправляется как есть.

Ошибки backend (`422 WorkflowValidationError`, включая случай "arch_repo_dir must live inside workspace_dir") показываются через существующий `ErrorBanner` без парсинга текста как структурированного контракта — просто как `detail` message с возможностью retry, форма при этом сохраняет введённые значения (ошибка не должна сбрасывать state формы).

## State и data flow

- Значения формы — локальный React state в новом компоненте (не персистится между reload, аналогично `RepositoryAccessCard`).
- `useCreateInitArchResponse` меняет сигнатуру: принимает `{ conversationId: string; input: InitArchInput }` вместо одного `conversationId`.
- После успешного сабмита источник истины — снапшот `GET /conversations/{id}` (как и сейчас), форма размонтируется, т.к. `activeResponse` становится не `null`.
- Типы полей формы описываются в `shared/api/models.ts` рядом с остальными domain-моделями (`InitArchInput`), а не только inline в компоненте — чтобы `endpoints.ts`/`hooks.ts`/форма использовали один источник типов.

## Тестирование (минимум для этой фичи)

- unit: валидация полей формы (граничные случаи: пустой `repo_list`, `timeout_seconds <= 0`, пустой `product_name`); отдельно — что `analysis_scope: "full"` уходит в `input` без участия пользователя.
- component: рендер формы, сабмит с валидными данными вызывает `createResponse` с ожидаемым `input`, показ `ErrorBanner` при `422` без потери введённых значений.
- существующий тест backend `test_create_response_init_arch_returns_202` уже покрывает контракт со стороны API — новых backend-тестов эта фича не требует.

## Критерии готовности

- Пользователь может запустить `init_arch` из UI, не зная о существовании 7 обязательных полей API заранее — 6 из них форма запрашивает явно, `analysis_scope` подставляется константой без участия пользователя.
- Пустая отправка невозможна: клиентская валидация блокирует сабмит раньше, чем запрос уйдёт на backend.
- `422` от backend отображается как понятная ошибка, форма не теряет введённые данные.
- Advanced-поля (`workspace_dir`, `arch_repo_dir`) не мешают базовому сценарию — дефолты покрывают typical single-repo local run без их редактирования.

## Out of scope

- Валидация формата repo URL на клиенте сверх `trim()`/непустоты — уже валидируется backend'ом (`_parse_repo_list_entry` не бросает ошибку на произвольной строке, значит специальный клиентский парсинг не нужен).
- Persist черновика формы между reload/сессиями.
- Автоподстановка `product_name`/`repo_list` из уже проверенных в Setup репозиториев — `RepositoryAccessCard` не персистит проверенные URL нигде, откуда фронт мог бы их прочитать; это отдельное расширение backend contract, не часть этой фичи.
- Изменение backend-валидации `engine_name` для `init_arch` (сейчас only client-side restriction) — вне scope, т.к. рушить существующий контракт `create_response_async` не требуется для решения проблемы.
