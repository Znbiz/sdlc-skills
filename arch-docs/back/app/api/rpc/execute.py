import asyncio
import uuid

import fastapi
import pydantic
import structlog
from fastapi import status

from app.services.agent_pool import get_agent_pool
from app.services.task_registry import CliTask, TaskStatus, get_registry
from app.services.task_runner import execute_engine_task

router = fastapi.APIRouter()
logger = structlog.get_logger()

_background_tasks: set[asyncio.Task] = set()


class ExecuteRequest(pydantic.BaseModel, frozen=True):
    engine: str
    prompt: str
    workspace: str = "/workspace"
    output_format: str = "stream-json"
    sandbox: str = "danger-full-access"
    allowed_tools: list[str] | None = None
    session_id: str | None = None
    timeout_seconds: int = 300
    provider_connection_id: str | None = None

    @pydantic.field_validator("engine")
    @classmethod
    def validate_engine(cls, engine_value: str) -> str:
        if engine_value not in ("claude", "codex", "langgraph"):
            msg = "engine must be 'claude', 'codex' or 'langgraph'"
            raise ValueError(msg)
        return engine_value

    @pydantic.model_validator(mode="after")
    def validate_provider_connection_requires_codex(self) -> "ExecuteRequest":
        if self.provider_connection_id is not None and self.engine not in ("codex", "langgraph"):
            msg = "provider_connection_id is only supported with engine='codex' or 'langgraph'"
            raise ValueError(msg)
        if self.provider_connection_id is None and self.engine == "langgraph":
            msg = "provider_connection_id is required for engine='langgraph'"
            raise ValueError(msg)
        return self


class ExecuteResponse(pydantic.BaseModel, frozen=True):
    task_id: str
    task_status: str
    created_at: str


@router.post("/execute/", status_code=status.HTTP_202_ACCEPTED)
async def execute(request: ExecuteRequest) -> ExecuteResponse:
    cli_task = CliTask(
        task_id=str(uuid.uuid4()),
        engine_name=request.engine,
        provider_connection_id=request.provider_connection_id,
        prompt_text=request.prompt,
        workspace_dir=request.workspace,
        sandbox_mode=request.sandbox,
        session_id=request.session_id,
        timeout_seconds=request.timeout_seconds,
    )

    registry = get_registry()
    registry[cli_task.task_id] = cli_task

    agent_pool = get_agent_pool()
    task = asyncio.create_task(execute_engine_task(cli_task, agent_pool))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    logger.info("cli_task.created", task_id=cli_task.task_id, engine=cli_task.engine_name)

    return ExecuteResponse(
        task_id=cli_task.task_id,
        task_status=TaskStatus.PENDING,
        created_at=cli_task.created_at.isoformat(),
    )
