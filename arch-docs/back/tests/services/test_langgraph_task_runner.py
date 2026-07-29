import asyncio
import unittest.mock
import uuid

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage

from app.services.agent_pool import AgentPool
from app.services.langgraph_task_runner import (
    _LiveEventCallbackHandler,
    run_langgraph_task,
)
from app.services.llm_providers import LlmProviderConnectionDetail, LlmProviderConnectionNotFoundError
from app.services.task_registry import CliTask, TaskStatus
from app.services.workflow_event_bus import get_workflow_event_bus, reset_workflow_event_bus

_UNSET_CONNECTION_ID = object()


def _make_task(  # noqa: PLR0913
    *,
    provider_connection_id: str | None = _UNSET_CONNECTION_ID,  # type: ignore[assignment]
    workspace_dir: str = "/workspace",
    extra_allowed_roots: list[str] | None = None,
    timeout_seconds: int = 30,
    task_status: TaskStatus = TaskStatus.PENDING,
    workflow_id: str | None = None,
) -> CliTask:
    if provider_connection_id is _UNSET_CONNECTION_ID:
        provider_connection_id = str(uuid.uuid4())
    return CliTask(
        task_id=str(uuid.uuid4()),
        engine_name="langgraph",
        provider_connection_id=provider_connection_id,
        prompt_text="do the thing",
        workspace_dir=workspace_dir,
        extra_allowed_roots=extra_allowed_roots or [],
        timeout_seconds=timeout_seconds,
        task_status=task_status,
        workflow_id=workflow_id,
    )


def _make_pool() -> AgentPool:
    return AgentPool(pool_size=2)


def _make_connection(*, wire_api: str = "chat") -> LlmProviderConnectionDetail:
    return LlmProviderConnectionDetail(
        connection_id=uuid.uuid4(),
        name="test-connection",
        base_url="https://example.invalid/v1",
        model="test-model",
        wire_api=wire_api,
        requires_openai_auth=False,
        token="secret-token",
    )


def _make_fake_agent(final_message: AIMessage) -> unittest.mock.MagicMock:
    fake_agent = unittest.mock.MagicMock()
    fake_agent.ainvoke = unittest.mock.AsyncMock(return_value={"messages": [final_message]})
    return fake_agent


@pytest.fixture(autouse=True)
def _clean_workflow_event_bus():
    reset_workflow_event_bus()
    yield
    reset_workflow_event_bus()


