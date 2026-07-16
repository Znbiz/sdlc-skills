import asyncio
import enum
import os
import pathlib
import typing


class CliAuthStatus(enum.StrEnum):
    OK = enum.auto()
    AUTH_EXPIRED = enum.auto()
    NOT_INITIALIZED = enum.auto()


class CliAuthInfo(typing.TypedDict):
    authenticated: bool
    auth_status: str
    auth_file_exists: bool


_CODEX_AUTH_FILE: typing.Final = pathlib.Path("~/.codex/auth.json").expanduser()
_CLAUDE_AUTH_DIR: typing.Final = pathlib.Path("~/.claude").expanduser()

_SMOKE_TIMEOUT: typing.Final[float] = 10.0
_CODEX_AUTH_EXIT_CODES: typing.Final[frozenset[int]] = frozenset({401, 403})


async def _run_smoke(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ},
        )
        _, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=_SMOKE_TIMEOUT)
        return proc.returncode or 0, stderr_bytes.decode().lower()
    except TimeoutError, OSError:
        return -1, ""


async def check_codex_auth() -> CliAuthInfo:
    file_exists = _CODEX_AUTH_FILE.exists()

    if not file_exists:
        return CliAuthInfo(
            authenticated=False,
            auth_status=CliAuthStatus.NOT_INITIALIZED,
            auth_file_exists=False,
        )

    exit_code, stderr_text = await _run_smoke(["codex", "exec", "--json", "--skip-git-repo-check", "echo ok"])

    if exit_code == 0:
        return CliAuthInfo(authenticated=True, auth_status=CliAuthStatus.OK, auth_file_exists=True)

    if exit_code in _CODEX_AUTH_EXIT_CODES or "auth" in stderr_text:
        return CliAuthInfo(authenticated=False, auth_status=CliAuthStatus.AUTH_EXPIRED, auth_file_exists=True)

    return CliAuthInfo(authenticated=False, auth_status=CliAuthStatus.AUTH_EXPIRED, auth_file_exists=True)


async def check_claude_auth() -> CliAuthInfo:
    auth_dir_exists = _CLAUDE_AUTH_DIR.exists() and any(_CLAUDE_AUTH_DIR.iterdir())

    if not auth_dir_exists:
        return CliAuthInfo(
            authenticated=False,
            auth_status=CliAuthStatus.NOT_INITIALIZED,
            auth_file_exists=False,
        )

    exit_code, stderr_text = await _run_smoke(["claude", "-p", "echo ok", "--output-format", "json"])

    if exit_code == 0:
        return CliAuthInfo(authenticated=True, auth_status=CliAuthStatus.OK, auth_file_exists=True)

    auth_phrases = ("not logged in", "authentication", "oauth", "unauthorized", "login required")
    if any(phrase in stderr_text for phrase in auth_phrases):
        return CliAuthInfo(authenticated=False, auth_status=CliAuthStatus.AUTH_EXPIRED, auth_file_exists=True)

    return CliAuthInfo(authenticated=False, auth_status=CliAuthStatus.AUTH_EXPIRED, auth_file_exists=True)
