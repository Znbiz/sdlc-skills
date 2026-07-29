#!/bin/sh
set -e
mkdir -p /home/appuser/.config/llm-provider-catalogs
chown -R appuser:appuser /home/appuser/.claude /home/appuser/.codex /home/appuser/.config/git-credentials-store /home/appuser/.config/llm-provider-secrets /home/appuser/.config/llm-provider-catalogs /home/appuser/.ssh /workspace 2>/dev/null || true
exec gosu appuser "$@"
