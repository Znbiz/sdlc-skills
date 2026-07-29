"""End-to-end coverage for the `analyze_repositories`/`analyze_repositories_item` graph topology.

Runs the *real* compiled LangGraph (`compile_graph()` + `MemorySaver`), mocking only the external LLM CLI
call (`LlmWorkerService.run_task`). Everything else — guard/domain operations, checkpoint persistence — is
real, so these tests prove the actual graph-level behavior described in
docs/spec/2026-07-26-analyze-repositories-merge-checklist-items.md (superseding
docs/spec/2026-07-21-analyze-repositories-per-item-nodes.md): one LLM call per *repository* (covering every
routed checklist item in that one call), a per-repository checkpoint, and no repeated LLM work after a
simulated crash-and-resume - at repository granularity, not item granularity.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from langgraph.checkpoint.memory import MemorySaver

from app.workflows.init_arch.domain import (
    AnalysisTargetCommitStatus,
    LlmTaskKind,
    LlmTaskResult,
    RepositoryExecution,
    StepId,
    WorkflowSessionRecord,
)
from app.workflows.init_arch.graph import compile_graph
from app.workflows.init_arch.state import InitArchState

_CHECKLIST_ITEMS = {
    "repository_classification": "references/checklist-repository-classification.md",
    "entrypoints_and_interfaces": "references/checklist-entrypoints-and-interfaces.md",
    "tech_stack_collection": "references/checklist-tech-stack.md",
}


def _seed_state(session: WorkflowSessionRecord) -> InitArchState:
    return InitArchState(
        session_id=session.session_id,
        session=session,
        workspace_dir="/workspace/repo",
        arch_repo_dir="/workspace/repo/arch-doc",
        engine_name="claude",
        timeout_seconds=60,
        progress_file_path="/workspace/repo/arch-doc/progress.yaml",
        last_llm_result=None,
        last_guard_output="",
        step_error=None,
        retry_count=0,
    )


def _make_llm_service() -> MagicMock:
    llm_service = MagicMock()
    llm_service.run_task = AsyncMock(
        side_effect=lambda request, **_: LlmTaskResult(
            task_kind=LlmTaskKind.REPOSITORY_CHECKLIST_ITEM,
            step_id=StepId.ANALYZE_REPOSITORIES,
            notes=f"processed {request.repository_name}",
            # Every seeded repository has default (NOT_STARTED) commit_range_status -> FULL_REQUIRED
            # severity -> all of _CHECKLIST_ITEMS routed together in the one merged call per repository.
            # Reporting all of them back models an agent that genuinely addressed everything it was
            # asked for in that single call - the honest-completion contract itself (partial/zero
            # completion) is covered separately in test_nodes.py.
            completed_checklist_items=list(_CHECKLIST_ITEMS),
        )
    )
    return llm_service


def _two_repository_session() -> WorkflowSessionRecord:
    return WorkflowSessionRecord(
        session_id="wf-analyze-repos",
        product_name="Prod",
        analysis_scope="full",
        current_step=StepId.ANALYZE_REPOSITORIES,
        repositories=[
            RepositoryExecution(
                repository_name="svc-a", analysis_target_commit_status=AnalysisTargetCommitStatus.PENDING
            ),
            RepositoryExecution(
                repository_name="svc-b", analysis_target_commit_status=AnalysisTargetCommitStatus.PENDING
            ),
        ],
    )


async def test_analyze_repositories_checkpoints_after_every_repository() -> None:
    """One merged LLM call per repository, and its checkpoint reflects all of that repo's items at once."""
    session = _two_repository_session()
    checkpointer = MemorySaver()
    config = {"configurable": {"thread_id": session.session_id}}
    llm_service = _make_llm_service()

    with (
        patch("app.workflows.init_arch.nodes.CHECKLIST_ITEM_TO_REFERENCE", _CHECKLIST_ITEMS),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service", return_value=llm_service),
    ):
        graph = compile_graph(checkpointer=checkpointer)
        await graph.aupdate_state(config, dict(_seed_state(session)), as_node="assess_scope_and_domains")

        item_node_checklist_lengths: list[int] = []
        final_session = session
        async for event in graph.astream(None, config=config):
            for node_name, node_output in event.items():
                if node_name == "analyze_repositories_item":
                    snapshot = await graph.aget_state(config)
                    svc_a = next(
                        repo for repo in snapshot.values["session"].repositories if repo.repository_name == "svc-a"
                    )
                    item_node_checklist_lengths.append(len(svc_a.checklist_items_completed))
                if isinstance(node_output, dict) and node_output.get("session") is not None:
                    final_session = node_output["session"]
            # Scope this test to the analyze_repositories step only — stop as soon as the repo-loop node
            # hands control to interview_user, without driving the rest of the (unrelated) pipeline.
            if final_session.current_step is StepId.INTERVIEW_USER:
                break

    # 1 merged call x 2 repos = 2 LLM calls total — not one per checklist item.
    assert llm_service.run_task.await_count == 2
    assert final_session.current_step is StepId.INTERVIEW_USER
    for repository in final_session.repositories:
        assert repository.analysis_status == "completed"
        assert set(repository.checklist_items_completed) == set(_CHECKLIST_ITEMS)

    # svc-a's own `analyze_repositories_item` checkpoint (there's exactly one, since it's a single merged
    # call) already carries all 3 of its items at once, not 1/2/3 building up across three separate calls —
    # the accepted trade-off from the per-item design (2026-07-21) this change reverses.
    assert item_node_checklist_lengths[:1] == [3]


