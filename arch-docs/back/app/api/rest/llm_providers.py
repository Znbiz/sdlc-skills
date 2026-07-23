import uuid  # noqa: TC003 - FastAPI resolves path-param annotations at runtime, so this must stay a real import

import fastapi
import pydantic
from fastapi import status

from app.services.llm_providers import (
    LlmProviderConnectionAlreadyExistsError,
    LlmProviderConnectionNotFoundError,
    LlmProviderConnectionSummary,
    LlmProviderConnectionValidationError,
    create_llm_provider_connection_async,
    delete_llm_provider_connection_async,
    get_llm_provider_connection_async,
    list_llm_provider_connections_async,
    update_llm_provider_connection_async,
)

router = fastapi.APIRouter()


class LlmProviderConnectionSummaryResponse(pydantic.BaseModel, frozen=True):
    connection_id: uuid.UUID
    name: str
    base_url: str
    model: str
    wire_api: str
    requires_openai_auth: bool


class LlmProviderConnectionDetailResponse(pydantic.BaseModel, frozen=True):
    connection_id: uuid.UUID
    name: str
    base_url: str
    model: str
    wire_api: str
    requires_openai_auth: bool
    token: str | None = None


class CreateLlmProviderConnectionRequest(pydantic.BaseModel, frozen=True):
    name: str
    base_url: str
    model: str
    token: str
    wire_api: str = "chat"
    requires_openai_auth: bool = False


class UpdateLlmProviderConnectionRequest(pydantic.BaseModel, frozen=True):
    name: str
    base_url: str
    model: str
    token: str | None = None
    wire_api: str = "chat"
    requires_openai_auth: bool = False


def _summary_response(summary: LlmProviderConnectionSummary) -> LlmProviderConnectionSummaryResponse:
    return LlmProviderConnectionSummaryResponse(
        connection_id=summary.connection_id,
        name=summary.name,
        base_url=summary.base_url,
        model=summary.model,
        wire_api=summary.wire_api,
        requires_openai_auth=summary.requires_openai_auth,
    )


@router.get("/llm-providers/")
async def list_llm_provider_connections() -> list[LlmProviderConnectionSummaryResponse]:
    connections = await list_llm_provider_connections_async()
    return [_summary_response(connection) for connection in connections]


@router.get("/llm-providers/{connection_id}/")
async def get_llm_provider_connection(connection_id: uuid.UUID) -> LlmProviderConnectionDetailResponse:
    try:
        detail = await get_llm_provider_connection_async(connection_id)
    except LlmProviderConnectionNotFoundError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    # Token is intentionally never returned - the field only signals "configured"/"not configured".
    return LlmProviderConnectionDetailResponse(
        connection_id=detail.connection_id,
        name=detail.name,
        base_url=detail.base_url,
        model=detail.model,
        wire_api=detail.wire_api,
        requires_openai_auth=detail.requires_openai_auth,
        token="********" if detail.token else None,
    )


@router.post("/llm-providers/", status_code=status.HTTP_201_CREATED)
async def create_llm_provider_connection(
    request: CreateLlmProviderConnectionRequest,
) -> LlmProviderConnectionSummaryResponse:
    try:
        summary = await create_llm_provider_connection_async(
            name=request.name,
            base_url=request.base_url,
            model=request.model,
            token=request.token,
            wire_api=request.wire_api,
            requires_openai_auth=request.requires_openai_auth,
        )
    except LlmProviderConnectionValidationError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except LlmProviderConnectionAlreadyExistsError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _summary_response(summary)


@router.put("/llm-providers/{connection_id}/")
async def update_llm_provider_connection(
    connection_id: uuid.UUID, request: UpdateLlmProviderConnectionRequest
) -> LlmProviderConnectionSummaryResponse:
    try:
        summary = await update_llm_provider_connection_async(
            connection_id=connection_id,
            name=request.name,
            base_url=request.base_url,
            model=request.model,
            token=request.token,
            wire_api=request.wire_api,
            requires_openai_auth=request.requires_openai_auth,
        )
    except LlmProviderConnectionNotFoundError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LlmProviderConnectionValidationError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except LlmProviderConnectionAlreadyExistsError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _summary_response(summary)


@router.delete("/llm-providers/{connection_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_llm_provider_connection(connection_id: uuid.UUID) -> fastapi.Response:
    try:
        await delete_llm_provider_connection_async(connection_id)
    except LlmProviderConnectionNotFoundError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return fastapi.Response(status_code=status.HTTP_204_NO_CONTENT)
