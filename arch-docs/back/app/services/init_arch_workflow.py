from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import datetime
import json
import pathlib
import shutil
import typing
import uuid

import structlog
from langgraph.types import Command

from app.db.session import get_session
from app.db.task_repo import (
    delete_cli_tasks_for_conversation,
    delete_cli_tasks_for_workflow,
    get_cli_task,
    list_cli_tasks_for_conversation,
)
from app.db.workflow_repo import (
    create_conversation,
    delete_conversation,
    delete_workflow_run,
    get_conversation,
    get_workflow_run,
    list_conversation_items,
    list_conversations,
    list_required_actions,
    list_workflow_runs_for_conversation,
    update_conversation_product_name,
    update_conversation_repositories,
    upsert_workflow_run,
)
from app.services.agent_pool import get_agent_pool
from app.services.docs_browser import build_docs_tree, delete_docs_path, read_docs_file
from app.services.repository_url import canonicalize_repo_path, normalize_repository_url
from app.services.task_registry import CliTask, TaskStatus
from app.services.task_registry import get_registry as get_task_registry
from app.services.task_runner import cancel_cli_task, execute_engine_task
from app.services.workflow_event_bus import get_workflow_event_bus
from app.services.workflow_registry import WorkflowRecord, WorkflowStatus, get_workflow_registry
from app.settings import GatewaySettings, get_gateway_settings
from app.workflows.init_arch.checkpointer import get_checkpointer
from app.workflows.init_arch.domain import (
    RepositoryExecution,
    StepId,
    WorkflowSessionRecord,
    next_pending_checklist_item,
    route_checklist_items,
    step_label_ru,
)
from app.workflows.init_arch.graph import compile_graph
from app.workflows.init_arch.historical import get_historical_prep_service
from app.workflows.init_arch.prompts import CHECKLIST_ITEM_TO_REFERENCE
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
        "engine_name",
        "timeout_seconds",
    }
)


@dataclasses.dataclass(frozen=True)
class WorkflowTypeConfig:
    # None = не ограничено. Для init_arch — 1: общая на весь conversation arch_repo_dir
    # (см. раздел 1 в arch-docs/docs/spec/2026-07-23-per-workflow-workspace-and-browser.md)
    # безопасна только при максимум одном активном run одновременно.
    max_concurrent_instances_per_conversation: int | None
    # Читает ли этот тип workflow список репозиториев conversation при старте.
    uses_conversation_repositories: bool


WORKFLOW_TYPE_REGISTRY: typing.Final[dict[str, WorkflowTypeConfig]] = {
    "init_arch": WorkflowTypeConfig(
        max_concurrent_instances_per_conversation=1,
        uses_conversation_repositories=True,
    ),
}

# Тип, отсутствующий в реестре (все существующие CliTask-типы — update_arch/query), трактуется
# как неограниченный: они не привязаны к conversation_workspace_dir/arch_repo_dir, поэтому общий
# инвариант "максимум 1" на них не распространяется (см. "Что не входит" в спеке раздела 1).
_DEFAULT_WORKFLOW_TYPE_CONFIG: typing.Final = WorkflowTypeConfig(
    max_concurrent_instances_per_conversation=None,
    uses_conversation_repositories=False,
)


def _workflow_type_config(workflow_type: str) -> WorkflowTypeConfig:
    return WORKFLOW_TYPE_REGISTRY.get(workflow_type, _DEFAULT_WORKFLOW_TYPE_CONFIG)


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _ensure_directory(path: str) -> None:
    """Best-effort eager `mkdir -p`.

    Mirrors the file's existing "log and continue" convention for filesystem/DB side effects that
    aren't strictly required for the in-memory/DB state change to succeed (see
    `persist_workflow_record()`) - a workspace root that doesn't exist yet (e.g. a non-container
    dev/test environment, or a transient permissions issue) shouldn't block conversation/run
    creation; the directory gets created lazily anyway the first time a node actually writes into it
    (`_prepare_workspace_directories()` in nodes.py).
    """
    try:
        pathlib.Path(path).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("workspace.mkdir_failed", path=path, error=str(exc))


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


