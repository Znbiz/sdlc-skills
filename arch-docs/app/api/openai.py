from __future__ import annotations

import asyncio
import datetime
import json
import typing
import uuid

import fastapi
import pydantic
from fastapi import status
from fastapi.responses import StreamingResponse

from app.services.init_arch_workflow import (
    WorkflowNotFoundError,
    WorkflowValidationError,
    create_response_async,
    get_response_async,
    stream_response_events_async,
)

router = fastapi.APIRouter()

_MODEL_TO_WORKFLOW_TYPE: typing.Final[dict[str, str]] = {
    "arch-docs-init_arch": "init_arch",
    "arch-docs-update_arch": "update_arch",
    "arch-docs-query": "query",
}
_TERMINAL_RESPONSE_STATUSES: typing.Final[frozenset[str]] = frozenset({"success", "failed", "cancelled", "interrupted"})
_OPENAI_STATUS_BY_RESPONSE_STATUS: typing.Final[dict[str, str]] = {
    "pending": "queued",
    "running": "in_progress",
    "interrupted": "requires_action",
    "success": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
}


class OpenAIResponsesRequest(pydantic.BaseModel, frozen=True):
    model: str
    input: typing.Any = None
    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    stream: bool = False


class OpenAIChatMessage(pydantic.BaseModel, frozen=True):
    role: str
    content: str | list[dict[str, typing.Any]]


class OpenAIChatCompletionsRequest(pydantic.BaseModel, frozen=True):
    model: str
    messages: list[OpenAIChatMessage]
    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    stream: bool = False


def _raise_validation_error(message: str) -> typing.NoReturn:
    raise fastapi.HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=message)


def _created_timestamp(iso_value: str) -> int:
    return int(datetime.datetime.fromisoformat(iso_value).timestamp())


def _workflow_type_for_model(model: str) -> str:
    workflow_type = _MODEL_TO_WORKFLOW_TYPE.get(model)
    if workflow_type is None:
        _raise_validation_error(f"Unsupported model: {model}")
    return workflow_type


def _conversation_id_from_metadata(metadata: dict[str, typing.Any]) -> str:
    raw_conversation_id = metadata.get("conversation_id")
    if isinstance(raw_conversation_id, str) and raw_conversation_id:
        return raw_conversation_id
    return f"conv_{uuid.uuid4()}"


def _response_text_from_terminal_result(terminal_result: dict[str, typing.Any] | None) -> str | None:
    if terminal_result is None:
        return None
    output_text = terminal_result.get("output_text")
    if isinstance(output_text, str) and output_text:
        return output_text
    error_text = terminal_result.get("error_text")
    if isinstance(error_text, str) and error_text:
        return error_text
    return None


def _extract_text_content(content: str | list[dict[str, typing.Any]]) -> str:
    if isinstance(content, str):
        return content

    text_chunks = [
        item["text"]
        for item in content
        if item.get("type") in {"text", "input_text"} and isinstance(item.get("text"), str)
    ]
    return "\n".join(text_chunks)


def _extract_user_question(messages: list[OpenAIChatMessage]) -> str:
    user_messages = [message for message in messages if message.role == "user"]
    if not user_messages:
        _raise_validation_error("chat.completions requires at least one user message")

    question = _extract_text_content(user_messages[-1].content).strip()
    if not question:
        _raise_validation_error("chat.completions user message content must not be empty")
    return question


