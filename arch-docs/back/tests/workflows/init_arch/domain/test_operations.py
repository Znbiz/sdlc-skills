import datetime as dt
import typing

import pytest

from app.workflows.init_arch.domain import (
    AnalysisTargetCommitStatus,
    CommitRangeStatus,
    DomainDefinition,
    DomainStrategy,
    NextWindowConfirmationStatus,
    OpenQuestionRecord,
    RepositoryExecution,
    StepId,
    VolumeClass,
    WorkflowSessionRecord,
    WorkflowStatus,
)
from app.workflows.init_arch.domain.operations import (
    DomainOperationError,
    advance_step,
    close_question,
    confirm_next_temporal_window,
    domain_assessment_is_complete,
    fail_step,
    finalize_session,
    historical_prep_is_complete,
    mark_checklist_item,
    next_pending_checklist_item,
    next_pending_repository,
    open_question,
    record_answer,
    register_repository,
    request_next_temporal_window_confirmation,
    set_domain_assessment,
    start_session,
)


def test_start_session_defaults_to_define_scope() -> None:
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")

    assert session.session_id == "wf-1"
    assert session.current_step is StepId.DEFINE_SCOPE
    assert session.status is WorkflowStatus.PENDING


def test_advance_step_requires_previous_steps() -> None:
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")

    with pytest.raises(DomainOperationError, match="required_previous_steps"):
        advance_step(session, StepId.CLONE_REPOSITORIES)


def test_advance_step_updates_current_and_completed_steps() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        current_step=StepId.REQUEST_REPOSITORY_LIST,
        completed_steps=[StepId.DEFINE_SCOPE],
    )

    updated = advance_step(session, StepId.PREPARE_TEMP_WORKSPACE)

    assert updated.status is WorkflowStatus.IN_PROGRESS
    assert updated.current_step is StepId.PREPARE_TEMP_WORKSPACE
    assert updated.completed_steps == [StepId.DEFINE_SCOPE, StepId.REQUEST_REPOSITORY_LIST]


def test_advance_step_enforces_historical_prep_for_historical_gate() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        current_step=StepId.PLAN_REPOSITORY_ORDER,
        completed_steps=[
            StepId.DEFINE_SCOPE,
            StepId.REQUEST_REPOSITORY_LIST,
            StepId.PREPARE_TEMP_WORKSPACE,
            StepId.CLONE_REPOSITORIES,
            StepId.REFRESH_MAIN_BRANCHES,
        ],
    )

    with pytest.raises(DomainOperationError, match="historical prep"):
        advance_step(session, StepId.ASSESS_SCOPE_AND_DOMAINS)


def test_advance_step_requires_resolved_snapshot_targets_for_historical_gate() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        current_step=StepId.PLAN_REPOSITORY_ORDER,
        completed_steps=[
            StepId.DEFINE_SCOPE,
            StepId.REQUEST_REPOSITORY_LIST,
            StepId.PREPARE_TEMP_WORKSPACE,
            StepId.CLONE_REPOSITORIES,
            StepId.REFRESH_MAIN_BRANCHES,
        ],
        historical_analysis={
            "anchor_repository_name": "svc-a",
            "anchor_created_at": dt.date(2024, 1, 1),
            "current_snapshot_at": dt.date(2024, 4, 1),
            "ordered_repository_names": ["svc-a"],
        },
        repositories=[
            RepositoryExecution(
                repository_name="svc-a",
                created_at=dt.date(2024, 1, 1),
                analysis_target_date=dt.date(2024, 4, 1),
                analysis_target_commit_status=AnalysisTargetCommitStatus.PENDING,
            )
        ],
    )

    with pytest.raises(DomainOperationError, match="historical prep"):
        advance_step(session, StepId.ASSESS_SCOPE_AND_DOMAINS)


def test_historical_prep_is_incomplete_when_repository_order_is_not_sorted() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        historical_analysis={
            "anchor_repository_name": "svc-a",
            "anchor_created_at": dt.date(2024, 1, 1),
            "current_snapshot_at": dt.date(2024, 4, 1),
            "ordered_repository_names": ["svc-b", "svc-a"],
        },
        repositories=[
            RepositoryExecution(
                repository_name="svc-a",
                created_at=dt.date(2024, 1, 1),
                analysis_target_date=dt.date(2024, 4, 1),
                analysis_target_commit_status=AnalysisTargetCommitStatus.RESOLVED,
            ),
            RepositoryExecution(
                repository_name="svc-b",
                created_at=dt.date(2024, 2, 1),
                analysis_target_date=dt.date(2024, 4, 1),
                analysis_target_commit_status=AnalysisTargetCommitStatus.RESOLVED,
            ),
        ],
    )

    assert historical_prep_is_complete(session) is False


