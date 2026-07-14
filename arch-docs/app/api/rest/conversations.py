from __future__ import annotations

import typing

import fastapi
import pydantic
from fastapi import status
from fastapi.responses import StreamingResponse

from app.services.init_arch_workflow import (
    WorkflowNotFoundError,
    WorkflowValidationError,
    create_conversation_async,
    create_response_async,
    get_conversation_async,
    get_response_async,
    list_conversation_items_async,
    stream_response_events_async,
    submit_response_action_async,
)

router = fastapi.APIRouter()


class RequiredActionResponse(pydantic.BaseModel, frozen=True):
    action_type: str
    question_id: str | None = None
    action_status: str
    payload: dict[str, typing.Any] = pydantic.Field(default_factory=dict)


class ResponseStatusResponse(pydantic.BaseModel, frozen=True):
    response_id: str
    conversation_id: str
    workflow_type: str
    response_status: str
    current_step_id: str
    current_repo_name: str
    workspace_dir: str
    arch_repo_dir: str
    completed_steps: list[str]
    required_actions: list[RequiredActionResponse]
    created_at: str
    updated_at: str
    error_message: str | None = None
    terminal_result: dict[str, typing.Any] | None = None


class ConversationResponse(pydantic.BaseModel, frozen=True):
    conversation_id: str
    created_at: str
    updated_at: str
    active_response: ResponseStatusResponse | None


class ConversationItemResponse(pydantic.BaseModel, frozen=True):
    item_id: str
    item_kind: str
    actor: str
    step_id: str | None = None
    payload: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    created_at: str


class ConversationItemsResponse(pydantic.BaseModel, frozen=True):
    conversation_id: str
    items: list[ConversationItemResponse]


class CreateResponseRequest(pydantic.BaseModel, frozen=True):
    conversation_id: str
    workflow_type: str
    input: dict[str, typing.Any] = pydantic.Field(default_factory=dict)


class ResponseActionRequest(pydantic.BaseModel, frozen=True):
    action_type: str
    question_id: str | None = None
    answer: str | None = None
    field: str | None = None
    value: typing.Any = None


def _not_found(exc: WorkflowNotFoundError) -> fastapi.HTTPException:
    return fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _response_model(payload: dict[str, typing.Any]) -> ResponseStatusResponse:
    return ResponseStatusResponse(
        response_id=payload["response_id"],
        conversation_id=payload["conversation_id"],
        workflow_type=payload["workflow_type"],
        response_status=payload["response_status"],
        current_step_id=payload["current_step_id"],
        current_repo_name=payload["current_repo_name"],
        workspace_dir=payload["workspace_dir"],
        arch_repo_dir=payload["arch_repo_dir"],
        completed_steps=list(payload["completed_steps"]),
        required_actions=[RequiredActionResponse.model_validate(action) for action in payload["required_actions"]],
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
        error_message=payload.get("error_message"),
        terminal_result=payload.get("terminal_result"),
    )


@router.post("/conversations/", status_code=status.HTTP_201_CREATED)
async def create_conversation() -> ConversationResponse:
    payload = await create_conversation_async()
    return ConversationResponse.model_validate(payload)


@router.get("/conversations/{conversation_id}/")
async def get_conversation(conversation_id: str) -> ConversationResponse:
    try:
        payload = await get_conversation_async(conversation_id)
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc

    active_response = payload.get("active_response")
    return ConversationResponse(
        conversation_id=payload["conversation_id"],
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
        active_response=_response_model(active_response) if isinstance(active_response, dict) else None,
    )


@router.get("/conversations/{conversation_id}/items/")
async def list_conversation_items(conversation_id: str) -> ConversationItemsResponse:
    try:
        await get_conversation_async(conversation_id)
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc

    items = await list_conversation_items_async(conversation_id)
    return ConversationItemsResponse(
        conversation_id=conversation_id,
        items=[ConversationItemResponse.model_validate(item) for item in items],
    )


@router.get("/conversations/{conversation_id}/stream/")
async def stream_conversation(conversation_id: str) -> StreamingResponse:
    try:
        payload = await get_conversation_async(conversation_id)
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc

    active_response = payload.get("active_response")
    if not isinstance(active_response, dict):

        async def _empty_stream() -> typing.AsyncGenerator[str, None]:
            if False:
                yield ""

        return StreamingResponse(_empty_stream(), media_type="text/event-stream")

    return StreamingResponse(
        stream_response_events_async(active_response["response_id"]),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/responses/", status_code=status.HTTP_202_ACCEPTED)
async def create_response(request: CreateResponseRequest) -> ResponseStatusResponse:
    try:
        payload = await create_response_async(
            conversation_id=request.conversation_id,
            workflow_type=request.workflow_type,
            input_payload=dict(request.input),
        )
    except WorkflowValidationError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _response_model(payload)


@router.get("/responses/{response_id}/")
async def get_response(response_id: str) -> ResponseStatusResponse:
    try:
        payload = await get_response_async(response_id)
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc
    return _response_model(payload)


@router.post("/responses/{response_id}/actions/", status_code=status.HTTP_202_ACCEPTED)
async def submit_response_action(response_id: str, request: ResponseActionRequest) -> ResponseStatusResponse:
    try:
        payload = await submit_response_action_async(
            response_id,
            action_type=request.action_type,
            question_id=request.question_id,
            answer=request.answer,
            field=request.field,
            value=request.value,
        )
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc
    except WorkflowValidationError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _response_model(payload)
