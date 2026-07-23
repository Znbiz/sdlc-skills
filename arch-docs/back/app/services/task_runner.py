import asyncio
import datetime
import json
import os
import typing
import uuid

import structlog

from app.db.session import get_session
from app.db.task_repo import upsert_cli_task
from app.services.agent_pool import AgentPool, get_agent_pool
from app.services.llm_provider_credentials import EXTERNAL_LLM_API_KEY_ENV_VAR
from app.services.llm_providers import (
    LlmProviderConnectionDetail,
    LlmProviderConnectionNotFoundError,
    get_llm_provider_connection_async,
)
from app.services.task_registry import CliTask, TaskRegistry, TaskStatus
from app.services.text_sanitization import sanitize_text
from app.services.workflow_event_bus import get_workflow_event_bus
from app.settings import get_gateway_settings
from app.workflows.init_arch.audit import WorkflowAuditService, get_workflow_audit_service
from app.workflows.init_arch.domain import (
    AuditActor,
    EventType,
    LlmTaskRequest,
    LlmTaskResult,
    WorkflowEventRecord,
    step_label_ru,
)

logger = structlog.get_logger()

# asyncio.StreamReader defaults to a 64 KiB line limit (`asyncio.streams._DEFAULT_LIMIT`) - codex
# routinely emits single --json lines well past that (e.g. a tool-output line embedding a whole
# file's contents), which makes `reader.readline()` raise `LimitOverrunError: Separator is found,
# but chunk is longer than limit`. That's deterministic for the same input, so the workflow's
# step-retry loop just re-runs the same losing call three times before giving up. Raise the limit
# instead of retrying around it.
_STDOUT_STREAM_LIMIT: typing.Final[int] = 10 * 1024 * 1024

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


_CLAUDE_AUTH_ERROR_SUBSTRINGS: typing.Final[tuple[str, ...]] = (
    "not logged in",
    "authentication_failed",
    "login required",
    "authentication required",
    "unauthorized",
    "oauth",
)
_CODEX_AUTH_ERROR_EXIT_CODES: typing.Final[frozenset[int]] = frozenset({401, 403})
_CLAUDE_LIMIT_ERROR_SUBSTRINGS: typing.Final[tuple[str, ...]] = (
    "usage limit reached",
    "rate limit exceeded",
    "too many requests",
)
_CODEX_LIMIT_ERROR_EXIT_CODES: typing.Final[frozenset[int]] = frozenset({429})
_CODEX_LIMIT_ERROR_SUBSTRINGS: typing.Final[tuple[str, ...]] = (
    "insufficient_quota",
    "quota exceeded",
    "rate limit exceeded",
    "too many requests",
)
FAILURE_REASON_AUTH_EXPIRED: typing.Final[str] = "auth_expired"
FAILURE_REASON_LIMIT_EXHAUSTED: typing.Final[str] = "limit_exhausted"


def _external_provider_overrides(connection: LlmProviderConnectionDetail) -> list[str]:
    # Passed as `-c` overrides on this one `codex exec` invocation rather than written into the
    # shared config.toml, so concurrent tasks using different connections (or none at all) never
    # collide - see arch-docs/docs/spec/2026-07-24-external-llm-provider.md, section 4.
    requires_openai_auth = "true" if connection.requires_openai_auth else "false"
    overrides = [
        "model_provider=external",
        "model_providers.external.name=external",
        f"model_providers.external.base_url={connection.base_url}",
        f"model_providers.external.env_key={EXTERNAL_LLM_API_KEY_ENV_VAR}",
        f"model_providers.external.wire_api={connection.wire_api}",
        f"model_providers.external.requires_openai_auth={requires_openai_auth}",
        f"model={connection.model}",
    ]
    args: list[str] = []
    for override in overrides:
        args.extend(["-c", override])
    return args


