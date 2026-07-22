# codebase-memory

## Текущая настройка репозитория

- MCP server в проекте: `codebase-memory-mcp`
- Бинарник: `/usr/local/bin/codebase-memory-mcp`
- Рекомендуемая индексация этого checkout: `index_repository(repo_path="/Users/aanekraso2/github.com/znbiz/sdlc", name="sdlc", persistence=true)`

## Важно про `project`

- Для всех запросов используй точное значение поля `project`, которое возвращает `index_repository`.
- Для этого checkout после индексации 2026-07-22 сервис вернул: `Users-aanekraso2-github.com-znbiz-sdlc-sdlc`
- Если checkout переедет в другой путь, значение `project` тоже изменится.

## Когда переиндексировать

- после переключения веток
- после больших `pull` или `rebase`
- после переименования или переноса файлов
- после изменения публичных API, роутинга или точек входа
