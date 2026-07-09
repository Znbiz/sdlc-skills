from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.workflow_repo import append_workflow_event, get_workflow_run, mark_running_workflows_failed, upsert_workflow_run
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


async def test_get_workflow_run_deserializes_session(mock_session):
    class _WorkflowModel:
        workflow_id = "wf-1"
        conversation_id = "conv-1"
        workflow_status = "interrupted"
        current_step_id = "interview_user"
        current_repo_name = ""
        completed_steps = ["define_scope"]
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


async def test_mark_running_workflows_failed_returns_count(mock_session):
    result = MagicMock()
    result.fetchall.return_value = [("wf-1", "conv-1", "define_scope"), ("wf-2", "conv-2", "interview_user")]
    mock_session.execute = AsyncMock(return_value=result)

    count = await mark_running_workflows_failed(mock_session)

    assert count == 2
    mock_session.commit.assert_called_once()
