"""Shared `CliTask` support used by both execution paths (subprocess CLI and in-process LangGraph).

Kept separate from `task_runner.py` and `langgraph_task_runner.py` so neither engine-specific
module has to import the other just to reach these helpers - see
arch-docs/docs/spec/2026-07-25-langgraph-api-agent-runner.md, section 5.
"""

from __future__ import annotations

import pathlib
import tempfile
import typing
import uuid

import structlog

from app.db.session import get_session
from app.db.task_repo import upsert_cli_task
from app.db.workflow_repo import increment_workflow_token_usage
from app.services.llm_providers import (
    LlmProviderConnectionDetail,
    LlmProviderConnectionNotFoundError,
    get_llm_provider_connection_async,
)
from app.services.task_registry import CliTask

logger = structlog.get_logger()

FAILURE_REASON_AUTH_EXPIRED: typing.Final[str] = "auth_expired"
FAILURE_REASON_LIMIT_EXHAUSTED: typing.Final[str] = "limit_exhausted"

_db_enabled: bool = False


def set_db_enabled(enabled: bool) -> None:
    global _db_enabled  # noqa: PLW0603
    _db_enabled = enabled


async def _persist_task(cli_task: CliTask) -> None:
    if not _db_enabled:
        return
    try:
        async with get_session() as session:
            await upsert_cli_task(session, cli_task)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cli_task.persist_failed", task_id=cli_task.task_id, error=str(exc))


async def _persist_token_usage(
    workflow_id: str | None, *, model_name: str, input_tokens: int, output_tokens: int
) -> dict[str, dict[str, int]] | None:
    if not _db_enabled or not workflow_id or (input_tokens == 0 and output_tokens == 0):
        return None
    try:
        async with get_session() as session:
            return await increment_workflow_token_usage(
                session,
                workflow_id=workflow_id,
                model_name=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("workflow.token_usage_persist_failed", workflow_id=workflow_id, error=str(exc))
        return None


def _task_log_context(cli_task: CliTask) -> dict[str, str | None]:
    return {"task_id": cli_task.task_id, "workflow_id": cli_task.workflow_id, "step_id": cli_task.step_id}


class _ProviderConnectionMissingError(Exception):
    pass


async def _resolve_provider_connection(cli_task: CliTask) -> LlmProviderConnectionDetail | None:
    if cli_task.provider_connection_id is None:
        return None
    try:
        return await get_llm_provider_connection_async(uuid.UUID(cli_task.provider_connection_id))
    except LlmProviderConnectionNotFoundError:
        raise _ProviderConnectionMissingError from None


# prompt_text may be embedded as a literal CLI argument or handed straight to a LangGraph agent -
# either way, a repository with a large expanded diff/changed-file context (see prompts.py's
# _EXPANDED_DIFF_CONTEXT_STEPS) can make it large enough to be worth spilling to a file rather than
# inlining, so both execution paths share the same overflow threshold and mechanism.
_MAX_INLINE_PROMPT_CHARS: typing.Final[int] = 50_000
_PROMPT_OVERFLOW_DIRNAME: typing.Final[str] = "arch-docs-prompt-overflow"


def _resolve_cli_prompt(cli_task: CliTask) -> str:
    """Return the prompt text to embed as this task's CLI argument (or hand to the agent).

    Oversized prompts are written to a file *outside* any workspace/repo tree the user can browse
    (so it doesn't clutter the project file tree the way `.artifact-snapshots`/`.temp` already do)
    and replaced with a short pointer - the agent reads the file itself via its own Read tool, so
    there's no argv (or, for claude's piped-stdin path, its documented 10 MB cap) size limit to
    hit at all.
    """
    if len(cli_task.prompt_text) <= _MAX_INLINE_PROMPT_CHARS:
        return cli_task.prompt_text

    overflow_dir = pathlib.Path(tempfile.gettempdir()) / _PROMPT_OVERFLOW_DIRNAME
    overflow_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = overflow_dir / f"{cli_task.task_id}.txt"
    prompt_path.write_text(cli_task.prompt_text, encoding="utf-8")
    return (
        f"Полный текст инструкций и контекста для этого шага записан в файл {prompt_path} - "
        "он не поместился в аргумент командной строки. Прочитай этот файл целиком (например, "
        "инструментом Read) и выполни всё, что в нём написано, прежде чем отвечать."
    )
