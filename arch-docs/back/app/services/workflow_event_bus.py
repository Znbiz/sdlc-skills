from __future__ import annotations

import asyncio
import collections
import typing

WorkflowEvent: typing.TypeAlias = dict[str, typing.Any]


class WorkflowEventBus:
    """In-memory pub/sub for live workflow SSE events, keyed by `workflow_id`.

    Publishers (task_runner.py, init_arch_workflow.py) call `publish()` the moment an event
    happens; `_stream_live_workflow_events()` subscribes per SSE connection and drains the
    queue with low latency instead of polling coarse `WorkflowRecord` snapshots. See
    arch-docs/docs/spec/2026-07-22-realtime-workflow-observability.md.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[WorkflowEvent]]] = collections.defaultdict(list)

    def publish(self, workflow_id: str, event: WorkflowEvent) -> None:
        if not workflow_id:
            return
        for queue in self._subscribers.get(workflow_id, []):
            queue.put_nowait(event)

    def subscribe(self, workflow_id: str) -> asyncio.Queue[WorkflowEvent]:
        queue: asyncio.Queue[WorkflowEvent] = asyncio.Queue()
        self._subscribers[workflow_id].append(queue)
        return queue

    def unsubscribe(self, workflow_id: str, queue: asyncio.Queue[WorkflowEvent]) -> None:
        subscribers = self._subscribers.get(workflow_id)
        if subscribers is None:
            return
        if queue in subscribers:
            subscribers.remove(queue)
        if not subscribers:
            self._subscribers.pop(workflow_id, None)


_bus: WorkflowEventBus | None = None


def get_workflow_event_bus() -> WorkflowEventBus:
    global _bus  # noqa: PLW0603
    if _bus is None:
        _bus = WorkflowEventBus()
    return _bus


def reset_workflow_event_bus() -> None:
    global _bus  # noqa: PLW0603
    _bus = WorkflowEventBus()