def _build_workflow_input(
    *,
    workflow_type: str,
    request_input: typing.Any,
    metadata: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    if workflow_type == "query":
        question = request_input if isinstance(request_input, str) else _extract_text_content(request_input or "")
        repo_path = metadata.get("repo_path")
        if not isinstance(repo_path, str) or not repo_path:
            _raise_validation_error("query facade requires metadata.repo_path")
        if not isinstance(question, str) or not question.strip():
            _raise_validation_error("query facade requires textual input")
        input_payload: dict[str, typing.Any] = {
            "repo_path": repo_path,
            "question": question.strip(),
        }
    elif isinstance(request_input, dict):
        input_payload = dict(request_input)
    else:
        _raise_validation_error(f"{workflow_type} facade requires object input")

    for field_name in ("engine_name", "timeout_seconds"):
        if field_name in metadata and field_name not in input_payload:
            input_payload[field_name] = metadata[field_name]
    return input_payload


def _build_openai_response_payload(response_payload: dict[str, typing.Any], *, model: str) -> dict[str, typing.Any]:
    response_status = str(response_payload["response_status"])
    terminal_result = response_payload.get("terminal_result")
    output_text = _response_text_from_terminal_result(terminal_result if isinstance(terminal_result, dict) else None)
    output_items: list[dict[str, typing.Any]] = []
    if output_text is not None:
        output_items.append(
            {
                "id": f"msg_{response_payload['response_id']}",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": output_text, "annotations": []}],
            }
        )

    payload: dict[str, typing.Any] = {
        "id": response_payload["response_id"],
        "object": "response",
        "created": _created_timestamp(response_payload["created_at"]),
        "model": model,
        "status": _OPENAI_STATUS_BY_RESPONSE_STATUS.get(response_status, response_status),
        "output": output_items,
        "metadata": {
            "conversation_id": response_payload["conversation_id"],
            "workflow_type": response_payload["workflow_type"],
            "backend_response_id": response_payload["response_id"],
            "current_step_id": response_payload["current_step_id"],
        },
    }
    required_actions = response_payload.get("required_actions")
    if isinstance(required_actions, list) and required_actions:
        payload["required_action"] = {"type": "user_input", "actions": required_actions}
    if output_text is None and response_payload.get("error_message"):
        payload["error"] = {"message": response_payload["error_message"], "type": "workflow_error"}
    return payload


def _build_chat_completion_payload(response_payload: dict[str, typing.Any], *, model: str) -> dict[str, typing.Any]:
    output_text = _response_text_from_terminal_result(response_payload.get("terminal_result"))
    if output_text is None:
        output_text = ""

    return {
        "id": response_payload["response_id"],
        "object": "chat.completion",
        "created": _created_timestamp(response_payload["created_at"]),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": output_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


async def wait_for_terminal_response_async(response_id: str, *, timeout_seconds: int) -> dict[str, typing.Any]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        response_payload = await get_response_async(response_id)
        if str(response_payload["response_status"]) in _TERMINAL_RESPONSE_STATUSES:
            return response_payload
        if asyncio.get_running_loop().time() >= deadline:
            raise fastapi.HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Timed out waiting for response {response_id}",
            )
        await asyncio.sleep(0.2)


def _openai_sse(payload: dict[str, typing.Any] | str) -> str:
    if isinstance(payload, str):
        return f"data: {payload}\n\n"
    return f"data: {json.dumps(payload)}\n\n"


def _terminal_event_type(openai_status: str) -> str:
    if openai_status == "failed":
        return "response.failed"
    if openai_status == "cancelled":
        return "response.cancelled"
    if openai_status == "requires_action":
        return "response.requires_action"
    return "response.completed"


def _final_response_chunk(*, model: str, response_payload: dict[str, typing.Any]) -> str:
    mapped_response = _build_openai_response_payload(response_payload, model=model)
    return _openai_sse({"type": _terminal_event_type(mapped_response["status"]), "response": mapped_response})


def _response_delta_chunk(*, response_id: str, event_payload: dict[str, typing.Any]) -> str | None:
    event_type = str(event_payload.get("event_type", "event"))
    event_data = event_payload.get("event_data")
    if event_type not in {"output", "progress", "cli_output"} or not isinstance(event_data, str):
        return None
    return _openai_sse(
        {
            "type": "response.output_text.delta",
            "response_id": response_id,
            "delta": event_data,
        }
    )


async def stream_openai_response_async(
    *,
    model: str,
    response_payload: dict[str, typing.Any],
) -> typing.AsyncGenerator[str, None]:
    openai_response = _build_openai_response_payload(response_payload, model=model)
    yield _openai_sse({"type": "response.created", "response": openai_response})

    if openai_response["status"] in {"completed", "failed", "cancelled", "requires_action"}:
        yield _openai_sse({"type": _terminal_event_type(openai_response["status"]), "response": openai_response})
        yield _openai_sse("[DONE]")
        return

    async for chunk in stream_response_events_async(response_payload["response_id"]):
        if not chunk.startswith("data: "):
            continue
        raw_payload = chunk.removeprefix("data: ").strip()
        if not raw_payload:
            continue
        event_payload = json.loads(raw_payload)
        event_type = str(event_payload.get("event_type", "event"))
        delta_chunk = _response_delta_chunk(response_id=response_payload["response_id"], event_payload=event_payload)
        if delta_chunk is not None:
            yield delta_chunk
            continue

        if event_type == "interrupted":
            final_response = await get_response_async(response_payload["response_id"])
            yield _final_response_chunk(model=model, response_payload=final_response)
            yield _openai_sse("[DONE]")
            return

        if event_type in {"done", "workflow_done", "workflow_failed", "workflow_cancelled"}:
            final_response = await get_response_async(response_payload["response_id"])
            yield _final_response_chunk(model=model, response_payload=final_response)
            yield _openai_sse("[DONE]")
            return


async def stream_chat_completion_async(
    *,
    model: str,
    conversation_id: str,
    question: str,
    repo_path: str,
) -> typing.AsyncGenerator[str, None]:
    response_payload = await create_response_async(
        conversation_id=conversation_id,
        workflow_type="query",
        input_payload={"repo_path": repo_path, "question": question},
    )
    created = _created_timestamp(response_payload["created_at"])
    response_id = response_payload["response_id"]

    async for chunk in stream_response_events_async(response_id):
        if not chunk.startswith("data: "):
            continue
        raw_payload = chunk.removeprefix("data: ").strip()
        if not raw_payload:
            continue
        event_payload = json.loads(raw_payload)
        event_type = str(event_payload.get("event_type", "event"))
        event_data = event_payload.get("event_data")
        if event_type in {"output", "progress", "cli_output"} and isinstance(event_data, str):
            yield _openai_sse(
                {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": event_data},
                            "finish_reason": None,
                        }
                    ],
                }
            )
            continue

        if event_type in {"done", "workflow_done"}:
            yield _openai_sse(
                {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
            )
            yield _openai_sse("[DONE]")
            return

        if event_type in {"workflow_failed", "workflow_cancelled", "interrupted"}:
            final_response = await get_response_async(response_id)
            error_text = final_response.get("error_message") or (
                "OpenAI chat facade received a non-terminal query response"
            )
            raise fastapi.HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=error_text)


