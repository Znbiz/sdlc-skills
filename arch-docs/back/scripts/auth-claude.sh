#!/usr/bin/env bash
# Однократная интерактивная авторизация Claude Code через OAuth flow.
# После выполнения токены сохраняются в volume claude-auth и переживают рестарты контейнера.

set -euo pipefail

IMAGE="${IMAGE:-arch-docs-arch-docs}"
VOLUME="${VOLUME:-claude-auth}"

echo "Запуск OAuth flow для Claude Code..."
echo "Откройте ссылку из вывода ниже в браузере и подтвердите авторизацию."
echo ""

docker run -it --rm \
  -v "${VOLUME}:/home/appuser/.claude" \
  "${IMAGE}" \
  claude auth login

echo ""
echo "Авторизация завершена. Токены сохранены в volume '${VOLUME}'."
