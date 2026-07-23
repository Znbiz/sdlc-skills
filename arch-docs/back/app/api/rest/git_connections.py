import uuid  # noqa: TC003 - FastAPI resolves path-param annotations at runtime, so this must stay a real import

import fastapi
import pydantic
from fastapi import status

from app.services.git_connections import (
    GitConnectionAlreadyExistsError,
    GitConnectionNotFoundError,
    GitConnectionSummary,
    GitConnectionValidationError,
    create_git_connection_async,
    delete_git_connection_async,
    get_git_connection_async,
    list_git_connections_async,
    update_git_connection_async,
)

router = fastapi.APIRouter()


def _validate_host(value: str) -> str:
    stripped = value.strip()
    if not stripped or "/" in stripped or "://" in stripped:
        msg = "host must be a bare hostname, e.g. 'github.com'"
        raise ValueError(msg)
    return stripped


class GitConnectionSummaryResponse(pydantic.BaseModel, frozen=True):
    connection_id: uuid.UUID
    host: str
    connection_type: str


class GitConnectionDetailResponse(pydantic.BaseModel, frozen=True):
    connection_id: uuid.UUID
    host: str
    connection_type: str
    token: str | None = None
    username: str | None = None


class CreateGitConnectionRequest(pydantic.BaseModel, frozen=True):
    host: str
    connection_type: str
    token: str | None = None
    username: str | None = None

    @pydantic.field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        return _validate_host(value)


class UpdateGitConnectionRequest(pydantic.BaseModel, frozen=True):
    host: str
    connection_type: str
    token: str | None = None
    username: str | None = None

    @pydantic.field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        return _validate_host(value)


def _summary_response(summary: GitConnectionSummary) -> GitConnectionSummaryResponse:
    return GitConnectionSummaryResponse(
        connection_id=summary.connection_id, host=summary.host, connection_type=summary.connection_type
    )


@router.get("/git-connections/")
async def list_git_connections() -> list[GitConnectionSummaryResponse]:
    connections = await list_git_connections_async()
    return [_summary_response(connection) for connection in connections]


@router.get("/git-connections/{connection_id}/")
async def get_git_connection(connection_id: uuid.UUID) -> GitConnectionDetailResponse:
    try:
        detail = await get_git_connection_async(connection_id)
    except GitConnectionNotFoundError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return GitConnectionDetailResponse(
        connection_id=detail.connection_id,
        host=detail.host,
        connection_type=detail.connection_type,
        token=detail.token,
        username=detail.username,
    )


@router.post("/git-connections/", status_code=status.HTTP_201_CREATED)
async def create_git_connection(request: CreateGitConnectionRequest) -> GitConnectionSummaryResponse:
    try:
        summary = await create_git_connection_async(
            host=request.host,
            connection_type=request.connection_type,
            token=request.token,
            username=request.username,
        )
    except GitConnectionValidationError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except GitConnectionAlreadyExistsError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _summary_response(summary)


@router.put("/git-connections/{connection_id}/")
async def update_git_connection(
    connection_id: uuid.UUID, request: UpdateGitConnectionRequest
) -> GitConnectionSummaryResponse:
    try:
        summary = await update_git_connection_async(
            connection_id=connection_id,
            host=request.host,
            connection_type=request.connection_type,
            token=request.token,
            username=request.username,
        )
    except GitConnectionNotFoundError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GitConnectionValidationError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except GitConnectionAlreadyExistsError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _summary_response(summary)


@router.delete("/git-connections/{connection_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_git_connection(connection_id: uuid.UUID) -> fastapi.Response:
    try:
        await delete_git_connection_async(connection_id)
    except GitConnectionNotFoundError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return fastapi.Response(status_code=status.HTTP_204_NO_CONTENT)
