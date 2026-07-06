---
title: "Безопасность gateway"
type: security
sources:
  - gateway-service/src/api/auth.py
related:
  - architecture/hld.md
  - features/0001-user-authentication.md
created: "2026-07-03"
updated: "2026-07-03"
confidence: medium
domain: identity
repositories:
  - gateway-service
---

# Безопасность

## Источники

- `gateway-service/src/api/auth.py`

- CLI-токен передаётся в `Authorization` header.
