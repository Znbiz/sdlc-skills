from __future__ import annotations

import asyncio
import datetime
import typing
import uuid

import fastapi
import pydantic
import structlog
from fastapi import status

from app.services.workflow_registry import WorkflowRecord, WorkflowStatus, get_workflow_registry
from app.workflows.init_arch.checkpointer import get_checkpointer
from app.workflows.init_arch.graph import compile_graph
from app.workflows.init_arch.state import InitArchState

router = fastapi.APIRouter()
logger = structlog.get_logger()

_background_tasks: set[asyncio.Task] = set()


class InitWorkflowRequest(pydantic.BaseModel, frozen=True):
    product_name: str
    analysis_scope: str = "full"
    workspace_dir: str
    arch_repo_dir: str
    repo_list: list[str] = pydantic.Field(default_factory=list)
    engine_name: str = "claude"
    timeout_seconds: int = 600


class InitWorkflowResponse(pydantic.BaseModel, frozen=True):
    workflow_id: str
    workflow_status: str
    current_step_id: str
    created_at: str


class ResumeWorkflowRequest(pydantic.BaseModel, frozen=True):
    field: str | None = None
    value: typing.Any = None
    answer: str | None = None


class ResumeWorkflowResponse(pydantic.BaseModel, frozen=True):
    workflow_id: str
    workflow_status: str
    current_step_id: str


async def _run_workflow(record: WorkflowRecord, initial_state: InitArchState) -> None:
    registry = get_workflow_registry()
    try:
        checkpointer = await get_checkpointer()
        graph = compile_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": record.workflow_id}}

        async for event in graph.astream(initial_state, config=config):
            for node_name, node_output in event.items():
                if node_name == "__interrupt__":
                    record.workflow_status = WorkflowStatus.INTERRUPTED
                    interrupt_data = node_output[0].value if node_output else {}
                    record.pending_interrupt = interrupt_data
                    record.updated_at = datetime.datetime.now(datetime.timezone.utc)
                    logger.info("workflow.interrupted", workflow_id=record.workflow_id, interrupt=interrupt_data)
                    return
                if isinstance(node_output, dict):
                    if "current_step_id" in node_output:
                        record.current_step_id = node_output["current_step_id"]
                    if "completed_steps" in node_output:
                        record.completed_steps = node_output["completed_steps"]
                    if "current_repo_name" in node_output:
                        record.current_repo_name = node_output["current_repo_name"]
                    if "last_cli_output" in node_output:
                        record.last_cli_output_snippet = str(node_output["last_cli_output"])[:500]
                    record.updated_at = datetime.datetime.now(datetime.timezone.utc)

        record.workflow_status = WorkflowStatus.SUCCESS
        record.updated_at = datetime.datetime.now(datetime.timezone.utc)
        logger.info("workflow.completed", workflow_id=record.workflow_id)

    except Exception as exc:  # noqa: BLE001
        record.workflow_status = WorkflowStatus.FAILED
        record.error_message = str(exc)
        record.updated_at = datetime.datetime.now(datetime.timezone.utc)
        logger.error("workflow.failed", workflow_id=record.workflow_id, error=str(exc))
    finally:
        registry.pop(record.workflow_id, None)
        registry[record.workflow_id] = record


@router.post("/workflows/init/", status_code=status.HTTP_202_ACCEPTED)
async def init_workflow(request: InitWorkflowRequest) -> InitWorkflowResponse:
    workflow_id = str(uuid.uuid4())
    progress_file_path = f"{request.arch_repo_dir}/repo-initialization-progress.yaml"

    record = WorkflowRecord(workflow_id=workflow_id)
    registry = get_workflow_registry()
    registry[workflow_id] = record

    initial_state = InitArchState(
        product_name=request.product_name,
        analysis_scope=request.analysis_scope,
        workspace_dir=request.workspace_dir,
        arch_repo_dir=request.arch_repo_dir,
        engine_name=request.engine_name,
        timeout_seconds=request.timeout_seconds,
        progress_file_path=progress_file_path,
        current_step_id="define_scope",
        current_repo_name="",
        completed_steps=[],
        repo_list=list(request.repo_list),
        domain_strategy="",
        open_questions=[],
        answered_questions=[],
        pending_user_question="",
        last_cli_output="",
        last_guard_output="",
        step_error=None,
        retry_count=0,
    )

    task = asyncio.create_task(_run_workflow(record, initial_state))
    record.asyncio_task = task
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    logger.info("workflow.init.started", workflow_id=workflow_id, product=request.product_name)

    return InitWorkflowResponse(
        workflow_id=workflow_id,
        workflow_status=record.workflow_status,
        current_step_id=record.current_step_id,
        created_at=record.created_at.isoformat(),
    )


def _build_resume_value(interrupt_type: str, request: ResumeWorkflowRequest) -> typing.Any:
    if interrupt_type == "user_input" and request.field and request.value is not None:
        return {request.field: request.value}
    if interrupt_type == "user_question" and request.answer is not None:
        return {"answer": request.answer}
    raise fastapi.HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Invalid resume payload for interrupt type",
    )


async def _resume_workflow_task(record: WorkflowRecord, resume_value: typing.Any) -> None:
    try:
        checkpointer = await get_checkpointer()
        graph = compile_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": record.workflow_id}}
        async for event in graph.astream(resume_value, config=config):
            for node_name, node_output in event.items():
                if node_name == "__interrupt__":
                    record.workflow_status = WorkflowStatus.INTERRUPTED
                    record.pending_interrupt = node_output[0].value if node_output else {}
                    record.updated_at = datetime.datetime.now(datetime.timezone.utc)
                    return
                if isinstance(node_output, dict):
                    if "current_step_id" in node_output:
                        record.current_step_id = node_output["current_step_id"]
                    if "completed_steps" in node_output:
                        record.completed_steps = node_output["completed_steps"]
                    record.updated_at = datetime.datetime.now(datetime.timezone.utc)
        record.workflow_status = WorkflowStatus.SUCCESS
        record.updated_at = datetime.datetime.now(datetime.timezone.utc)
    except Exception as exc:  # noqa: BLE001
        record.workflow_status = WorkflowStatus.FAILED
        record.error_message = str(exc)
        record.updated_at = datetime.datetime.now(datetime.timezone.utc)


@router.post("/workflows/{workflow_id}/resume/", status_code=status.HTTP_202_ACCEPTED)
async def resume_workflow(workflow_id: str, request: ResumeWorkflowRequest) -> ResumeWorkflowResponse:
    registry = get_workflow_registry()
    record = registry.get(workflow_id)
    if record is None:
        raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if record.workflow_status != WorkflowStatus.INTERRUPTED:
        raise fastapi.HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Workflow is not interrupted (status: {record.workflow_status})",
        )

    interrupt_type = (record.pending_interrupt or {}).get("interrupt_type", "")
    resume_value = _build_resume_value(interrupt_type, request)

    record.workflow_status = WorkflowStatus.RUNNING
    record.pending_interrupt = None
    record.updated_at = datetime.datetime.now(datetime.timezone.utc)

    task = asyncio.create_task(_resume_workflow_task(record, resume_value))
    record.asyncio_task = task
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    logger.info("workflow.resumed", workflow_id=workflow_id)

    return ResumeWorkflowResponse(
        workflow_id=workflow_id,
        workflow_status=record.workflow_status,
        current_step_id=record.current_step_id,
    )
