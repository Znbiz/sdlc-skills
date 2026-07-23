from __future__ import annotations

import dataclasses
import datetime
import enum
import typing

if typing.TYPE_CHECKING:
    import asyncio


class TaskStatus(enum.StrEnum):
    PENDING = enum.auto()
    RUNNING = enum.auto()
    SUCCESS = enum.auto()
    FAILED = enum.auto()
    CANCELLED = enum.auto()


@dataclasses.dataclass(kw_only=True, slots=True)
class CliTask:
    task_id: str
    engine_name: str
    prompt_text: str
    provider_connection_id: str | None = None
    workspace_dir: str
    conversation_id: str | None = None
    response_type: str | None = None
    workflow_id: str | None = None
    step_id: str | None = None
    repository_name: str | None = None
    domain_id: str | None = None
    expected_schema_name: str | None = None
    sandbox_mode: str = "danger-full-access"
    session_id: str | None = None
    timeout_seconds: int = 300
    task_status: TaskStatus = TaskStatus.PENDING
    subprocess_handle: asyncio.subprocess.Process | None = None
    stdout_lines: list[str] = dataclasses.field(default_factory=list)
    stderr_lines: list[str] = dataclasses.field(default_factory=list)
    exit_code: int | None = None
    task_result: str | None = None
    task_error: str | None = None
    created_at: datetime.datetime = dataclasses.field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
    started_at: datetime.datetime | None = None
    finished_at: datetime.datetime | None = None


TaskRegistry: typing.TypeAlias = dict[str, CliTask]

_registry: TaskRegistry = {}


def get_registry() -> TaskRegistry:
    return _registry


def reset_registry() -> None:
    _registry.clear()
