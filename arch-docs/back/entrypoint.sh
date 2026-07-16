#!/bin/sh
set -e
chown -R appuser:appuser /home/appuser/.claude /home/appuser/.codex /home/appuser/.config/git-credentials-store /workspace 2>/dev/null || true
exec gosu appuser "$@"
