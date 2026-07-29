from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models import ArtifactEventModel, WorkflowStepTransitionModel
from app.db.workflow_repo import (
    _build_artifact_event_model,
    _build_required_actions,
    _session_payload,
    append_workflow_event,
    create_conversation,
    delete_workflow_run,
    get_conversation,
    get_workflow_run,
    increment_workflow_token_usage,
    list_conversation_items,
    mark_running_workflows_paused,
    upsert_workflow_run,
)
from app.services.workflow_registry import WorkflowRecord, WorkflowStatus
from app.workflows.init_arch.domain import (
    AuditActor,
    EventType,
    OpenQuestionRecord,
    StepId,
    WorkflowEventRecord,
    WorkflowSessionRecord,
)


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    return session


async def test_upsert_workflow_run_creates_conversation_and_actions(mock_session):
    record = WorkflowRecord(
        workflow_id="wf-1",
        conversation_id="conv-1",
        workflow_status=WorkflowStatus.INTERRUPTED,
        current_step_id="interview_user",
        pending_interrupt={"interrupt_type": "user_question", "question_id": "Q-1", "question": "Need details?"},
        session=WorkflowSessionRecord(
            session_id="wf-1",
            product_name="arch-docs",
            analysis_scope="full",
            current_step=StepId.INTERVIEW_USER,
            open_questions=[OpenQuestionRecord(question_id="Q-1", question_text="Need details?")],
        ),
    )

    await upsert_workflow_run(mock_session, record)

    assert mock_session.add.call_count >= 4
    mock_session.commit.assert_called_once()


async def test_upsert_workflow_run_persists_step_transition_record(mock_session):
    record = WorkflowRecord(
        workflow_id="wf-1",
        conversation_id="conv-1",
        workflow_status=WorkflowStatus.RUNNING,
        current_step_id="request_repository_list",
        completed_steps=["define_scope"],
    )

    await upsert_workflow_run(mock_session, record)

    added_models = [call.args[0] for call in mock_session.add.call_args_list]
    step_transition = next(model for model in added_models if isinstance(model, WorkflowStepTransitionModel))
    assert step_transition.workflow_id == "wf-1"
    assert step_transition.conversation_id == "conv-1"
    assert step_transition.previous_step_id is None
    assert step_transition.current_step_id == "request_repository_list"
    assert step_transition.completed_steps == ["define_scope"]


async def test_append_workflow_event_writes_conversation_item(mock_session):
    event = WorkflowEventRecord(
        event_type=EventType.GUARD_COMMAND_APPLIED,
        actor=AuditActor.SERVICE,
        session_id="wf-1",
        step_id=StepId.DEFINE_SCOPE,
        payload={"command": "init"},
    )

    await append_workflow_event(mock_session, event)

    assert mock_session.add.call_count >= 1
    mock_session.commit.assert_called_once()


async def test_append_workflow_event_persists_artifact_event_record(mock_session):
    event = WorkflowEventRecord(
        event_type=EventType.ARTIFACT_WRITTEN,
        actor=AuditActor.SERVICE,
        session_id="wf-1",
        step_id=StepId.REFINE_FEATURES,
        payload={"artifact_path": "wiki/index.md", "artifact_kind": "navigation_artifact"},
    )

    await append_workflow_event(mock_session, event)

    added_models = [call.args[0] for call in mock_session.add.call_args_list]
    artifact_event = next(model for model in added_models if isinstance(model, ArtifactEventModel))
    assert artifact_event.workflow_id == "wf-1"
    assert artifact_event.event_type == "artifact_written"
    assert artifact_event.artifact_path == "wiki/index.md"
    assert artifact_event.artifact_kind == "navigation_artifact"
    assert artifact_event.step_id == "refine_features"


