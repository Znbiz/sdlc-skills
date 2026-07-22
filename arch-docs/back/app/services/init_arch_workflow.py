from __future__ import annotations

import asyncio
import contextlib
import datetime
import json
import pathlib
import re
import shutil
import typing
import uuid

import structlog

from app.db.session import get_session
from app.db.task_repo import delete_cli_tasks_for_workflow, get_cli_task, list_cli_tasks_for_conversation
from app.db.workflow_repo import (
    create_conversation,
    delete_workflow_run,
    get_conversation,
    get_workflow_run,
    list_conversation_items,
    list_required_actions,
    list_workflow_runs_for_conversation,
    upsert_workflow_run,
)
from app.services.agent_pool import get_agent_pool
from app.services.git_credentials import list_configured_hosts
from app.services.task_registry import CliTask, TaskStatus
from app.services.task_registry import get_registry as get_task_registry
from app.services.task_runner import cancel_cli_task, run_cli_task
from app.services.workflow_event_bus import get_workflow_event_bus
from app.services.workflow_registry import WorkflowRecord, WorkflowStatus, get_workflow_registry
from app.settings import GatewaySettings, get_gateway_settings
from app.workflows.init_arch.checkpointer import get_checkpointer
from app.workflows.init_arch.domain import RepositoryExecution, StepId, WorkflowSessionRecord, step_label_ru
from app.workflows.init_arch.graph import compile_graph
from app.workflows.init_arch.snapshot import parse_snapshot_yaml, write_snapshot_file
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


_INIT_ARCH_REQUIRED_FIELDS: typing.Final = frozenset(
    {
        "product_name",
        "analysis_scope",
        "workspace_dir",
        "arch_repo_dir",
        "repo_list",
        "engine_name",
        "timeout_seconds",
    }
)


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
        missing_fields = sorted(_INIT_ARCH_REQUIRED_FIELDS - input_payload.keys())
        if missing_fields:
            raise WorkflowValidationError(f"init_arch requires fields: {', '.join(missing_fields)}")
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

    if action_type == "restart":
        # Unlike every other action, restart deletes the WorkflowRecord entirely - there's nothing
        # left for get_response_async(response_id) to return afterward, so this returns early with
        # the conversation payload (active_response: None) instead of falling through below.
        return await restart_init_arch_workflow(response_id)

    if action_type == "pause":
        await pause_init_arch_workflow(response_id)
    elif action_type == "continue":
        await continue_init_arch_workflow(response_id)
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
    elif action_type == "retry":
        await retry_init_arch_workflow(response_id, action=str(value) if value is not None else "retry")
    else:
        raise WorkflowValidationError(f"Unsupported action_type: {action_type}")
    return await get_response_async(response_id)


def _sse(payload: dict[str, typing.Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


# service/llm_worker/user (app.workflows.init_arch.domain.AuditActor, persisted as a plain string on
# conversation_items.actor) -> the actor vocabulary SSE consumers see. See
# arch-docs/docs/spec/2026-07-22-realtime-workflow-observability.md.
_PERSISTED_ACTOR_TO_SSE: typing.Final[dict[str, str]] = {
    "service": "workflow",
    "llm_worker": "llm",
    "user": "user",
}

# item_kind (== EventType.value, persisted) -> unified live event_type, so a page reload/reconnect
# (persisted replay) renders identically to what the live SSE stream already sent.
_ITEM_KIND_TO_EVENT_TYPE: typing.Final[dict[str, str]] = {
    "llm_task_requested": "llm_call_started",
    "llm_task_completed": "llm_call_completed",
    "llm_task_failed": "llm_call_failed",
}


def _conversation_item_to_sse_payload(event: dict[str, typing.Any]) -> dict[str, typing.Any]:
    payload = dict(event.get("payload", {}))
    item_kind = str(event.get("item_kind", "event"))
    actor = _PERSISTED_ACTOR_TO_SSE.get(str(event.get("actor", "")), "workflow")
    if item_kind == "step_transition":
        step_id = payload.get("current_step_id") or event.get("step_id", "")
        return {
            "event_type": "step_started",
            "actor": "workflow",
            "step_id": step_id,
            "step_label": step_label_ru(step_id),
            "repo_name": payload.get("current_repo_name", ""),
        }
    event_type = _ITEM_KIND_TO_EVENT_TYPE.get(item_kind, item_kind)
    return {"event_type": event_type, "actor": actor, **payload}


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
                "actor": "llm",
                "event_data": record.last_cli_output_snippet,
                "stream_source": "stdout",
            }
        )

    terminal_event = _terminal_event_for_status(record)
    if terminal_event is not None:
        yield _sse(terminal_event)


