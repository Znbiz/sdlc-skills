# arch-docs-front

React SPA для сервиса `arch-docs`: подготовка окружения (`Setup`), полный интерактивный запуск `init_arch` (`Init Workflow`) и просмотр сгенерированной документации (`Docs`).

Спецификация: [docs/spec/2026-07-14-arch-docs-react-spa.md](../docs/spec/2026-07-14-arch-docs-react-spa.md).

## Стек

- React 18 + TypeScript, Vite
- React Router (client-side маршрутизация, deep-links)
- `@tanstack/react-query` — server state, кэш, ре-фетч
- `EventSource` (нативный SSE) — live-обновления auth/workflow
- `react-markdown` + `remark-gfm`, `yaml` — просмотр документации
- Vitest + Testing Library + MSW — unit/component/contract тесты

## Разработка

```bash
npm install
npm run dev       # http://localhost:5173, ожидает backend на VITE_API_BASE_PATH
npm run build     # tsc -b && vite build
npm run test      # vitest run
npm run lint
```

По умолчанию dev-сервер обращается к `/api` (см. `.env.example`). Backend должен быть поднят отдельно (см. `../docker-compose.yml`) либо проксирован через дev-прокси.

## Env contract

| Переменная | Назначение | По умолчанию |
| --- | --- | --- |
| `VITE_API_BASE_PATH` | Префикс REST/RPC/SSE-запросов к backend | `/api` |
| `VITE_APP_TITLE` | Заголовок в шапке приложения | `arch-docs` |

Frontend не хранит собственный runtime-секрет: авторизация к backend (`Authorization: Bearer`) инжектируется верхнеуровневым `nginx`, а не браузером — см. `../nginx-templates/default.conf.template`.

## Docker

Сборка контейнера:

```bash
docker build -t arch-docs-front .
docker run -p 8080:80 arch-docs-front
```

В составе продукта контейнер `arch-docs-front` собирается и поднимается через `../docker-compose.yml` вместе с `arch-docs` (`../back`) и `nginx`:

```bash
cd ..
docker compose up --build
```

`nginx` слушает `:80`, отдаёт SPA (с fallback на `index.html` для client-side роутов) и проксирует `/api/*` и SSE в `arch-docs`.

## Структура

```text
src/
├── app/            bootstrap, router, app shell, тема
├── shared/         типизированный API-клиент, SSE-хелпер, UI-примитивы, форматирование, error mapping
├── features/setup/     Setup: auth CLI, PAT, repository access-check
├── features/workflow/  Init Workflow: conversation/response, SSE, required_actions
├── features/docs/      Docs Viewer: дерево, просмотр markdown/yaml/json/text
└── features/dashboard/ компактный summary-экран на "/"
```

## Известные ограничения первой версии

- Только просмотр документации, без редактирования.
- Нет multi-user авторизации, visual diff между runs, offline-режима.
- e2e happy-path (`auth -> init -> docs`) не автоматизирован — предусмотрен архитектурой, но пока покрыт только smoke-уровнем в `../e2e/`, без сценарного прохода.
