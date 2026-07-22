from __future__ import annotations

import asyncio  # noqa: TC003
import dataclasses
import datetime
import enum
import typing

from app.workflows.init_arch.domain import WorkflowSessionRecord


class WorkflowStatus(enum.StrEnum):
    RUNNING = enum.auto()
    INTERRUPTED = enum.auto()
    PAUSED = enum.auto()
    SUCCESS = enum.auto()
    FAILED = enum.auto()
    CANCELLED = enum.auto()


@dataclasses.dataclass(kw_only=True, slots=True)
class WorkflowRecord:
    workflow_id: str
    conversation_id: str | None = None
    workflow_status: WorkflowStatus = WorkflowStatus.RUNNING
    current_step_id: str = "define_scope"
    current_repo_name: str = ""
    workspace_dir: str = ""
    arch_repo_dir: str = ""
    completed_steps: list[str] = dataclasses.field(default_factory=list)
    session: WorkflowSessionRecord | None = None
    pending_interrupt: dict[str, typing.Any] | None = None
    last_cli_output_snippet: str = ""
    created_at: datetime.datetime = dataclasses.field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
    updated_at: datetime.datetime = dataclasses.field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
    asyncio_task: asyncio.Task | None = None
    error_message: str | None = None
    pause_requested: bool = False


WorkflowRegistry: typing.TypeAlias = dict[str, WorkflowRecord]

_registry: WorkflowRegistry = {}


def get_workflow_registry() -> WorkflowRegistry:
    return _registry


def reset_workflow_registry() -> None:
    _registry.clear()