@router.get("/v1/models")
async def list_models() -> dict[str, typing.Any]:
    created = int(datetime.datetime(2026, 7, 9, tzinfo=datetime.timezone.utc).timestamp())
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "created": created,
                "owned_by": "arch-docs",
                "metadata": {"workflow_type": workflow_type, "transport": "openai_compat"},
            }
            for model_id, workflow_type in _MODEL_TO_WORKFLOW_TYPE.items()
        ],
    }


@router.post("/v1/responses")
async def create_openai_response(request: OpenAIResponsesRequest) -> typing.Any:
    workflow_type = _workflow_type_for_model(request.model)
    conversation_id = _conversation_id_from_metadata(request.metadata)
    input_payload = _build_workflow_input(
        workflow_type=workflow_type,
        request_input=request.input,
        metadata=request.metadata,
    )
    try:
        response_payload = await create_response_async(
            conversation_id=conversation_id,
            workflow_type=workflow_type,
            input_payload=input_payload,
        )
    except WorkflowValidationError as exc:
        _raise_validation_error(str(exc))

    if request.stream:
        return StreamingResponse(
            stream_openai_response_async(model=request.model, response_payload=response_payload),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return _build_openai_response_payload(response_payload, model=request.model)


@router.get("/v1/responses/{response_id}")
async def get_openai_response(response_id: str, model: str) -> dict[str, typing.Any]:
    try:
        response_payload = await get_response_async(response_id)
    except WorkflowNotFoundError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _build_openai_response_payload(response_payload, model=model)


@router.post("/v1/chat/completions")
async def create_chat_completion(request: OpenAIChatCompletionsRequest) -> typing.Any:
    workflow_type = _workflow_type_for_model(request.model)
    if workflow_type != "query":
        _raise_validation_error("chat.completions currently supports only the arch-docs-query model")

    conversation_id = _conversation_id_from_metadata(request.metadata)
    repo_path = request.metadata.get("repo_path")
    if not isinstance(repo_path, str) or not repo_path:
        _raise_validation_error("chat.completions requires metadata.repo_path")

    question = _extract_user_question(request.messages)
    if request.stream:
        return StreamingResponse(
            stream_chat_completion_async(
                model=request.model,
                conversation_id=conversation_id,
                question=question,
                repo_path=repo_path,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    try:
        response_payload = await create_response_async(
            conversation_id=conversation_id,
            workflow_type="query",
            input_payload={
                "repo_path": repo_path,
                "question": question,
                "engine_name": request.metadata.get("engine_name", "claude"),
                "timeout_seconds": request.metadata.get("timeout_seconds", 120),
            },
        )
        final_response = await wait_for_terminal_response_async(
            response_payload["response_id"],
            timeout_seconds=int(request.metadata.get("timeout_seconds", 120)),
        )
    except WorkflowValidationError as exc:
        _raise_validation_error(str(exc))
    return _build_chat_completion_payload(final_response, model=request.model)
