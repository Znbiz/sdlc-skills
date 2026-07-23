from __future__ import annotations

import typing

import fastapi
import pydantic
from fastapi import status
from fastapi.responses import StreamingResponse

from app.api.rest.docs import DocsFileResponse, DocsTreeNode
from app.services.docs_browser import DocsFileNotFoundError, DocsPathForbiddenError
from app.services.init_arch_workflow import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    WorkflowValidationError,
    add_conversation_repository_async,
    build_conversation_workspace_tree_async,
    create_conversation_async,
    create_response_async,
    delete_conversation_async,
    get_conversation_async,
    get_conversation_repositories_async,
    get_response_async,
    list_conversation_items_async,
    list_conversation_responses_async,
    list_conversations_async,
    list_workflow_events_async,
    read_conversation_workspace_file_async,
    remove_conversation_repository_async,
    set_conversation_repositories_async,
    stream_response_events_async,
    submit_response_action_async,
    update_conversation_product_name_async,
)

router = fastapi.APIRouter()


class RequiredActionResponse(pydantic.BaseModel, frozen=True):
    action_type: str
    question_id: str | None = None
    action_status: str
    payload: dict[str, typing.Any] = pydantic.Field(default_factory=dict)


class RepositoryStatusResponse(pydantic.BaseModel, frozen=True):
    repository_name: str
    repository_url: str
    main_branch: str
    remote_head_commit: str
    remote_head_commit_date: str | None = None
    analysis_target_commit: str
    analysis_target_commit_date: str | None = None
    analysis_status: str
    commit_range_status: str


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
    repositories: list[RepositoryStatusResponse] = pydantic.Field(default_factory=list)
    repository_list_editable: bool = False
    created_at: str
    updated_at: str
    error_message: str | None = None
    terminal_result: dict[str, typing.Any] | None = None


class PreviousInitInputResponse(pydantic.BaseModel, frozen=True):
    product_name: str
    analysis_scope: str
    workspace_dir: str
    arch_repo_dir: str


class ConversationRepositoryResponse(pydantic.BaseModel, frozen=True):
    repository_name: str
    repository_url: str


class ConversationResponse(pydantic.BaseModel, frozen=True):
    conversation_id: str
    product_name: str | None = None
    repositories: list[ConversationRepositoryResponse] = pydantic.Field(default_factory=list)
    workspace_dir: str = ""
    created_at: str
    updated_at: str
    active_response: ResponseStatusResponse | None
    previous_init_input: PreviousInitInputResponse | None = None


class UpdateProductNameRequest(pydantic.BaseModel, frozen=True):
    product_name: str


class SetRepositoriesRequest(pydantic.BaseModel, frozen=True):
    entries: list[str]


class AddRepositoryRequest(pydantic.BaseModel, frozen=True):
    entry: str


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


def _conversation_model(payload: dict[str, typing.Any]) -> ConversationResponse:
    active_response = payload.get("active_response")
    return ConversationResponse(
        conversation_id=payload["conversation_id"],
        product_name=payload.get("product_name"),
        repositories=[
            ConversationRepositoryResponse.model_validate(repository) for repository in payload.get("repositories", [])
        ],
        workspace_dir=payload.get("workspace_dir", ""),
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
        active_response=_response_model(active_response) if isinstance(active_response, dict) else None,
    )


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
        repositories=[
            RepositoryStatusResponse.model_validate(repository) for repository in payload.get("repositories", [])
        ],
        repository_list_editable=bool(payload.get("repository_list_editable", False)),
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
        error_message=payload.get("error_message"),
        terminal_result=payload.get("terminal_result"),
    )


@router.post("/conversations/", status_code=status.HTTP_201_CREATED)
async def create_conversation() -> ConversationResponse:
    payload = await create_conversation_async()
    return ConversationResponse.model_validate(payload)


@router.get("/conversations/")
async def list_conversations(limit: int = 20) -> list[ConversationResponse]:
    payloads = await list_conversations_async(limit=limit)
    return [_conversation_model(payload) for payload in payloads]


@router.get("/conversations/{conversation_id}/")
async def get_conversation(conversation_id: str) -> ConversationResponse:
    try:
        payload = await get_conversation_async(conversation_id)
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc

    return _conversation_model(payload)


@router.patch("/conversations/{conversation_id}/")
async def update_conversation_product_name(
    conversation_id: str, request: UpdateProductNameRequest
) -> ConversationResponse:
    try:
        payload = await update_conversation_product_name_async(conversation_id, request.product_name)
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc
    return _conversation_model(payload)


