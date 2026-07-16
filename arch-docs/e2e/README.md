# arch-docs e2e

Playwright-тесты полного стека (`nginx` + `arch-docs` backend + `arch-docs-front`).

## Предпосылки

E2e-тесты не поднимают стек сами — предполагается, что `docker compose up` уже запущен
из `arch-docs/` и SPA доступна на `http://localhost`:

```bash
cd arch-docs
docker compose --env-file .env.docker up -d
```

## Запуск

```bash
cd arch-docs/e2e
npm install
npx playwright install --with-deps chromium
npm test
```

Базовый URL можно переопределить через `E2E_BASE_URL` (по умолчанию `http://localhost`).

## Что покрыто сейчас

Только smoke-уровень: nginx отдаёт SPA на `/`, SPA fallback работает на клиентских route
(`/setup`), backend доступен через `/v1/models`. Сценарные e2e (`auth -> init -> docs`)
— следующий шаг, см. `docs/spec/2026-07-14-arch-docs-react-spa.md`, этап 7.
