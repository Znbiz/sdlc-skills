from __future__ import annotations

import asyncio
import datetime
import json
import pathlib
import typing
import uuid

import structlog

from app.db.session import get_session
from app.db.task_repo import get_cli_task, list_cli_tasks_for_conversation
from app.db.workflow_repo import (
    create_conversation,
    get_conversation,
    get_workflow_run,
    list_conversation_items,
    list_required_actions,
    list_workflow_runs_for_conversation,
    upsert_workflow_run,
)
from app.services.agent_pool import get_agent_pool
from app.services.task_registry import CliTask, TaskStatus
from app.services.task_registry import get_registry as get_task_registry
from app.services.task_runner import cancel_cli_task, run_cli_task
from app.services.workflow_registry import WorkflowRecord, WorkflowStatus, get_workflow_registry
from app.settings import GatewaySettings, get_gateway_settings
from app.workflows.init_arch.checkpointer import get_checkpointer
from app.workflows.init_arch.domain import RepositoryExecution, WorkflowSessionRecord
from app.workflows.init_arch.graph import compile_graph
from app.workflows.init_arch.state import InitArchState

logger = structlog.get_logger()

_background_tasks: set[asyncio.Task[None]] = set()
_WORKFLOW_POLL_INTERVAL: typing.Final[float] = 0.2
_TASK_POLL_INTERVAL: typing.Final[float] = 0.05
_UPDATE_ARCH_PROMPT_BASE: typing.Final[str] = "/update-repo-arch-skill"


class WorkflowNotFoundError(LookupError):
    pass


class WorkflowConflictError(RuntimeError):
    pass


class WorkflowValidationError(ValueError):
    pass


class ArchRepoNotAvailableError(RuntimeError):
    pass


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def apply_node_output(record: WorkflowRecord, node_output: dict[str, typing.Any]) -> None:
    if "session" in node_output:
        record.session = node_output["session"]
        record.current_step_id = record.session.current_step.value
        record.completed_steps = [step.value for step in record.session.completed_steps]
    if "current_step_id" in node_output:
        record.current_step_id = node_output["current_step_id"]
    if "completed_steps" in node_output:
        record.completed_steps = node_output["completed_steps"]
    if "current_repo_name" in node_output:
        record.current_repo_name = node_output["current_repo_name"]
    if "last_cli_output" in node_output:
        record.last_cli_output_snippet = str(node_output["last_cli_output"])[:500]
    record.updated_at = utcnow()


def apply_interrupt(record: WorkflowRecord, interrupt_payload: typing.Any) -> None:
    record.workflow_status = WorkflowStatus.INTERRUPTED
    record.pending_interrupt = interrupt_payload[0].value if interrupt_payload else {}
    record.updated_at = utcnow()


def get_workflow_record(workflow_id: str) -> WorkflowRecord:
    record = get_workflow_registry().get(workflow_id)
    if record is None:
        raise WorkflowNotFoundError(f"Workflow {workflow_id!r} not found")
    return record


async def persist_workflow_record(record: WorkflowRecord) -> None:
    try:
        async with get_session() as session:
            await upsert_workflow_run(session, record)
    except Exception as exc:  # noqa: BLE001
        logger.warning("workflow.persist_failed", workflow_id=record.workflow_id, error=str(exc))


