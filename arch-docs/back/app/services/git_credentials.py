import asyncio
import enum
import os
import pathlib
import typing

from app.services.status_taxonomy import ReasonCode

_CREDENTIALS_DIR: typing.Final = pathlib.Path("~/.config/git-credentials-store").expanduser()
_CREDENTIALS_FILE: typing.Final = _CREDENTIALS_DIR / "credentials"
_GIT_CONFIG_GLOBAL_PATH: typing.Final = _CREDENTIALS_DIR / "gitconfig"

_GIT_CONFIG_TIMEOUT: typing.Final[float] = 10.0
_GIT_ACCESS_TIMEOUT: typing.Final[float] = 20.0

# git-credential-store's `get` verb only returns an entry that has both a username and a
# password component (`user:pass@host`). A bare `token@host` line (no colon) is stored fine
# but never matched back on lookup, so PAT-only tokens need a placeholder username to become
# the password half of the pair. Both GitHub and GitLab accept any non-empty username here.
_DEFAULT_TOKEN_USERNAME: typing.Final[str] = "oauth2"  # noqa: S105 (placeholder username, not a secret)


class GitAccessStatus(enum.StrEnum):
    OK = enum.auto()
    AUTH_FAILED = enum.auto()
    TIMEOUT = enum.auto()
    ERROR = enum.auto()


class GitAccessResult(typing.TypedDict):
    accessible: bool
    access_status: str
    reason_code: str | None
    message: str


_AUTH_FAILURE_PHRASES: typing.Final[tuple[str, ...]] = (
    "permission denied",
    "authentication failed",
    "could not read from remote repository",
    "access denied",
    "invalid username or password",
    "http basic: access denied",
)


async def _run_git_config(args: list[str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "config",
        "--global",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=_GIT_CONFIG_TIMEOUT)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "timeout"
    return proc.returncode or 0, stderr_bytes.decode(errors="replace")


async def _run_git_access_check(cmd: list[str], *, env: dict[str, str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        _, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=_GIT_ACCESS_TIMEOUT)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "timeout"
    return proc.returncode or 0, stderr_bytes.decode(errors="replace")


async def ensure_git_credentials_store() -> None:
    _CREDENTIALS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not _CREDENTIALS_FILE.exists():
        _CREDENTIALS_FILE.touch(mode=0o600)

    # GIT_CONFIG_GLOBAL redirects `git config --global` away from the real ~/.gitconfig
    # onto our own persisted file. This is required (not just a convenience): the LLM
    # worker subprocess (codex/claude CLI) inherits our process's os.environ when it runs
    # its own `git clone`, so setting this here is what makes credentials visible to it.
    os.environ["GIT_CONFIG_GLOBAL"] = str(_GIT_CONFIG_GLOBAL_PATH)

    credential_helper_line = f"helper = store --file={_CREDENTIALS_FILE}"
    if _GIT_CONFIG_GLOBAL_PATH.exists() and credential_helper_line in _GIT_CONFIG_GLOBAL_PATH.read_text():
        return

    exit_code, stderr_text = await _run_git_config(["credential.helper", f"store --file={_CREDENTIALS_FILE}"])
    if exit_code != 0:
        msg = f"git config credential.helper failed: {stderr_text}"
        raise RuntimeError(msg)


def _host_of_credentials_line(line: str) -> str:
    without_scheme = line.split("://", 1)[-1]
    without_auth = without_scheme.rsplit("@", 1)[-1]
    return without_auth.strip("/")


async def set_git_token(*, host: str, token: str, username: str | None = None) -> None:
    await ensure_git_credentials_store()

    auth_part = f"{username or _DEFAULT_TOKEN_USERNAME}:{token}"
    new_entry = f"https://{auth_part}@{host}"

    existing_lines = _CREDENTIALS_FILE.read_text().splitlines() if _CREDENTIALS_FILE.exists() else []
    kept_lines = [line for line in existing_lines if line and _host_of_credentials_line(line) != host]
    kept_lines.append(new_entry)

    _CREDENTIALS_FILE.write_text("\n".join(kept_lines) + "\n")
    _CREDENTIALS_FILE.chmod(0o600)


async def list_configured_hosts() -> list[str]:
    if not _CREDENTIALS_FILE.exists():
        return []
    return [_host_of_credentials_line(line) for line in _CREDENTIALS_FILE.read_text().splitlines() if line]


async def delete_git_token(host: str) -> bool:
    if not _CREDENTIALS_FILE.exists():
        return False
    existing_lines = _CREDENTIALS_FILE.read_text().splitlines()
    kept_lines = [line for line in existing_lines if line and _host_of_credentials_line(line) != host]
    if len(kept_lines) == len(existing_lines):
        return False
    content = "\n".join(kept_lines)
    _CREDENTIALS_FILE.write_text(f"{content}\n" if content else "")
    _CREDENTIALS_FILE.chmod(0o600)
    return True


def classify_git_access_failure(stderr_text: str) -> GitAccessStatus:
    lowered = stderr_text.lower()
    if "timeout" in lowered:
        return GitAccessStatus.TIMEOUT
    if any(phrase in lowered for phrase in _AUTH_FAILURE_PHRASES):
        return GitAccessStatus.AUTH_FAILED
    return GitAccessStatus.ERROR


_ACCESS_STATUS_REASON_CODES: typing.Final[dict[GitAccessStatus, ReasonCode]] = {
    GitAccessStatus.AUTH_FAILED: ReasonCode.GIT_ACCESS_AUTH_FAILED,
    GitAccessStatus.TIMEOUT: ReasonCode.GIT_ACCESS_TIMEOUT,
    GitAccessStatus.ERROR: ReasonCode.GIT_ACCESS_ERROR,
}


async def check_git_access(repository_url: str) -> GitAccessResult:
    if not await list_configured_hosts():
        return GitAccessResult(
            accessible=False,
            access_status=GitAccessStatus.AUTH_FAILED,
            reason_code=ReasonCode.GIT_PAT_MISSING,
            message="No Git personal access token is configured",
        )

    await ensure_git_credentials_store()

    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        exit_code, stderr_text = await _run_git_access_check(
            ["git", "ls-remote", "--exit-code", repository_url, "HEAD"],
            env=env,
        )
    except FileNotFoundError:
        return GitAccessResult(
            accessible=False,
            access_status=GitAccessStatus.ERROR,
            reason_code=ReasonCode.GIT_BINARY_MISSING,
            message="git binary is not available in this container",
        )

    if exit_code == 0:
        return GitAccessResult(accessible=True, access_status=GitAccessStatus.OK, reason_code=None, message="ok")

    access_status = classify_git_access_failure(stderr_text)
    return GitAccessResult(
        accessible=False,
        access_status=access_status,
        reason_code=_ACCESS_STATUS_REASON_CODES[access_status],
        message=stderr_text.strip() or f"git ls-remote exited with code {exit_code}",
    )
