import asyncio
import enum
import os
import pathlib
import typing

_SSH_DIR: typing.Final = pathlib.Path("~/.ssh").expanduser()
_PRIVATE_KEY_PATH: typing.Final = _SSH_DIR / "id_ed25519"
_PUBLIC_KEY_PATH: typing.Final = _SSH_DIR / "id_ed25519.pub"
_SSH_CONFIG_PATH: typing.Final = _SSH_DIR / "config"
_KNOWN_HOSTS_PATH: typing.Final = _SSH_DIR / "known_hosts"

_KEY_COMMENT: typing.Final[str] = "arch-docs-service"
_KEYGEN_TIMEOUT: typing.Final[float] = 15.0
_GIT_ACCESS_TIMEOUT: typing.Final[float] = 20.0

_SSH_CONFIG_CONTENT: typing.Final[str] = (
    "Host *\n"
    "    StrictHostKeyChecking accept-new\n"
    f"    UserKnownHostsFile {_KNOWN_HOSTS_PATH}\n"
    f"    IdentityFile {_PRIVATE_KEY_PATH}\n"
    "    IdentitiesOnly yes\n"
)


class GitAccessStatus(enum.StrEnum):
    OK = enum.auto()
    AUTH_FAILED = enum.auto()
    TIMEOUT = enum.auto()
    ERROR = enum.auto()


class GitAccessResult(typing.TypedDict):
    accessible: bool
    access_status: str
    message: str


_AUTH_FAILURE_PHRASES: typing.Final[tuple[str, ...]] = (
    "permission denied",
    "authentication failed",
    "could not read from remote repository",
    "access denied",
)


async def _run_keygen(cmd: list[str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=_KEYGEN_TIMEOUT)
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


async def ensure_ssh_key() -> str:
    _SSH_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    if not _PRIVATE_KEY_PATH.exists():
        exit_code, stderr_text = await _run_keygen(
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-N",
                "",
                "-f",
                str(_PRIVATE_KEY_PATH),
                "-C",
                _KEY_COMMENT,
            ]
        )
        if exit_code != 0:
            msg = f"ssh-keygen failed: {stderr_text}"
            raise RuntimeError(msg)
        _PRIVATE_KEY_PATH.chmod(0o600)

    if not _SSH_CONFIG_PATH.exists() or _SSH_CONFIG_PATH.read_text() != _SSH_CONFIG_CONTENT:
        _SSH_CONFIG_PATH.write_text(_SSH_CONFIG_CONTENT)
        _SSH_CONFIG_PATH.chmod(0o600)

    if not _KNOWN_HOSTS_PATH.exists():
        _KNOWN_HOSTS_PATH.touch(mode=0o600)

    return _PUBLIC_KEY_PATH.read_text().strip()


async def get_public_key() -> str:
    return await ensure_ssh_key()


def _classify_git_access_failure(stderr_text: str) -> GitAccessStatus:
    lowered = stderr_text.lower()
    if "timeout" in lowered:
        return GitAccessStatus.TIMEOUT
    if any(phrase in lowered for phrase in _AUTH_FAILURE_PHRASES):
        return GitAccessStatus.AUTH_FAILED
    return GitAccessStatus.ERROR


async def check_git_access(repository_url: str) -> GitAccessResult:
    await ensure_ssh_key()

    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_SSH_COMMAND": f"ssh -F {_SSH_CONFIG_PATH}",
    }
    exit_code, stderr_text = await _run_git_access_check(
        ["git", "ls-remote", "--exit-code", repository_url, "HEAD"],
        env=env,
    )

    if exit_code == 0:
        return GitAccessResult(accessible=True, access_status=GitAccessStatus.OK, message="ok")

    access_status = _classify_git_access_failure(stderr_text)
    return GitAccessResult(
        accessible=False,
        access_status=access_status,
        message=stderr_text.strip() or f"git ls-remote exited with code {exit_code}",
    )
