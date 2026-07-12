async def test_list_openai_models_returns_workflow_models(async_client, auth_headers):
    response = await async_client.get("/v1/models", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "list"
    model_ids = {item["id"] for item in payload["data"]}
    assert {"arch-docs-init_arch", "arch-docs-update_arch", "arch-docs-query"} <= model_ids


async def test_create_openai_response_maps_model_to_backend_response(async_client, auth_headers, monkeypatch):
    captured: dict[str, object] = {}

    async def _fake_create_response_async(
        *, conversation_id: str, workflow_type: str, input_payload: dict[str, object]
    ):
        captured["conversation_id"] = conversation_id
        captured["workflow_type"] = workflow_type
        captured["input_payload"] = input_payload
        return {
            "response_id": "wf-openai-init",
            "conversation_id": conversation_id,
            "workflow_type": workflow_type,
            "response_status": "running",
            "current_step_id": "define_scope",
            "current_repo_name": "",
            "completed_steps": [],
            "required_actions": [],
            "created_at": "2026-07-09T10:00:00+00:00",
            "updated_at": "2026-07-09T10:00:00+00:00",
            "terminal_result": None,
        }

    monkeypatch.setattr("app.api.openai.create_response_async", _fake_create_response_async)

    response = await async_client.post(
        "/v1/responses",
        json={
            "model": "arch-docs-init_arch",
            "input": {
                "product_name": "TestProduct",
                "analysis_scope": "full",
                "workspace_dir": "/workspace/test",
                "arch_repo_dir": "/workspace/test/arch-doc",
                "repo_list": ["repo-a"],
            },
            "metadata": {
                "conversation_id": "conv-openai-init",
                "engine_name": "claude",
                "timeout_seconds": 60,
            },
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "wf-openai-init"
    assert payload["object"] == "response"
    assert payload["model"] == "arch-docs-init_arch"
    assert payload["status"] == "in_progress"
    assert payload["metadata"]["conversation_id"] == "conv-openai-init"
    assert captured == {
        "conversation_id": "conv-openai-init",
        "workflow_type": "init_arch",
        "input_payload": {
            "product_name": "TestProduct",
            "analysis_scope": "full",
            "workspace_dir": "/workspace/test",
            "arch_repo_dir": "/workspace/test/arch-doc",
            "repo_list": ["repo-a"],
            "engine_name": "claude",
            "timeout_seconds": 60,
        },
    }


async def test_chat_completions_returns_query_answer(async_client, auth_headers, monkeypatch):
    async def _fake_create_response_async(
        *, conversation_id: str, workflow_type: str, input_payload: dict[str, object]
    ):
        assert conversation_id == "conv-openai-query"
        assert workflow_type == "query"
        assert input_payload["repo_path"] == "/workspace/repo"
        assert input_payload["question"] == "What does this repo do?"
        return {
            "response_id": "task-openai-query",
            "conversation_id": conversation_id,
            "workflow_type": workflow_type,
            "response_status": "pending",
            "current_step_id": "",
            "current_repo_name": "repo",
            "completed_steps": [],
            "required_actions": [],
            "created_at": "2026-07-09T10:00:00+00:00",
            "updated_at": "2026-07-09T10:00:00+00:00",
            "terminal_result": None,
        }

    async def _fake_wait_for_terminal_response_async(response_id: str, *, timeout_seconds: int):
        assert response_id == "task-openai-query"
        assert timeout_seconds == 45
        return {
            "response_id": response_id,
            "conversation_id": "conv-openai-query",
            "workflow_type": "query",
            "response_status": "success",
            "current_step_id": "",
            "current_repo_name": "repo",
            "completed_steps": [],
            "required_actions": [],
            "created_at": "2026-07-09T10:00:00+00:00",
            "updated_at": "2026-07-09T10:00:01+00:00",
            "terminal_result": {"output_text": "Architecture docs gateway."},
        }

    monkeypatch.setattr("app.api.openai.create_response_async", _fake_create_response_async)
    monkeypatch.setattr("app.api.openai.wait_for_terminal_response_async", _fake_wait_for_terminal_response_async)

    response = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": "arch-docs-query",
            "messages": [{"role": "user", "content": "What does this repo do?"}],
            "metadata": {
                "conversation_id": "conv-openai-query",
                "repo_path": "/workspace/repo",
                "timeout_seconds": 45,
            },
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "chat.completion"
    assert payload["model"] == "arch-docs-query"
    assert payload["choices"][0]["message"]["role"] == "assistant"
    assert payload["choices"][0]["message"]["content"] == "Architecture docs gateway."


async def test_chat_completions_stream_returns_openai_sse(async_client, auth_headers, monkeypatch):
    async def _fake_stream_chat_completion_async(*, model: str, conversation_id: str, question: str, repo_path: str):
        assert model == "arch-docs-query"
        assert conversation_id == "conv-openai-stream"
        assert question == "Summarize the repo"
        assert repo_path == "/workspace/repo"
        yield 'data: {"object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant","content":"hello"},"finish_reason":null}]}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr("app.api.openai.stream_chat_completion_async", _fake_stream_chat_completion_async)

    response = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": "arch-docs-query",
            "stream": True,
            "messages": [{"role": "user", "content": "Summarize the repo"}],
            "metadata": {
                "conversation_id": "conv-openai-stream",
                "repo_path": "/workspace/repo",
            },
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "chat.completion.chunk" in response.text
    assert "[DONE]" in response.text
from unittest.mock import AsyncMock

import fastapi
import pytest

from app.api import openai as openai_module


def test_workflow_type_for_model_rejects_unknown_model():
    with pytest.raises(fastapi.HTTPException) as exc_info:
        openai_module._workflow_type_for_model("unknown")

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Unsupported model: unknown"


def test_conversation_id_from_metadata_generates_value_when_missing(monkeypatch):
    monkeypatch.setattr("app.api.openai.uuid.uuid4", lambda: "abc123")

    assert openai_module._conversation_id_from_metadata({}) == "conv_abc123"
    assert openai_module._conversation_id_from_metadata({"conversation_id": "conv-fixed"}) == "conv-fixed"


def test_response_text_from_terminal_result_prefers_output_then_error():
    assert openai_module._response_text_from_terminal_result(None) is None
    assert openai_module._response_text_from_terminal_result({"output_text": "done"}) == "done"
    assert openai_module._response_text_from_terminal_result({"error_text": "boom"}) == "boom"


def test_extract_user_question_supports_multipart_content():
    messages = [
        openai_module.OpenAIChatMessage(role="assistant", content="old"),
        openai_module.OpenAIChatMessage(
            role="user",
            content=[
                {"type": "text", "text": "What does"},
                {"type": "input_text", "text": " this service do?"},
            ],
        ),
    ]

    assert openai_module._extract_user_question(messages) == "What does\n this service do?"


def test_extract_user_question_validates_missing_or_empty_user_message():
    with pytest.raises(fastapi.HTTPException, match="at least one user message"):
        openai_module._extract_user_question([])

    with pytest.raises(fastapi.HTTPException, match="must not be empty"):
        openai_module._extract_user_question([openai_module.OpenAIChatMessage(role="user", content="   ")])


def test_build_workflow_input_for_query_validates_repo_and_text():
    payload = openai_module._build_workflow_input(
        workflow_type="query",
        request_input=[{"type": "text", "text": " Explain arch-doc "}],
        metadata={"repo_path": "/repo", "engine_name": "codex", "timeout_seconds": 33},
    )

    assert payload == {
        "repo_path": "/repo",
        "question": "Explain arch-doc",
        "engine_name": "codex",
        "timeout_seconds": 33,
    }

    with pytest.raises(fastapi.HTTPException, match="requires metadata.repo_path"):
        openai_module._build_workflow_input(
            workflow_type="query",
            request_input="question",
            metadata={},
        )

    with pytest.raises(fastapi.HTTPException, match="requires textual input"):
        openai_module._build_workflow_input(
            workflow_type="query",
            request_input=[],
            metadata={"repo_path": "/repo"},
        )


def test_build_workflow_input_for_non_query_requires_object():
    payload = openai_module._build_workflow_input(
        workflow_type="init_arch",
        request_input={"product_name": "svc"},
        metadata={"timeout_seconds": 90},
    )

    assert payload == {"product_name": "svc", "timeout_seconds": 90}

    with pytest.raises(fastapi.HTTPException, match="init_arch facade requires object input"):
        openai_module._build_workflow_input(
            workflow_type="init_arch",
            request_input="bad",
            metadata={},
        )


def test_build_openai_response_payload_maps_required_actions_and_errors():
    response_payload = {
        "response_id": "wf-1",
        "conversation_id": "conv-1",
        "workflow_type": "init_arch",
        "response_status": "interrupted",
        "current_step_id": "interview_user",
        "required_actions": [{"action_type": "user_question", "question_id": "Q-1", "action_status": "open"}],
        "created_at": "2026-07-09T10:00:00+00:00",
        "error_message": "Need more details",
        "terminal_result": {"error_text": "Need more details"},
    }

    payload = openai_module._build_openai_response_payload(response_payload, model="arch-docs-init_arch")

    assert payload["status"] == "requires_action"
    assert payload["required_action"]["actions"][0]["question_id"] == "Q-1"
    assert payload["output"][0]["content"][0]["text"] == "Need more details"


def test_build_chat_completion_payload_uses_empty_output_when_terminal_result_missing():
    payload = openai_module._build_chat_completion_payload(
        {
            "response_id": "resp-1",
            "created_at": "2026-07-09T10:00:00+00:00",
            "terminal_result": None,
        },
        model="arch-docs-query",
    )

    assert payload["choices"][0]["message"]["content"] == ""


async def test_wait_for_terminal_response_times_out(monkeypatch):
    monkeypatch.setattr(
        "app.api.openai.get_response_async",
        AsyncMock(return_value={"response_status": "running"}),
    )
    monkeypatch.setattr("app.api.openai.asyncio.sleep", AsyncMock())

    with pytest.raises(fastapi.HTTPException, match="Timed out waiting for response resp-1"):
        await openai_module.wait_for_terminal_response_async("resp-1", timeout_seconds=0)


async def test_stream_openai_response_async_emits_final_chunk_for_interrupted_event(monkeypatch):
    async def _fake_stream(_response_id: str):
        yield 'data: {"event_type":"interrupted","question":"Need details"}\n\n'

    monkeypatch.setattr("app.api.openai.stream_response_events_async", _fake_stream)
    monkeypatch.setattr(
        "app.api.openai.get_response_async",
        AsyncMock(
            return_value={
                "response_id": "wf-2",
                "conversation_id": "conv-2",
                "workflow_type": "init_arch",
                "response_status": "interrupted",
                "current_step_id": "interview_user",
                "required_actions": [],
                "created_at": "2026-07-09T10:00:00+00:00",
                "error_message": None,
                "terminal_result": None,
            }
        ),
    )

    chunks = [
        chunk
        async for chunk in openai_module.stream_openai_response_async(
            model="arch-docs-init_arch",
            response_payload={
                "response_id": "wf-2",
                "conversation_id": "conv-2",
                "workflow_type": "init_arch",
                "response_status": "running",
                "current_step_id": "define_scope",
                "required_actions": [],
                "created_at": "2026-07-09T10:00:00+00:00",
                "terminal_result": None,
            },
        )
    ]

    assert any('"type": "response.created"' in chunk for chunk in chunks)
    assert any('"type": "response.requires_action"' in chunk for chunk in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"


async def test_stream_chat_completion_async_raises_on_failed_terminal_event(monkeypatch):
    async def _fake_create_response_async(**_kwargs):
        return {
            "response_id": "task-1",
            "created_at": "2026-07-09T10:00:00+00:00",
        }

    async def _fake_stream(_response_id: str):
        yield 'data: {"event_type":"workflow_failed","event_data":"boom"}\n\n'

    monkeypatch.setattr("app.api.openai.create_response_async", _fake_create_response_async)
    monkeypatch.setattr("app.api.openai.stream_response_events_async", _fake_stream)
    monkeypatch.setattr(
        "app.api.openai.get_response_async",
        AsyncMock(return_value={"error_message": "worker failed"}),
    )

    with pytest.raises(fastapi.HTTPException, match="worker failed"):
        [chunk async for chunk in openai_module.stream_chat_completion_async(
            model="arch-docs-query",
            conversation_id="conv-1",
            question="What is this?",
            repo_path="/repo",
        )]


async def test_create_openai_response_stream_returns_event_stream(async_client, auth_headers, monkeypatch):
    async def _fake_create_response_async(**_kwargs):
        return {
            "response_id": "wf-stream-1",
            "conversation_id": "conv-stream-1",
            "workflow_type": "init_arch",
            "response_status": "running",
            "current_step_id": "define_scope",
            "required_actions": [],
            "created_at": "2026-07-09T10:00:00+00:00",
            "updated_at": "2026-07-09T10:00:00+00:00",
            "terminal_result": None,
        }

    monkeypatch.setattr("app.api.openai.create_response_async", _fake_create_response_async)
    monkeypatch.setattr(
        "app.api.openai.stream_openai_response_async",
        lambda **_kwargs: _fake_stream(),
    )

    async def _fake_stream():
        yield 'data: {"type":"response.created"}\n\n'
        yield "data: [DONE]\n\n"

    response = await async_client.post(
        "/v1/responses",
        json={
            "model": "arch-docs-init_arch",
            "stream": True,
            "input": {"product_name": "svc"},
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "response.created" in response.text


async def test_get_openai_response_returns_404_when_backend_response_missing(async_client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        "app.api.openai.get_response_async",
        AsyncMock(side_effect=openai_module.WorkflowNotFoundError("missing response")),
    )

    response = await async_client.get("/v1/responses/missing?model=arch-docs-query", headers=auth_headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "missing response"


async def test_chat_completions_rejects_non_query_model(async_client, auth_headers):
    response = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": "arch-docs-init_arch",
            "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"repo_path": "/repo"},
        },
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert "supports only the arch-docs-query model" in response.json()["detail"]


async def test_submit_openai_response_action_confirms_temporal_window(async_client, auth_headers, monkeypatch):
    captured: dict[str, object] = {}

    async def _fake_submit_response_action_async(response_id: str, **kwargs):
        captured["response_id"] = response_id
        captured.update(kwargs)
        return {
            "response_id": response_id,
            "conversation_id": "conv-window",
            "workflow_type": "init_arch",
            "response_status": "running",
            "current_step_id": "refresh_main_branches",
            "current_repo_name": "",
            "completed_steps": [],
            "required_actions": [],
            "created_at": "2026-07-09T10:00:00+00:00",
            "updated_at": "2026-07-09T10:00:00+00:00",
            "terminal_result": None,
        }

    monkeypatch.setattr("app.api.openai.submit_response_action_async", _fake_submit_response_action_async)

    response = await async_client.post(
        "/v1/responses/wf-window/actions?model=arch-docs-init_arch",
        json={"action_type": "confirm_temporal_window", "value": "continue_to_next_window"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert captured["response_id"] == "wf-window"
    assert captured["action_type"] == "confirm_temporal_window"
    assert captured["value"] == "continue_to_next_window"
    assert response.json()["metadata"]["current_step_id"] == "refresh_main_branches"


async def test_submit_openai_response_action_returns_404_when_response_missing(async_client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        "app.api.openai.submit_response_action_async",
        AsyncMock(side_effect=openai_module.WorkflowNotFoundError("missing response")),
    )

    response = await async_client.post(
        "/v1/responses/missing/actions?model=arch-docs-query",
        json={"action_type": "cancel"},
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "missing response"


async def test_submit_openai_response_action_returns_422_on_validation_error(async_client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        "app.api.openai.submit_response_action_async",
        AsyncMock(side_effect=openai_module.WorkflowValidationError("confirm_temporal_window requires a value")),
    )

    response = await async_client.post(
        "/v1/responses/wf-bad/actions?model=arch-docs-init_arch",
        json={"action_type": "confirm_temporal_window"},
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "confirm_temporal_window requires a value"