def _build_cmd(cli_task: CliTask, provider_connection: LlmProviderConnectionDetail | None = None) -> list[str]:
    if cli_task.engine_name == "claude":
        # Non-interactive (`-p`) runs have nobody to approve tool calls, so without this the
        # agent silently fails every write/Bash action (mkdir, git clone, ...) and only reports
        # the block in its final text answer - the CLI still exits 0, so callers see "success".
        # The container's own filesystem/user isolation is the actual security boundary here,
        # matching how `codex` is configured (see config.toml `approval_policy = "never"`,
        # `sandbox_mode = "danger-full-access"`).
        cmd = [
            "claude",
            "-p",
            cli_task.prompt_text,
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "bypassPermissions",
        ]
        if cli_task.session_id:
            cmd.extend(["--resume", cli_task.session_id])
        return cmd
    provider_overrides = _external_provider_overrides(provider_connection) if provider_connection else []
    if cli_task.session_id:
        return [
            "codex",
            "exec",
            "resume",
            cli_task.session_id,
            *provider_overrides,
            "--json",
            cli_task.prompt_text,
        ]
    # `--sandbox` mirrors `claude`'s `bypassPermissions` above: codex's own sandbox modes
    # (`workspace-write`/`read-only`) set up a nested bubblewrap sandbox on Linux, which needs
    # an unprivileged user namespace (`unshare(CLONE_NEWUSER)`) - blocked by Docker's default
    # seccomp profile, so it fails with a bwrap namespace error and the agent can't touch the
    # filesystem at all. `danger-full-access` skips that nested sandbox and relies on the
    # container's own isolation instead, same as claude.
    return [
        "codex",
        "exec",
        "--sandbox",
        cli_task.sandbox_mode,
        "--skip-git-repo-check",
        *provider_overrides,
        "--json",
        cli_task.prompt_text,
    ]


def _is_auth_error(engine_name: str, exit_code: int, stderr_text: str) -> bool:
    if engine_name == "claude":
        return exit_code != 0 and any(phrase in stderr_text.lower() for phrase in _CLAUDE_AUTH_ERROR_SUBSTRINGS)
    return exit_code in _CODEX_AUTH_ERROR_EXIT_CODES or (
        exit_code != 0 and "auth" in stderr_text.lower() and "error" in stderr_text.lower()
    )


def _is_limit_error(engine_name: str, exit_code: int, stderr_text: str) -> bool:
    if exit_code == 0:
        return False
    lowered = stderr_text.lower()
    if engine_name == "claude":
        return any(phrase in lowered for phrase in _CLAUDE_LIMIT_ERROR_SUBSTRINGS)
    return exit_code in _CODEX_LIMIT_ERROR_EXIT_CODES or any(
        phrase in lowered for phrase in _CODEX_LIMIT_ERROR_SUBSTRINGS
    )


def _clamp_timeout_seconds(timeout_seconds: int) -> int:
    max_timeout = get_gateway_settings().workflows.init.max_step_timeout_seconds
    return max(1, min(timeout_seconds, max_timeout))


def _iter_json_lines(stdout_lines: list[str]) -> typing.Iterator[dict[str, typing.Any]]:
    for line in stdout_lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            yield payload


def _extract_claude_result_text(stdout_lines: list[str]) -> str:
    # claude --output-format stream-json emits one JSON object per line (system/assistant/result
    # events); the final answer text lives in the last `type: result` event's `result` field.
    result_text = ""
    for payload in _iter_json_lines(stdout_lines):
        if payload.get("type") == "result":
            result_text = payload.get("result") or ""
    return result_text


def _extract_codex_result_text(stdout_lines: list[str]) -> str:
    # codex exec --json emits one JSON object per line; the final agent answer arrives as an
    # `item.completed` event whose item has type `agent_message`.
    result_text = ""
    for payload in _iter_json_lines(stdout_lines):
        if payload.get("type") != "item.completed":
            continue
        item = payload.get("item") or {}
        if item.get("type") == "agent_message":
            result_text = item.get("text") or ""
    return result_text


def _extract_result_text(engine_name: str, stdout_lines: list[str]) -> str:
    if engine_name == "claude":
        return _extract_claude_result_text(stdout_lines)
    if engine_name == "codex":
        return _extract_codex_result_text(stdout_lines)
    return "\n".join(stdout_lines)


# `type` values that are pure protocol noise for the live SSE tail - already surfaced elsewhere
# (claude "result" -> `llm_call_completed.raw_output`; both "system"/"thread.started" are init
# handshakes with nothing user-relevant). Anything NOT in this set but also not recognized by the
# classifiers below still gets shown (see `_classify_live_stream_line` fallback) rather than
# silently dropped, so a CLI output-format change can't make the live stream go quiet.
_CLAUDE_NOISE_TYPES: typing.Final[frozenset[str]] = frozenset({"system", "result"})
_CODEX_NOISE_TYPES: typing.Final[frozenset[str]] = frozenset({"thread.started", "turn.started", "turn.completed"})


