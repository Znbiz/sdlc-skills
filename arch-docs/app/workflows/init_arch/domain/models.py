from __future__ import annotations

import datetime as dt  # noqa: TC003
import enum
from typing import Literal

import pydantic


class StepId(str, enum.Enum):
    DEFINE_SCOPE = "define_scope"
    REQUEST_REPOSITORY_LIST = "request_repository_list"
    PREPARE_TEMP_WORKSPACE = "prepare_temp_workspace"
    CLONE_REPOSITORIES = "clone_repositories"
    REFRESH_MAIN_BRANCHES = "refresh_main_branches"
    PLAN_REPOSITORY_ORDER = "plan_repository_order"
    ASSESS_SCOPE_AND_DOMAINS = "assess_scope_and_domains"
    ANALYZE_REPOSITORIES = "analyze_repositories"
    INTERVIEW_USER = "interview_user"
    REFINE_FEATURES = "refine_features"
    BUILD_NAVIGATION_INDEX = "build_navigation_index"
    RUN_KNOWLEDGE_LINT = "run_knowledge_lint"
    VALIDATE_FINAL = "validate_final"
    FINALIZE_PROGRESS = "finalize_progress"
    DONE = "done"


class WorkflowStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_USER = "waiting_for_user"
    FAILED = "failed"
    COMPLETED = "completed"


class DomainStrategy(str, enum.Enum):
    PER_MODULE = "per_module"
    PER_DOMAIN = "per_domain"


class AuditActor(str, enum.Enum):
    SERVICE = "service"
    LLM_WORKER = "llm_worker"
    USER = "user"


class EventType(str, enum.Enum):
    WORKFLOW_STEP_STARTED = "workflow_step_started"
    WORKFLOW_STEP_COMPLETED = "workflow_step_completed"
    WORKFLOW_STEP_FAILED = "workflow_step_failed"
    GUARD_COMMAND_REQUESTED = "guard_command_requested"
    GUARD_COMMAND_APPLIED = "guard_command_applied"
    LLM_TASK_REQUESTED = "llm_task_requested"
    LLM_TASK_COMPLETED = "llm_task_completed"
    LLM_TASK_FAILED = "llm_task_failed"
    USER_QUESTION_OPENED = "user_question_opened"
    USER_ANSWER_RECORDED = "user_answer_recorded"
    ARTIFACT_WRITTEN = "artifact_written"
    ARTIFACT_REJECTED = "artifact_rejected"


class AnalysisTargetCommitStatus(str, enum.Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    MISSING = "missing"
    CHECKED_OUT = "checked_out"


class LlmTaskKind(str, enum.Enum):
    STEP_EXECUTION = "step_execution"
    REPOSITORY_CHECKLIST_ITEM = "repository_checklist_item"
    KNOWLEDGE_SYNTHESIS = "knowledge_synthesis"
    INTERVIEW_RECONCILIATION = "interview_reconciliation"


class DomainDefinition(pydantic.BaseModel):
    domain_id: str
    name: str
    paths: list[str] = pydantic.Field(default_factory=list)
    signal: str = ""
    subdomains: list[str] = pydantic.Field(default_factory=list)


class RepositoryExecution(pydantic.BaseModel):
    repository_name: str
    role: str = ""
    repository_url: str = ""
    created_at: dt.date | None = None
    main_branch: str = ""
    remote_head_commit: str = ""
    analysis_target_date: dt.date | None = None
    analysis_target_commit: str = ""
    analysis_target_commit_status: AnalysisTargetCommitStatus = AnalysisTargetCommitStatus.PENDING
    domain_strategy: DomainStrategy | None = None
    domains: list[DomainDefinition] = pydantic.Field(default_factory=list)
    checklist_items_completed: list[str] = pydantic.Field(default_factory=list)
    analysis_status: Literal["pending", "in_progress", "completed"] = "pending"


class HistoricalAnalysisState(pydantic.BaseModel):
    anchor_repository_name: str = ""
    anchor_created_at: dt.date | None = None
    current_snapshot_at: dt.date | None = None
    ordered_repository_names: list[str] = pydantic.Field(default_factory=list)
    completed_snapshot_dates: list[dt.date] = pydantic.Field(default_factory=list)
    prep_notes: str = ""
    window_index: int = 0


class ArtifactRecord(pydantic.BaseModel):
    artifact_path: str
    artifact_kind: str
    source_refs: list[str] = pydantic.Field(default_factory=list)
    last_updated_step: StepId | None = None


class OpenQuestionRecord(pydantic.BaseModel):
    question_id: str
    question_text: str
    status: Literal["open", "answered", "closed"] = "open"
    target_artifacts: list[str] = pydantic.Field(default_factory=list)
    related_repositories: list[str] = pydantic.Field(default_factory=list)
    answer_text: str = ""


class WorkflowSessionRecord(pydantic.BaseModel):
    session_id: str
    product_name: str
    analysis_scope: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    current_step: StepId = StepId.DEFINE_SCOPE
    completed_steps: list[StepId] = pydantic.Field(default_factory=list)
    repositories: list[RepositoryExecution] = pydantic.Field(default_factory=list)
    historical_analysis: HistoricalAnalysisState = pydantic.Field(default_factory=HistoricalAnalysisState)
    artifacts: list[ArtifactRecord] = pydantic.Field(default_factory=list)
    open_questions: list[OpenQuestionRecord] = pydantic.Field(default_factory=list)


class LlmTaskRequest(pydantic.BaseModel):
    session_id: str = ""
    task_kind: LlmTaskKind
    step_id: StepId
    prompt_text: str
    workspace_dir: str
    timeout_seconds: int
    expected_schema_name: str
    repository_name: str = ""
    domain_id: str = ""


class LlmTaskResult(pydantic.BaseModel):
    task_kind: LlmTaskKind
    step_id: StepId
    completed_actions: list[str] = pydantic.Field(default_factory=list)
    created_artifacts: list[str] = pydantic.Field(default_factory=list)
    open_questions_found: list[str] = pydantic.Field(default_factory=list)
    notes: str = ""
    raw_output: str = ""


class WorkflowEventRecord(pydantic.BaseModel):
    event_type: EventType
    actor: AuditActor
    step_id: StepId | None = None
    session_id: str = ""
    repository_name: str = ""
    domain_id: str = ""
    payload: dict[str, str | int | float | bool | None] = pydantic.Field(default_factory=dict)
