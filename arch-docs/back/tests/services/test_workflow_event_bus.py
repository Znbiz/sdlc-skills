import asyncio

from app.services.workflow_event_bus import WorkflowEventBus


def test_publish_delivers_to_subscribed_queue():
    bus = WorkflowEventBus()
    queue = bus.subscribe("wf-1")

    bus.publish("wf-1", {"event_type": "step_started"})

    assert queue.get_nowait() == {"event_type": "step_started"}


def test_publish_ignores_unsubscribed_workflow():
    bus = WorkflowEventBus()
    bus.subscribe("wf-1")

    bus.publish("wf-other", {"event_type": "step_started"})

    # publish() must use dict.get(), not `[]`, so it never autovivifies a defaultdict entry for a
    # workflow nobody subscribed to (that would leak an ever-growing empty-list entry per publish).
    assert "wf-other" not in bus._subscribers


def test_publish_with_empty_workflow_id_is_noop():
    bus = WorkflowEventBus()

    bus.publish("", {"event_type": "step_started"})

    assert bus._subscribers == {}


def test_publish_fans_out_to_multiple_subscribers():
    bus = WorkflowEventBus()
    queue_a = bus.subscribe("wf-1")
    queue_b = bus.subscribe("wf-1")

    bus.publish("wf-1", {"event_type": "llm_call_started"})

    assert queue_a.get_nowait()["event_type"] == "llm_call_started"
    assert queue_b.get_nowait()["event_type"] == "llm_call_started"


def test_unsubscribe_removes_queue_and_cleans_up_empty_workflow_entry():
    bus = WorkflowEventBus()
    queue = bus.subscribe("wf-1")

    bus.unsubscribe("wf-1", queue)

    assert "wf-1" not in bus._subscribers


def test_unsubscribe_unknown_workflow_is_a_noop():
    bus = WorkflowEventBus()
    queue = asyncio.Queue()

    bus.unsubscribe("does-not-exist", queue)  # must not raise
