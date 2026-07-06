from __future__ import annotations

import asyncio
import typing
import uuid

import fastapi
import pydantic
import structlog
from fastapi import status

from app.services.agent_pool import get_agent_pool
from app.services.task_registry import CliTask, TaskStatus, get_registry
from app.services.task_runner import run_cli_task

router = fastapi.APIRouter()
logger = structlog.get_logger()

_background_tasks: set[asyncio.Task] = set()

_UPDATE_ARCH_PROMPT_BASE: typing.Final = "/update-repo-arch-skill"


class UpdateArchRequest(pydantic.BaseModel, frozen=True):
    repo_path: str
    diff_context: str = ""
    engine_name: str = "claude"
    timeout_seconds: int = 600

    @pydantic.field_validator("engine_name")
    @classmethod
    def validate_engine_name(cls, value: str) -> str:
        if value not in ("claude", "codex"):
            msg = "engine_name must be 'claude' or 'codex'"
            raise ValueError(msg)
        return value


class QueryArchRequest(pydantic.BaseModel, frozen=True):
    question: str
    repo_path: str
    engine_name: str = "claude"
    timeout_seconds: int = 120

    @pydantic.field_validator("engine_name")
    @classmethod
    def validate_engine_name(cls, value: str) -> str:
        if value not in ("claude", "codex"):
            msg = "engine_name must be 'claude' or 'codex'"
            raise ValueError(msg)
        return value


class ArchOpTaskResponse(pydantic.BaseModel, frozen=True):
    task_id: str
    task_status: str
    created_at: str


def _enqueue_arch_task(
    prompt_text: str,
    workspace_dir: str,
    engine_name: str,
    timeout_seconds: int,
) -> CliTask:
    cli_task = CliTask(
        task_id=str(uuid.uuid4()),
        engine_name=engine_name,
        prompt_text=prompt_text,
        workspace_dir=workspace_dir,
        sandbox_mode="workspace-write",
        timeout_seconds=timeout_seconds,
    )
    registry = get_registry()
    registry[cli_task.task_id] = cli_task
    agent_pool = get_agent_pool()
    bg_task = asyncio.create_task(run_cli_task(cli_task, agent_pool))
    _background_tasks.add(bg_task)
    bg_task.add_done_callback(_background_tasks.discard)
    return cli_task


@router.post("/update-arch/", status_code=status.HTTP_202_ACCEPTED)
async def update_arch(request: UpdateArchRequest) -> ArchOpTaskResponse:
    prompt_text = (
        f"{_UPDATE_ARCH_PROMPT_BASE}\n{request.diff_context}" if request.diff_context else _UPDATE_ARCH_PROMPT_BASE
    )
    cli_task = _enqueue_arch_task(
        prompt_text=prompt_text,
        workspace_dir=request.repo_path,
        engine_name=request.engine_name,
        timeout_seconds=request.timeout_seconds,
    )
    logger.info("arch_op.update_arch.created", task_id=cli_task.task_id, repo_path=request.repo_path)
    return ArchOpTaskResponse(
        task_id=cli_task.task_id,
        task_status=TaskStatus.PENDING,
        created_at=cli_task.created_at.isoformat(),
    )


@router.post("/query-arch/", status_code=status.HTTP_202_ACCEPTED)
async def query_arch(request: QueryArchRequest) -> ArchOpTaskResponse:
    prompt_text = f"Прочитай arch-doc/ и ответь на вопрос: {request.question}"
    cli_task = _enqueue_arch_task(
        prompt_text=prompt_text,
        workspace_dir=request.repo_path,
        engine_name=request.engine_name,
        timeout_seconds=request.timeout_seconds,
    )
    logger.info("arch_op.query_arch.created", task_id=cli_task.task_id, repo_path=request.repo_path)
    return ArchOpTaskResponse(
        task_id=cli_task.task_id,
        task_status=TaskStatus.PENDING,
        created_at=cli_task.created_at.isoformat(),
    )
