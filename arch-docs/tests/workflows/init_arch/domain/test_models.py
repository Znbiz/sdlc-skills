import datetime as dt

from app.workflows.init_arch.domain import (
    STEP_DEFINITION_BY_ID,
    STEP_DEFINITIONS,
    AnalysisTargetCommitStatus,
    AuditActor,
    CommitRangeStatus,
    DomainStrategy,
    EventType,
    LlmTaskKind,
    LlmTaskRequest,
    LlmTaskResult,
    RepositoryExecution,
    StepId,
    WorkflowEventRecord,
    WorkflowSessionRecord,
    WorkflowStatus,
)


def test_workflow_session_defaults() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
    )

    assert session.status is WorkflowStatus.PENDING
    assert session.current_step is StepId.DEFINE_SCOPE
    assert session.repositories == []
    assert session.historical_analysis.ordered_repository_names == []


def test_repository_execution_supports_historical_fields() -> None:
    repository = RepositoryExecution(
        repository_name="service-a",
        created_at=dt.date(2024, 1, 1),
        analysis_target_date=dt.date(2024, 4, 1),
        analysis_target_commit="abc123",
        analysis_target_commit_status=AnalysisTargetCommitStatus.RESOLVED,
        previous_analysis_target_commit="prev123",
        window_start_commit="prev123",
        window_end_commit="abc123",
        commit_range="prev123..abc123",
        commit_range_status=CommitRangeStatus.RANGE_RESOLVED,
        diff_stat_summary=" 1 file changed",
        commit_log_summary="abc123 feature: add temporal state",
        changed_paths=["app/workflows/init_arch/domain/models.py"],
        renamed_paths=["old.py -> new.py"],
        deleted_paths=["legacy.py"],
        temporal_delta_note="Temporal delta prepared for this repository window.",
        domain_strategy=DomainStrategy.PER_DOMAIN,
    )

    assert repository.analysis_target_commit == "abc123"
    assert repository.analysis_target_commit_status is AnalysisTargetCommitStatus.RESOLVED
    assert repository.previous_analysis_target_commit == "prev123"
    assert repository.window_end_commit == "abc123"
    assert repository.commit_range_status is CommitRangeStatus.RANGE_RESOLVED
    assert repository.changed_paths == ["app/workflows/init_arch/domain/models.py"]
    assert repository.deleted_paths == ["legacy.py"]
    assert repository.domain_strategy is DomainStrategy.PER_DOMAIN


def test_historical_analysis_state_supports_previous_snapshot_metadata() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        historical_analysis={
            "anchor_repository_name": "service-a",
            "anchor_created_at": dt.date(2024, 1, 1),
            "previous_snapshot_at": dt.date(2024, 3, 1),
            "current_snapshot_at": dt.date(2024, 4, 1),
            "window_index": 1,
        },
    )

    assert session.historical_analysis.previous_snapshot_at == dt.date(2024, 3, 1)
    assert session.historical_analysis.window_index == 1


def test_step_definitions_mark_historical_gate() -> None:
    assess = STEP_DEFINITION_BY_ID[StepId.ASSESS_SCOPE_AND_DOMAINS]
    analyze = STEP_DEFINITION_BY_ID[StepId.ANALYZE_REPOSITORIES]

    assert assess.requires_historical_prep is True
    assert analyze.requires_historical_prep is True
    assert len(STEP_DEFINITIONS) >= 10


def test_llm_task_request_and_result_are_typed() -> None:
    request = LlmTaskRequest(
        task_kind=LlmTaskKind.KNOWLEDGE_SYNTHESIS,
        step_id=StepId.REFINE_FEATURES,
        prompt_text="summarize findings",
        workspace_dir="/workspace/tmp/workspace",
        timeout_seconds=300,
        expected_schema_name="knowledge_synthesis_v1",
    )
    result = LlmTaskResult(
        task_kind=LlmTaskKind.KNOWLEDGE_SYNTHESIS,
        step_id=StepId.REFINE_FEATURES,
        completed_actions=["updated features index"],
        created_artifacts=["features/service-a.md"],
    )

    assert request.task_kind is LlmTaskKind.KNOWLEDGE_SYNTHESIS
    assert result.created_artifacts == ["features/service-a.md"]


def test_workflow_event_record_captures_actor_and_event_type() -> None:
    event = WorkflowEventRecord(
        event_type=EventType.LLM_TASK_COMPLETED,
        actor=AuditActor.LLM_WORKER,
        step_id=StepId.ANALYZE_REPOSITORIES,
        session_id="wf-1",
        repository_name="service-a",
        payload={"retry_count": 0},
    )

    assert event.actor is AuditActor.LLM_WORKER
    assert event.event_type is EventType.LLM_TASK_COMPLETED
    assert event.payload["retry_count"] == 0