async def test_get_workflow_run_deserializes_session(mock_session):
    class _WorkflowModel:
        workflow_id = "wf-1"
        conversation_id = "conv-1"
        workflow_status = "interrupted"
        current_step_id = "interview_user"
        current_repo_name = ""
        workspace_dir = ""
        arch_repo_dir = ""
        completed_steps = ["define_scope"]
        token_usage_by_model = {"claude-sonnet-4-5": {"input_tokens": 10, "output_tokens": 2}}
        session_payload = {
            "session_id": "wf-1",
            "product_name": "arch-docs",
            "analysis_scope": "full",
            "current_step": "interview_user",
            "completed_steps": ["define_scope"],
            "repositories": [],
            "historical_analysis": {
                "anchor_repository_name": "",
                "anchor_created_at": None,
                "current_snapshot_at": None,
                "ordered_repository_names": [],
                "completed_snapshot_dates": [],
                "prep_notes": "",
                "window_index": 0,
            },
            "artifacts": [],
            "open_questions": [],
            "status": "pending",
        }
        pending_interrupt_payload = {"interrupt_type": "user_question"}
        last_cli_output_snippet = ""
        created_at = updated_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        error_message = None

    mock_session.get = AsyncMock(return_value=_WorkflowModel())

    record = await get_workflow_run(mock_session, "wf-1")

    assert record is not None
    assert record.conversation_id == "conv-1"
    assert record.session is not None
    assert record.session.current_step is StepId.INTERVIEW_USER
    assert record.token_usage_by_model == {"claude-sonnet-4-5": {"input_tokens": 10, "output_tokens": 2}}


async def test_mark_running_workflows_paused_returns_count(mock_session):
    result = MagicMock()
    result.fetchall.return_value = [("wf-1", "conv-1", "define_scope"), ("wf-2", "conv-2", "interview_user")]
    mock_session.execute = AsyncMock(return_value=result)

    count = await mark_running_workflows_paused(mock_session)

    assert count == 2
    mock_session.commit.assert_called_once()


def test_session_payload_returns_none_for_missing_session():
    assert _session_payload(None) is None


def test_build_required_actions_merges_interrupt_and_open_questions():
    record = WorkflowRecord(
        workflow_id="wf-actions",
        conversation_id="conv-actions",
        workflow_status=WorkflowStatus.INTERRUPTED,
        pending_interrupt={"interrupt_type": "user_question", "question_id": "Q-1"},
        session=WorkflowSessionRecord(
            session_id="wf-actions",
            product_name="arch-docs",
            analysis_scope="full",
            current_step=StepId.INTERVIEW_USER,
            open_questions=[
                OpenQuestionRecord(question_id="Q-1", question_text="duplicate"),
                OpenQuestionRecord(question_id="Q-2", question_text="new"),
            ],
        ),
    )

    actions = _build_required_actions(record, conversation_id="conv-actions")

    assert [action.question_id for action in actions] == ["Q-1", "Q-2"]


def test_build_artifact_event_model_returns_none_for_irrelevant_or_invalid_events():
    ignored_event = WorkflowEventRecord(
        event_type=EventType.GUARD_COMMAND_APPLIED,
        actor=AuditActor.SERVICE,
        session_id="wf-1",
        step_id=StepId.DEFINE_SCOPE,
        payload={},
    )
    invalid_event = WorkflowEventRecord(
        event_type=EventType.ARTIFACT_WRITTEN,
        actor=AuditActor.SERVICE,
        session_id="wf-1",
        step_id=StepId.DEFINE_SCOPE,
        payload={"artifact_path": "wiki/index.md"},
    )

    assert _build_artifact_event_model(ignored_event, conversation_id="conv-1") is None
    assert _build_artifact_event_model(invalid_event, conversation_id="conv-1") is None


async def test_append_workflow_event_ignores_missing_session_id(mock_session):
    event = WorkflowEventRecord(
        event_type=EventType.GUARD_COMMAND_APPLIED,
        actor=AuditActor.SERVICE,
        session_id="",
        step_id=StepId.DEFINE_SCOPE,
        payload={},
    )

    await append_workflow_event(mock_session, event)

    mock_session.add.assert_not_called()


