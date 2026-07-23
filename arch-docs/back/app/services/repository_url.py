from __future__ import annotations

import re
import typing

from app.services.git_connections import get_connection_type_for_host

_SCP_LIKE_SSH_URL_PATTERN: typing.Final[re.Pattern[str]] = re.compile(r"^git@(?P<host>[^:/]+):(?P<path>.+)$")
_HTTP_URL_PATTERN: typing.Final[re.Pattern[str]] = re.compile(r"^(?P<scheme>https?)://(?P<host>[^/]+)/(?P<path>.+)$")


def canonicalize_repo_path(path: str) -> str:
    return path.strip().rstrip("/").removesuffix(".git")


def extract_repo_host_and_path(url: str) -> tuple[str, str, str] | None:
    """Parse `url` into `(scheme, host, path)`, where `scheme` is `"ssh"`, `"http"` or `"https"`."""
    scp_match = _SCP_LIKE_SSH_URL_PATTERN.match(url)
    if scp_match:
        return "ssh", scp_match.group("host"), canonicalize_repo_path(scp_match.group("path"))

    http_match = _HTTP_URL_PATTERN.match(url)
    if http_match:
        return http_match.group("scheme"), http_match.group("host"), canonicalize_repo_path(http_match.group("path"))

    return None


async def normalize_repository_url(raw_url: str) -> str:
    """Bring a user-submitted repository URL to a canonical clone URL for `host`'s transport.

    Users paste this in error-prone shapes: the SCP-like SSH form (`git@host:path.git`) and a
    bare web address-bar copy (`https://host/path`, no `.git`, maybe a trailing slash). The
    transport that actually works is decided by how `host` is registered in "Git-подключения"
    (see app/services/git_connections.py) — an https:// URL for a host with only a deploy key
    (no PAT) can never authenticate over HTTPS ("could not read Username"), and a PAT is
    HTTPS-only (git's credential helper never applies to the SSH transport), so this rewrites
    the URL to whichever scheme matches the host's actual connection_type, regardless of which
    form the user happened to paste. Unregistered hosts are left on their original scheme.

    Callers must re-run this at clone time, not only when a repository entry is first added -
    the registered connection for a host can change (or be added) after the entry was stored,
    and a stale URL from before that change will fail to authenticate.
    """
    stripped = raw_url.strip()

    parsed = extract_repo_host_and_path(stripped)
    if parsed is None:
        return stripped
    original_scheme, host, path = parsed

    connection_type = await get_connection_type_for_host(host)
    if connection_type == "ssh":
        return f"git@{host}:{path}.git"
    if connection_type == "token":
        return f"https://{host}/{path}.git"

    if original_scheme == "ssh":
        return f"git@{host}:{path}.git"
    return f"{original_scheme}://{host}/{path}.git"
