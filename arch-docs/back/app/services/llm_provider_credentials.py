from __future__ import annotations

import pathlib
import typing
import uuid  # noqa: TC003 - used at runtime as a parameter annotation, not just for type checking

_SECRETS_DIR: typing.Final = pathlib.Path("~/.config/llm-provider-secrets").expanduser()

# Env var name Codex CLI is told (via `-c model_providers.external.env_key=...`) to read the
# bearer token from - see task_runner._build_cmd(). Deliberately NOT written into os.environ
# globally (unlike git_credentials.GIT_CONFIG_GLOBAL): it is merged into the env dict of the one
# subprocess call that needs it (task_runner.run_cli_task), so concurrent CliTask runs using
# different connections (or no external connection at all) never see each other's token.
EXTERNAL_LLM_API_KEY_ENV_VAR: typing.Final[str] = "ARCH_DOCS_EXTERNAL_LLM_API_KEY"


def _secret_file(connection_id: uuid.UUID) -> pathlib.Path:
    return _SECRETS_DIR / f"{connection_id}.token"


def ensure_llm_provider_secrets_store() -> None:
    _SECRETS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)


def set_llm_provider_token(connection_id: uuid.UUID, token: str) -> None:
    ensure_llm_provider_secrets_store()
    secret_file = _secret_file(connection_id)
    secret_file.write_text(token)
    secret_file.chmod(0o600)


def get_llm_provider_token(connection_id: uuid.UUID) -> str | None:
    secret_file = _secret_file(connection_id)
    if not secret_file.exists():
        return None
    return secret_file.read_text()


def delete_llm_provider_token(connection_id: uuid.UUID) -> bool:
    secret_file = _secret_file(connection_id)
    if not secret_file.exists():
        return False
    secret_file.unlink()
    return True
