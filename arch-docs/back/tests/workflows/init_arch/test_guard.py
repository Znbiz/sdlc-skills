import datetime as dt
from unittest.mock import MagicMock

from app.workflows.init_arch.domain import (
    AuditActor,
    DomainDefinition,
    DomainStrategy,
    EventType,
    NextWindowConfirmationStatus,
    OpenQuestionRecord,
    RepositoryDomainAssessment,
    RepositoryExecution,
    StepId,
    VolumeClass,
    WorkflowStatus,
    advance_step,
    open_question,
    start_session,
)
from app.workflows.init_arch.guard import InitArchGuardService


async def test_guard_service_advance_step_returns_typed_result() -> None:
    service = InitArchGuardService()
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")

    result = await service.advance_step(
        session,
        StepId.REQUEST_REPOSITORY_LIST,
        progress_file_path="/workspace/tmp/progress.yaml",
    )

    assert result.session.current_step is StepId.REQUEST_REPOSITORY_LIST
    assert result.session.status is WorkflowStatus.IN_PROGRESS
    assert result.bridge_output == "Advanced workflow to request_repository_list"


async def test_guard_service_advance_step_emits_audit_events() -> None:
    audit_service = MagicMock()
    service = InitArchGuardService(audit_service=audit_service)
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")

    await service.advance_step(
        session,
        StepId.REQUEST_REPOSITORY_LIST,
        progress_file_path="/workspace/tmp/progress.yaml",
    )

    recorded_events = [call.args[0] for call in audit_service.record.call_args_list]
    assert [event.event_type for event in recorded_events] == [
        EventType.GUARD_COMMAND_REQUESTED,
        EventType.GUARD_COMMAND_APPLIED,
    ]
    assert all(event.actor is AuditActor.SERVICE for event in recorded_events)
    assert recorded_events[0].payload["command"] == "advance"
    assert recorded_events[1].payload["current_step"] == StepId.REQUEST_REPOSITORY_LIST.value


async def test_guard_service_marks_repo_item_and_question_answers() -> None:
    service = InitArchGuardService()
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")
    session = service.register_repository_sync(
        session,
        RepositoryExecution(repository_name="svc-a"),
    )
    session = open_question(session, OpenQuestionRecord(question_id="Q-1", question_text="What API?"))

    repo_result = await service.complete_repository_item(
        session,
        repository_name="svc-a",
        item_id="repository_classification",
        progress_file_path="/workspace/tmp/progress.yaml",
    )
    answer_result = await service.record_user_answer(
        repo_result.session,
        question_id="Q-1",
        answer_text="RPC",
        progress_file_path="/workspace/tmp/progress.yaml",
    )

    assert repo_result.session.repositories[0].checklist_items_completed == ["repository_classification"]
    assert answer_result.session.open_questions[0].answer_text == "RPC"


async def test_guard_service_registers_and_closes_open_questions() -> None:
    service = InitArchGuardService()
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")

    opened_result = await service.register_open_questions(
        session,
        question_texts=["What API?", "What API?", "How is auth handled?"],
        repository_name="svc-a",
        progress_file_path="/workspace/tmp/progress.yaml",
    )
    closed_result = await service.close_user_question(
        opened_result.session,
        question_id="Q-1",
        progress_file_path="/workspace/tmp/progress.yaml",
    )

    assert [question.question_id for question in opened_result.session.open_questions] == ["Q-1", "Q-2"]
    assert opened_result.session.open_questions[0].related_repositories == ["svc-a"]
    assert closed_result.session.open_questions[0].status == "closed"


async def test_guard_service_start_repository_emits_repo_audit_events() -> None:
    audit_service = MagicMock()
    service = InitArchGuardService(audit_service=audit_service)
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")
    session = service.register_repository_sync(
        session,
        RepositoryExecution(repository_name="svc-a"),
    )

    result = await service.start_repository(
        session,
        repository_name="svc-a",
        progress_file_path="/workspace/tmp/progress.yaml",
    )

    assert result.session.repositories[0].analysis_status == "in_progress"
    recorded_events = [call.args[0] for call in audit_service.record.call_args_list]
    assert [event.event_type for event in recorded_events] == [
        EventType.GUARD_COMMAND_REQUESTED,
        EventType.GUARD_COMMAND_APPLIED,
    ]
    assert recorded_events[0].repository_name == "svc-a"
    assert recorded_events[1].repository_name == "svc-a"