async def test_create_conversation_returns_existing_conversation(mock_session):
    existing = MagicMock()
    mock_session.get = AsyncMock(return_value=existing)

    conversation = await create_conversation(mock_session, conversation_id="conv-1")

    assert conversation is existing
    mock_session.commit.assert_not_called()


async def test_list_conversation_items_returns_empty_without_filters(mock_session):
    items = await list_conversation_items(mock_session)

    assert items == []


async def test_increment_workflow_token_usage_returns_empty_for_missing_workflow(mock_session):
    result = await increment_workflow_token_usage(
        mock_session, workflow_id="missing", model_name="claude-sonnet-4-5", input_tokens=10, output_tokens=2
    )
    assert result == {}
    mock_session.commit.assert_not_called()


async def test_increment_workflow_token_usage_accumulates_across_calls(db_session):
    record = WorkflowRecord(workflow_id="wf-usage", conversation_id="conv-usage", current_step_id="define_scope")
    await upsert_workflow_run(db_session, record)

    first = await increment_workflow_token_usage(
        db_session, workflow_id="wf-usage", model_name="claude-sonnet-4-5", input_tokens=50, output_tokens=10
    )
    second = await increment_workflow_token_usage(
        db_session, workflow_id="wf-usage", model_name="claude-sonnet-4-5", input_tokens=25, output_tokens=5
    )
    third = await increment_workflow_token_usage(
        db_session, workflow_id="wf-usage", model_name="gpt-4o-mini", input_tokens=100, output_tokens=20
    )

    assert first == {"claude-sonnet-4-5": {"input_tokens": 50, "output_tokens": 10}}
    assert second == {"claude-sonnet-4-5": {"input_tokens": 75, "output_tokens": 15}}
    assert third == {
        "claude-sonnet-4-5": {"input_tokens": 75, "output_tokens": 15},
        "gpt-4o-mini": {"input_tokens": 100, "output_tokens": 20},
    }

    reloaded = await get_workflow_run(db_session, "wf-usage")
    assert reloaded is not None
    assert reloaded.token_usage_by_model == third


async def test_upsert_and_get_workflow_run_round_trips_path_metadata(db_session):
    record = WorkflowRecord(
        workflow_id="wf-paths",
        conversation_id="conv-paths",
        workspace_dir="/workspace",
        arch_repo_dir="/workspace/arch",
    )

    await upsert_workflow_run(db_session, record)
    loaded = await get_workflow_run(db_session, "wf-paths")

    assert loaded.workspace_dir == "/workspace"
    assert loaded.arch_repo_dir == "/workspace/arch"


async def test_delete_workflow_run_cascades_children_but_keeps_conversation(db_session):
    record = WorkflowRecord(
        workflow_id="wf-delete",
        conversation_id="conv-delete",
        workspace_dir="/workspace",
        arch_repo_dir="/workspace/arch",
    )
    await upsert_workflow_run(db_session, record)
    await append_workflow_event(
        db_session,
        WorkflowEventRecord(
            event_type=EventType.WORKFLOW_STEP_STARTED,
            actor=AuditActor.SERVICE,
            session_id="wf-delete",
            step_id=StepId.DEFINE_SCOPE,
            payload={},
        ),
    )

    deleted = await delete_workflow_run(db_session, "wf-delete")

    assert deleted is True
    assert await get_workflow_run(db_session, "wf-delete") is None
    assert await list_conversation_items(db_session, workflow_id="wf-delete") == []
    # restart's whole point is that the conversation/URL survives - only the run is wiped.
    assert await get_conversation(db_session, "conv-delete") is not None


async def test_delete_workflow_run_returns_false_when_nothing_to_delete(db_session):
    assert await delete_workflow_run(db_session, "does-not-exist") is False
