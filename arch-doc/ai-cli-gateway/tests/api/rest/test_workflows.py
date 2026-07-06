import pytest

from app.services.workflow_registry import (
    WorkflowRecord,
    WorkflowStatus,
    get_workflow_registry,
    reset_workflow_registry,
)


@pytest.fixture(autouse=True)
def clean_workflow_registry():
    reset_workflow_registry()
    yield
    reset_workflow_registry()


async def test_get_workflow_not_found(async_client, auth_headers):
    resp = await async_client.get("/api/rest/workflows/nonexistent-id/", headers=auth_headers)
    assert resp.status_code == 404


async def test_get_workflow_running(async_client, auth_headers):
    record = WorkflowRecord(workflow_id="wf-test-1", current_step_id="define_scope")
    get_workflow_registry()["wf-test-1"] = record

    resp = await async_client.get("/api/rest/workflows/wf-test-1/", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["workflow_id"] == "wf-test-1"
    assert data["workflow_status"] == "running"
    assert data["current_step_id"] == "define_scope"
    assert data["pending_interrupt"] is None


async def test_get_workflow_interrupted(async_client, auth_headers):
    record = WorkflowRecord(
        workflow_id="wf-test-2",
        workflow_status=WorkflowStatus.INTERRUPTED,
        pending_interrupt={
            "interrupt_type": "user_question",
            "question": "What is the architecture?",
        },
    )
    get_workflow_registry()["wf-test-2"] = record

    resp = await async_client.get("/api/rest/workflows/wf-test-2/", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["workflow_status"] == "interrupted"
    assert data["pending_interrupt"]["interrupt_type"] == "user_question"
    assert data["pending_interrupt"]["question"] == "What is the architecture?"


async def test_get_workflow_no_auth(async_client):
    resp = await async_client.get("/api/rest/workflows/some-id/")
    assert resp.status_code == 401


async def test_get_workflow_failed_with_error(async_client, auth_headers):
    record = WorkflowRecord(
        workflow_id="wf-test-3",
        workflow_status=WorkflowStatus.FAILED,
        error_message="CLI failed",
    )
    get_workflow_registry()["wf-test-3"] = record

    resp = await async_client.get("/api/rest/workflows/wf-test-3/", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["workflow_status"] == "failed"
    assert data["error_message"] == "CLI failed"