@router.delete("/conversations/{conversation_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: str) -> fastapi.Response:
    try:
        await delete_conversation_async(conversation_id)
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc
    return fastapi.Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/conversations/{conversation_id}/repositories/")
async def get_conversation_repositories(conversation_id: str) -> list[ConversationRepositoryResponse]:
    try:
        repositories = await get_conversation_repositories_async(conversation_id)
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc
    return [ConversationRepositoryResponse.model_validate(repository) for repository in repositories]


@router.put("/conversations/{conversation_id}/repositories/")
async def set_conversation_repositories(
    conversation_id: str, request: SetRepositoriesRequest
) -> list[ConversationRepositoryResponse]:
    try:
        repositories = await set_conversation_repositories_async(conversation_id, request.entries)
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc
    return [ConversationRepositoryResponse.model_validate(repository) for repository in repositories]


@router.post("/conversations/{conversation_id}/repositories/", status_code=status.HTTP_201_CREATED)
async def add_conversation_repository(
    conversation_id: str, request: AddRepositoryRequest
) -> list[ConversationRepositoryResponse]:
    try:
        repositories = await add_conversation_repository_async(conversation_id, request.entry)
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc
    except WorkflowValidationError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return [ConversationRepositoryResponse.model_validate(repository) for repository in repositories]


@router.delete("/conversations/{conversation_id}/repositories/{repository_name}/")
async def remove_conversation_repository(
    conversation_id: str, repository_name: str
) -> list[ConversationRepositoryResponse]:
    try:
        repositories = await remove_conversation_repository_async(conversation_id, repository_name)
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc
    except WorkflowValidationError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return [ConversationRepositoryResponse.model_validate(repository) for repository in repositories]


@router.get("/conversations/{conversation_id}/responses/")
async def list_conversation_responses(conversation_id: str) -> list[ResponseStatusResponse]:
    try:
        payloads = await list_conversation_responses_async(conversation_id)
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc
    return [_response_model(payload) for payload in payloads]


@router.get("/conversations/{conversation_id}/workspace/tree/")
async def get_conversation_workspace_tree(conversation_id: str) -> DocsTreeNode:
    try:
        tree = await build_conversation_workspace_tree_async(conversation_id)
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc
    return DocsTreeNode.model_validate(tree)


@router.get("/conversations/{conversation_id}/workspace/file/")
async def get_conversation_workspace_file(conversation_id: str, path: str) -> DocsFileResponse:
    try:
        file_payload = await read_conversation_workspace_file_async(conversation_id, path)
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc
    except DocsPathForbiddenError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except DocsFileNotFoundError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return DocsFileResponse.model_validate(file_payload)


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
    except WorkflowConflictError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _response_model(payload)


@router.get("/responses/{response_id}/")
async def get_response(response_id: str) -> ResponseStatusResponse:
    try:
        payload = await get_response_async(response_id)
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc
    return _response_model(payload)


@router.get("/responses/{response_id}/items/")
async def list_response_items(response_id: str) -> ConversationItemsResponse:
    """Timeline for one specific run.

    Unlike `/conversations/{id}/items/` (always scoped to the conversation's most-recently-updated
    run), this stays correct for the run selector on the project page (section 5 of the spec), where
    a user can select an older, non-active run.
    """
    try:
        payload = await get_response_async(response_id)
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc

    items = await list_workflow_events_async(response_id)
    return ConversationItemsResponse(
        conversation_id=payload["conversation_id"],
        items=[ConversationItemResponse.model_validate(item) for item in items],
    )


@router.post("/responses/{response_id}/actions/", status_code=status.HTTP_202_ACCEPTED)
async def submit_response_action(
    response_id: str, request: ResponseActionRequest
) -> ResponseStatusResponse | ConversationResponse:
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

    # `restart` deletes the WorkflowRecord entirely and returns a conversation-shaped payload
    # (active_response: None) instead of a ResponseStatusResponse - see
    # restart_init_arch_workflow() / arch-docs/docs/spec/2026-07-22-realtime-workflow-observability.md §8.
    if "active_response" in payload:
        active_response = payload.get("active_response")
        previous_init_input = payload.get("previous_init_input")
        return ConversationResponse(
            conversation_id=payload["conversation_id"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            active_response=_response_model(active_response) if isinstance(active_response, dict) else None,
            previous_init_input=PreviousInitInputResponse.model_validate(previous_init_input)
            if isinstance(previous_init_input, dict)
            else None,
        )
    return _response_model(payload)
