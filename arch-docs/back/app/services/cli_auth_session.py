from __future__ import annotations

import dataclasses
import datetime
import enum
import typing

if typing.TYPE_CHECKING:
    import asyncio

_AUTH_SESSION_TTL_SECONDS: typing.Final[int] = 600


class AuthFlowStatus(enum.StrEnum):
    PENDING = enum.auto()
    SUCCESS = enum.auto()
    FAILED = enum.auto()
    EXPIRED = enum.auto()


@dataclasses.dataclass(kw_only=True, slots=True)
class CliAuthSession:
    auth_session_id: str
    cli_engine: str
    auth_flow_status: AuthFlowStatus = AuthFlowStatus.PENDING
    instructions: str | None = None
    verification_uri: str | None = None
    user_code: str | None = None
    subprocess_handle: asyncio.subprocess.Process | None = None
    output_lines: list[str] = dataclasses.field(default_factory=list)
    created_at: datetime.datetime = dataclasses.field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
    expires_at: datetime.datetime = dataclasses.field(
        default_factory=lambda: (
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=_AUTH_SESSION_TTL_SECONDS)
        ),
    )


AuthSessionRegistry: typing.TypeAlias = dict[str, CliAuthSession]

_registry: AuthSessionRegistry = {}


def get_auth_session_registry() -> AuthSessionRegistry:
    return _registry


def reset_auth_session_registry() -> None:
    _registry.clear()