async def test_guard_service_assess_repository_domains_updates_session_and_emits_events() -> None:
    audit_service = MagicMock()
    service = InitArchGuardService(audit_service=audit_service)
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")
    session = service.register_repository_sync(
        session,
        RepositoryExecution(repository_name="svc-a"),
    )

    result = await service.assess_repository_domains(
        session,
        repository_name="svc-a",
        assessment=RepositoryDomainAssessment(
            volume_class=VolumeClass.LARGE,
            strategy=DomainStrategy.PER_DOMAIN,
            domains=[DomainDefinition(domain_id="billing", name="Биллинг", paths=["apps/billing/"])],
        ),
        progress_file_path="/workspace/tmp/progress.yaml",
    )

    repository = result.session.repositories[0]
    assert repository.volume_class is VolumeClass.LARGE
    assert repository.domain_strategy is DomainStrategy.PER_DOMAIN
    assert [domain.domain_id for domain in repository.domains] == ["billing"]

    recorded_events = [call.args[0] for call in audit_service.record.call_args_list]
    assert [event.event_type for event in recorded_events] == [
        EventType.GUARD_COMMAND_REQUESTED,
        EventType.GUARD_COMMAND_APPLIED,
    ]
    assert recorded_events[0].payload["command"] == "domain_assess"
    assert recorded_events[1].payload["strategy"] == "per_domain"
    assert recorded_events[1].payload["volume_class"] == "large"
    assert recorded_events[1].payload["domain_count"] == "1"


async def test_guard_service_finalize_progress_marks_done() -> None:
    service = InitArchGuardService()
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")
    session = advance_step(session, StepId.REQUEST_REPOSITORY_LIST)

    result = await service.finalize_progress(session, progress_file_path="/workspace/tmp/progress.yaml")

    assert result.session.current_step is StepId.DONE
    assert result.session.status is WorkflowStatus.COMPLETED
    assert result.bridge_output == "Finalized workflow session"


async def test_guard_service_requests_and_confirms_next_temporal_window() -> None:
    audit_service = MagicMock()
    service = InitArchGuardService(audit_service=audit_service)
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")
    session = session.model_copy(
        update={
            "historical_analysis": session.historical_analysis.model_copy(
                update={"current_snapshot_at": dt.date(2024, 4, 10)}
            )
        }
    )

    requested_result = await service.request_next_temporal_window(
        session,
        next_snapshot_at=dt.date(2024, 7, 10),
        progress_file_path="/workspace/tmp/progress.yaml",
    )

    assert requested_result.session.historical_analysis.awaiting_window_confirmation is True
    assert requested_result.session.historical_analysis.next_snapshot_at == dt.date(2024, 7, 10)
    assert requested_result.session.status is WorkflowStatus.WAITING_FOR_USER

    confirmed_result = await service.confirm_next_temporal_window(
        requested_result.session,
        action="continue_to_next_window",
        progress_file_path="/workspace/tmp/progress.yaml",
    )

    assert confirmed_result.session.historical_analysis.current_snapshot_at == dt.date(2024, 7, 10)
    assert (
        confirmed_result.session.historical_analysis.next_window_confirmation_status
        is NextWindowConfirmationStatus.CONFIRMED
    )
    recorded_commands = [
        call.args[0].payload.get("command") for call in audit_service.record.call_args_list if call.args[0].payload
    ]
    assert "request_next_temporal_window" in recorded_commands
    assert "confirm_next_temporal_window" in recorded_commands


async def test_guard_service_validation_is_internal_summary() -> None:
    service = InitArchGuardService()
    session = start_session(session_id="wf-1", product_name="arch-docs", analysis_scope="full")

    result = await service.run_validation(session, progress_file_path="/workspace/tmp/progress.yaml")

    assert result.session is session
    assert result.bridge_output == "Validation passed for define_scope"