class TestRunLanggraphTaskSuccess:
    async def test_success_sets_result_status_usage_and_model(self) -> None:
        cli_task = _make_task()
        connection = _make_connection()
        final_message = AIMessage(
            content='{"notes": "done"}',
            usage_metadata={"input_tokens": 42, "output_tokens": 7, "total_tokens": 49},
        )

        with (
            unittest.mock.patch(
                "app.services.cli_task_support.get_llm_provider_connection_async",
                new=unittest.mock.AsyncMock(return_value=connection),
            ),
            unittest.mock.patch(
                "app.services.langgraph_task_runner.create_agent",
                return_value=_make_fake_agent(final_message),
            ),
        ):
            await run_langgraph_task(cli_task, _make_pool())

        assert cli_task.task_status == TaskStatus.SUCCESS
        assert cli_task.task_result == '{"notes": "done"}'
        assert cli_task.input_tokens == 42
        assert cli_task.output_tokens == 7
        assert cli_task.model_name == "test-model"
        assert cli_task.started_at is not None
        assert cli_task.finished_at is not None

    async def test_allowed_roots_include_workspace_and_extra_roots(self) -> None:
        cli_task = _make_task(workspace_dir="/workspace", extra_allowed_roots=["/arch-repo"])
        connection = _make_connection()
        final_message = AIMessage(content="done")
        captured_tools_call: dict = {}

        def _fake_build_agent_tools(allowed_roots, **_kwargs):
            captured_tools_call["allowed_roots"] = allowed_roots
            return []

        with (
            unittest.mock.patch(
                "app.services.cli_task_support.get_llm_provider_connection_async",
                new=unittest.mock.AsyncMock(return_value=connection),
            ),
            unittest.mock.patch(
                "app.services.langgraph_task_runner.build_agent_tools", side_effect=_fake_build_agent_tools
            ),
            unittest.mock.patch(
                "app.services.langgraph_task_runner.create_agent",
                return_value=_make_fake_agent(final_message),
            ),
        ):
            await run_langgraph_task(cli_task, _make_pool())

        assert captured_tools_call["allowed_roots"] == ["/workspace", "/arch-repo"]

    async def test_recursion_limit_and_prompt_are_passed_to_ainvoke(self) -> None:
        cli_task = _make_task()
        connection = _make_connection()
        fake_agent = _make_fake_agent(AIMessage(content="done"))

        with (
            unittest.mock.patch(
                "app.services.cli_task_support.get_llm_provider_connection_async",
                new=unittest.mock.AsyncMock(return_value=connection),
            ),
            unittest.mock.patch("app.services.langgraph_task_runner.create_agent", return_value=fake_agent),
        ):
            await run_langgraph_task(cli_task, _make_pool())

        call_args, call_kwargs = fake_agent.ainvoke.call_args
        assert call_args[0]["messages"][0]["content"] == "do the thing"
        assert call_kwargs["config"]["recursion_limit"] == 100

    async def test_always_uses_chat_completions_regardless_of_wire_api(self) -> None:
        # Real-world finding (e2e against the actual "GLM 5.2" gateway): `use_responses_api=True`
        # crashes inside langchain_openai's own response parsing for this gateway (it leaves
        # usage.input_tokens/output_tokens unset under Responses API), while Chat Completions
        # against the same gateway/model works correctly. `wire_api` reflects what *codex* needs,
        # not what LangGraph should use - see `_build_model`'s docstring/comment.
        cli_task = _make_task()
        connection = _make_connection(wire_api="responses")
        fake_agent = _make_fake_agent(AIMessage(content="done"))
        captured_model_kwargs: dict = {}

        def _fake_chat_openai(**kwargs):
            captured_model_kwargs.update(kwargs)
            return unittest.mock.MagicMock()

        with (
            unittest.mock.patch(
                "app.services.cli_task_support.get_llm_provider_connection_async",
                new=unittest.mock.AsyncMock(return_value=connection),
            ),
            unittest.mock.patch("app.services.langgraph_task_runner.ChatOpenAI", side_effect=_fake_chat_openai),
            unittest.mock.patch("app.services.langgraph_task_runner.create_agent", return_value=fake_agent),
        ):
            await run_langgraph_task(cli_task, _make_pool())

        assert captured_model_kwargs["use_responses_api"] is False
        assert captured_model_kwargs["base_url"] == connection.base_url
        assert captured_model_kwargs["api_key"] == connection.token
        assert captured_model_kwargs["model"] == connection.model


class TestRunLanggraphTaskProviderConnection:
    async def test_missing_provider_connection_id_fails_without_calling_agent(self) -> None:
        cli_task = _make_task(provider_connection_id=None)

        with unittest.mock.patch("app.services.langgraph_task_runner.create_agent") as mock_create_agent:
            await run_langgraph_task(cli_task, _make_pool())

        mock_create_agent.assert_not_called()
        assert cli_task.task_status == TaskStatus.FAILED
        assert "provider_connection_id is required" in cli_task.task_error

    async def test_connection_not_found_fails_with_connection_id_in_message(self) -> None:
        missing_connection_id = str(uuid.uuid4())
        cli_task = _make_task(provider_connection_id=missing_connection_id)

        with unittest.mock.patch(
            "app.services.cli_task_support.get_llm_provider_connection_async",
            new=unittest.mock.AsyncMock(side_effect=LlmProviderConnectionNotFoundError(missing_connection_id)),
        ):
            await run_langgraph_task(cli_task, _make_pool())

        assert cli_task.task_status == TaskStatus.FAILED
        assert missing_connection_id in cli_task.task_error

    async def test_cancelled_pending_task_is_skipped(self) -> None:
        cli_task = _make_task(task_status=TaskStatus.CANCELLED)

        with unittest.mock.patch("app.services.langgraph_task_runner.create_agent") as mock_create_agent:
            await run_langgraph_task(cli_task, _make_pool())

        mock_create_agent.assert_not_called()
        assert cli_task.task_status == TaskStatus.CANCELLED


