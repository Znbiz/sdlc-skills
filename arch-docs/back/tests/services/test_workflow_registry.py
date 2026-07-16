from app.services.workflow_registry import (
    WorkflowRecord,
    WorkflowStatus,
    get_workflow_registry,
    reset_workflow_registry,
)
from app.workflows.init_arch.domain import StepId, WorkflowSessionRecord


def test_registry_starts_empty():
    reset_workflow_registry()
    assert get_workflow_registry() == {}


def test_add_and_retrieve_record():
    reset_workflow_registry()
    record = WorkflowRecord(workflow_id="wf-1")
    registry = get_workflow_registry()
    registry["wf-1"] = record
    assert get_workflow_registry()["wf-1"] is record


def test_reset_clears_registry():
    registry = get_workflow_registry()
    registry["wf-x"] = WorkflowRecord(workflow_id="wf-x")
    reset_workflow_registry()
    assert "wf-x" not in get_workflow_registry()


def test_workflow_record_defaults():
    rec = WorkflowRecord(workflow_id="abc")
    assert rec.conversation_id is None
    assert rec.workflow_status == WorkflowStatus.RUNNING
    assert rec.current_step_id == "define_scope"
    assert rec.completed_steps == []
    assert rec.pending_interrupt is None
    assert rec.error_message is None
    assert rec.session is None


def test_workflow_record_can_store_typed_session():
    rec = WorkflowRecord(
        workflow_id="abc",
        session=WorkflowSessionRecord(
            session_id="wf-1",
            product_name="arch-docs",
            analysis_scope="full",
            current_step=StepId.ANALYZE_REPOSITORIES,
        ),
    )

    assert rec.session is not None
    assert rec.session.current_step is StepId.ANALYZE_REPOSITORIES
