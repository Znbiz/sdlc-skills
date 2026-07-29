from __future__ import annotations

import asyncio
import datetime
import typing

import openai
import structlog
from langchain.agents import create_agent
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_openai import ChatOpenAI

from app.services.cli_task_support import (
    FAILURE_REASON_AUTH_EXPIRED,
    FAILURE_REASON_LIMIT_EXHAUSTED,
    _persist_task,
    _ProviderConnectionMissingError,
    _resolve_cli_prompt,
    _resolve_provider_connection,
    _task_log_context,
)
from app.services.langgraph_agent_tools import build_agent_tools
from app.services.task_registry import CliTask, TaskStatus
from app.services.text_sanitization import sanitize_text
from app.services.workflow_event_bus import get_workflow_event_bus
from app.settings import get_gateway_settings
from app.workflows.init_arch.domain import step_label_ru

if typing.TYPE_CHECKING:
    from langchain_core.messages import AIMessage, BaseMessage

    from app.services.agent_pool import AgentPool
    from app.services.llm_providers import LlmProviderConnectionDetail

logger = structlog.get_logger()

# Extra safety net on top of `timeout_seconds` (which already bounds wall time) - bounds the
# tool-calling loop by step count instead. codex/claude have no equivalent limit at all; this is
# affordable precisely because the agent now runs in-process rather than as an external CLI. See
# arch-docs/docs/spec/2026-07-25-langgraph-api-agent-runner.md, section 4, item 7.
_RECURSION_LIMIT: typing.Final[int] = 100


def _emit_agent_event(cli_task: CliTask, *, event_type: str, **fields: str) -> None:
    """Publish one live-observability event and append its trace line to `cli_task.stdout_lines`.

    `stdout_lines` is the same field the CLI path fills from subprocess stdout - it backs both
    `GET /rest/tasks/{id}/stream/` and the persisted `stdout_output` column
    (`task_repo.upsert_cli_task`). Without this, both channels would be silently empty for
    LangGraph tasks - see spec section 7, "Пробел №1".
    """
    settings = get_gateway_settings()
    if "text" in fields:
        fields["text"] = sanitize_text(fields["text"], max_chars=settings.audit.max_output_chars) or ""
    if "tool_input" in fields:
        fields["tool_input"] = sanitize_text(fields["tool_input"], max_chars=settings.audit.max_output_chars) or ""

    cli_task.stdout_lines.append(_format_trace_line(event_type, fields))

    if not cli_task.workflow_id:
        return
    step_id = cli_task.step_id or ""
    event: dict[str, typing.Any] = {
        "event_type": event_type,
        "actor": "llm",
        "step_id": step_id,
        "step_label": step_label_ru(step_id),
        "repo_name": cli_task.repository_name or "",
        "domain_id": cli_task.domain_id or "",
        "llm_call_id": cli_task.task_id,
        **fields,
    }
    get_workflow_event_bus().publish(cli_task.workflow_id, event)


def _format_trace_line(event_type: str, fields: dict[str, str]) -> str:
    if event_type == "llm_tool_call":
        return f"[tool] {fields.get('tool_name', '')}({fields.get('tool_input', '')})"
    return f"[assistant] {fields.get('text', '')}"


class _LiveEventCallbackHandler(AsyncCallbackHandler):
    """Turns LangChain tool/model callbacks into the same event shape as `_publish_live_stdout_line`.

    Mirrors what `_classify_claude_stream_line`/`_classify_codex_stream_line` extract from CLI
    stdout (tool calls and assistant text) but reads it directly off structured callbacks instead
    of guessing a JSON shape - see spec section 6.
    """

    def __init__(self, cli_task: CliTask) -> None:
        self._cli_task = cli_task

    async def on_tool_start(self, serialized: dict[str, typing.Any], input_str: str, **_kwargs: typing.Any) -> None:
        tool_name = str((serialized or {}).get("name", ""))
        _emit_agent_event(self._cli_task, event_type="llm_tool_call", tool_name=tool_name, tool_input=input_str)

    async def on_llm_end(self, response: typing.Any, **_kwargs: typing.Any) -> None:
        for generation_list in response.generations:
            for generation in generation_list:
                message: BaseMessage | None = getattr(generation, "message", None)
                text = message.content if message is not None and isinstance(message.content, str) else ""
                if text:
                    _emit_agent_event(self._cli_task, event_type="llm_message", text=text)


def _build_model(provider_connection: LlmProviderConnectionDetail) -> ChatOpenAI:
    # Always Chat Completions, never Responses API - deliberately ignores
    # `provider_connection.wire_api`. That field records what *codex* needs (a newer codex CLI
    # only speaks Responses API at all, see 2026-07-24-external-llm-provider.md section 8), not
    # what the gateway actually supports or what LangGraph needs - LangGraph has none of codex's
    # tool-type constraints. Confirmed end-to-end against the real "GLM 5.2" gateway
    # (turbocloud.ru): `use_responses_api=True` (i.e. trusting wire_api="responses" here) 500s
    # inside langchain_openai's own response parsing (`_create_usage_metadata_responses` does
    # `input_tokens + output_tokens` on a `None + None` when this gateway's Responses API leaves
    # usage fields unset), while Chat Completions against the same gateway/model works and reports
    # usage correctly. See arch-docs/docs/spec/2026-07-25-langgraph-api-agent-runner.md.
    return ChatOpenAI(
        base_url=provider_connection.base_url,
        api_key=provider_connection.token,
        model=provider_connection.model,
        use_responses_api=False,
    )


