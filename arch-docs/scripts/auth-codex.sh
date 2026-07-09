#!/usr/bin/env bash
# Однократная интерактивная авторизация Codex CLI через device-auth flow.
# После выполнения токен сохраняется в volume codex-auth и переживает рестарты контейнера.

set -euo pipefail

IMAGE="${IMAGE:-arch-docs-arch-docs}"
VOLUME="${VOLUME:-codex-auth}"

echo "Запуск device-auth flow для Codex CLI..."
echo "Откройте ссылку из вывода ниже в браузере и подтвердите авторизацию."
echo ""

docker run -it --rm \
  -v "${VOLUME}:/home/appuser/.codex" \
  "${IMAGE}" \
  codex login --device-auth

echo ""
echo "Авторизация завершена. Токен сохранён в volume '${VOLUME}'."
