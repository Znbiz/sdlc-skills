from __future__ import annotations

import dataclasses
import typing

from app.db.git_host_repo import (
    create_git_host,
    delete_git_host,
    get_git_host_by_host,
    get_git_host_by_id,
    list_git_hosts,
    update_git_host,
)
from app.db.session import get_session
from app.services.git_credentials import delete_git_token, get_stored_token, set_git_token

if typing.TYPE_CHECKING:
    import uuid

ConnectionType = typing.Literal["token", "ssh"]

_CONNECTION_TYPES: typing.Final[frozenset[str]] = frozenset({"token", "ssh"})


class GitConnectionNotFoundError(Exception):
    pass


class GitConnectionAlreadyExistsError(Exception):
    pass


class GitConnectionValidationError(Exception):
    pass


@dataclasses.dataclass(frozen=True, slots=True)
class GitConnectionSummary:
    connection_id: uuid.UUID
    host: str
    connection_type: str


@dataclasses.dataclass(frozen=True, slots=True)
class GitConnectionDetail:
    connection_id: uuid.UUID
    host: str
    connection_type: str
    token: str | None
    username: str | None


def _validate_connection_type(connection_type: str) -> None:
    if connection_type not in _CONNECTION_TYPES:
        msg = f"connection_type must be one of {sorted(_CONNECTION_TYPES)}, got {connection_type!r}"
        raise GitConnectionValidationError(msg)


def _validate_token(connection_type: str, token: str | None) -> None:
    if connection_type == "token" and (not token or not token.strip()):
        msg = "token must not be empty for connection_type='token'"
        raise GitConnectionValidationError(msg)


async def _write_credential(*, host: str, connection_type: str, token: str | None, username: str | None) -> None:
    if connection_type == "token":
        await set_git_token(host=host, token=token, username=username)  # type: ignore[arg-type]
    else:
        # Switching (or creating) as SSH relies on the service's single shared key - no
        # per-host secret to store, so any leftover token for this host is dropped.
        await delete_git_token(host)


async def get_connection_type_for_host(host: str) -> str | None:
    """Return the registered `connection_type` ("token"/"ssh") for `host`, or `None` if unregistered.

    Used by repository-URL normalization (see `_normalize_repository_url()` in
    `app/services/init_arch_workflow.py`) to pick the clone transport that matches how the host
    is actually configured, instead of whatever scheme the user happened to paste.
    """
    async with get_session() as session:
        row = await get_git_host_by_host(session, host)
    return row.connection_type if row is not None else None


async def list_git_connections_async() -> list[GitConnectionSummary]:
    async with get_session() as session:
        rows = await list_git_hosts(session)
    return [
        GitConnectionSummary(connection_id=row.connection_id, host=row.host, connection_type=row.connection_type)
        for row in rows
    ]


async def get_git_connection_async(connection_id: uuid.UUID) -> GitConnectionDetail:
    async with get_session() as session:
        row = await get_git_host_by_id(session, connection_id)
    if row is None:
        raise GitConnectionNotFoundError(connection_id)

    if row.connection_type == "token":
        stored = await get_stored_token(row.host)
        username, token = stored if stored is not None else (None, None)
        return GitConnectionDetail(
            connection_id=row.connection_id,
            host=row.host,
            connection_type=row.connection_type,
            token=token,
            username=username,
        )

    return GitConnectionDetail(
        connection_id=row.connection_id, host=row.host, connection_type=row.connection_type, token=None, username=None
    )


async def create_git_connection_async(
    *,
    host: str,
    connection_type: str,
    token: str | None = None,
    username: str | None = None,
) -> GitConnectionSummary:
    _validate_connection_type(connection_type)
    _validate_token(connection_type, token)

    async with get_session() as session:
        existing = await get_git_host_by_host(session, host)
    if existing is not None:
        raise GitConnectionAlreadyExistsError(host)

    await _write_credential(host=host, connection_type=connection_type, token=token, username=username)

    async with get_session() as session:
        row = await create_git_host(session, host=host, connection_type=connection_type)
    return GitConnectionSummary(connection_id=row.connection_id, host=row.host, connection_type=row.connection_type)


async def update_git_connection_async(
    *,
    connection_id: uuid.UUID,
    host: str,
    connection_type: str,
    token: str | None = None,
    username: str | None = None,
) -> GitConnectionSummary:
    _validate_connection_type(connection_type)
    _validate_token(connection_type, token)

    async with get_session() as session:
        current = await get_git_host_by_id(session, connection_id)
        if current is None:
            raise GitConnectionNotFoundError(connection_id)

        conflicting = await get_git_host_by_host(session, host)
        if conflicting is not None and conflicting.connection_id != connection_id:
            raise GitConnectionAlreadyExistsError(host)

    previous_host = current.host
    await _write_credential(host=host, connection_type=connection_type, token=token, username=username)
    if previous_host != host:
        # The credential store keys secrets by host - moving the record to a new host must not
        # leave a stale token entry behind under the old hostname.
        await delete_git_token(previous_host)

    async with get_session() as session:
        row = await update_git_host(session, connection_id=connection_id, host=host, connection_type=connection_type)
    if row is None:
        raise GitConnectionNotFoundError(connection_id)
    return GitConnectionSummary(connection_id=row.connection_id, host=row.host, connection_type=row.connection_type)


async def delete_git_connection_async(connection_id: uuid.UUID) -> None:
    async with get_session() as session:
        deleted = await delete_git_host(session, connection_id)
    if deleted is None:
        raise GitConnectionNotFoundError(connection_id)
    await delete_git_token(deleted.host)