async def get_workflow_record_async(workflow_id: str) -> WorkflowRecord:
    registry = get_workflow_registry()
    record = registry.get(workflow_id)
    if record is not None:
        return record

    try:
        async with get_session() as session:
            record = await get_workflow_run(session, workflow_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("workflow.load_failed", workflow_id=workflow_id, error=str(exc))
        record = None

    if record is None:
        raise WorkflowNotFoundError(f"Workflow {workflow_id!r} not found")

    registry[workflow_id] = record
    return record


async def list_workflow_required_actions_async(workflow_id: str) -> list[dict[str, typing.Any]]:
    try:
        async with get_session() as session:
            actions = await list_required_actions(session, workflow_id=workflow_id)
    except Exception:  # noqa: BLE001
        return []
    return [
        {
            "action_type": action.action_type,
            "question_id": action.question_id,
            "action_status": action.action_status,
            "payload": dict(action.payload_json or {}),
        }
        for action in actions
    ]


async def list_workflow_events_async(workflow_id: str) -> list[dict[str, typing.Any]]:
    try:
        async with get_session() as session:
            items = await list_conversation_items(session, workflow_id=workflow_id)
    except Exception:  # noqa: BLE001
        return []
    return [
        {
            "item_id": str(item.item_id),
            "item_kind": item.item_kind,
            "actor": item.actor,
            "step_id": item.step_id,
            "payload": dict(item.payload_json or {}),
            "created_at": item.created_at.isoformat(),
        }
        for item in items
    ]


def _task_updated_at(task: CliTask) -> datetime.datetime:
    return task.finished_at or task.started_at or task.created_at


def _build_terminal_result(*, output_text: str | None = None, error_text: str | None = None) -> dict[str, str] | None:
    if output_text:
        return {"output_text": output_text}
    if error_text:
        return {"error_text": error_text}
    return None


async def get_cli_task_async(task_id: str) -> CliTask:
    registry = get_task_registry()
    task = registry.get(task_id)
    if task is not None:
        return task

    try:
        async with get_session() as session:
            task = await get_cli_task(session, task_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("task.load_failed", task_id=task_id, error=str(exc))
        task = None

    if task is None:
        raise WorkflowNotFoundError(f"Response {task_id!r} not found")

    registry[task_id] = task
    return task


async def list_cli_tasks_for_conversation_async(conversation_id: str) -> list[CliTask]:
    registry_tasks = [
        task
        for task in get_task_registry().values()
        if (task.conversation_id or task.workflow_id or task.task_id) == conversation_id
    ]
    if registry_tasks:
        return sorted(registry_tasks, key=_task_updated_at, reverse=True)

    try:
        async with get_session() as session:
            return await list_cli_tasks_for_conversation(session, conversation_id=conversation_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("task.list_for_conversation_failed", conversation_id=conversation_id, error=str(exc))
        return []


def _serialize_required_actions(actions: list[dict[str, typing.Any]]) -> list[dict[str, typing.Any]]:
    return [
        {
            "action_type": action["action_type"],
            "question_id": action.get("question_id"),
            "action_status": action["action_status"],
            "payload": dict(action.get("payload", {})),
        }
        for action in actions
    ]


def _fallback_required_actions(record: WorkflowRecord) -> list[dict[str, typing.Any]]:
    pending_interrupt = record.pending_interrupt or {}
    if not pending_interrupt:
        return []
    return [
        {
            "action_type": str(pending_interrupt.get("interrupt_type", "user_input")),
            "question_id": pending_interrupt.get("question_id"),
            "action_status": "open",
            "payload": dict(pending_interrupt),
        }
    ]


def _workflow_response_payload(
    record: WorkflowRecord,
    required_actions: list[dict[str, typing.Any]],
) -> dict[str, typing.Any]:
    return {
        "response_id": record.workflow_id,
        "conversation_id": record.conversation_id or record.workflow_id,
        "workflow_type": "init_arch",
        "response_status": str(record.workflow_status),
        "current_step_id": record.current_step_id,
        "current_repo_name": record.current_repo_name,
        "workspace_dir": record.workspace_dir,
        "arch_repo_dir": record.arch_repo_dir,
        "completed_steps": list(record.completed_steps),
        "required_actions": _serialize_required_actions(required_actions),
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "error_message": record.error_message,
        "terminal_result": _build_terminal_result(error_text=record.error_message)
        if record.workflow_status == WorkflowStatus.FAILED
        else None,
    }


def _task_response_payload(task: CliTask) -> dict[str, typing.Any]:
    conversation_id = task.conversation_id or task.workflow_id or task.task_id
    task_result = task.task_result or ("\n".join(task.stdout_lines) if task.stdout_lines else None)
    return {
        "response_id": task.task_id,
        "conversation_id": conversation_id,
        "workflow_type": task.response_type or "query",
        "response_status": str(task.task_status),
        "current_step_id": "",
        "current_repo_name": task.repository_name or pathlib.Path(task.workspace_dir).name,
        "workspace_dir": task.workspace_dir,
        "arch_repo_dir": "",
        "completed_steps": [],
        "required_actions": [],
        "created_at": task.created_at.isoformat(),
        "updated_at": _task_updated_at(task).isoformat(),
        "error_message": task.task_error,
        "terminal_result": _build_terminal_result(output_text=task_result, error_text=task.task_error),
    }


async def get_response_async(response_id: str) -> dict[str, typing.Any]:
    try:
        record = await get_workflow_record_async(response_id)
    except WorkflowNotFoundError:
        task = await get_cli_task_async(response_id)
        return _task_response_payload(task)

    required_actions = await list_workflow_required_actions_async(response_id)
    if not required_actions:
        required_actions = _fallback_required_actions(record)
    return _workflow_response_payload(record, required_actions)


async def get_response_arch_repo_dir_async(response_id: str) -> str:
    record = await get_workflow_record_async(response_id)
    if not record.arch_repo_dir:
        raise ArchRepoNotAvailableError(f"No arch_repo_dir recorded for response {response_id!r}")
    return record.arch_repo_dir


def _active_conversation_record(conversation_id: str) -> WorkflowRecord | None:
    records = [
        record
        for record in get_workflow_registry().values()
        if (record.conversation_id or record.workflow_id) == conversation_id
    ]
    if not records:
        return None
    return max(records, key=lambda record: record.updated_at)


def _active_conversation_task(conversation_id: str) -> CliTask | None:
    tasks = [
        task
        for task in get_task_registry().values()
        if (task.conversation_id or task.workflow_id or task.task_id) == conversation_id
    ]
    if not tasks:
        return None
    return max(tasks, key=_task_updated_at)


async def create_conversation_async(conversation_id: str | None = None) -> dict[str, typing.Any]:
    resolved_conversation_id = conversation_id or str(uuid.uuid4())
    now = utcnow()
    try:
        async with get_session() as session:
            conversation = await create_conversation(session, conversation_id=resolved_conversation_id, created_at=now)
            created_at = conversation.created_at
            updated_at = conversation.updated_at
    except Exception:  # noqa: BLE001
        created_at = now
        updated_at = now
    return {
        "conversation_id": resolved_conversation_id,
        "created_at": created_at.isoformat(),
        "updated_at": updated_at.isoformat(),
        "active_response": None,
    }


async def get_conversation_async(conversation_id: str) -> dict[str, typing.Any]:
    active_record = _active_conversation_record(conversation_id)
    active_task = _active_conversation_task(conversation_id)
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None

    if active_record is None and active_task is None:
        try:
            async with get_session() as session:
                conversation = await get_conversation(session, conversation_id)
                if conversation is not None:
                    created_at = conversation.created_at
                    updated_at = conversation.updated_at
                runs = await list_workflow_runs_for_conversation(session, conversation_id=conversation_id)
                tasks = await list_cli_tasks_for_conversation(session, conversation_id=conversation_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("conversation.load_failed", conversation_id=conversation_id, error=str(exc))
            runs = []
            tasks = []
        if runs:
            active_record = runs[0]
            created_at = created_at or active_record.created_at
            updated_at = updated_at or active_record.updated_at
        if tasks:
            active_task = tasks[0]
            created_at = created_at or active_task.created_at
            updated_at = updated_at or _task_updated_at(active_task)

    if active_record is None and active_task is None and created_at is None:
        raise WorkflowNotFoundError(f"Conversation {conversation_id!r} not found")

    if active_record is not None and (active_task is None or active_record.updated_at >= _task_updated_at(active_task)):
        active_response = await get_response_async(active_record.workflow_id)
        created_at = created_at or active_record.created_at
        updated_at = updated_at or active_record.updated_at
    elif active_task is not None:
        active_response = _task_response_payload(active_task)
        created_at = created_at or active_task.created_at
        updated_at = updated_at or _task_updated_at(active_task)
    else:
        active_response = None

    return {
        "conversation_id": conversation_id,
        "created_at": (created_at or utcnow()).isoformat(),
        "updated_at": (updated_at or utcnow()).isoformat(),
        "active_response": active_response,
    }


async def list_conversation_items_async(conversation_id: str) -> list[dict[str, typing.Any]]:
    active_record = _active_conversation_record(conversation_id)
    if active_record is not None:
        return await list_workflow_events_async(active_record.workflow_id)

    tasks = await list_cli_tasks_for_conversation_async(conversation_id)
    if tasks:
        items: list[dict[str, typing.Any]] = []
        for task in reversed(tasks):
            items.extend(_task_conversation_items(task))
        return items

    try:
        async with get_session() as session:
            items = await list_conversation_items(session, conversation_id=conversation_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("conversation.items_load_failed", conversation_id=conversation_id, error=str(exc))
        return []

    return [
        {
            "item_id": str(item.item_id),
            "item_kind": item.item_kind,
            "actor": item.actor,
            "step_id": item.step_id,
            "payload": dict(item.payload_json or {}),
            "created_at": item.created_at.isoformat(),
        }
        for item in items
    ]


def _task_conversation_items(task: CliTask) -> list[dict[str, typing.Any]]:
    items: list[dict[str, typing.Any]] = [
        {
            "item_id": f"{task.task_id}:started",
            "item_kind": "response_started",
            "actor": "service",
            "step_id": None,
            "payload": {"response_id": task.task_id, "workflow_type": task.response_type or "query"},
            "created_at": task.created_at.isoformat(),
        }
    ]
    for idx, line in enumerate(task.stderr_lines):
        items.append(
            {
                "item_id": f"{task.task_id}:stderr:{idx}",
                "item_kind": "progress",
                "actor": "llm_worker",
                "step_id": None,
                "payload": {"event_data": line, "stream_source": "stderr"},
                "created_at": (task.started_at or task.created_at).isoformat(),
            }
        )
    for idx, line in enumerate(task.stdout_lines):
        items.append(
            {
                "item_id": f"{task.task_id}:stdout:{idx}",
                "item_kind": "output",
                "actor": "llm_worker",
                "step_id": None,
                "payload": {"event_data": line, "stream_source": "stdout"},
                "created_at": (task.started_at or task.created_at).isoformat(),
            }
        )
    if task.task_status in {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED}:
        items.append(
            {
                "item_id": f"{task.task_id}:done",
                "item_kind": "done",
                "actor": "service",
                "step_id": None,
                "payload": {
                    "response_id": task.task_id,
                    "task_status": str(task.task_status),
                    "task_error": task.task_error,
                },
                "created_at": _task_updated_at(task).isoformat(),
            }
        )
    return items


def _enqueue_cli_task(cli_task: CliTask) -> CliTask:
    registry = get_task_registry()
    registry[cli_task.task_id] = cli_task
    task = asyncio.create_task(run_cli_task(cli_task, get_agent_pool()))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return cli_task


def _build_update_arch_prompt(diff_context: str) -> str:
    return f"{_UPDATE_ARCH_PROMPT_BASE}\n{diff_context}" if diff_context else _UPDATE_ARCH_PROMPT_BASE


def _build_query_prompt(question: str) -> str:
    return f"Прочитай arch-doc/ и ответь на вопрос: {question}"


def _validate_engine_name(engine_name: str) -> str:
    if engine_name not in {"claude", "codex"}:
        raise WorkflowValidationError("engine_name must be 'claude' or 'codex'")
    return engine_name


async def create_response_async(
    *,
    conversation_id: str,
    workflow_type: str,
    input_payload: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    await create_conversation_async(conversation_id)
    if workflow_type == "init_arch":
        record = await start_init_arch_workflow(conversation_id=conversation_id, **input_payload)
        return await get_response_async(record.workflow_id)

    if workflow_type == "update_arch":
        repo_path = str(input_payload.get("repo_path", ""))
        if not repo_path:
            raise WorkflowValidationError("update_arch requires repo_path")
        prompt_text = _build_update_arch_prompt(str(input_payload.get("diff_context", "")))
        engine_name = _validate_engine_name(str(input_payload.get("engine_name", "claude")))
        cli_task = CliTask(
            task_id=str(uuid.uuid4()),
            engine_name=engine_name,
            prompt_text=prompt_text,
            workspace_dir=repo_path,
            conversation_id=conversation_id,
            response_type="update_arch",
            timeout_seconds=int(input_payload.get("timeout_seconds", 600)),
        )
        _enqueue_cli_task(cli_task)
        return _task_response_payload(cli_task)

    if workflow_type == "query":
        repo_path = str(input_payload.get("repo_path", ""))
        question = str(input_payload.get("question", ""))
        if not repo_path or not question:
            raise WorkflowValidationError("query requires repo_path and question")
        engine_name = _validate_engine_name(str(input_payload.get("engine_name", "claude")))
        cli_task = CliTask(
            task_id=str(uuid.uuid4()),
            engine_name=engine_name,
            prompt_text=_build_query_prompt(question),
            workspace_dir=repo_path,
            conversation_id=conversation_id,
            response_type="query",
            timeout_seconds=int(input_payload.get("timeout_seconds", 120)),
        )
        _enqueue_cli_task(cli_task)
        return _task_response_payload(cli_task)

    raise WorkflowValidationError(f"Unsupported workflow_type: {workflow_type}")


async def submit_response_action_async(
    response_id: str,
    *,
    action_type: str,
    question_id: str | None = None,
    answer: str | None = None,
    field: str | None = None,
    value: typing.Any = None,
) -> dict[str, typing.Any]:
    try:
        await get_workflow_record_async(response_id)
    except WorkflowNotFoundError:
        task = await get_cli_task_async(response_id)
        if action_type != "cancel":
            raise WorkflowValidationError(f"Unsupported action_type for task-backed response: {action_type}") from None
        registry = get_task_registry()
        await cancel_cli_task(task.task_id, registry)
        return _task_response_payload(registry.get(task.task_id, task))

    if action_type == "cancel":
        await cancel_init_arch_workflow(response_id)
    elif action_type == "answer_question":
        if question_id is None or answer is None:
            raise WorkflowValidationError("answer_question requires question_id and answer")
        await answer_init_arch_question(response_id, question_id=question_id, answer=answer)
    elif action_type == "resume":
        await resume_init_arch_workflow(response_id, field=field, value=value, answer=answer)
    elif action_type == "confirm_temporal_window":
        if value is None:
            raise WorkflowValidationError("confirm_temporal_window requires a value")
        await confirm_init_arch_temporal_window(response_id, action=str(value))
    else:
        raise WorkflowValidationError(f"Unsupported action_type: {action_type}")
    return await get_response_async(response_id)


def _sse(payload: dict[str, typing.Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _conversation_item_to_sse_payload(event: dict[str, typing.Any]) -> dict[str, typing.Any]:
    payload = dict(event.get("payload", {}))
    item_kind = str(event.get("item_kind", "event"))
    if item_kind == "step_transition":
        return {
            "event_type": "step_started",
            "step_id": payload.get("current_step_id") or event.get("step_id", ""),
            "repo_name": payload.get("current_repo_name", ""),
        }
    return {"event_type": item_kind, **payload}


async def _stream_persisted_workflow_events(workflow_id: str) -> typing.AsyncGenerator[str, None]:
    record = await get_workflow_record_async(workflow_id)
    events = await list_workflow_events_async(workflow_id)
    emitted_cli_output = False

    for event in events:
        payload = _conversation_item_to_sse_payload(event)
        if payload.get("event_type") == "cli_output":
            emitted_cli_output = True
        yield _sse(payload)

    if record.last_cli_output_snippet and not emitted_cli_output:
        yield _sse(
            {
                "event_type": "cli_output",
                "event_data": record.last_cli_output_snippet,
                "stream_source": "stdout",
            }
        )

    if record.workflow_status == WorkflowStatus.INTERRUPTED:
        yield _sse({"event_type": "interrupted", **(record.pending_interrupt or {})})
    elif record.workflow_status == WorkflowStatus.SUCCESS:
        yield _sse({"event_type": "workflow_done", "workflow_status": "success"})
    elif record.workflow_status == WorkflowStatus.FAILED:
        yield _sse({"event_type": "workflow_failed", "error_message": record.error_message or "unknown error"})
    elif record.workflow_status == WorkflowStatus.CANCELLED:
        yield _sse({"event_type": "workflow_cancelled", "workflow_status": "cancelled"})


async def _stream_live_workflow_events(workflow_id: str) -> typing.AsyncGenerator[str, None]:
    registry = get_workflow_registry()
    record = registry.get(workflow_id)
    if record is None:
        try:
            async for chunk in _stream_persisted_workflow_events(workflow_id):
                yield chunk
        except WorkflowNotFoundError:
            yield _sse({"event_type": "error", "error_message": f"Workflow {workflow_id!r} not found"})
        return

    last_step = ""
    last_snippet = ""
    while True:
        current = registry.get(workflow_id)
        if current is None:
            break

        if current.current_step_id != last_step:
            last_step = current.current_step_id
            yield _sse({"event_type": "step_started", "step_id": last_step, "repo_name": current.current_repo_name})

        if current.last_cli_output_snippet != last_snippet:
            last_snippet = current.last_cli_output_snippet
            yield _sse({"event_type": "cli_output", "event_data": last_snippet, "stream_source": "stdout"})

        if current.workflow_status == WorkflowStatus.INTERRUPTED:
            yield _sse({"event_type": "interrupted", **(current.pending_interrupt or {})})
            break
        if current.workflow_status == WorkflowStatus.SUCCESS:
            yield _sse({"event_type": "workflow_done", "workflow_status": "success"})
            break
        if current.workflow_status == WorkflowStatus.FAILED:
            yield _sse({"event_type": "workflow_failed", "error_message": current.error_message or "unknown error"})
            break
        if current.workflow_status == WorkflowStatus.CANCELLED:
            yield _sse({"event_type": "workflow_cancelled", "workflow_status": "cancelled"})
            break

        await asyncio.sleep(_WORKFLOW_POLL_INTERVAL)


async def _stream_task_events(response_id: str) -> typing.AsyncGenerator[str, None]:
    registry = get_task_registry()
    task = registry.get(response_id)
    if task is None:
        task = await get_cli_task_async(response_id)
        for item in _task_conversation_items(task):
            yield _sse(_conversation_item_to_sse_payload(item))
        return

    last_stdout_idx = 0
    last_stderr_idx = 0
    while task.task_status not in {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED}:
        for line in task.stderr_lines[last_stderr_idx:]:
            yield _sse({"event_type": "progress", "event_data": line, "stream_source": "stderr"})
        last_stderr_idx = len(task.stderr_lines)

        for line in task.stdout_lines[last_stdout_idx:]:
            yield _sse({"event_type": "output", "event_data": line, "stream_source": "stdout"})
        last_stdout_idx = len(task.stdout_lines)
        await asyncio.sleep(_TASK_POLL_INTERVAL)

    for line in task.stderr_lines[last_stderr_idx:]:
        yield _sse({"event_type": "progress", "event_data": line, "stream_source": "stderr"})
    for line in task.stdout_lines[last_stdout_idx:]:
        yield _sse({"event_type": "output", "event_data": line, "stream_source": "stdout"})

    exit_code = task.subprocess_handle.returncode if task.subprocess_handle else task.exit_code
    yield _sse({"event_type": "done", "exit_code": exit_code, "task_id": task.task_id})


async def stream_response_events_async(response_id: str) -> typing.AsyncGenerator[str, None]:
    try:
        await get_workflow_record_async(response_id)
    except WorkflowNotFoundError:
        async for chunk in _stream_task_events(response_id):
            yield chunk
        return

    async for chunk in _stream_live_workflow_events(response_id):
        yield chunk


async def run_workflow(record: WorkflowRecord, initial_state: InitArchState) -> None:
    registry = get_workflow_registry()
    try:
        checkpointer = await get_checkpointer()
        graph = compile_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": record.workflow_id}}

        async for event in graph.astream(initial_state, config=config):
            for node_name, node_output in event.items():
                if node_name == "__interrupt__":
                    apply_interrupt(record, node_output)
                    await persist_workflow_record(record)
                    logger.info(
                        "workflow.interrupted",
                        workflow_id=record.workflow_id,
                        interrupt=record.pending_interrupt,
                    )
                    return
                if isinstance(node_output, dict):
                    apply_node_output(record, node_output)
                    await persist_workflow_record(record)

        record.workflow_status = WorkflowStatus.SUCCESS
        record.updated_at = utcnow()
        await persist_workflow_record(record)
        logger.info("workflow.completed", workflow_id=record.workflow_id)
    except asyncio.CancelledError:
        record.workflow_status = WorkflowStatus.CANCELLED
        record.error_message = "Workflow cancelled"
        record.pending_interrupt = None
        record.updated_at = utcnow()
        await persist_workflow_record(record)
        logger.info("workflow.cancelled", workflow_id=record.workflow_id)
        raise
    except Exception as exc:  # noqa: BLE001
        record.workflow_status = WorkflowStatus.FAILED
        record.error_message = str(exc)
        record.updated_at = utcnow()
        await persist_workflow_record(record)
        logger.error("workflow.failed", workflow_id=record.workflow_id, error=str(exc))
    finally:
        registry[record.workflow_id] = record


async def resume_workflow_task(record: WorkflowRecord, resume_value: typing.Any) -> None:
    try:
        checkpointer = await get_checkpointer()
        graph = compile_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": record.workflow_id}}
        async for event in graph.astream(resume_value, config=config):
            for node_name, node_output in event.items():
                if node_name == "__interrupt__":
                    apply_interrupt(record, node_output)
                    await persist_workflow_record(record)
                    return
                if isinstance(node_output, dict):
                    apply_node_output(record, node_output)
                    await persist_workflow_record(record)
        record.workflow_status = WorkflowStatus.SUCCESS
        record.updated_at = utcnow()
        await persist_workflow_record(record)
    except asyncio.CancelledError:
        record.workflow_status = WorkflowStatus.CANCELLED
        record.error_message = "Workflow cancelled"
        record.pending_interrupt = None
        record.updated_at = utcnow()
        await persist_workflow_record(record)
        logger.info("workflow.cancelled", workflow_id=record.workflow_id)
        raise
    except Exception as exc:  # noqa: BLE001
        record.workflow_status = WorkflowStatus.FAILED
        record.error_message = str(exc)
        record.updated_at = utcnow()
        await persist_workflow_record(record)


def schedule_resume(record: WorkflowRecord, *, resume_value: typing.Any) -> None:
    record.workflow_status = WorkflowStatus.RUNNING
    record.pending_interrupt = None
    record.updated_at = utcnow()

    task = asyncio.create_task(resume_workflow_task(record, resume_value))
    record.asyncio_task = task
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def build_resume_value(*, interrupt_type: str, field: str | None, value: typing.Any, answer: str | None) -> typing.Any:
    if interrupt_type == "user_input" and field and value is not None:
        return {field: value}
    if interrupt_type == "user_question" and answer is not None:
        return {"answer": answer}
    if interrupt_type == "temporal_window_confirmation" and value is not None:
        return {"action": value}
    raise WorkflowValidationError("Invalid resume payload for interrupt type")


def _resolve_init_arch_paths(
    *,
    workspace_dir: str,
    arch_repo_dir: str,
    settings: GatewaySettings | None = None,
) -> tuple[str, str, str]:
    resolved_settings = settings or get_gateway_settings()
    workspace_path = pathlib.Path(workspace_dir).expanduser().resolve()
    raw_workspace_path = (workspace_path / resolved_settings.workflows.init.raw_workspace_subdir).resolve()
    arch_repo_path = (
        pathlib.Path(arch_repo_dir).expanduser().resolve()
        if arch_repo_dir
        else (workspace_path / resolved_settings.workflows.init.arch_repo_dirname).resolve()
    )

    if raw_workspace_path == arch_repo_path or raw_workspace_path in arch_repo_path.parents:
        raise WorkflowValidationError("arch_repo_dir must not live inside raw workspace")
    if (
        arch_repo_path not in workspace_path.parents
        and arch_repo_path != workspace_path
        and workspace_path not in arch_repo_path.parents
    ):
        raise WorkflowValidationError("arch_repo_dir must live inside workspace_dir")

    return str(workspace_path), str(arch_repo_path), str(raw_workspace_path)


def _parse_repo_list_entry(entry: str) -> RepositoryExecution:
    stripped = entry.strip()
    if "://" in stripped or stripped.startswith("git@"):
        repository_name = stripped.rstrip("/").rsplit("/", 1)[-1]
        repository_name = repository_name.removesuffix(".git")
        return RepositoryExecution(repository_name=repository_name, repository_url=stripped)
    return RepositoryExecution(repository_name=stripped)


async def start_init_arch_workflow(
    *,
    product_name: str,
    analysis_scope: str,
    workspace_dir: str,
    arch_repo_dir: str,
    repo_list: list[str],
    engine_name: str,
    timeout_seconds: int,
    conversation_id: str | None = None,
) -> WorkflowRecord:
    resolved_workspace_dir, resolved_arch_repo_dir, resolved_raw_workspace_dir = _resolve_init_arch_paths(
        workspace_dir=workspace_dir,
        arch_repo_dir=arch_repo_dir,
    )
    workflow_id = str(uuid.uuid4())
    progress_file_path = f"{resolved_arch_repo_dir}/repo-initialization-progress.yaml"
    session = WorkflowSessionRecord(
        session_id=workflow_id,
        product_name=product_name,
        analysis_scope=analysis_scope,
        repositories=[_parse_repo_list_entry(repo_entry) for repo_entry in repo_list],
    )

    record = WorkflowRecord(
        workflow_id=workflow_id,
        conversation_id=conversation_id or workflow_id,
        session=session,
        workspace_dir=resolved_workspace_dir,
        arch_repo_dir=resolved_arch_repo_dir,
    )
    registry = get_workflow_registry()
    registry[workflow_id] = record
    await persist_workflow_record(record)

    initial_state = InitArchState(
        session_id=session.session_id,
        session=session,
        workspace_dir=resolved_workspace_dir,
        raw_workspace_dir=resolved_raw_workspace_dir,
        arch_repo_dir=resolved_arch_repo_dir,
        engine_name=engine_name,
        timeout_seconds=timeout_seconds,
        progress_file_path=progress_file_path,
        last_llm_result=None,
        last_guard_output="",
        step_error=None,
        retry_count=0,
    )

    task = asyncio.create_task(run_workflow(record, initial_state))
    record.asyncio_task = task
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    logger.info("workflow.init.started", workflow_id=workflow_id, product=product_name)
    return record


async def resume_init_arch_workflow(
    workflow_id: str,
    *,
    field: str | None,
    value: typing.Any,
    answer: str | None,
) -> WorkflowRecord:
    record = await get_workflow_record_async(workflow_id)
    if record.workflow_status != WorkflowStatus.INTERRUPTED:
        raise WorkflowConflictError(f"Workflow is not interrupted (status: {record.workflow_status})")

    interrupt_type = (record.pending_interrupt or {}).get("interrupt_type", "")
    resume_value = build_resume_value(interrupt_type=interrupt_type, field=field, value=value, answer=answer)
    schedule_resume(record, resume_value=resume_value)
    await persist_workflow_record(record)
    logger.info("workflow.resumed", workflow_id=workflow_id)
    return record


async def answer_init_arch_question(workflow_id: str, *, question_id: str, answer: str) -> WorkflowRecord:
    record = await get_workflow_record_async(workflow_id)
    if record.workflow_status != WorkflowStatus.INTERRUPTED:
        raise WorkflowConflictError(f"Workflow is not interrupted (status: {record.workflow_status})")

    pending_interrupt = record.pending_interrupt or {}
    if pending_interrupt.get("interrupt_type") != "user_question":
        raise WorkflowConflictError("Workflow is not waiting for a user question")
    if pending_interrupt.get("question_id") != question_id:
        raise WorkflowConflictError("Question id does not match the pending interrupt")

    schedule_resume(record, resume_value={"answer": answer})
    await persist_workflow_record(record)
    logger.info("workflow.question.answered", workflow_id=workflow_id, question_id=question_id)
    return record


async def confirm_init_arch_temporal_window(workflow_id: str, *, action: str) -> WorkflowRecord:
    record = await get_workflow_record_async(workflow_id)
    if record.workflow_status != WorkflowStatus.INTERRUPTED:
        raise WorkflowConflictError(f"Workflow is not interrupted (status: {record.workflow_status})")

    pending_interrupt = record.pending_interrupt or {}
    if pending_interrupt.get("interrupt_type") != "temporal_window_confirmation":
        raise WorkflowConflictError("Workflow is not waiting for a temporal window confirmation")
    if action not in {"continue_to_next_window", "finish_temporal_analysis"}:
        raise WorkflowValidationError(f"Unsupported temporal window confirmation action: {action}")

    schedule_resume(record, resume_value={"action": action})
    await persist_workflow_record(record)
    logger.info("workflow.temporal_window.confirmed", workflow_id=workflow_id, action=action)
    return record


async def cancel_init_arch_workflow(workflow_id: str) -> WorkflowRecord:
    record = await get_workflow_record_async(workflow_id)
    if record.workflow_status in (WorkflowStatus.SUCCESS, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED):
        raise WorkflowConflictError(f"Workflow is not cancellable (status: {record.workflow_status})")

    task = record.asyncio_task
    if task is not None and not task.done():
        task.cancel()

    record.workflow_status = WorkflowStatus.CANCELLED
    record.pending_interrupt = None
    record.error_message = "Workflow cancelled"
    record.updated_at = utcnow()
    await persist_workflow_record(record)
    logger.info("workflow.cancel.requested", workflow_id=workflow_id)
    return record