def _iso_date(value: datetime.date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _build_repository_statuses(record: WorkflowRecord) -> list[dict[str, typing.Any]]:
    session = record.session
    if session is None or not session.repositories:
        return []
    # Best-effort only (see `HistoricalPrepService.get_commit_dates()`) - a repo that isn't
    # cloned yet, or whose stored hash no longer resolves, just reports `None` dates rather than
    # failing the whole status response.
    commit_dates = get_historical_prep_service().get_commit_dates(session, workspace_dir=record.workspace_dir)
    all_checklist_item_ids = list(CHECKLIST_ITEM_TO_REFERENCE)
    return [
        {
            "repository_name": repository.repository_name,
            "repository_url": repository.repository_url,
            "main_branch": repository.main_branch,
            "remote_head_commit": repository.remote_head_commit,
            "remote_head_commit_date": _iso_date(
                commit_dates.get(repository.repository_name, {}).get("remote_head_commit_date")
            ),
            "analysis_target_commit": repository.analysis_target_commit,
            "analysis_target_commit_date": _iso_date(
                commit_dates.get(repository.repository_name, {}).get("analysis_target_commit_date")
            ),
            "analysis_status": repository.analysis_status,
            "commit_range_status": str(repository.commit_range_status.value),
            "checklist_items_completed": list(repository.checklist_items_completed),
            "checklist_items_routed": route_checklist_items(
                repository, all_checklist_item_ids=all_checklist_item_ids
            ),
            "current_checklist_item_id": (
                next_pending_checklist_item(repository, all_checklist_item_ids=all_checklist_item_ids)
                if repository.repository_name == record.current_repo_name
                else None
            ),
        }
        for repository in session.repositories
    ]


def _analysis_window(record: WorkflowRecord) -> tuple[str | None, str | None, int]:
    session = record.session
    if session is None:
        return None, None, 0
    historical = session.historical_analysis
    window_start = historical.previous_snapshot_at or historical.anchor_created_at
    return _iso_date(window_start), _iso_date(historical.current_snapshot_at), historical.window_index


def _workflow_response_payload(
    record: WorkflowRecord,
    required_actions: list[dict[str, typing.Any]],
) -> dict[str, typing.Any]:
    analysis_window_start, analysis_window_end, analysis_window_index = _analysis_window(record)
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
        "token_usage_by_model": {model_name: dict(usage) for model_name, usage in record.token_usage_by_model.items()},
        "required_actions": _serialize_required_actions(required_actions),
        "repositories": _build_repository_statuses(record),
        "analysis_window_start": analysis_window_start,
        "analysis_window_end": analysis_window_end,
        "analysis_window_index": analysis_window_index,
        "repository_list_editable": (
            record.workflow_status in {WorkflowStatus.PAUSED, WorkflowStatus.INTERRUPTED}
            and record.session is not None
            and record.session.current_step in _REPOSITORY_LIST_EDITABLE_STEPS
        ),
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


async def _refresh_token_usage_from_db(record: WorkflowRecord) -> None:
    """Refresh `record.token_usage_by_model` from `workflow_runs` before serializing a response.

    `_persist_token_usage()` (`cli_task_support.py`) writes usage straight to the DB - nothing ever
    updates the in-memory `WorkflowRecord` copy held in `get_workflow_registry()` while a workflow
    is running, so the "registry hit always wins over its DB snapshot" rule elsewhere in this file
    would otherwise permanently serve a stale, empty `token_usage_by_model` for any active run.
    """
    try:
        async with get_session() as session:
            db_record = await get_workflow_run(session, record.workflow_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("workflow.token_usage_refresh_failed", workflow_id=record.workflow_id, error=str(exc))
        return
    if db_record is not None:
        record.token_usage_by_model = db_record.token_usage_by_model


async def get_response_async(response_id: str) -> dict[str, typing.Any]:
    try:
        record = await get_workflow_record_async(response_id)
    except WorkflowNotFoundError:
        task = await get_cli_task_async(response_id)
        return _task_response_payload(task)

    await _refresh_token_usage_from_db(record)
    required_actions = await list_workflow_required_actions_async(response_id)
    if not required_actions:
        required_actions = _fallback_required_actions(record)
    return _workflow_response_payload(record, required_actions)


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
            product_name = conversation.product_name
            repositories = list(conversation.repositories or [])
    except Exception:  # noqa: BLE001
        created_at = now
        updated_at = now
        product_name = None
        repositories = []

    conversation_workspace_dir = _resolve_conversation_workspace_dir(resolved_conversation_id)
    _ensure_directory(conversation_workspace_dir)

    return {
        "conversation_id": resolved_conversation_id,
        "product_name": product_name,
        "repositories": repositories,
        "workspace_dir": conversation_workspace_dir,
        "created_at": created_at.isoformat(),
        "updated_at": updated_at.isoformat(),
        "active_response": None,
    }


async def get_conversation_async(conversation_id: str) -> dict[str, typing.Any]:
    active_record = _active_conversation_record(conversation_id)
    active_task = _active_conversation_task(conversation_id)
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    product_name: str | None = None
    repositories: list[dict[str, typing.Any]] = []
    conversation_found = False

    try:
        async with get_session() as session:
            conversation = await get_conversation(session, conversation_id)
            if conversation is not None:
                conversation_found = True
                created_at = conversation.created_at
                updated_at = conversation.updated_at
                product_name = conversation.product_name
                repositories = list(conversation.repositories or [])
            if active_record is None and active_task is None:
                runs = await list_workflow_runs_for_conversation(session, conversation_id=conversation_id)
                tasks = await list_cli_tasks_for_conversation(session, conversation_id=conversation_id)
            else:
                runs = []
                tasks = []
    except Exception as exc:  # noqa: BLE001
        logger.warning("conversation.load_failed", conversation_id=conversation_id, error=str(exc))
        runs = []
        tasks = []

    if active_record is None and runs:
        active_record = runs[0]
        created_at = created_at or active_record.created_at
        updated_at = updated_at or active_record.updated_at
    if active_task is None and tasks:
        active_task = tasks[0]
        created_at = created_at or active_task.created_at
        updated_at = updated_at or _task_updated_at(active_task)

    if not conversation_found and active_record is None and active_task is None:
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
        "product_name": product_name,
        "repositories": repositories,
        "workspace_dir": _resolve_conversation_workspace_dir(conversation_id),
        "created_at": (created_at or utcnow()).isoformat(),
        "updated_at": (updated_at or utcnow()).isoformat(),
        "active_response": active_response,
    }


async def list_conversations_async(*, limit: int = 20) -> list[dict[str, typing.Any]]:
    try:
        async with get_session() as session:
            conversations = await list_conversations(session, limit=limit)
            conversation_ids = [conversation.conversation_id for conversation in conversations]
    except Exception as exc:  # noqa: BLE001
        logger.warning("conversations.list_failed", error=str(exc))
        conversation_ids = []

    # Merge in conversations only present in the in-memory registry (a workflow currently
    # running/paused whose `conversations` row was written but not yet reflected in `conversation_ids`
    # above due to a race, or - defensively - not written at all) so an active run is never dropped
    # from the list.
    registry_conversation_ids = {
        record.conversation_id for record in get_workflow_registry().values() if record.conversation_id is not None
    }
    ordered_conversation_ids = list(dict.fromkeys([*conversation_ids, *registry_conversation_ids]))

    payloads: list[dict[str, typing.Any]] = []
    for conversation_id in ordered_conversation_ids:
        try:
            payloads.append(await get_conversation_async(conversation_id))
        except WorkflowNotFoundError:
            continue

    payloads.sort(key=lambda payload: payload["updated_at"], reverse=True)
    return payloads[:limit]


class ConversationNotFoundError(WorkflowNotFoundError):
    pass


async def _require_conversation(conversation_id: str) -> None:
    async with get_session() as session:
        conversation = await get_conversation(session, conversation_id)
    if conversation is None:
        raise ConversationNotFoundError(f"Conversation {conversation_id!r} not found")


def _repository_entry_payload(repository: RepositoryExecution) -> dict[str, str]:
    return {"repository_name": repository.repository_name, "repository_url": repository.repository_url}


async def get_conversation_repositories_async(conversation_id: str) -> list[dict[str, str]]:
    await _require_conversation(conversation_id)
    repositories = await _load_conversation_repositories(conversation_id)
    return [_repository_entry_payload(repository) for repository in repositories]


async def set_conversation_repositories_async(conversation_id: str, entries: list[str]) -> list[dict[str, str]]:
    await _require_conversation(conversation_id)
    repositories = [await _parse_repo_list_entry(entry) for entry in entries]
    async with get_session() as session:
        await update_conversation_repositories(
            session,
            conversation_id=conversation_id,
            repositories=[_repository_entry_payload(repository) for repository in repositories],
        )
    return [_repository_entry_payload(repository) for repository in repositories]


async def add_conversation_repository_async(conversation_id: str, entry: str) -> list[dict[str, str]]:
    await _require_conversation(conversation_id)
    repositories = await _load_conversation_repositories(conversation_id)
    new_repository = await _parse_repo_list_entry(entry)
    if any(repository.repository_name == new_repository.repository_name for repository in repositories):
        raise WorkflowValidationError(f"Repository {new_repository.repository_name!r} is already tracked")
    return await set_conversation_repositories_async(
        conversation_id, [repo.repository_url or repo.repository_name for repo in [*repositories, new_repository]]
    )


async def remove_conversation_repository_async(conversation_id: str, repository_name: str) -> list[dict[str, str]]:
    await _require_conversation(conversation_id)
    repositories = await _load_conversation_repositories(conversation_id)
    remaining = [repository for repository in repositories if repository.repository_name != repository_name]
    if len(remaining) == len(repositories):
        raise WorkflowValidationError(f"Repository {repository_name!r} is not tracked")
    return await set_conversation_repositories_async(
        conversation_id, [repo.repository_url or repo.repository_name for repo in remaining]
    )


async def update_conversation_product_name_async(conversation_id: str, product_name: str) -> dict[str, typing.Any]:
    await _require_conversation(conversation_id)
    async with get_session() as session:
        await update_conversation_product_name(session, conversation_id=conversation_id, product_name=product_name)
    return await get_conversation_async(conversation_id)


async def delete_conversation_async(conversation_id: str) -> None:
    await _require_conversation(conversation_id)

    workflow_registry = get_workflow_registry()
    registry_records = [
        record
        for record in workflow_registry.values()
        if (record.conversation_id or record.workflow_id) == conversation_id
    ]
    for record in registry_records:
        task = record.asyncio_task
        if task is None or task.done():
            continue
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(task, timeout=10.0)

    task_registry = get_task_registry()
    registry_task_ids = [task_id for task_id, task in task_registry.items() if task.conversation_id == conversation_id]
    for task_id in registry_task_ids:
        await cancel_cli_task(task_id, task_registry)

    async with get_session() as session:
        db_records = await list_workflow_runs_for_conversation(session, conversation_id=conversation_id)
        workflow_ids = {record.workflow_id for record in db_records}
        workflow_ids.update(record.workflow_id for record in registry_records)

        if workflow_ids:
            checkpointer = await get_checkpointer()
            for workflow_id in workflow_ids:
                await checkpointer.adelete_thread(workflow_id)

        await delete_cli_tasks_for_conversation(session, conversation_id)
        await delete_conversation(session, conversation_id)

    for record in registry_records:
        workflow_registry.pop(record.workflow_id, None)
    for task_id in registry_task_ids:
        task_registry.pop(task_id, None)

    shutil.rmtree(_resolve_conversation_workspace_dir(conversation_id), ignore_errors=True)
    logger.info("conversation.deleted", conversation_id=conversation_id)


async def list_conversation_responses_async(conversation_id: str) -> list[dict[str, typing.Any]]:
    """List every run (`workflow_id`) of this conversation, most recently updated first.

    Merges the DB (`workflow_runs`, authoritative for anything not currently active) with the
    in-memory registry (authoritative for a run's live status while this process holds it) the same
    way `get_response_async()`/`_active_conversation_record()` already do for a single run - a
    registry hit always wins over its DB snapshot.
    """
    await _require_conversation(conversation_id)
    try:
        async with get_session() as session:
            db_records = await list_workflow_runs_for_conversation(session, conversation_id=conversation_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("conversation.responses_list_failed", conversation_id=conversation_id, error=str(exc))
        db_records = []

    registry = get_workflow_registry()
    records_by_id = {record.workflow_id: record for record in db_records}
    # token_usage_by_model is only ever updated in the DB (see `_refresh_token_usage_from_db`) - a
    # registry hit is used for everything else, but its `token_usage_by_model` is patched in from
    # the DB snapshot we already fetched above, instead of trusting the stale in-memory value.
    db_token_usage_by_id = {record.workflow_id: record.token_usage_by_model for record in db_records}
    for record in registry.values():
        if (record.conversation_id or record.workflow_id) == conversation_id:
            if record.workflow_id in db_token_usage_by_id:
                record.token_usage_by_model = db_token_usage_by_id[record.workflow_id]
            records_by_id[record.workflow_id] = record

    ordered_records = sorted(records_by_id.values(), key=lambda record: record.updated_at, reverse=True)
    payloads: list[dict[str, typing.Any]] = []
    for record in ordered_records:
        required_actions = await list_workflow_required_actions_async(record.workflow_id)
        if not required_actions:
            required_actions = _fallback_required_actions(record)
        payloads.append(_workflow_response_payload(record, required_actions))
    return payloads


async def build_conversation_workspace_tree_async(conversation_id: str) -> dict[str, typing.Any]:
    await _require_conversation(conversation_id)
    workspace_dir = _resolve_conversation_workspace_dir(conversation_id)
    # Self-heal for conversations created before eager directory creation was introduced
    # (see create_conversation_async()) - without this, build_docs_tree() raises an unhandled
    # FileNotFoundError instead of returning an empty tree for a pre-existing conversation.
    _ensure_directory(workspace_dir)
    return build_docs_tree(workspace_dir)


async def read_conversation_workspace_file_async(conversation_id: str, path: str) -> dict[str, typing.Any]:
    await _require_conversation(conversation_id)
    workspace_dir = _resolve_conversation_workspace_dir(conversation_id)
    _ensure_directory(workspace_dir)
    return read_docs_file(workspace_dir, path)


async def delete_conversation_workspace_path_async(conversation_id: str, path: str) -> None:
    await _require_conversation(conversation_id)
    workspace_dir = _resolve_conversation_workspace_dir(conversation_id)
    _ensure_directory(workspace_dir)
    delete_docs_path(workspace_dir, path)


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
    task = asyncio.create_task(execute_engine_task(cli_task, get_agent_pool()))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return cli_task


def _build_update_arch_prompt(diff_context: str) -> str:
    return f"{_UPDATE_ARCH_PROMPT_BASE}\n{diff_context}" if diff_context else _UPDATE_ARCH_PROMPT_BASE


def _build_query_prompt(question: str) -> str:
    return f"Прочитай arch-doc/ и ответь на вопрос: {question}"


def _validate_engine_name(engine_name: str) -> str:
    if engine_name not in {"claude", "codex", "langgraph"}:
        raise WorkflowValidationError("engine_name must be 'claude', 'codex' or 'langgraph'")
    return engine_name


def _validate_provider_connection_id(engine_name: str, provider_connection_id: str | None) -> str | None:
    # An external LLM connection under `codex` always runs under codex (see
    # arch-docs/docs/spec/2026-07-24-external-llm-provider.md, section 3) - claude does not go
    # through this mechanism. `langgraph` is the inverse case: it *only* talks to an external
    # connection (there is no built-in auth to fall back on), so a connection is mandatory - see
    # arch-docs/docs/spec/2026-07-25-langgraph-api-agent-runner.md, section 1.
    if provider_connection_id is not None and engine_name not in ("codex", "langgraph"):
        msg = "provider_connection_id is only supported with engine_name='codex' or 'langgraph'"
        raise WorkflowValidationError(msg)
    if provider_connection_id is None and engine_name == "langgraph":
        raise WorkflowValidationError("provider_connection_id is required for engine_name='langgraph'")
    return provider_connection_id


_ACTIVE_WORKFLOW_STATUSES: typing.Final = {WorkflowStatus.RUNNING, WorkflowStatus.PAUSED, WorkflowStatus.INTERRUPTED}


def _count_active_conversation_workflows(conversation_id: str) -> int:
    # Same in-process-only limitation as the existing guard in
    # `resume_init_arch_workflow_from_snapshot()` - this only sees workflows tracked by this
    # process's in-memory registry, not other processes/instances.
    return sum(
        1
        for record in get_workflow_registry().values()
        if (record.conversation_id or record.workflow_id) == conversation_id
        and record.workflow_status in _ACTIVE_WORKFLOW_STATUSES
    )


async def _sync_forward_product_name_if_empty(conversation_id: str, product_name: str) -> None:
    try:
        async with get_session() as session:
            conversation = await get_conversation(session, conversation_id)
            if conversation is not None and not conversation.product_name:
                await update_conversation_product_name(
                    session, conversation_id=conversation_id, product_name=product_name
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("conversation.product_name_sync_failed", conversation_id=conversation_id, error=str(exc))


async def create_response_async(
    *,
    conversation_id: str,
    workflow_type: str,
    input_payload: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    await create_conversation_async(conversation_id)

    type_config = _workflow_type_config(workflow_type)
    if type_config.max_concurrent_instances_per_conversation is not None:
        active_count = _count_active_conversation_workflows(conversation_id)
        if active_count >= type_config.max_concurrent_instances_per_conversation:
            raise WorkflowConflictError(
                f"conversation {conversation_id!r} already has {active_count} active {workflow_type!r} "
                f"run(s); max_concurrent_instances_per_conversation="
                f"{type_config.max_concurrent_instances_per_conversation}"
            )

    if workflow_type == "init_arch":
        missing_fields = sorted(_INIT_ARCH_REQUIRED_FIELDS - input_payload.keys())
        if missing_fields:
            raise WorkflowValidationError(f"init_arch requires fields: {', '.join(missing_fields)}")
        if type_config.uses_conversation_repositories:
            repositories = await _load_conversation_repositories(conversation_id)
            if not repositories:
                raise WorkflowValidationError(
                    "conversation has no repositories configured; add at least one repository "
                    "(POST /conversations/{id}/repositories/) before starting init_arch"
                )
        product_name = str(input_payload.get("product_name") or "").strip()
        if product_name:
            await _sync_forward_product_name_if_empty(conversation_id, product_name)
        record = await start_init_arch_workflow(conversation_id=conversation_id, **input_payload)
        return await get_response_async(record.workflow_id)

    if workflow_type == "update_arch":
        repo_path = str(input_payload.get("repo_path", ""))
        if not repo_path:
            raise WorkflowValidationError("update_arch requires repo_path")
        prompt_text = _build_update_arch_prompt(str(input_payload.get("diff_context", "")))
        engine_name = _validate_engine_name(str(input_payload.get("engine_name", "claude")))
        provider_connection_id = _validate_provider_connection_id(
            engine_name, input_payload.get("provider_connection_id")
        )
        cli_task = CliTask(
            task_id=str(uuid.uuid4()),
            engine_name=engine_name,
            provider_connection_id=provider_connection_id,
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
        provider_connection_id = _validate_provider_connection_id(
            engine_name, input_payload.get("provider_connection_id")
        )
        cli_task = CliTask(
            task_id=str(uuid.uuid4()),
            engine_name=engine_name,
            provider_connection_id=provider_connection_id,
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

    await _dispatch_workflow_action(
        response_id, action_type=action_type, question_id=question_id, answer=answer, field=field, value=value
    )
    return await get_response_async(response_id)


def _require_string_value(action_type: str, value: typing.Any) -> str:
    if not value or not str(value).strip():
        raise WorkflowValidationError(f"{action_type} requires a non-empty value")
    return str(value)


async def _dispatch_workflow_action(
    response_id: str,
    *,
    action_type: str,
    question_id: str | None,
    answer: str | None,
    field: str | None,
    value: typing.Any,
) -> None:
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
    elif action_type == "add_repository":
        await add_repository_to_workflow(response_id, repo_entry=_require_string_value(action_type, value))
    elif action_type == "remove_repository":
        await remove_repository_from_workflow(response_id, repository_name=_require_string_value(action_type, value))
    else:
        raise WorkflowValidationError(f"Unsupported action_type: {action_type}")


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

        # Must be `Command(resume=...)`, not the bare resume_value dict: langgraph only resumes
        # the pending `interrupt()` call in place (e.g. staying inside `assess_scope_and_domains`)
        # when the input is a Command. A plain dict input is instead treated as a brand-new
        # invocation and restarts the whole graph from START - re-running (and, per
        # node_clone_repositories, re-cloning) every upstream step on every single resume/retry.
        # Confirmed against a real langgraph MemorySaver run before fixing.
        #
        # `resume_value is None` (continue_init_arch_workflow: PAUSED -> RUNNING with nothing to
        # feed a pending interrupt(), because a pause is a plain cancellation, not an interrupt())
        # is a distinct case that must NOT go through Command: `Command(resume=None)` against a
        # thread with no pending interrupt() hits a real langgraph bug - an UnboundLocalError on its
        # internal `resume_is_map` (langgraph 1.2.7, `pregel/_loop.py`, confirmed via a real e2e run
        # against Postgres before fixing). langgraph's own contract for "no interrupt, just carry on
        # from the last checkpoint" is a bare `None` stream input - the same one `run_workflow()`'s
        # `as_node`-resume path already uses.
        stream_input = Command(resume=resume_value) if resume_value is not None else None
        failed = await _drive_graph_stream(record, graph, config, stream_input)
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


def _resolve_conversation_workspace_dir(conversation_id: str, *, settings: GatewaySettings | None = None) -> str:
    resolved_settings = settings or get_gateway_settings()
    return str((pathlib.Path(resolved_settings.workspace_dir) / conversation_id).resolve())


def _resolve_init_arch_paths(
    *,
    workspace_dir: str,
    arch_repo_dir: str,
    settings: GatewaySettings | None = None,
) -> tuple[str, str, str]:
    resolved_settings = settings or get_gateway_settings()
    workspace_path = pathlib.Path(workspace_dir).expanduser().resolve()
    # `raw_workspace_path` (`.temp/`) is project-level, not per-run: repositories are artifacts of
    # the conversation, shared and reused by every workflow run in it, not scoped to whichever
    # `workflow_id` happened to clone them first. `_clone_repositories()` (nodes.py) always deletes
    # and re-clones on top of it, so a stale/partial checkout from an earlier run is never trusted.
    raw_workspace_path = (workspace_path / ".temp").resolve()
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


async def _parse_repo_list_entry(entry: str) -> RepositoryExecution:
    stripped = entry.strip()
    if "://" in stripped or stripped.startswith("git@"):
        normalized_url = await normalize_repository_url(stripped)
        repository_name = canonicalize_repo_path(normalized_url).rsplit("/", 1)[-1]
        return RepositoryExecution(repository_name=repository_name, repository_url=normalized_url)
    return RepositoryExecution(repository_name=stripped)


async def _load_conversation_repositories(conversation_id: str) -> list[RepositoryExecution]:
    """Read the conversation-level repository list (see `set_conversation_repositories_async()`).

    Entries are already normalized (canonical clone URL, derived name) at the point they were
    added to the conversation, so this just deserializes - no re-parsing needed.
    """
    try:
        async with get_session() as session:
            conversation = await get_conversation(session, conversation_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("conversation.repositories_load_failed", conversation_id=conversation_id, error=str(exc))
        return []
    if conversation is None:
        return []
    return [RepositoryExecution.model_validate(entry) for entry in conversation.repositories or []]


async def start_init_arch_workflow(
    *,
    product_name: str,
    analysis_scope: str,
    workspace_dir: str,
    arch_repo_dir: str,
    engine_name: str,
    timeout_seconds: int,
    conversation_id: str | None = None,
    repo_list: list[str] | None = None,
    provider_connection_id: str | None = None,
) -> WorkflowRecord:
    """Start a fresh `init_arch` run.

    `repo_list` is a direct-call escape hatch (used by tests and `resume_init_arch_workflow_from_snapshot()`-
    adjacent tooling) - the REST-facing path (`create_response_async()`) never passes it and this
    reads `conversation.repositories` instead (raise "список репозиториев — настройка conversation",
    see arch-docs/docs/spec/2026-07-23-per-workflow-workspace-and-browser.md section 2).
    """
    workflow_id = str(uuid.uuid4())
    resolved_workspace_dir, resolved_arch_repo_dir, resolved_raw_workspace_dir = _resolve_init_arch_paths(
        workspace_dir=workspace_dir,
        arch_repo_dir=arch_repo_dir,
    )
    provider_connection_id = _validate_provider_connection_id(engine_name, provider_connection_id)
    progress_file_path = f"{resolved_arch_repo_dir}/repo-initialization-progress.yaml"
    if repo_list is not None:
        repositories = [await _parse_repo_list_entry(repo_entry) for repo_entry in repo_list]
    else:
        repositories = await _load_conversation_repositories(conversation_id or workflow_id)
    _ensure_directory(resolved_raw_workspace_dir)
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
        provider_connection_id=provider_connection_id,
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
    provider_connection_id: str | None = None,
) -> WorkflowRecord:
    snapshot = parse_snapshot_yaml(yaml_text)
    workflow_id = str(uuid.uuid4())
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

    progress_file_path = f"{resolved_arch_repo_dir}/repo-initialization-progress.yaml"
    _ensure_directory(resolved_raw_workspace_dir)
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
        provider_connection_id=provider_connection_id or snapshot.provider_connection_id,
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


# Editing the repository list is only safe before `plan_repository_order` has run - that step
# (and `resolve_target_commits` after it) computes `historical_analysis.ordered_repository_names`,
# `analysis_target_date`/`analysis_target_commit` etc. for the *whole* repository set in one pass
# (see historical.py). A repo added/removed after that point would leave those derived fields
# inconsistent for the rest of the run. Restricting edits to this window keeps `session.repositories`
# always freshly (re)computed downstream, so no special-casing is needed there.
_REPOSITORY_LIST_EDITABLE_STEPS: typing.Final[frozenset[StepId]] = frozenset(
    {StepId.REQUEST_REPOSITORY_LIST, StepId.PREPARE_TEMP_WORKSPACE, StepId.CLONE_REPOSITORIES}
)


def _ensure_repository_list_editable(record: WorkflowRecord) -> WorkflowSessionRecord:
    if record.workflow_status not in {WorkflowStatus.PAUSED, WorkflowStatus.INTERRUPTED}:
        raise WorkflowConflictError(
            "Repository list is only editable while the workflow is paused or interrupted "
            f"(status: {record.workflow_status})"
        )
    if record.session is None:
        raise WorkflowValidationError("Workflow session is not initialized yet")
    if record.session.current_step not in _REPOSITORY_LIST_EDITABLE_STEPS:
        raise WorkflowConflictError(
            "Repository list can only be edited before repository order planning "
            f"(current step: {record.session.current_step.value})"
        )
    return record.session


async def _update_workflow_session_checkpoint(record: WorkflowRecord, session: WorkflowSessionRecord) -> None:
    """Patch the paused/interrupted LangGraph checkpoint's `session` key so a resume picks up the edit.

    `record.session` is a projection kept in sync via `apply_node_output()` - it is not what
    `continue_init_arch_workflow()`/`retry_init_arch_workflow()` actually resume from. Those replay
    from the LangGraph checkpoint keyed by `thread_id=workflow_id`, so an edit that only touches
    `record.session` would be silently discarded on resume. `aupdate_state()` is the same mechanism
    LangGraph's human-in-the-loop pattern uses to let a caller edit state while a thread is
    interrupted, before resuming it.
    """
    checkpointer = await get_checkpointer()
    graph = compile_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": record.workflow_id}}
    await graph.aupdate_state(config, {"session": session})


async def add_repository_to_workflow(workflow_id: str, *, repo_entry: str) -> WorkflowRecord:
    record = await get_workflow_record_async(workflow_id)
    session = _ensure_repository_list_editable(record)

    new_repository = await _parse_repo_list_entry(repo_entry)
    if any(repository.repository_name == new_repository.repository_name for repository in session.repositories):
        raise WorkflowValidationError(f"Repository {new_repository.repository_name!r} is already tracked")

    updated_session = session.model_copy(update={"repositories": [*session.repositories, new_repository]})
    await _update_workflow_session_checkpoint(record, updated_session)
    record.session = updated_session
    record.updated_at = utcnow()
    await persist_workflow_record(record)
    logger.info("workflow.repository.added", workflow_id=workflow_id, repository_name=new_repository.repository_name)
    return record


async def remove_repository_from_workflow(workflow_id: str, *, repository_name: str) -> WorkflowRecord:
    record = await get_workflow_record_async(workflow_id)
    session = _ensure_repository_list_editable(record)

    remaining = [repository for repository in session.repositories if repository.repository_name != repository_name]
    if len(remaining) == len(session.repositories):
        raise WorkflowValidationError(f"Repository {repository_name!r} is not tracked")
    if not remaining:
        raise WorkflowValidationError("Cannot remove the last remaining repository")

    updated_session = session.model_copy(update={"repositories": remaining})
    await _update_workflow_session_checkpoint(record, updated_session)
    record.session = updated_session
    record.updated_at = utcnow()
    await persist_workflow_record(record)
    logger.info("workflow.repository.removed", workflow_id=workflow_id, repository_name=repository_name)
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
    """Wipe this workflow run's DB rows and LangGraph checkpoint so the conversation can restart.

    Deletes DB rows and the LangGraph checkpoint. Available from *any* status
    (`RUNNING`/`PAUSED`/`INTERRUPTED`/`FAILED`/`SUCCESS`/`CANCELLED`) - unlike `pause`, this isn't a
    stop, it's "I don't want this run anymore." See spec section 8 in
    arch-docs/docs/spec/2026-07-22-realtime-workflow-observability.md.

    Nothing on disk is deleted: `workspace_dir`/`arch_repo_dir` (accumulated documentation) and the
    raw repository clones under `workspace_dir/.temp/` are all project-level artifacts shared by
    every run of this conversation, not scratch owned by this one run -
    `_clone_repositories()` (nodes.py) already deletes and re-clones on top of them fresh at the
    start of the next run regardless of what this run left behind (see
    arch-docs/docs/spec/2026-07-23-per-workflow-workspace-and-browser.md).

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
        # in-flight CLI subprocess and its own DB/task-result writes *before* we start deleting the
        # DB rows and checkpoint below, or the two race.
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(task, timeout=10.0)

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
    # `repo_list` is deliberately absent - repositories are now a conversation-level setting
    # (`conversation.repositories`, see section 2 of the spec) that survives restart on its own;
    # there is no longer a per-run copy to recover here.
    return {
        "product_name": session.product_name,
        "analysis_scope": session.analysis_scope,
        "workspace_dir": record.workspace_dir,
        "arch_repo_dir": record.arch_repo_dir,
        # engine_name/timeout_seconds are only ever kept in the transient InitArchState passed to
        # `run_workflow()`, never persisted on WorkflowRecord/WorkflowSessionRecord - there is no
        # value to recover here, so these are left for the form's own defaults.
    }
