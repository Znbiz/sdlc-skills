from __future__ import annotations

import asyncio
import collections

import structlog

from app.db.session import get_session
from app.db.workflow_repo import append_workflow_event
from app.workflows.init_arch.domain import WorkflowEventRecord

logger = structlog.get_logger()


class WorkflowAuditService:
    def __init__(self) -> None:
        self._events: dict[str, list[WorkflowEventRecord]] = collections.defaultdict(list)
        self._pending_persist_tasks: set[asyncio.Task[None]] = set()

    def record(self, event: WorkflowEventRecord) -> None:
        if not event.session_id:
            return
        self._events[event.session_id].append(event)
        try:
            task = asyncio.get_running_loop().create_task(self._persist_event(event))
        except RuntimeError:
            return
        self._pending_persist_tasks.add(task)
        task.add_done_callback(self._pending_persist_tasks.discard)

    def list_events(self, session_id: str) -> list[WorkflowEventRecord]:
        return list(self._events.get(session_id, []))

    def clear(self, session_id: str | None = None) -> None:
        if session_id is None:
            self._events.clear()
            return
        self._events.pop(session_id, None)

    async def wait_for_pending_persist(self) -> None:
        """Await fire-and-forget `_persist_event` tasks spawned by `record()`.

        `record()` intentionally doesn't await persistence so it stays a sync call usable from
        anywhere. Callers that need every write flushed before proceeding (tests truncating
        tables between runs, in particular - a lingering write racing a TRUNCATE deadlocks
        Postgres) must drain the in-flight tasks explicitly via this method.
        """
        pending_tasks = list(self._pending_persist_tasks)
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)

    async def _persist_event(self, event: WorkflowEventRecord) -> None:
        try:
            async with get_session() as session:
                await append_workflow_event(session, event)
        except Exception as exc:  # noqa: BLE001
            logger.warning("workflow.audit_persist_failed", session_id=event.session_id, error=str(exc))


_workflow_audit_service: WorkflowAuditService | None = None


def get_workflow_audit_service() -> WorkflowAuditService:
    global _workflow_audit_service  # noqa: PLW0603
    if _workflow_audit_service is None:
        _workflow_audit_service = WorkflowAuditService()
    return _workflow_audit_service
