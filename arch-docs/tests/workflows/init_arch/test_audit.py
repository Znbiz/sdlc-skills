from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from app.workflows.init_arch.audit import WorkflowAuditService, get_workflow_audit_service
from app.workflows.init_arch.domain import AuditActor, EventType, StepId, WorkflowEventRecord


def _event(session_id: str = "wf-1") -> WorkflowEventRecord:
    return WorkflowEventRecord(
        event_type=EventType.GUARD_COMMAND_APPLIED,
        actor=AuditActor.SERVICE,
        session_id=session_id,
        step_id=StepId.DEFINE_SCOPE,
        payload={"command": "advance"},
    )


def test_record_ignores_empty_session_id():
    service = WorkflowAuditService()

    service.record(_event(session_id=""))

    assert service.list_events("wf-1") == []


def test_record_without_running_loop_keeps_event_in_memory():
    service = WorkflowAuditService()

    service.record(_event())

    assert len(service.list_events("wf-1")) == 1


async def test_persist_event_swallows_storage_errors():
    service = WorkflowAuditService()

    @asynccontextmanager
    async def _fake_get_session():
        yield MagicMock()

    with (
        patch("app.workflows.init_arch.audit.get_session", _fake_get_session),
        patch("app.workflows.init_arch.audit.append_workflow_event", new=AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        await service._persist_event(_event())


def test_clear_and_singleton_getter_work():
    service = WorkflowAuditService()
    service.record(_event())
    service.clear("wf-1")
    assert service.list_events("wf-1") == []

    singleton = get_workflow_audit_service()
    assert get_workflow_audit_service() is singleton