def _classify_claude_stream_line(payload: dict[str, typing.Any]) -> dict[str, typing.Any] | None:
    if payload.get("type") != "assistant":
        return None
    content = (payload.get("message") or {}).get("content") or []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            return {
                "event_type": "llm_tool_call",
                "tool_name": str(block.get("name", "")),
                "tool_input": json.dumps(block.get("input", {}), ensure_ascii=False),
            }
        if block.get("type") == "text" and block.get("text"):
            return {"event_type": "llm_message", "text": str(block["text"])}
    return None


def _classify_codex_stream_line(payload: dict[str, typing.Any]) -> dict[str, typing.Any] | None:
    if payload.get("type") != "item.completed":
        return None
    item = payload.get("item") or {}
    item_type = item.get("type")
    if item_type == "command_execution":
        return {"event_type": "llm_tool_call", "tool_name": "shell", "tool_input": str(item.get("command", ""))}
    if item_type in {"agent_message", "reasoning"} and item.get("text"):
        return {"event_type": "llm_message", "text": str(item["text"])}
    return None


_STREAM_LINE_CLASSIFIERS: typing.Final[
    dict[str, typing.Callable[[dict[str, typing.Any]], dict[str, typing.Any] | None]]
] = {
    "claude": _classify_claude_stream_line,
    "codex": _classify_codex_stream_line,
}
_STREAM_LINE_NOISE_TYPES: typing.Final[dict[str, frozenset[str]]] = {
    "claude": _CLAUDE_NOISE_TYPES,
    "codex": _CODEX_NOISE_TYPES,
}


def _classify_live_stream_line(engine_name: str, raw_line: str) -> dict[str, typing.Any] | None:
    """Classify one raw stdout line from a running `claude`/`codex` subprocess for the live SSE tail.

    Returns an `llm_tool_call`/`llm_message` event dict, or `None` to drop the line as noise. See
    arch-docs/docs/spec/2026-07-22-realtime-workflow-observability.md, section 3.
    """
    stripped = raw_line.strip()
    if not stripped:
        return None

    fallback = {"event_type": "llm_message", "text": raw_line}
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        payload = None

    if not isinstance(payload, dict):
        return fallback

    classifier = _STREAM_LINE_CLASSIFIERS.get(engine_name)
    if classifier is None:
        return fallback

    classified = classifier(payload)
    if classified is not None:
        return classified
    if str(payload.get("type", "")) in _STREAM_LINE_NOISE_TYPES.get(engine_name, frozenset()):
        return None
    return fallback


async def _drain_stream(
    reader: asyncio.StreamReader,
    lines: list[str],
    *,
    on_line: typing.Callable[[str], None] | None = None,
) -> None:
    while True:
        raw = await reader.readline()
        if not raw:
            break
        line = raw.decode().rstrip("\n")
        lines.append(line)
        if on_line is not None:
            on_line(line)


def _task_log_context(cli_task: CliTask) -> dict[str, str | None]:
    return {"task_id": cli_task.task_id, "workflow_id": cli_task.workflow_id, "step_id": cli_task.step_id}


def _publish_live_stdout_line(cli_task: CliTask, raw_line: str) -> None:
    if not cli_task.workflow_id:
        return
    event = _classify_live_stream_line(cli_task.engine_name, raw_line)
    if event is None:
        return

    max_chars = get_gateway_settings().audit.max_output_chars
    if "text" in event:
        event["text"] = sanitize_text(event["text"], max_chars=max_chars) or ""
    if "tool_input" in event:
        event["tool_input"] = sanitize_text(event["tool_input"], max_chars=max_chars) or ""

    step_id = cli_task.step_id or ""
    event.update(
        {
            "actor": "llm",
            "step_id": step_id,
            "step_label": step_label_ru(step_id),
            "repo_name": cli_task.repository_name or "",
            "domain_id": cli_task.domain_id or "",
            "llm_call_id": cli_task.task_id,
        }
    )
    get_workflow_event_bus().publish(cli_task.workflow_id, event)


async def _terminate_subprocess(proc: asyncio.subprocess.Process) -> None:
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except TimeoutError:
        proc.kill()