def test_historical_prep_is_incomplete_when_snapshot_date_is_not_propagated() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        historical_analysis={
            "anchor_repository_name": "svc-a",
            "anchor_created_at": dt.date(2024, 1, 1),
            "current_snapshot_at": dt.date(2024, 4, 1),
            "ordered_repository_names": ["svc-a", "svc-b"],
        },
        repositories=[
            RepositoryExecution(
                repository_name="svc-a",
                created_at=dt.date(2024, 1, 1),
                analysis_target_date=dt.date(2024, 4, 1),
                analysis_target_commit_status=AnalysisTargetCommitStatus.RESOLVED,
            ),
            RepositoryExecution(
                repository_name="svc-b",
                created_at=dt.date(2024, 2, 1),
                analysis_target_date=dt.date(2024, 5, 1),
                analysis_target_commit_status=AnalysisTargetCommitStatus.RESOLVED,
            ),
        ],
    )

    assert historical_prep_is_complete(session) is False


def test_historical_prep_requires_temporal_range_for_non_first_window() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        historical_analysis={
            "anchor_repository_name": "svc-a",
            "anchor_created_at": dt.date(2024, 1, 1),
            "previous_snapshot_at": dt.date(2024, 3, 1),
            "current_snapshot_at": dt.date(2024, 4, 1),
            "ordered_repository_names": ["svc-a"],
        },
        repositories=[
            RepositoryExecution(
                repository_name="svc-a",
                created_at=dt.date(2024, 1, 1),
                analysis_target_date=dt.date(2024, 4, 1),
                analysis_target_commit="abc123",
                analysis_target_commit_status=AnalysisTargetCommitStatus.RESOLVED,
                commit_range_status=CommitRangeStatus.NOT_STARTED,
            )
        ],
    )

    assert historical_prep_is_complete(session) is False


def test_historical_prep_requires_window_end_to_match_target_commit() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        historical_analysis={
            "anchor_repository_name": "svc-a",
            "anchor_created_at": dt.date(2024, 1, 1),
            "previous_snapshot_at": dt.date(2024, 3, 1),
            "current_snapshot_at": dt.date(2024, 4, 1),
            "ordered_repository_names": ["svc-a"],
        },
        repositories=[
            RepositoryExecution(
                repository_name="svc-a",
                created_at=dt.date(2024, 1, 1),
                analysis_target_date=dt.date(2024, 4, 1),
                analysis_target_commit="abc123",
                analysis_target_commit_status=AnalysisTargetCommitStatus.RESOLVED,
                window_start_commit="prev123",
                window_end_commit="other999",
                commit_range="prev123..abc123",
                commit_range_status=CommitRangeStatus.RANGE_RESOLVED,
            )
        ],
    )

    assert historical_prep_is_complete(session) is False


def test_historical_prep_accepts_no_changes_for_non_first_window() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        historical_analysis={
            "anchor_repository_name": "svc-a",
            "anchor_created_at": dt.date(2024, 1, 1),
            "previous_snapshot_at": dt.date(2024, 3, 1),
            "current_snapshot_at": dt.date(2024, 4, 1),
            "ordered_repository_names": ["svc-a"],
        },
        repositories=[
            RepositoryExecution(
                repository_name="svc-a",
                created_at=dt.date(2024, 1, 1),
                analysis_target_date=dt.date(2024, 4, 1),
                analysis_target_commit="abc123",
                analysis_target_commit_status=AnalysisTargetCommitStatus.RESOLVED,
                window_start_commit="abc123",
                window_end_commit="abc123",
                commit_range="",
                commit_range_status=CommitRangeStatus.NO_CHANGES,
                temporal_delta_note="",
            )
        ],
    )

    assert historical_prep_is_complete(session) is True


def test_historical_prep_rejects_range_resolved_without_diff_collection() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        historical_analysis={
            "anchor_repository_name": "svc-a",
            "anchor_created_at": dt.date(2024, 1, 1),
            "previous_snapshot_at": dt.date(2024, 3, 1),
            "current_snapshot_at": dt.date(2024, 4, 1),
            "ordered_repository_names": ["svc-a"],
        },
        repositories=[
            RepositoryExecution(
                repository_name="svc-a",
                created_at=dt.date(2024, 1, 1),
                analysis_target_date=dt.date(2024, 4, 1),
                analysis_target_commit="abc123",
                analysis_target_commit_status=AnalysisTargetCommitStatus.RESOLVED,
                window_start_commit="prev123",
                window_end_commit="abc123",
                commit_range="prev123..abc123",
                commit_range_status=CommitRangeStatus.RANGE_RESOLVED,
            )
        ],
    )

    assert historical_prep_is_complete(session) is False


