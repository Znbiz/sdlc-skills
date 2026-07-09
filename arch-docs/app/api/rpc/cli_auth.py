import asyncio
import os
import uuid

import fastapi
import pydantic
import structlog
from fastapi import status

from app.services.cli_auth_session import (
    AuthFlowStatus,
    CliAuthSession,
    get_auth_session_registry,
)

router = fastapi.APIRouter()
logger = structlog.get_logger()

_background_tasks: set[asyncio.Task] = set()

_CODEX_AUTH_CMD: list[str] = ["codex", "login", "--device-auth"]
_CLAUDE_AUTH_CMD: list[str] = ["claude", "auth", "login"]

_SUCCESS_PHRASES: tuple[str, ...] = ("logged in", "authenticated", "success", "authorization complete")
_FAILURE_PHRASES: tuple[str, ...] = ("error", "failed", "denied", "expired")


class InitAuthRequest(pydantic.BaseModel, frozen=True):
    cli_engine: str

    @pydantic.field_validator("cli_engine")
    @classmethod
    def validate_engine(cls, value: str) -> str:
        if value not in ("codex", "claude"):
            msg = "cli_engine must be 'codex' or 'claude'"
            raise ValueError(msg)
        return value


class InitAuthResponse(pydantic.BaseModel, frozen=True):
    auth_session_id: str
    cli_engine: str
    auth_flow_status: str
    instructions: str | None
    expires_at: str


async def _collect_auth_output(reader: asyncio.StreamReader, session: CliAuthSession) -> None:
    while True:
        raw = await reader.readline()
        if not raw:
            break
        line = raw.decode().strip()
        if not line:
            continue
        session.output_lines.append(line)
        line_lower = line.lower()
        if session.instructions is None and ("http" in line_lower or "code" in line_lower):
            session.instructions = line
        if any(phrase in line_lower for phrase in _SUCCESS_PHRASES):
            session.auth_flow_status = AuthFlowStatus.SUCCESS
        elif any(phrase in line_lower for phrase in _FAILURE_PHRASES):
            session.auth_flow_status = AuthFlowStatus.FAILED


def _finalize_auth_status(session: CliAuthSession, return_code: int) -> None:
    if session.auth_flow_status != AuthFlowStatus.PENDING:
        return
    session.auth_flow_status = AuthFlowStatus.SUCCESS if return_code == 0 else AuthFlowStatus.FAILED


async def _run_auth_session(session: CliAuthSession) -> None:
    cmd = _CODEX_AUTH_CMD if session.cli_engine == "codex" else _CLAUDE_AUTH_CMD
    logger.info("cli_auth.session.started", auth_session_id=session.auth_session_id, engine=session.cli_engine)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ},
        )
        session.subprocess_handle = proc
        await asyncio.gather(
            _collect_auth_output(proc.stdout, session),  # type: ignore[arg-type]
            _collect_auth_output(proc.stderr, session),  # type: ignore[arg-type]
        )
        await proc.wait()
        _finalize_auth_status(session, proc.returncode or 0)

    except OSError as exc:
        session.auth_flow_status = AuthFlowStatus.FAILED
        logger.error("cli_auth.session.os_error", auth_session_id=session.auth_session_id, error=str(exc))

    logger.info(
        "cli_auth.session.finished",
        auth_session_id=session.auth_session_id,
        auth_flow_status=session.auth_flow_status,
    )


@router.post("/cli-auth/init/", status_code=status.HTTP_202_ACCEPTED)
async def init_cli_auth(request: InitAuthRequest) -> InitAuthResponse:
    session = CliAuthSession(
        auth_session_id=str(uuid.uuid4()),
        cli_engine=request.cli_engine,
    )

    registry = get_auth_session_registry()
    registry[session.auth_session_id] = session

    bg_task = asyncio.create_task(_run_auth_session(session))
    _background_tasks.add(bg_task)
    bg_task.add_done_callback(_background_tasks.discard)

    logger.info("cli_auth.init", auth_session_id=session.auth_session_id, engine=request.cli_engine)

    return InitAuthResponse(
        auth_session_id=session.auth_session_id,
        cli_engine=session.cli_engine,
        auth_flow_status=session.auth_flow_status,
        instructions=session.instructions,
        expires_at=session.expires_at.isoformat(),
    )