def _drain_bus_events(queue: asyncio.Queue[dict[str, typing.Any]]) -> list[dict[str, typing.Any]]:
    drained: list[dict[str, typing.Any]] = []
    while True:
        try:
            drained.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            return drained


def _terminal_event_for_status(current: WorkflowRecord) -> dict[str, typing.Any] | None:
    if current.workflow_status == WorkflowStatus.INTERRUPTED:
        return {"event_type": "interrupted", "actor": "workflow", **(current.pending_interrupt or {})}
    if current.workflow_status == WorkflowStatus.SUCCESS:
        return {"event_type": "workflow_done", "actor": "workflow", "workflow_status": "success"}
    if current.workflow_status == WorkflowStatus.FAILED:
        return {
            "event_type": "workflow_failed",
            "actor": "workflow",
            "error_message": current.error_message or "unknown error",
        }
    if current.workflow_status == WorkflowStatus.CANCELLED:
        return {"event_type": "workflow_cancelled", "actor": "workflow", "workflow_status": "cancelled"}
    if current.workflow_status == WorkflowStatus.PAUSED:
        return {
            "event_type": "workflow_paused",
            "actor": "workflow",
            "step_id": current.current_step_id,
            "step_label": step_label_ru(current.current_step_id),
            "repo_name": current.current_repo_name,
        }
    return None


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

    bus = get_workflow_event_bus()
    subscription = bus.subscribe(workflow_id)
    try:
        last_step = ""
        last_snippet = ""
        while True:
            current = registry.get(workflow_id)
            if current is None:
                break

            for bus_event in _drain_bus_events(subscription):
                yield _sse(bus_event)

            if current.current_step_id != last_step:
                last_step = current.current_step_id
                yield _sse(
                    {
                        "event_type": "step_started",
                        "actor": "workflow",
                        "step_id": last_step,
                        "step_label": step_label_ru(last_step),
                        "repo_name": current.current_repo_name,
                    }
                )

            if current.last_cli_output_snippet != last_snippet:
                last_snippet = current.last_cli_output_snippet
                yield _sse(
                    {
                        "event_type": "cli_output",
                        "actor": "llm",
                        "event_data": last_snippet,
                        "stream_source": "stdout",
                    }
                )

            terminal_event = _terminal_event_for_status(current)
            if terminal_event is not None:
                yield _sse(terminal_event)
                break

            try:
                bus_event = await asyncio.wait_for(subscription.get(), timeout=_WORKFLOW_POLL_INTERVAL)
                yield _sse(bus_event)
            except TimeoutError:
                pass
    finally:
        bus.unsubscribe(workflow_id, subscription)


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


_GRAPH_ERROR_NODE_NAME: typing.Final[str] = "handle_error"


async def _drive_graph_stream(
    record: WorkflowRecord, graph: typing.Any, config: dict[str, typing.Any], stream_input: typing.Any
) -> bool:
    """Advance the graph until it interrupts or reaches END.

    Returns True if the run should be treated as failed: the graph's own retry/error routing
    (see `_route_after_node` in graph.py) can exhaust retries and route through the
    `handle_error` node straight to END without raising a Python exception, so a clean
    `astream` completion does not by itself mean the workflow succeeded.
    """
    reached_handle_error = False
    last_step_error: str | None = None

    async for event in graph.astream(stream_input, config=config):
        for node_name, node_output in event.items():
            if node_name == "__interrupt__":
                apply_interrupt(record, node_output)
                await persist_workflow_record(record)
                await _write_progress_snapshot(graph, config)
                logger.info(
                    "workflow.interrupted",
                    workflow_id=record.workflow_id,
                    interrupt=record.pending_interrupt,
                )
                return False
            # LangGraph reports a node that returned `{}` (no state update) as `None` here,
            # not `{}` - so this must be checked before the isinstance/apply_node_output gate.
            if node_name == _GRAPH_ERROR_NODE_NAME:
                reached_handle_error = True
            if not isinstance(node_output, dict):
                continue
            if node_output.get("step_error"):
                last_step_error = node_output["step_error"]
            apply_node_output(record, node_output)
            await persist_workflow_record(record)
            await _write_progress_snapshot(graph, config)

    if reached_handle_error:
        record.error_message = last_step_error or "Workflow step failed after exhausting retries"
    return reached_handle_error


