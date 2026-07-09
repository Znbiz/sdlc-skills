import asyncio
import datetime
import json
import typing

import fastapi
import pydantic
import structlog
from fastapi.responses import StreamingResponse

from app.services.cli_auth_checker import check_claude_auth, check_codex_auth
from app.services.cli_auth_session import AuthFlowStatus, get_auth_session_registry

router = fastapi.APIRouter()
logger = structlog.get_logger()

_AUTH_POLL_INTERVAL: typing.Final[float] = 0.1
_AUTH_TERMINAL_STATUSES: typing.Final[frozenset[AuthFlowStatus]] = frozenset(
    {
        AuthFlowStatus.SUCCESS,
        AuthFlowStatus.FAILED,
        AuthFlowStatus.EXPIRED,
    }
)


class CliEngineAuthInfo(pydantic.BaseModel, frozen=True):
    authenticated: bool
    auth_status: str
    auth_file_exists: bool


class CliAuthStatusResponse(pydantic.BaseModel, frozen=True):
    codex: CliEngineAuthInfo
    claude: CliEngineAuthInfo


class AuthSessionResponse(pydantic.BaseModel, frozen=True):
    auth_session_id: str
    cli_engine: str
    auth_flow_status: str
    instructions: str | None


@router.get("/cli-auth/")
async def get_cli_auth_status() -> CliAuthStatusResponse:
    codex_info, claude_info = await asyncio.gather(check_codex_auth(), check_claude_auth())
    return CliAuthStatusResponse(
        codex=CliEngineAuthInfo(**codex_info),
        claude=CliEngineAuthInfo(**claude_info),
    )


@router.get("/cli-auth/auth-sessions/{auth_session_id}/")
async def get_auth_session(auth_session_id: str) -> AuthSessionResponse:
    registry = get_auth_session_registry()
    session = registry.get(auth_session_id)
    if session is None:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail="Auth session not found")

    if (
        session.auth_flow_status == AuthFlowStatus.PENDING
        and datetime.datetime.now(datetime.timezone.utc) > session.expires_at
    ):
        session.auth_flow_status = AuthFlowStatus.EXPIRED

    return AuthSessionResponse(
        auth_session_id=session.auth_session_id,
        cli_engine=session.cli_engine,
        auth_flow_status=session.auth_flow_status,
        instructions=session.instructions,
    )


async def _stream_auth_session_events(auth_session_id: str) -> typing.AsyncGenerator[str, None]:
    registry = get_auth_session_registry()
    session = registry.get(auth_session_id)
    if session is None:
        not_found_msg = f"Auth session {auth_session_id!r} not found"
        yield f"data: {json.dumps({'event_type': 'error', 'error_message': not_found_msg})}\n\n"
        return

    logger.info("sse.cli_auth_stream.connected", auth_session_id=auth_session_id)
    last_idx = 0

    while session.auth_flow_status not in _AUTH_TERMINAL_STATUSES:
        if datetime.datetime.now(datetime.timezone.utc) > session.expires_at:
            session.auth_flow_status = AuthFlowStatus.EXPIRED
            break

        for line in session.output_lines[last_idx:]:
            yield f"data: {json.dumps({'event_type': 'instructions', 'event_data': line})}\n\n"
        last_idx = len(session.output_lines)

        await asyncio.sleep(_AUTH_POLL_INTERVAL)

    for line in session.output_lines[last_idx:]:
        yield f"data: {json.dumps({'event_type': 'instructions', 'event_data': line})}\n\n"

    if session.auth_flow_status == AuthFlowStatus.SUCCESS:
        yield f"data: {json.dumps({'event_type': 'auth_success', 'cli_engine': session.cli_engine})}\n\n"
    else:
        yield f"data: {json.dumps({'event_type': 'auth_failed', 'error_message': str(session.auth_flow_status)})}\n\n"


@router.get("/cli-auth/auth-sessions/{auth_session_id}/stream/")
async def stream_auth_session(auth_session_id: str) -> StreamingResponse:
    return StreamingResponse(
        _stream_auth_session_events(auth_session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
