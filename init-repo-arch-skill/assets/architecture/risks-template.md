---
title: "Известные риски и технический долг"
type: risk
sources:
  - <repo-name/path/to/file>
related:
  - architecture/security.md
created: "<YYYY-MM-DD>"
updated: "<YYYY-MM-DD>"
confidence: medium
domain: "<domain-id>"
repositories:
  - <repo-name>
---

# Известные риски и технический долг

Фиксируй только то, что подтверждается кодом, конфигурацией, тестами или известными инцидентами. Не выдумывай риски — помечай предположения явно.

| ID | Описание | Компонент / сервис | Категория | Серьёзность | Тип утверждения | Источники | Текущее смягчение | Рекомендуемое действие |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `RISK-001` | `<описание риска>` | `<service-name>` | `reliability \| security \| performance \| maintainability \| compliance` | `critical \| high \| medium \| low` | `наблюдаемый факт \| выведено косвенно \| требует подтверждения` | `<repo-name/path/to/file>` | `<что уже сделано или намеренно не сделано>` | `<что стоит сделать>` |

## Категории

- **reliability** — нет retry, нет circuit breaker, единая точка отказа, отсутствующий fallback, shared mutable state
- **security** — хранение секретов в коде, отсутствующая валидация, незащищённый эндпоинт, EOL-зависимость с CVE
- **performance** — N+1 запросы, отсутствующий индекс, синхронный вызов на critical path
- **maintainability** — EOL-фреймворк, отсутствующие тесты на критичный поток, размазанная бизнес-логика
- **compliance** — PII без шифрования at rest, отсутствующий audit log на регулируемые операции