class _ProviderConnectionMissingError(Exception):
    pass


async def _resolve_provider_connection(cli_task: CliTask) -> LlmProviderConnectionDetail | None:
    if cli_task.provider_connection_id is None:
        return None
    try:
        return await get_llm_provider_connection_async(uuid.UUID(cli_task.provider_connection_id))
    except LlmProviderConnectionNotFoundError:
        raise _ProviderConnectionMissingError from None


async def run_cli_task(cli_task: CliTask, agent_pool: AgentPool) -> None:  # noqa: PLR0915
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

        try:
            provider_connection = await _resolve_provider_connection(cli_task)
        except _ProviderConnectionMissingError:
            cli_task.task_status = TaskStatus.FAILED
            cli_task.task_error = f"LLM provider connection not found: {cli_task.provider_connection_id}"
            cli_task.finished_at = datetime.datetime.now(datetime.timezone.utc)
            logger.warning("cli_task.provider_connection_missing", **_task_log_context(cli_task))
            await _persist_task(cli_task)
            return

        cmd = _build_cmd(cli_task, provider_connection)

        # Per-call env, NOT a mutation of the shared os.environ (unlike git_credentials'
        # GIT_CONFIG_GLOBAL) - concurrent CliTask runs against different external LLM connections
        # (or none) must never observe each other's token. See spec §4.
        subprocess_env = {**os.environ}
        if provider_connection is not None and provider_connection.token:
            subprocess_env[EXTERNAL_LLM_API_KEY_ENV_VAR] = provider_connection.token

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cli_task.workspace_dir,
                env=subprocess_env,
                limit=_STDOUT_STREAM_LIMIT,
            )
            cli_task.subprocess_handle = proc

            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        _drain_stream(
                            proc.stdout,  # type: ignore[arg-type]
                            cli_task.stdout_lines,
                            on_line=lambda line: _publish_live_stdout_line(cli_task, line),
                        ),
                        _drain_stream(proc.stderr, cli_task.stderr_lines),  # type: ignore[arg-type]
                    ),
                    timeout=float(cli_task.timeout_seconds),
                )
            except TimeoutError:
                await _terminate_subprocess(proc)
                cli_task.task_status = TaskStatus.FAILED
                cli_task.task_error = "Timeout exceeded"
                cli_task.finished_at = datetime.datetime.now(datetime.timezone.utc)
                logger.warning("cli_task.timeout", **_task_log_context(cli_task))
                await _persist_task(cli_task)
                return
            except asyncio.CancelledError:
                # A pause/cancel of the *graph's* asyncio.Task (see
                # app.services.init_arch_workflow.pause_init_arch_workflow) cancels this whole call
                # chain too, since it's all one task - without an explicit terminate() here the
                # subprocess itself would keep running orphaned inside the container after the
                # Python side has already moved on. See spec §7 "Пауза и продолжение".
                await _terminate_subprocess(proc)
                raise

            await proc.wait()
            exit_code = proc.returncode or 0
            cli_task.exit_code = exit_code
            stderr_text = "\n".join(cli_task.stderr_lines)

            if _is_auth_error(cli_task.engine_name, exit_code, stderr_text):
                cli_task.task_status = TaskStatus.FAILED
                cli_task.task_error = f"{FAILURE_REASON_AUTH_EXPIRED}: {stderr_text}"
                logger.warning("cli_task.auth_error", **_task_log_context(cli_task))
            elif _is_limit_error(cli_task.engine_name, exit_code, stderr_text):
                cli_task.task_status = TaskStatus.FAILED
                cli_task.task_error = f"{FAILURE_REASON_LIMIT_EXHAUSTED}: {stderr_text}"
                logger.warning("cli_task.limit_error", **_task_log_context(cli_task), engine=cli_task.engine_name)
            elif exit_code != 0:
                cli_task.task_status = TaskStatus.FAILED
                cli_task.task_error = stderr_text or f"Exit code: {exit_code}"
                logger.warning("cli_task.failed", **_task_log_context(cli_task), exit_code=exit_code)
            else:
                cli_task.task_result = _extract_result_text(cli_task.engine_name, cli_task.stdout_lines)
                cli_task.task_status = TaskStatus.SUCCESS

        except (OSError, asyncio.LimitOverrunError) as exc:
            # LimitOverrunError still possible even past _STDOUT_STREAM_LIMIT for a truly
            # pathological single line - fail the task cleanly instead of letting it escape
            # run_cli_task uncaught (which left task_status stuck on RUNNING and made the workflow
            # node's retry loop burn 3 attempts on a deterministically-doomed re-run).
            cli_task.task_status = TaskStatus.FAILED
            cli_task.task_error = str(exc)
            logger.error("cli_task.stream_error", **_task_log_context(cli_task), error=str(exc))
        finally:
            cli_task.finished_at = datetime.datetime.now(datetime.timezone.utc)
            logger.info("cli_task.finished", **_task_log_context(cli_task), task_status=cli_task.task_status)
            await _persist_task(cli_task)


