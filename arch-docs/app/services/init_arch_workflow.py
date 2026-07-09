from __future__ import annotations

import asyncio
import datetime
import typing
import uuid

import structlog

from app.db.session import get_session
from app.db.workflow_repo import get_workflow_run, upsert_workflow_run
from app.services.workflow_registry import WorkflowRecord, WorkflowStatus, get_workflow_registry
from app.workflows.init_arch.checkpointer import get_checkpointer
from app.workflows.init_arch.domain import RepositoryExecution, WorkflowSessionRecord
from app.workflows.init_arch.graph import compile_graph
from app.workflows.init_arch.state import InitArchState

logger = structlog.get_logger()

_background_tasks: set[asyncio.Task[None]] = set()


class WorkflowNotFoundError(LookupError):
    pass


class WorkflowConflictError(RuntimeError):
    pass


class WorkflowValidationError(ValueError):
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
    raise WorkflowValidationError("Invalid resume payload for interrupt type")


async def start_init_arch_workflow(
    *,
    product_name: str,
    analysis_scope: str,
    workspace_dir: str,
    arch_repo_dir: str,
    repo_list: list[str],
    engine_name: str,
    timeout_seconds: int,
) -> WorkflowRecord:
    workflow_id = str(uuid.uuid4())
    progress_file_path = f"{arch_repo_dir}/repo-initialization-progress.yaml"
    session = WorkflowSessionRecord(
        session_id=workflow_id,
        product_name=product_name,
        analysis_scope=analysis_scope,
        repositories=[RepositoryExecution(repository_name=repo_name) for repo_name in repo_list],
    )

    record = WorkflowRecord(workflow_id=workflow_id, conversation_id=workflow_id, session=session)
    registry = get_workflow_registry()
    registry[workflow_id] = record
    await persist_workflow_record(record)

    initial_state = InitArchState(
        session_id=session.session_id,
        session=session,
        workspace_dir=workspace_dir,
        arch_repo_dir=arch_repo_dir,
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