def _finalize_langgraph_result(
    cli_task: CliTask, final_message: AIMessage, provider_connection: LlmProviderConnectionDetail
) -> None:
    content = final_message.content
    cli_task.task_result = content if isinstance(content, str) else str(content)
    cli_task.task_status = TaskStatus.SUCCESS
    usage = getattr(final_message, "usage_metadata", None) or {}
    cli_task.input_tokens = int(usage.get("input_tokens", 0))
    cli_task.output_tokens = int(usage.get("output_tokens", 0))
    cli_task.model_name = provider_connection.model


async def _invoke_agent(cli_task: CliTask, provider_connection: LlmProviderConnectionDetail) -> AIMessage:
    model = _build_model(provider_connection)
    allowed_roots = [cli_task.workspace_dir, *cli_task.extra_allowed_roots]
    agent = create_agent(model, tools=build_agent_tools(allowed_roots))
    prompt_text = _resolve_cli_prompt(cli_task)

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": prompt_text}]},
        config={"recursion_limit": _RECURSION_LIMIT, "callbacks": [_LiveEventCallbackHandler(cli_task)]},
    )
    return result["messages"][-1]


async def _resolve_langgraph_provider_connection(cli_task: CliTask) -> LlmProviderConnectionDetail | None:
    """Resolve the connection required for `engine_name="langgraph"`.

    On failure, marks `cli_task` `FAILED`, persists it and returns `None` - callers just check for
    `None` and stop, the same "no connection, no run" shape as `run_cli_task`'s
    `_ProviderConnectionMissingError` handling.
    """
    if cli_task.provider_connection_id is None:
        cli_task.task_status = TaskStatus.FAILED
        cli_task.task_error = "provider_connection_id is required for engine_name='langgraph'"
        cli_task.finished_at = datetime.datetime.now(datetime.timezone.utc)
        logger.warning("cli_task.provider_connection_missing", **_task_log_context(cli_task))
        await _persist_task(cli_task)
        return None

    try:
        return await _resolve_provider_connection(cli_task)
    except _ProviderConnectionMissingError:
        cli_task.task_status = TaskStatus.FAILED
        cli_task.task_error = f"LLM provider connection not found: {cli_task.provider_connection_id}"
        cli_task.finished_at = datetime.datetime.now(datetime.timezone.utc)
        logger.warning("cli_task.provider_connection_missing", **_task_log_context(cli_task))
        await _persist_task(cli_task)
        return None


async def _execute_langgraph_agent(cli_task: CliTask, provider_connection: LlmProviderConnectionDetail) -> None:
    try:
        invoke_task = asyncio.create_task(_invoke_agent(cli_task, provider_connection))
        cli_task.async_task_handle = invoke_task

        try:
            final_message = await asyncio.wait_for(invoke_task, timeout=float(cli_task.timeout_seconds))
        except TimeoutError:
            invoke_task.cancel()
            cli_task.task_status = TaskStatus.FAILED
            cli_task.task_error = "Timeout exceeded"
            logger.warning("cli_task.timeout", **_task_log_context(cli_task))
            return
        except asyncio.CancelledError:
            # A pause/cancel of the graph's asyncio.Task cancels this whole call chain too (see
            # run_cli_task's identical handling) - explicitly cancel the child task since
            # cancelling the coroutine awaiting it does NOT automatically cancel a sibling
            # asyncio.Task created via `create_task`.
            invoke_task.cancel()
            raise

        _finalize_langgraph_result(cli_task, final_message, provider_connection)

    except openai.AuthenticationError as exc:
        cli_task.task_status = TaskStatus.FAILED
        cli_task.task_error = f"{FAILURE_REASON_AUTH_EXPIRED}: {exc}"
        logger.warning("cli_task.auth_error", **_task_log_context(cli_task))
    except openai.RateLimitError as exc:
        cli_task.task_status = TaskStatus.FAILED
        cli_task.task_error = f"{FAILURE_REASON_LIMIT_EXHAUSTED}: {exc}"
        logger.warning("cli_task.limit_error", **_task_log_context(cli_task), engine=cli_task.engine_name)
    except Exception as exc:  # noqa: BLE001
        cli_task.task_status = TaskStatus.FAILED
        cli_task.task_error = str(exc)
        logger.error("cli_task.agent_error", **_task_log_context(cli_task), error=str(exc))
    finally:
        cli_task.finished_at = datetime.datetime.now(datetime.timezone.utc)
        logger.info("cli_task.finished", **_task_log_context(cli_task), task_status=cli_task.task_status)
        await _persist_task(cli_task)


async def run_langgraph_task(cli_task: CliTask, agent_pool: AgentPool) -> None:
    """Run one `CliTask` through a LangGraph tool-calling agent.

    Talks to the provider's API directly (no `codex`/`claude` subprocess) - see
    arch-docs/docs/spec/2026-07-25-langgraph-api-agent-runner.md.
    """
    logger.info("cli_task.queued", **_task_log_context(cli_task), engine=cli_task.engine_name)
    await _persist_task(cli_task)

    async with agent_pool:
        if cli_task.task_status == TaskStatus.CANCELLED:
            logger.info("cli_task.skipped_cancelled", **_task_log_context(cli_task))
            return

        cli_task.task_status = TaskStatus.RUNNING
        cli_task.started_at = datetime.datetime.now(datetime.timezone.utc)
        logger.info("cli_task.started", **_task_log_context(cli_task), engine=cli_task.engine_name)
        await _persist_task(cli_task)

        provider_connection = await _resolve_langgraph_provider_connection(cli_task)
        if provider_connection is None:
            return

        await _execute_langgraph_agent(cli_task, provider_connection)