async def _write_progress_snapshot(graph: typing.Any, config: dict[str, typing.Any]) -> None:
    state_snapshot = await graph.aget_state(config)
    write_snapshot_file(state_snapshot.values)


async def _handle_workflow_cancellation(record: WorkflowRecord) -> None:
    """Shared `except asyncio.CancelledError` handling for `run_workflow`/`resume_workflow_task`.

    A cancelled asyncio.Task means either `pause_init_arch_workflow()` (resumable, `PAUSED` - see
    `continue_init_arch_workflow()`) or some other, non-pause cancellation (terminal, `CANCELLED` -
    e.g. the planned `restart_init_arch_workflow()`'s pre-delete cancellation). `record.pause_requested`,
    set by the pause path right before cancelling, is what tells the two apart. See spec sections
    7-8 in arch-docs/docs/spec/2026-07-22-realtime-workflow-observability.md.
    """
    if record.pause_requested:
        record.workflow_status = WorkflowStatus.PAUSED
        record.error_message = None
        logger.info("workflow.paused", workflow_id=record.workflow_id)
    else:
        record.workflow_status = WorkflowStatus.CANCELLED
        record.error_message = "Workflow cancelled"
        logger.info("workflow.cancelled", workflow_id=record.workflow_id)
    record.pause_requested = False
    record.pending_interrupt = None
    record.updated_at = utcnow()
    await persist_workflow_record(record)


async def run_workflow(record: WorkflowRecord, initial_state: InitArchState, *, as_node: str | None = None) -> None:
    registry = get_workflow_registry()
    try:
        checkpointer = await get_checkpointer()
        graph = compile_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": record.workflow_id}}

        if as_node is not None:
            await graph.aupdate_state(config, dict(initial_state), as_node=as_node)
            stream_input: typing.Any = None
        else:
            stream_input = initial_state

        failed = await _drive_graph_stream(record, graph, config, stream_input)
        if record.workflow_status == WorkflowStatus.INTERRUPTED:
            return

        record.workflow_status = WorkflowStatus.FAILED if failed else WorkflowStatus.SUCCESS
        record.updated_at = utcnow()
        await persist_workflow_record(record)
        if failed:
            logger.error("workflow.failed", workflow_id=record.workflow_id, error=record.error_message)
        else:
            logger.info("workflow.completed", workflow_id=record.workflow_id)
    except asyncio.CancelledError:
        await _handle_workflow_cancellation(record)
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

        failed = await _drive_graph_stream(record, graph, config, resume_value)
        if record.workflow_status == WorkflowStatus.INTERRUPTED:
            return

        record.workflow_status = WorkflowStatus.FAILED if failed else WorkflowStatus.SUCCESS
        record.updated_at = utcnow()
        await persist_workflow_record(record)
    except asyncio.CancelledError:
        await _handle_workflow_cancellation(record)
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
    if interrupt_type == "step_failed" and value is not None:
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


_SCP_LIKE_SSH_URL_PATTERN: typing.Final[re.Pattern[str]] = re.compile(r"^git@(?P<host>[^:/]+):(?P<path>.+)$")


def _canonicalize_repo_path(path: str) -> str:
    return path.strip().rstrip("/").removesuffix(".git")