async def test_analyze_repositories_resume_after_crash_does_not_repeat_completed_repository() -> None:
    """Stopping mid-stream (simulated crash) and resuming from the same checkpoint must not redo LLM work.

    Granularity is now per-repository, not per-item (accepted trade-off, see
    2026-07-26-analyze-repositories-merge-checklist-items.md): a crash after svc-a's one merged call has
    checkpointed must not resend svc-a to the LLM on resume, but a crash *during* svc-a's call (not
    modeled here - the mocked LLM call is a single atomic await) would redo svc-a's whole checklist, not
    just its remaining items.
    """
    session = _two_repository_session()
    checkpointer = MemorySaver()
    config = {"configurable": {"thread_id": session.session_id}}
    llm_service = _make_llm_service()

    with (
        patch("app.workflows.init_arch.nodes.CHECKLIST_ITEM_TO_REFERENCE", _CHECKLIST_ITEMS),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service", return_value=llm_service),
    ):
        graph = compile_graph(checkpointer=checkpointer)
        await graph.aupdate_state(config, dict(_seed_state(session)), as_node="assess_scope_and_domains")

        # Simulate a process crash: stop consuming the stream right after svc-a's one merged
        # `analyze_repositories_item` call has gone through (and therefore been checkpointed).
        processed_item_nodes = 0
        async for event in graph.astream(None, config=config):
            if "analyze_repositories_item" in event:
                processed_item_nodes += 1
            if processed_item_nodes == 1:
                break

        assert llm_service.run_task.await_count == 1
        mid_crash_state = await graph.aget_state(config)
        svc_a_after_crash = next(
            repo for repo in mid_crash_state.values["session"].repositories if repo.repository_name == "svc-a"
        )
        assert set(svc_a_after_crash.checklist_items_completed) == set(_CHECKLIST_ITEMS)

        # "Restart": a fresh call into the same checkpointer/thread_id, exactly like a new process picking up
        # `run_workflow()` after a crash (see `_drive_graph_stream`/`run_workflow` in init_arch_workflow.py).
        # Scoped to analyze_repositories the same way as the happy-path test: stop once it hands off to
        # interview_user, without driving the rest of the (unrelated) pipeline.
        final_session = mid_crash_state.values["session"]
        async for event in graph.astream(None, config=config):
            for node_output in event.values():
                if isinstance(node_output, dict) and node_output.get("session") is not None:
                    final_session = node_output["session"]
            if final_session.current_step is StepId.INTERVIEW_USER:
                break

    # Exactly 2 total LLM calls across both runs (1 before the simulated crash + 1 after) — svc-a, already
    # completed before the crash, is not re-sent to the LLM.
    assert llm_service.run_task.await_count == 2
    repository_names_per_call = [call.args[0].repository_name for call in llm_service.run_task.await_args_list]
    assert repository_names_per_call == ["svc-a", "svc-b"]
    for repository in final_session.repositories:
        assert repository.analysis_status == "completed"
        assert set(repository.checklist_items_completed) == set(_CHECKLIST_ITEMS)
    assert final_session.current_step is StepId.INTERVIEW_USER
