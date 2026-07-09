from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from app.services import init_arch_workflow as workflow_module
from app.services.workflow_registry import WorkflowRecord, reset_workflow_registry


@pytest.fixture(autouse=True)
def clean_workflow_registry():
    reset_workflow_registry()
    yield
    reset_workflow_registry()


async def test_get_workflow_record_async_returns_registry_hit():
    record = WorkflowRecord(workflow_id="wf-1")
    workflow_module.get_workflow_registry()["wf-1"] = record

    resolved = await workflow_module.get_workflow_record_async("wf-1")

    assert resolved is record


async def test_get_workflow_record_async_loads_from_db_when_registry_empty():
    record = WorkflowRecord(workflow_id="wf-db", conversation_id="wf-db")
    fake_session = AsyncMock()

    @asynccontextmanager
    async def _fake_get_session():
        yield fake_session

    with (
        patch("app.services.init_arch_workflow.get_session", _fake_get_session),
        patch("app.services.init_arch_workflow.get_workflow_run", new=AsyncMock(return_value=record)),
    ):
        resolved = await workflow_module.get_workflow_record_async("wf-db")

    assert resolved.workflow_id == "wf-db"
    assert workflow_module.get_workflow_registry()["wf-db"] is resolved