async def cancel_cli_task(task_id: str, registry: TaskRegistry) -> None:
    cli_task = registry.get(task_id)
    if cli_task is None:
        return

    if cli_task.task_status == TaskStatus.PENDING:
        cli_task.task_status = TaskStatus.CANCELLED
        logger.info("cli_task.cancelled_pending", task_id=task_id)
        await _persist_task(cli_task)
        return

    if cli_task.subprocess_handle is None or cli_task.subprocess_handle.returncode is not None:
        return

    cli_task.subprocess_handle.terminate()
    try:
        await asyncio.wait_for(cli_task.subprocess_handle.wait(), timeout=5.0)
    except TimeoutError:
        cli_task.subprocess_handle.kill()

    cli_task.task_status = TaskStatus.CANCELLED
    cli_task.finished_at = datetime.datetime.now(datetime.timezone.utc)
    logger.info("cli_task.cancelled", task_id=task_id)
    await _persist_task(cli_task)


class LlmCliService:
    def __init__(self, audit_service: WorkflowAuditService | None = None) -> None:
        self._audit_service = audit_service or get_workflow_audit_service()

    async def run_task(
        self, request: LlmTaskRequest, *, engine_name: str, provider_connection_id: str | None = None
    ) -> LlmTaskResult:
        cli_task = self._build_cli_task(request, engine_name=engine_name, provider_connection_id=provider_connection_id)
        self._bind_request_metadata(cli_task, request)
        settings = get_gateway_settings()
        masked_prompt = sanitize_text(request.prompt_text, max_chars=settings.audit.max_prompt_chars) or ""
        self._record_event(
            request,
            EventType.LLM_TASK_REQUESTED,
            llm_call_id=cli_task.task_id,
            engine_name=engine_name,
            expected_schema=request.expected_schema_name,
            prompt_text=masked_prompt,
        )
        self._publish_live_event(
            request,
            "llm_call_started",
            llm_call_id=cli_task.task_id,
            engine_name=engine_name,
            prompt_text=masked_prompt,
        )
        await self._run_cli_task(cli_task)
        if cli_task.task_status != TaskStatus.SUCCESS:
            error_text = sanitize_text(cli_task.task_error, max_chars=settings.audit.max_error_chars) or (
                "CLI task failed"
            )
            self._record_event(
                request,
                EventType.LLM_TASK_FAILED,
                llm_call_id=cli_task.task_id,
                engine_name=engine_name,
                error=error_text,
            )
            self._publish_live_event(
                request,
                "llm_call_failed",
                llm_call_id=cli_task.task_id,
                engine_name=engine_name,
                error_reason=LlmTaskExecutionError._detect_reason(cli_task.task_error or ""),  # noqa: SLF001
                error=error_text,
            )
            raise LlmTaskExecutionError.from_cli_task(cli_task)

        parsed_result = self._parse_result(cli_task.task_result or "")
        raw_output = sanitize_text(cli_task.task_result, max_chars=settings.audit.max_output_chars) or ""
        self._record_event(
            request,
            EventType.LLM_TASK_COMPLETED,
            llm_call_id=cli_task.task_id,
            engine_name=engine_name,
            created_artifacts=str(len(parsed_result.get("created_artifacts", []))),
            open_questions=str(len(parsed_result.get("open_questions_found", []))),
            raw_output=raw_output,
        )
        self._publish_live_event(
            request,
            "llm_call_completed",
            llm_call_id=cli_task.task_id,
            engine_name=engine_name,
            raw_output=raw_output,
            completed_actions=parsed_result.get("completed_actions", []),
            created_artifacts=parsed_result.get("created_artifacts", []),
            open_questions_found=parsed_result.get("open_questions_found", []),
            notes=parsed_result.get("notes", ""),
        )
        return LlmTaskResult(
            task_kind=request.task_kind,
            step_id=request.step_id,
            completed_actions=parsed_result.get("completed_actions", []),
            created_artifacts=parsed_result.get("created_artifacts", []),
            open_questions_found=parsed_result.get("open_questions_found", []),
            diff_based_findings=parsed_result.get("diff_based_findings", []),
            snapshot_based_findings=parsed_result.get("snapshot_based_findings", []),
            domain_assessment=parsed_result.get("domain_assessment"),
            notes=parsed_result.get("notes", ""),
            raw_output=cli_task.task_result or "",
        )

    def _build_cli_task(
        self, request: LlmTaskRequest, *, engine_name: str, provider_connection_id: str | None = None
    ) -> CliTask:
        return CliTask(
            task_id=str(uuid.uuid4()),
            engine_name=engine_name,
            provider_connection_id=provider_connection_id,
            prompt_text=request.prompt_text,
            workspace_dir=request.workspace_dir,
            workflow_id=request.session_id or None,
            step_id=request.step_id.value,
            repository_name=request.repository_name or None,
            domain_id=request.domain_id or None,
            expected_schema_name=request.expected_schema_name,
            timeout_seconds=_clamp_timeout_seconds(request.timeout_seconds),
        )

    def _bind_request_metadata(self, cli_task: CliTask, request: LlmTaskRequest) -> None:
        cli_task.workflow_id = request.session_id or None
        cli_task.step_id = request.step_id.value
        cli_task.repository_name = request.repository_name or None
        cli_task.domain_id = request.domain_id or None
        cli_task.expected_schema_name = request.expected_schema_name

    async def _run_cli_task(self, cli_task: CliTask) -> None:
        await run_cli_task(cli_task, get_agent_pool())

    def _parse_result(self, raw_output: str) -> dict[str, typing.Any]:
        try:
            return json.loads(raw_output)
        except json.JSONDecodeError:
            return {
                "completed_actions": [],
                "created_artifacts": [],
                "open_questions_found": [],
                "notes": raw_output,
            }

    def _record_event(self, request: LlmTaskRequest, event_type: EventType, **payload: str) -> None:
        self._audit_service.record(
            WorkflowEventRecord(
                event_type=event_type,
                actor=AuditActor.LLM_WORKER,
                session_id=request.session_id,
                step_id=request.step_id,
                repository_name=request.repository_name,
                domain_id=request.domain_id,
                payload=payload,
            )
        )

    def _publish_live_event(self, request: LlmTaskRequest, event_type: str, **extra: typing.Any) -> None:
        if not request.session_id:
            return
        get_workflow_event_bus().publish(
            request.session_id,
            {
                "event_type": event_type,
                "actor": "llm",
                "step_id": request.step_id.value,
                "step_label": step_label_ru(request.step_id.value),
                "repo_name": request.repository_name,
                "domain_id": request.domain_id,
                "task_kind": request.task_kind.value,
                **extra,
            },
        )


class LlmTaskExecutionError(RuntimeError):
    def __init__(self, message: str, *, reason: str, engine_name: str, task_id: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.engine_name = engine_name
        self.task_id = task_id

    @classmethod
    def from_cli_task(cls, cli_task: CliTask) -> "LlmTaskExecutionError":
        message = cli_task.task_error or "CLI task failed"
        reason = cls._detect_reason(message)
        return cls(
            message,
            reason=reason,
            engine_name=cli_task.engine_name,
            task_id=cli_task.task_id,
        )

    @staticmethod
    def _detect_reason(message: str) -> str:
        if message.startswith(f"{FAILURE_REASON_AUTH_EXPIRED}:"):
            return FAILURE_REASON_AUTH_EXPIRED
        if message.startswith(f"{FAILURE_REASON_LIMIT_EXHAUSTED}:"):
            return FAILURE_REASON_LIMIT_EXHAUSTED
        return "task_failed"


_llm_cli_service: LlmCliService | None = None


def get_llm_cli_service() -> LlmCliService:
    global _llm_cli_service  # noqa: PLW0603
    if _llm_cli_service is None:
        _llm_cli_service = LlmCliService()
    return _llm_cli_service
