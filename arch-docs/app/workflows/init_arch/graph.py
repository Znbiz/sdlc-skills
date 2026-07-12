from __future__ import annotations

import typing

from langgraph.graph import END, START, StateGraph

from app.workflows.init_arch.domain import STEP_DEFINITIONS, StepId
from app.workflows.init_arch.nodes import (
    node_analyze_repositories,
    node_assess_scope_and_domains,
    node_build_navigation_index,
    node_clone_repositories,
    node_confirm_next_temporal_window,
    node_define_scope,
    node_finalize_progress,
    node_handle_error,
    node_interview_user,
    node_plan_repository_order,
    node_prepare_temp_workspace,
    node_refine_features,
    node_refresh_main_branches,
    node_request_repository_list,
    node_run_knowledge_lint,
    node_validate_final,
)
from app.workflows.init_arch.state import InitArchState

_MAX_RETRY: typing.Final[int] = 3
_CONFIRM_NEXT_WINDOW_NODE_NAME: typing.Final[str] = StepId.CONFIRM_NEXT_TEMPORAL_WINDOW.value
_REFRESH_MAIN_BRANCHES_NODE_NAME: typing.Final[str] = StepId.REFRESH_MAIN_BRANCHES.value
_FINALIZE_PROGRESS_NODE_NAME: typing.Final[str] = StepId.FINALIZE_PROGRESS.value

_NODE_FUNCTIONS: typing.Final[dict[StepId, typing.Any]] = {
    StepId.DEFINE_SCOPE: node_define_scope,
    StepId.REQUEST_REPOSITORY_LIST: node_request_repository_list,
    StepId.PREPARE_TEMP_WORKSPACE: node_prepare_temp_workspace,
    StepId.CLONE_REPOSITORIES: node_clone_repositories,
    StepId.REFRESH_MAIN_BRANCHES: node_refresh_main_branches,
    StepId.PLAN_REPOSITORY_ORDER: node_plan_repository_order,
    StepId.ASSESS_SCOPE_AND_DOMAINS: node_assess_scope_and_domains,
    StepId.ANALYZE_REPOSITORIES: node_analyze_repositories,
    StepId.INTERVIEW_USER: node_interview_user,
    StepId.REFINE_FEATURES: node_refine_features,
    StepId.BUILD_NAVIGATION_INDEX: node_build_navigation_index,
    StepId.RUN_KNOWLEDGE_LINT: node_run_knowledge_lint,
    StepId.VALIDATE_FINAL: node_validate_final,
    StepId.CONFIRM_NEXT_TEMPORAL_WINDOW: node_confirm_next_temporal_window,
    StepId.FINALIZE_PROGRESS: node_finalize_progress,
}

_LINEAR_STEP_IDS: typing.Final[list[StepId]] = [definition.step_id for definition in STEP_DEFINITIONS]
_LINEAR_NODES: typing.Final[list[tuple[str, typing.Any]]] = [
    (step_id.value, _NODE_FUNCTIONS[step_id]) for step_id in _LINEAR_STEP_IDS
]


def _route_after_node(node_name: str) -> typing.Callable[[InitArchState], str]:
    node_names = [n for n, _ in _LINEAR_NODES]
    node_idx = node_names.index(node_name)
    next_node = node_names[node_idx + 1] if node_idx + 1 < len(node_names) else END

    def route(state: InitArchState) -> str:
        if state.get("step_error"):
            if state.get("retry_count", 0) < _MAX_RETRY:
                return node_name
            return "handle_error"
        return next_node

    return route


def _route_after_confirm_next_temporal_window(state: InitArchState) -> str:
    if state.get("step_error"):
        if state.get("retry_count", 0) < _MAX_RETRY:
            return _CONFIRM_NEXT_WINDOW_NODE_NAME
        return "handle_error"
    if state["session"].current_step is StepId.REFRESH_MAIN_BRANCHES:
        return _REFRESH_MAIN_BRANCHES_NODE_NAME
    return _FINALIZE_PROGRESS_NODE_NAME


def build_graph() -> StateGraph:
    graph = StateGraph(InitArchState)

    for node_name, node_fn in _LINEAR_NODES:
        graph.add_node(node_name, node_fn)
    graph.add_node("handle_error", node_handle_error)

    graph.add_edge(START, "define_scope")

    for node_name, _ in _LINEAR_NODES[:-1]:
        if node_name == _CONFIRM_NEXT_WINDOW_NODE_NAME:
            graph.add_conditional_edges(node_name, _route_after_confirm_next_temporal_window)
        else:
            graph.add_conditional_edges(node_name, _route_after_node(node_name))

    graph.add_conditional_edges(
        "finalize_progress",
        lambda state: "handle_error" if state.get("step_error") and state.get("retry_count", 0) >= _MAX_RETRY else END,
    )
    graph.add_edge("handle_error", END)

    return graph


def compile_graph(checkpointer: typing.Any = None) -> typing.Any:
    graph = build_graph()
    return graph.compile(checkpointer=checkpointer)