class TestRunLanggraphTaskErrors:
    async def test_timeout_marks_failed_and_cancels_invoke_task(self) -> None:
        cli_task = _make_task(timeout_seconds=0)
        connection = _make_connection()

        async def _hang(*_args, **_kwargs):
            await asyncio.sleep(10)
            return {"messages": [AIMessage(content="too late")]}

        fake_agent = unittest.mock.MagicMock()
        fake_agent.ainvoke = _hang

        with (
            unittest.mock.patch(
                "app.services.cli_task_support.get_llm_provider_connection_async",
                new=unittest.mock.AsyncMock(return_value=connection),
            ),
            unittest.mock.patch("app.services.langgraph_task_runner.create_agent", return_value=fake_agent),
        ):
            await run_langgraph_task(cli_task, _make_pool())

        assert cli_task.task_status == TaskStatus.FAILED
        assert cli_task.task_error == "Timeout exceeded"
        assert cli_task.async_task_handle.cancelled()

    async def test_authentication_error_is_mapped_to_auth_expired(self) -> None:
        cli_task = _make_task()
        connection = _make_connection()
        response = httpx.Response(status_code=401, request=httpx.Request("POST", "https://example.invalid"))
        fake_agent = unittest.mock.MagicMock()
        fake_agent.ainvoke = unittest.mock.AsyncMock(
            side_effect=openai.AuthenticationError("bad key", response=response, body=None)
        )

        with (
            unittest.mock.patch(
                "app.services.cli_task_support.get_llm_provider_connection_async",
                new=unittest.mock.AsyncMock(return_value=connection),
            ),
            unittest.mock.patch("app.services.langgraph_task_runner.create_agent", return_value=fake_agent),
        ):
            await run_langgraph_task(cli_task, _make_pool())

        assert cli_task.task_status == TaskStatus.FAILED
        assert cli_task.task_error.startswith("auth_expired:")

    async def test_rate_limit_error_is_mapped_to_limit_exhausted(self) -> None:
        cli_task = _make_task()
        connection = _make_connection()
        response = httpx.Response(status_code=429, request=httpx.Request("POST", "https://example.invalid"))
        fake_agent = unittest.mock.MagicMock()
        fake_agent.ainvoke = unittest.mock.AsyncMock(
            side_effect=openai.RateLimitError("too many requests", response=response, body=None)
        )

        with (
            unittest.mock.patch(
                "app.services.cli_task_support.get_llm_provider_connection_async",
                new=unittest.mock.AsyncMock(return_value=connection),
            ),
            unittest.mock.patch("app.services.langgraph_task_runner.create_agent", return_value=fake_agent),
        ):
            await run_langgraph_task(cli_task, _make_pool())

        assert cli_task.task_status == TaskStatus.FAILED
        assert cli_task.task_error.startswith("limit_exhausted:")

    async def test_unexpected_error_marks_failed_with_message(self) -> None:
        cli_task = _make_task()
        connection = _make_connection()
        fake_agent = unittest.mock.MagicMock()
        fake_agent.ainvoke = unittest.mock.AsyncMock(side_effect=RuntimeError("boom"))

        with (
            unittest.mock.patch(
                "app.services.cli_task_support.get_llm_provider_connection_async",
                new=unittest.mock.AsyncMock(return_value=connection),
            ),
            unittest.mock.patch("app.services.langgraph_task_runner.create_agent", return_value=fake_agent),
        ):
            await run_langgraph_task(cli_task, _make_pool())

        assert cli_task.task_status == TaskStatus.FAILED
        assert cli_task.task_error == "boom"

    async def test_outer_cancellation_propagates_and_cancels_child_task(self) -> None:
        cli_task = _make_task(timeout_seconds=30)
        connection = _make_connection()

        async def _hang(*_args, **_kwargs):
            await asyncio.sleep(10)
            return {"messages": [AIMessage(content="too late")]}

        fake_agent = unittest.mock.MagicMock()
        fake_agent.ainvoke = _hang

        with (
            unittest.mock.patch(
                "app.services.cli_task_support.get_llm_provider_connection_async",
                new=unittest.mock.AsyncMock(return_value=connection),
            ),
            unittest.mock.patch("app.services.langgraph_task_runner.create_agent", return_value=fake_agent),
        ):
            outer_task = asyncio.create_task(run_langgraph_task(cli_task, _make_pool()))
            await asyncio.sleep(0.05)
            outer_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await outer_task

        assert cli_task.async_task_handle.cancelled()
        # Cancellation is not translated into FAILED/CANCELLED by run_langgraph_task itself - the
        # caller (cancel_cli_task or the workflow pause machinery) owns that decision. See spec
        # section 7, "Пробел №2".
        assert cli_task.task_status == TaskStatus.RUNNING
        assert cli_task.finished_at is not None


