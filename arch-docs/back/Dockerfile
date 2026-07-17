FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git openssh-client ca-certificates ripgrep curl gosu libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @openai/codex @anthropic-ai/claude-code

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_INSTALL_DIR=/usr/local/share/uv-python

RUN uv python install 3.14

RUN mkdir -p /app/skills

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --python 3.14

RUN usermod -l appuser node \
    && groupmod -n appuser node \
    && usermod -d /home/appuser -m appuser

COPY --chown=appuser:appuser app/ /app/app/
COPY --chown=appuser:appuser alembic.ini ./
COPY --chown=appuser:appuser migrations/ /app/migrations/

RUN mkdir -p /workspace && chown appuser:appuser /workspace

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uv", "run", "--project", "/app", "granian", "--interface", "asgi", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
