---
title: "Аутентификация пользователя"
type: feature
sources:
  - gateway-service/src/api/auth.py
  - gateway-service/tests/integration/test_auth.py
related:
  - architecture/hld.md
  - architecture/integrations/gateway-service.md
created: "2026-07-03"
updated: "2026-07-03"
confidence: high
domain: identity
repositories:
  - gateway-service
  - gateway-web
---

# Фича: Аутентификация пользователя

## Метаданные

- Идентификатор фичи: `FEAT-0001`
- Тип утверждения по умолчанию: `наблюдаемый факт`
- Основные источники:
  - `gateway-service/src/api/auth.py`
  - `gateway-service/tests/integration/test_auth.py`

## Текущее поведение

Gateway принимает credentials пользователя, выпускает CLI-токен и использует его для вызовов downstream API.

## Закрытые вопросы

- `Q-1` — подтверждение выдачи CLI-токена вынесено в этот feature-артефакт.

## Трассировка источников по разделам

| Раздел | Тип утверждения | Источники |
| --- | --- | --- |
| `Текущее поведение` | `наблюдаемый факт` | `gateway-service/src/api/auth.py`, `gateway-service/tests/integration/test_auth.py` |