def test_historical_prep_rejects_invalid_range() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        historical_analysis={
            "anchor_repository_name": "svc-a",
            "anchor_created_at": dt.date(2024, 1, 1),
            "previous_snapshot_at": dt.date(2024, 3, 1),
            "current_snapshot_at": dt.date(2024, 4, 1),
            "ordered_repository_names": ["svc-a"],
        },
        repositories=[
            RepositoryExecution(
                repository_name="svc-a",
                created_at=dt.date(2024, 1, 1),
                analysis_target_date=dt.date(2024, 4, 1),
                analysis_target_commit="abc123",
                analysis_target_commit_status=AnalysisTargetCommitStatus.RESOLVED,
                window_start_commit="prev123",
                window_end_commit="abc123",
                commit_range="",
                commit_range_status=CommitRangeStatus.INVALID_RANGE,
                temporal_delta_note="Window start commit is not an ancestor of the snapshot commit.",
            )
        ],
    )

    assert historical_prep_is_complete(session) is False


def test_historical_prep_accepts_diff_collected_for_non_first_window() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        historical_analysis={
            "anchor_repository_name": "svc-a",
            "anchor_created_at": dt.date(2024, 1, 1),
            "previous_snapshot_at": dt.date(2024, 3, 1),
            "current_snapshot_at": dt.date(2024, 4, 1),
            "ordered_repository_names": ["svc-a"],
        },
        repositories=[
            RepositoryExecution(
                repository_name="svc-a",
                created_at=dt.date(2024, 1, 1),
                analysis_target_date=dt.date(2024, 4, 1),
                analysis_target_commit="abc123",
                analysis_target_commit_status=AnalysisTargetCommitStatus.RESOLVED,
                window_start_commit="prev123",
                window_end_commit="abc123",
                commit_range="prev123..abc123",
                commit_range_status=CommitRangeStatus.DIFF_COLLECTED,
                diff_stat_summary="1 file changed",
                changed_paths=["README.md"],
                commit_log_summary="abc123 update readme",
            )
        ],
    )

    assert historical_prep_is_complete(session) is True


def test_historical_prep_accepts_baseline_missing_for_non_first_window() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        historical_analysis={
            "anchor_repository_name": "svc-a",
            "anchor_created_at": dt.date(2024, 1, 1),
            "previous_snapshot_at": dt.date(2024, 3, 1),
            "current_snapshot_at": dt.date(2024, 4, 1),
            "ordered_repository_names": ["svc-a"],
        },
        repositories=[
            RepositoryExecution(
                repository_name="svc-a",
                created_at=dt.date(2024, 1, 1),
                analysis_target_date=dt.date(2024, 4, 1),
                analysis_target_commit="abc123",
                analysis_target_commit_status=AnalysisTargetCommitStatus.RESOLVED,
                window_end_commit="abc123",
                commit_range_status=CommitRangeStatus.BASELINE_MISSING,
                temporal_delta_note="Previous snapshot commit is unavailable for this repository.",
            )
        ],
    )

    assert historical_prep_is_complete(session) is True


def test_register_repository_and_mark_checklist_item() -> None:
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")

    session = register_repository(
        session,
        RepositoryExecution(
            repository_name="svc-a",
            created_at=dt.date(2024, 1, 1),
            analysis_target_commit_status=AnalysisTargetCommitStatus.PENDING,
            domain_strategy=DomainStrategy.PER_DOMAIN,
            domains=[DomainDefinition(domain_id="payments", name="Payments")],
        ),
    )
    session = mark_checklist_item(session, repository_name="svc-a", item_id="repository_classification")

    assert session.repositories[0].repository_name == "svc-a"
    assert session.repositories[0].checklist_items_completed == ["repository_classification"]


def test_next_pending_repository_returns_none_without_repositories() -> None:
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")

    assert next_pending_repository(session) is None


def test_next_pending_repository_skips_completed_and_returns_first_pending() -> None:
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")
    session = register_repository(session, RepositoryExecution(repository_name="svc-a", analysis_status="completed"))
    session = register_repository(session, RepositoryExecution(repository_name="svc-b", analysis_status="in_progress"))
    session = register_repository(session, RepositoryExecution(repository_name="svc-c", analysis_status="pending"))

    repository = next_pending_repository(session)

    assert repository is not None
    assert repository.repository_name == "svc-b"


