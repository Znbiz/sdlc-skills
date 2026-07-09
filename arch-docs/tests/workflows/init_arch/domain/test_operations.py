import datetime as dt

import pytest

from app.workflows.init_arch.domain import (
    AnalysisTargetCommitStatus,
    DomainDefinition,
    DomainStrategy,
    OpenQuestionRecord,
    RepositoryExecution,
    StepId,
    WorkflowSessionRecord,
    WorkflowStatus,
)
from app.workflows.init_arch.domain.operations import (
    DomainOperationError,
    advance_step,
    close_question,
    fail_step,
    finalize_session,
    mark_checklist_item,
    open_question,
    record_answer,
    register_repository,
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
