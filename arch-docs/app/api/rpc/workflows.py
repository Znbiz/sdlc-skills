from __future__ import annotations

import typing

import fastapi
import pydantic
import structlog
from fastapi import status

from app.services.init_arch_workflow import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    WorkflowValidationError,
    answer_init_arch_question,
    cancel_init_arch_workflow,
    resume_init_arch_workflow,
    start_init_arch_workflow,
)

router = fastapi.APIRouter()
logger = structlog.get_logger()


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


class AnswerOpenQuestionRequest(pydantic.BaseModel, frozen=True):
    answer: str


def _not_found(exc: WorkflowNotFoundError) -> fastapi.HTTPException:
    return fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")


def _conflict(exc: WorkflowConflictError) -> fastapi.HTTPException:
    return fastapi.HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/workflows/init/", status_code=status.HTTP_202_ACCEPTED)
async def init_workflow(request: InitWorkflowRequest) -> InitWorkflowResponse:
    record = await start_init_arch_workflow(
        product_name=request.product_name,
        analysis_scope=request.analysis_scope,
        workspace_dir=request.workspace_dir,
        arch_repo_dir=request.arch_repo_dir,
        repo_list=request.repo_list,
        engine_name=request.engine_name,
        timeout_seconds=request.timeout_seconds,
    )
    return InitWorkflowResponse(
        workflow_id=record.workflow_id,
        workflow_status=record.workflow_status,
        current_step_id=record.current_step_id,
        created_at=record.created_at.isoformat(),
    )


@router.post("/workflows/{workflow_id}/resume/", status_code=status.HTTP_202_ACCEPTED)
async def resume_workflow(workflow_id: str, request: ResumeWorkflowRequest) -> ResumeWorkflowResponse:
    try:
        record = await resume_init_arch_workflow(
            workflow_id,
            field=request.field,
            value=request.value,
            answer=request.answer,
        )
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc
    except WorkflowConflictError as exc:
        raise _conflict(exc) from exc
    except WorkflowValidationError as exc:
        raise fastapi.HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return ResumeWorkflowResponse(
        workflow_id=record.workflow_id,
        workflow_status=record.workflow_status,
        current_step_id=record.current_step_id,
    )


@router.post("/workflows/{workflow_id}/questions/{question_id}/answer/", status_code=status.HTTP_202_ACCEPTED)
async def answer_open_question(
    workflow_id: str,
    question_id: str,
    request: AnswerOpenQuestionRequest,
) -> ResumeWorkflowResponse:
    try:
        record = await answer_init_arch_question(workflow_id, question_id=question_id, answer=request.answer)
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc
    except WorkflowConflictError as exc:
        raise _conflict(exc) from exc
    return ResumeWorkflowResponse(
        workflow_id=record.workflow_id,
        workflow_status=record.workflow_status,
        current_step_id=record.current_step_id,
    )


@router.delete("/workflows/{workflow_id}/")
async def cancel_workflow(workflow_id: str) -> ResumeWorkflowResponse:
    try:
        record = await cancel_init_arch_workflow(workflow_id)
    except WorkflowNotFoundError as exc:
        raise _not_found(exc) from exc
    except WorkflowConflictError as exc:
        raise _conflict(exc) from exc
    return ResumeWorkflowResponse(
        workflow_id=record.workflow_id,
        workflow_status=record.workflow_status,
        current_step_id=record.current_step_id,
    )