def test_next_pending_repository_returns_none_when_all_completed() -> None:
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")
    session = register_repository(session, RepositoryExecution(repository_name="svc-a", analysis_status="completed"))

    assert next_pending_repository(session) is None


def test_next_pending_checklist_item_returns_first_routed_item_not_yet_completed() -> None:
    repository = RepositoryExecution(
        repository_name="svc-a",
        checklist_items_completed=["repository_classification", "repository_structure_mapping"],
    )

    item_id = next_pending_checklist_item(
        repository,
        all_checklist_item_ids=[
            "repository_classification",
            "repository_structure_mapping",
            "entrypoints_and_interfaces",
        ],
    )

    assert item_id == "entrypoints_and_interfaces"


def test_next_pending_checklist_item_returns_none_when_all_routed_items_completed() -> None:
    repository = RepositoryExecution(
        repository_name="svc-a",
        checklist_items_completed=["repository_classification", "entrypoints_and_interfaces"],
    )

    item_id = next_pending_checklist_item(
        repository,
        all_checklist_item_ids=["repository_classification", "entrypoints_and_interfaces"],
    )

    assert item_id is None


def test_next_pending_checklist_item_narrows_to_routed_subset_on_no_signal_repository() -> None:
    repository = RepositoryExecution(
        repository_name="svc-a",
        commit_range_status=CommitRangeStatus.NO_CHANGES,
    )

    item_id = next_pending_checklist_item(
        repository,
        all_checklist_item_ids=["repository_classification", "repository_consistency_review"],
    )

    assert item_id == "repository_consistency_review"


def test_set_domain_assessment_updates_repository_fields() -> None:
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")
    session = register_repository(session, RepositoryExecution(repository_name="svc-a"))

    session = set_domain_assessment(
        session,
        repository_name="svc-a",
        volume_class=VolumeClass.LARGE,
        strategy=DomainStrategy.PER_DOMAIN,
        domains=[DomainDefinition(domain_id="billing", name="Биллинг", paths=["apps/billing/"])],
    )

    repository = session.repositories[0]
    assert repository.volume_class is VolumeClass.LARGE
    assert repository.domain_strategy is DomainStrategy.PER_DOMAIN
    assert repository.domains == [DomainDefinition(domain_id="billing", name="Биллинг", paths=["apps/billing/"])]


def test_set_domain_assessment_requires_existing_repository() -> None:
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")

    with pytest.raises(DomainOperationError, match="repository not found"):
        set_domain_assessment(
            session,
            repository_name="missing",
            volume_class=VolumeClass.SMALL,
            strategy=DomainStrategy.PER_MODULE,
            domains=[],
        )


def test_domain_assessment_is_complete_requires_all_repositories_assessed() -> None:
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")
    session = register_repository(session, RepositoryExecution(repository_name="svc-a"))
    session = register_repository(session, RepositoryExecution(repository_name="svc-b"))

    assert domain_assessment_is_complete(session) is False

    session = set_domain_assessment(
        session,
        repository_name="svc-a",
        volume_class=VolumeClass.SMALL,
        strategy=DomainStrategy.PER_MODULE,
        domains=[],
    )
    assert domain_assessment_is_complete(session) is False

    session = set_domain_assessment(
        session,
        repository_name="svc-b",
        volume_class=VolumeClass.SMALL,
        strategy=DomainStrategy.PER_MODULE,
        domains=[],
    )
    assert domain_assessment_is_complete(session) is True


def test_domain_assessment_is_complete_false_without_repositories() -> None:
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")

    assert domain_assessment_is_complete(session) is False


def test_request_next_temporal_window_confirmation_marks_session_waiting() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        historical_analysis={"current_snapshot_at": dt.date(2024, 4, 10)},
    )

    updated = request_next_temporal_window_confirmation(session, next_snapshot_at=dt.date(2024, 7, 10))

    assert updated.status is WorkflowStatus.WAITING_FOR_USER
    assert updated.historical_analysis.awaiting_window_confirmation is True
    assert updated.historical_analysis.last_completed_snapshot_at == dt.date(2024, 4, 10)
    assert updated.historical_analysis.next_snapshot_at == dt.date(2024, 7, 10)
    assert updated.historical_analysis.next_window_confirmation_status is NextWindowConfirmationStatus.PENDING