async def _normalize_repository_url(raw_url: str) -> str:
    """Bring a user-submitted repository URL to a canonical clone URL.

    Users paste this in two error-prone shapes: the SCP-like SSH form (`git@host:path.git`)
    and a bare web address-bar copy (`https://host/path`, no `.git`, maybe a trailing slash).
    A PAT is HTTPS-only — git's credential helper never applies to the SSH transport — so an
    SSH-form URL for a host that only has a PAT configured (no deploy key) can never
    authenticate. Rewrite it to HTTPS in that case; leave other SSH hosts alone since SSH
    deploy-key auth (see app/services/git_ssh.py) is presumably what's intended there.
    """
    stripped = raw_url.strip()

    scp_match = _SCP_LIKE_SSH_URL_PATTERN.match(stripped)
    if scp_match:
        host = scp_match.group("host")
        configured_hosts = await list_configured_hosts()
        if host not in configured_hosts:
            return stripped
        path = _canonicalize_repo_path(scp_match.group("path"))
        return f"https://{host}/{path}.git"

    if stripped.startswith(("http://", "https://")):
        scheme, _, rest = stripped.partition("://")
        path = _canonicalize_repo_path(rest)
        return f"{scheme}://{path}.git"

    return stripped


async def _parse_repo_list_entry(entry: str) -> RepositoryExecution:
    stripped = entry.strip()
    if "://" in stripped or stripped.startswith("git@"):
        normalized_url = await _normalize_repository_url(stripped)
        repository_name = _canonicalize_repo_path(normalized_url).rsplit("/", 1)[-1]
        return RepositoryExecution(repository_name=repository_name, repository_url=normalized_url)
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
    repositories = [await _parse_repo_list_entry(repo_entry) for repo_entry in repo_list]
    session = WorkflowSessionRecord(
        session_id=workflow_id,
        product_name=product_name,
        analysis_scope=analysis_scope,
        repositories=repositories,
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


async def resume_init_arch_workflow_from_snapshot(
    yaml_text: str,
    *,
    workspace_dir: str | None = None,
    arch_repo_dir: str | None = None,
    engine_name: str | None = None,
    timeout_seconds: int | None = None,
    conversation_id: str | None = None,
) -> WorkflowRecord:
    snapshot = parse_snapshot_yaml(yaml_text)
    resolved_workspace_dir, resolved_arch_repo_dir, resolved_raw_workspace_dir = _resolve_init_arch_paths(
        workspace_dir=workspace_dir or snapshot.workspace_dir,
        arch_repo_dir=arch_repo_dir or snapshot.arch_repo_dir,
    )
    # Защита от параллельного/повторного restore того же arch_repo_dir: если в in-memory
    # registry уже есть активный (RUNNING/INTERRUPTED) workflow для того же arch_repo_dir,
    # два фоновых run_workflow будут одновременно писать repo-initialization-progress.yaml
    # и гонять CLI-агентов по одному и тому же workspace, затирая друг друга.
    # Ограничение: этот guard видит только воркфлоу текущего процесса — параллельный restore,
    # запущенный из другого процесса/инстанса сервиса, он не поймает (это не cross-process lock).
    for existing_record in get_workflow_registry().values():
        if existing_record.arch_repo_dir != resolved_arch_repo_dir:
            continue
        if existing_record.workflow_status not in (WorkflowStatus.RUNNING, WorkflowStatus.INTERRUPTED):
            continue
        raise WorkflowConflictError(
            f"Workflow {existing_record.workflow_id!r} is already active "
            f"(status={existing_record.workflow_status}) for arch_repo_dir {resolved_arch_repo_dir!r}; "
            "refusing to start a concurrent restore. This check only covers workflows tracked "
            "by this process's in-memory registry, not other processes/instances."
        )

    workflow_id = str(uuid.uuid4())
    progress_file_path = f"{resolved_arch_repo_dir}/repo-initialization-progress.yaml"
    session = snapshot.session.model_copy(update={"session_id": workflow_id})

    record = WorkflowRecord(
        workflow_id=workflow_id,
        conversation_id=conversation_id or workflow_id,
        session=session,
        workspace_dir=resolved_workspace_dir,
        arch_repo_dir=resolved_arch_repo_dir,
        current_step_id=session.current_step.value,
        completed_steps=[step.value for step in session.completed_steps],
    )
    registry = get_workflow_registry()
    registry[workflow_id] = record
    await persist_workflow_record(record)

    if session.current_step is StepId.DONE:
        record.workflow_status = WorkflowStatus.SUCCESS
        record.updated_at = utcnow()
        await persist_workflow_record(record)
        logger.info(
            "workflow.rehydrated_already_done", workflow_id=workflow_id, source_workflow_id=snapshot.workflow_id
        )
        return record

    initial_state = InitArchState(
        session_id=session.session_id,
        session=session,
        workspace_dir=resolved_workspace_dir,
        raw_workspace_dir=resolved_raw_workspace_dir,
        arch_repo_dir=resolved_arch_repo_dir,
        engine_name=engine_name or snapshot.engine_name,
        timeout_seconds=timeout_seconds or snapshot.timeout_seconds,
        progress_file_path=progress_file_path,
        last_llm_result=None,
        last_guard_output="",
        step_error=None,
        retry_count=0,
    )
    # Инвариант: completed_steps заполняется в порядке прохождения графа (append-only), поэтому
    # последний элемент — это узел, непосредственно предшествующий session.current_step.
    # Гарантируется append-поведением advance_step (app/workflows/init_arch/domain/operations.py).
    as_node = session.completed_steps[-1].value if session.completed_steps else None

    task = asyncio.create_task(run_workflow(record, initial_state, as_node=as_node))
    record.asyncio_task = task
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    logger.info(
        "workflow.rehydrated",
        workflow_id=workflow_id,
        source_workflow_id=snapshot.workflow_id,
        as_node=as_node,
    )
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


async def retry_init_arch_workflow(workflow_id: str, *, action: str = "retry") -> WorkflowRecord:
    record = await get_workflow_record_async(workflow_id)
    if record.workflow_status != WorkflowStatus.INTERRUPTED:
        raise WorkflowConflictError(f"Workflow is not interrupted (status: {record.workflow_status})")

    pending_interrupt = record.pending_interrupt or {}
    if pending_interrupt.get("interrupt_type") != "step_failed":
        raise WorkflowConflictError("Workflow is not waiting for a step failure recovery decision")
    if action not in {"retry", "abort"}:
        raise WorkflowValidationError(f"Unsupported step failure recovery action: {action}")

    schedule_resume(record, resume_value={"action": action})
    await persist_workflow_record(record)
    logger.info("workflow.step_failure.recovery", workflow_id=workflow_id, action=action)
    return record


async def pause_init_arch_workflow(workflow_id: str) -> WorkflowRecord:
    """Stop a running workflow at the next node boundary without discarding progress.

    This sets `PAUSED`, a resumable status - `continue_init_arch_workflow()` picks it back up from
    the LangGraph checkpoint for this `workflow_id`'s `thread_id`. If the pause lands mid-LLM-call,
    that one node re-runs from scratch on resume (the same durability the checkpointer already
    provides across process restarts - see `resume_init_arch_workflow_from_snapshot()`'s `as_node`
    handling); everything before it is untouched. `WorkflowStatus.CANCELLED` still exists as an
    internal fallback status inside `_handle_workflow_cancellation()` for any future task
    cancellation that isn't a pause (e.g. the planned `restart_init_arch_workflow()`'s pre-delete
    cancellation - see spec section 8), but there is no longer a standalone user-facing "cancel"
    action - `pause` covers what it used to. See spec sections 7-8 in
    arch-docs/docs/spec/2026-07-22-realtime-workflow-observability.md.
    """
    record = await get_workflow_record_async(workflow_id)
    if record.workflow_status != WorkflowStatus.RUNNING:
        raise WorkflowConflictError(f"Workflow is not pausable (status: {record.workflow_status})")

    record.pause_requested = True
    task = record.asyncio_task
    if task is not None and not task.done():
        task.cancel()

    # Set PAUSED immediately rather than waiting for the cancelled task to unwind into
    # `_handle_workflow_cancellation()` - an optimistic update so a client polling right after this
    # call sees "paused", not a stale "running". If a live task exists, its cancellation handler
    # re-affirms the same status once it unwinds (idempotent); if there is none (e.g. record
    # rehydrated in a process that isn't running it), this is the only place PAUSED gets set at all.
    record.workflow_status = WorkflowStatus.PAUSED
    record.updated_at = utcnow()
    await persist_workflow_record(record)
    logger.info("workflow.pause.requested", workflow_id=workflow_id)
    return record


async def continue_init_arch_workflow(workflow_id: str) -> WorkflowRecord:
    record = await get_workflow_record_async(workflow_id)
    if record.workflow_status != WorkflowStatus.PAUSED:
        raise WorkflowConflictError(f"Workflow is not paused (status: {record.workflow_status})")

    record.workflow_status = WorkflowStatus.RUNNING
    record.updated_at = utcnow()

    task = asyncio.create_task(resume_workflow_task(record, None))
    record.asyncio_task = task
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    await persist_workflow_record(record)
    logger.info("workflow.continued", workflow_id=workflow_id)
    return record


async def restart_init_arch_workflow(workflow_id: str) -> dict[str, typing.Any]:
    """Wipe every artifact of a workflow run so the same conversation can start `init_arch` again.

    Deletes files, DB rows, and the LangGraph checkpoint. Available from *any* status
    (`RUNNING`/`PAUSED`/`INTERRUPTED`/`FAILED`/`SUCCESS`/`CANCELLED`) - unlike `pause`, this isn't a
    stop, it's "I don't want this run anymore." See spec section 8 in
    arch-docs/docs/spec/2026-07-22-realtime-workflow-observability.md.

    Deliberately does *not* return a `WorkflowRecord` - there is no longer one. Returns the same
    shape `get_conversation_async()` already returns for a conversation with nothing running
    (`active_response: None`), plus a `previous_init_input` field so the frontend can pre-fill the
    "start init_arch" form with the product name/analysis scope/repo list the user typed in when
    creating this run - those live only inside this same `WorkflowRecord.session` (see
    `WorkflowSessionRecord`), so they must be captured before the delete below or they're gone for
    good and the user has to retype the whole repo list from scratch.
    """
    record = await get_workflow_record_async(workflow_id)
    conversation_id = record.conversation_id or workflow_id
    previous_init_input = _capture_init_input_for_restart(record)

    task = record.asyncio_task
    if task is not None and not task.done():
        task.cancel()
        # Must actually wait for the task to unwind (not just fire the cancel and move on, like
        # pause does) - run_cli_task()'s CancelledError cleanup (§7) needs to finish terminating any
        # in-flight CLI subprocess *before* we start deleting the workspace/arch-repo directories
        # that subprocess may still be writing into underneath it.
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(task, timeout=10.0)

    # Re-derive the same two workflow-owned subdirectories `start_init_arch_workflow()` resolved at
    # creation time - never touch `workspace_dir` itself, it's user-supplied and may be shared.
    _, resolved_arch_repo_dir, resolved_raw_workspace_dir = _resolve_init_arch_paths(
        workspace_dir=record.workspace_dir,
        arch_repo_dir=record.arch_repo_dir,
    )
    shutil.rmtree(resolved_raw_workspace_dir, ignore_errors=True)
    shutil.rmtree(resolved_arch_repo_dir, ignore_errors=True)

    checkpointer = await get_checkpointer()
    await checkpointer.adelete_thread(workflow_id)

    async with get_session() as session:
        await delete_cli_tasks_for_workflow(session, workflow_id)
        await delete_workflow_run(session, workflow_id)

    get_workflow_registry().pop(workflow_id, None)
    task_registry = get_task_registry()
    for task_id in [tid for tid, cli_task in task_registry.items() if cli_task.workflow_id == workflow_id]:
        task_registry.pop(task_id, None)

    logger.info("workflow.restarted", workflow_id=workflow_id, conversation_id=conversation_id)
    payload = await get_conversation_async(conversation_id)
    payload["previous_init_input"] = previous_init_input
    return payload


def _capture_init_input_for_restart(record: WorkflowRecord) -> dict[str, typing.Any] | None:
    session = record.session
    if session is None:
        return None
    repo_list = [repo.repository_url or repo.repository_name for repo in session.repositories]
    return {
        "product_name": session.product_name,
        "analysis_scope": session.analysis_scope,
        "workspace_dir": record.workspace_dir,
        "arch_repo_dir": record.arch_repo_dir,
        "repo_list": repo_list,
        # engine_name/timeout_seconds are only ever kept in the transient InitArchState passed to
        # `run_workflow()`, never persisted on WorkflowRecord/WorkflowSessionRecord - there is no
        # value to recover here, so these are left for the form's own defaults.
    }
