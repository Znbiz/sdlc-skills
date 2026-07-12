from __future__ import annotations

import typing

from app.workflows.init_arch.domain import LlmTaskResult, WorkflowSessionRecord


class InitArchState(typing.TypedDict):
    session_id: str
    session: WorkflowSessionRecord
    workspace_dir: str
    raw_workspace_dir: str
    arch_repo_dir: str
    engine_name: str
    timeout_seconds: int
    progress_file_path: str
    last_llm_result: LlmTaskResult | None
    last_guard_output: str
    step_error: str | None
    retry_count: int