class TestLiveEventCallbackHandler:
    async def test_on_tool_start_emits_llm_tool_call_event_and_trace_line(self) -> None:
        cli_task = _make_task(workflow_id="wf-1")
        cli_task.step_id = "define_scope"
        subscription = get_workflow_event_bus().subscribe("wf-1")
        handler = _LiveEventCallbackHandler(cli_task)

        await handler.on_tool_start({"name": "read_file"}, "{'path': 'a.txt'}", run_id=uuid.uuid4())

        assert any("[tool] read_file" in line for line in cli_task.stdout_lines)
        event = subscription.get_nowait()
        assert event["event_type"] == "llm_tool_call"
        assert event["tool_name"] == "read_file"

    async def test_on_llm_end_emits_llm_message_event_for_text_content(self) -> None:
        cli_task = _make_task(workflow_id="wf-2")
        cli_task.step_id = "define_scope"
        subscription = get_workflow_event_bus().subscribe("wf-2")
        handler = _LiveEventCallbackHandler(cli_task)

        generation = unittest.mock.MagicMock()
        generation.message = AIMessage(content="hello from the model")
        response = unittest.mock.MagicMock()
        response.generations = [[generation]]

        await handler.on_llm_end(response, run_id=uuid.uuid4())

        assert any("[assistant] hello from the model" in line for line in cli_task.stdout_lines)
        event = subscription.get_nowait()
        assert event["event_type"] == "llm_message"
        assert event["text"] == "hello from the model"

    async def test_on_llm_end_skips_empty_content(self) -> None:
        cli_task = _make_task(workflow_id="wf-3")
        handler = _LiveEventCallbackHandler(cli_task)

        generation = unittest.mock.MagicMock()
        generation.message = AIMessage(content="")
        response = unittest.mock.MagicMock()
        response.generations = [[generation]]

        await handler.on_llm_end(response, run_id=uuid.uuid4())

        assert cli_task.stdout_lines == []

    async def test_events_without_workflow_id_still_append_trace_line(self) -> None:
        cli_task = _make_task(workflow_id=None)
        handler = _LiveEventCallbackHandler(cli_task)

        await handler.on_tool_start({"name": "run_shell"}, "ls", run_id=uuid.uuid4())

        assert any("[tool] run_shell" in line for line in cli_task.stdout_lines)