def test_request_next_temporal_window_confirmation_requires_resolved_snapshot() -> None:
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")

    with pytest.raises(DomainOperationError, match="snapshot window is resolved"):
        request_next_temporal_window_confirmation(session, next_snapshot_at=dt.date(2024, 7, 10))


def test_confirm_next_temporal_window_requires_pending_confirmation() -> None:
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")

    with pytest.raises(DomainOperationError, match="no pending temporal window confirmation"):
        confirm_next_temporal_window(session, action="continue_to_next_window")


def test_confirm_next_temporal_window_continue_advances_window() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        historical_analysis={
            "current_snapshot_at": dt.date(2024, 4, 10),
            "window_index": 0,
        },
    )
    session = request_next_temporal_window_confirmation(session, next_snapshot_at=dt.date(2024, 7, 10))

    updated = confirm_next_temporal_window(session, action="continue_to_next_window")

    assert updated.status is WorkflowStatus.IN_PROGRESS
    assert updated.historical_analysis.awaiting_window_confirmation is False
    assert updated.historical_analysis.previous_snapshot_at == dt.date(2024, 4, 10)
    assert updated.historical_analysis.current_snapshot_at == dt.date(2024, 7, 10)
    assert updated.historical_analysis.next_snapshot_at is None
    assert updated.historical_analysis.completed_snapshot_dates == [dt.date(2024, 4, 10)]
    assert updated.historical_analysis.window_index == 1
    assert updated.historical_analysis.next_window_confirmation_status is NextWindowConfirmationStatus.CONFIRMED


def test_confirm_next_temporal_window_continue_requires_next_snapshot_at() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        historical_analysis={
            "current_snapshot_at": dt.date(2024, 4, 10),
            "awaiting_window_confirmation": True,
        },
    )

    with pytest.raises(DomainOperationError, match="next_snapshot_at is not set"):
        confirm_next_temporal_window(session, action="continue_to_next_window")


def test_confirm_next_temporal_window_rejects_unsupported_action() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        historical_analysis={
            "current_snapshot_at": dt.date(2024, 4, 10),
            "awaiting_window_confirmation": True,
        },
    )

    with pytest.raises(DomainOperationError, match="unsupported temporal window confirmation action"):
        confirm_next_temporal_window(session, action=typing.cast("typing.Any", "unknown_action"))


def test_confirm_next_temporal_window_finish_stops_without_advancing() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        historical_analysis={"current_snapshot_at": dt.date(2024, 4, 10)},
    )
    session = request_next_temporal_window_confirmation(session, next_snapshot_at=dt.date(2024, 7, 10))

    updated = confirm_next_temporal_window(session, action="finish_temporal_analysis")

    assert updated.status is WorkflowStatus.IN_PROGRESS
    assert updated.historical_analysis.awaiting_window_confirmation is False
    assert updated.historical_analysis.current_snapshot_at == dt.date(2024, 4, 10)
    assert updated.historical_analysis.next_window_confirmation_status is NextWindowConfirmationStatus.STOPPED


def test_open_question_and_record_answer_update_session_status() -> None:
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")

    session = open_question(
        session,
        OpenQuestionRecord(question_id="Q-1", question_text="What transport does the service expose?"),
    )
    answered = record_answer(session, question_id="Q-1", answer_text="REST and MCP")

    assert answered.status is WorkflowStatus.IN_PROGRESS
    assert answered.open_questions[0].status == "answered"
    assert answered.open_questions[0].answer_text == "REST and MCP"


def test_close_question_keeps_waiting_status_when_more_questions_exist() -> None:
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")
    session = open_question(session, OpenQuestionRecord(question_id="Q-1", question_text="What transport?"))
    session = open_question(session, OpenQuestionRecord(question_id="Q-2", question_text="What auth?"))

    closed = close_question(session, question_id="Q-1")

    assert closed.open_questions[0].status == "closed"
    assert closed.status is WorkflowStatus.WAITING_FOR_USER


def test_fail_and_finalize_session() -> None:
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")

    failed = fail_step(session)
    assert failed.status is WorkflowStatus.FAILED

    finalized = finalize_session(
        WorkflowSessionRecord(
            session_id="wf-2",
            product_name="arch-docs",
            analysis_scope="full",
            current_step=StepId.FINALIZE_PROGRESS,
            completed_steps=[StepId.DEFINE_SCOPE],
        ),
    )
    assert finalized.current_step is StepId.DONE
    assert finalized.status is WorkflowStatus.COMPLETED
