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
from app.services.task_registry import CliTask, TaskRegistry, TaskStatus
from app.settings import get_gateway_settings
from app.workflows.init_arch.audit import WorkflowAuditService, get_workflow_audit_service
from app.workflows.init_arch.domain import AuditActor, EventType, LlmTaskRequest, LlmTaskResult, WorkflowEventRecord

logger = structlog.get_logger()

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


def _build_cmd(cli_task: CliTask) -> list[str]:
    if cli_task.engine_name == "claude":
        # Non-interactive (`-p`) runs have nobody to approve tool calls, so without this the
        # agent silently fails every write/Bash action (mkdir, git clone, ...) and only reports
        # the block in its final text answer - the CLI still exits 0, so callers see "success".
        # The container's own filesystem/user isolation is the actual security boundary here,
        # matching how `codex` is configured (see config.toml `approval_policy = "never"`).
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
    if cli_task.session_id:
        return [
            "codex",
            "exec",
            "resume",
            cli_task.session_id,
            "--json",
            cli_task.prompt_text,
        ]
    return [
        "codex",
        "exec",
        "--sandbox",
        cli_task.sandbox_mode,
        "--skip-git-repo-check",
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


async def _drain_stream(reader: asyncio.StreamReader, lines: list[str]) -> None:
    while True:
        raw = await reader.readline()
        if not raw:
            break
        lines.append(raw.decode().rstrip("\n"))


def _task_log_context(cli_task: CliTask) -> dict[str, str | None]:
    return {"task_id": cli_task.task_id, "workflow_id": cli_task.workflow_id, "step_id": cli_task.step_id}


async def run_cli_task(cli_task: CliTask, agent_pool: AgentPool) -> None:
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

        cmd = _build_cmd(cli_task)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cli_task.workspace_dir,
                env={**os.environ},
            )
            cli_task.subprocess_handle = proc

            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        _drain_stream(proc.stdout, cli_task.stdout_lines),  # type: ignore[arg-type]
                        _drain_stream(proc.stderr, cli_task.stderr_lines),  # type: ignore[arg-type]
                    ),
                    timeout=float(cli_task.timeout_seconds),
                )
            except TimeoutError:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except TimeoutError:
                    proc.kill()
                cli_task.task_status = TaskStatus.FAILED
                cli_task.task_error = "Timeout exceeded"
                cli_task.finished_at = datetime.datetime.now(datetime.timezone.utc)
                logger.warning("cli_task.timeout", **_task_log_context(cli_task))
                await _persist_task(cli_task)
                return

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

        except OSError as exc:
            cli_task.task_status = TaskStatus.FAILED
            cli_task.task_error = str(exc)
            logger.error("cli_task.os_error", **_task_log_context(cli_task), error=str(exc))
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

    async def run_task(self, request: LlmTaskRequest, *, engine_name: str) -> LlmTaskResult:
        cli_task = self._build_cli_task(request, engine_name=engine_name)
        self._bind_request_metadata(cli_task, request)
        self._record_event(
            request,
            EventType.LLM_TASK_REQUESTED,
            llm_call_id=cli_task.task_id,
            engine_name=engine_name,
            expected_schema=request.expected_schema_name,
        )
        await self._run_cli_task(cli_task)
        if cli_task.task_status != TaskStatus.SUCCESS:
            self._record_event(
                request,
                EventType.LLM_TASK_FAILED,
                llm_call_id=cli_task.task_id,
                engine_name=engine_name,
                error=cli_task.task_error or "CLI task failed",
            )
            raise LlmTaskExecutionError.from_cli_task(cli_task)

        parsed_result = self._parse_result(cli_task.task_result or "")
        self._record_event(
            request,
            EventType.LLM_TASK_COMPLETED,
            llm_call_id=cli_task.task_id,
            engine_name=engine_name,
            created_artifacts=str(len(parsed_result.get("created_artifacts", []))),
            open_questions=str(len(parsed_result.get("open_questions_found", []))),
        )
        return LlmTaskResult(
            task_kind=request.task_kind,
            step_id=request.step_id,
            completed_actions=parsed_result.get("completed_actions", []),
            created_artifacts=parsed_result.get("created_artifacts", []),
            open_questions_found=parsed_result.get("open_questions_found", []),
            diff_based_findings=parsed_result.get("diff_based_findings", []),
            snapshot_based_findings=parsed_result.get("snapshot_based_findings", []),
            notes=parsed_result.get("notes", ""),
            raw_output=cli_task.task_result or "",
        )

    def _build_cli_task(self, request: LlmTaskRequest, *, engine_name: str) -> CliTask:
        return CliTask(
            task_id=str(uuid.uuid4()),
            engine_name=engine_name,
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
