from __future__ import annotations

import typing

from langgraph.graph import END, START, StateGraph

from app.workflows.init_arch.nodes import (
    node_analyze_repositories,
    node_assess_scope_and_domains,
    node_build_navigation_index,
    node_clone_repositories,
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

_LINEAR_NODES: typing.Final[list[tuple[str, typing.Any]]] = [
    ("define_scope", node_define_scope),
    ("request_repository_list", node_request_repository_list),
    ("prepare_temp_workspace", node_prepare_temp_workspace),
    ("clone_repositories", node_clone_repositories),
    ("refresh_main_branches", node_refresh_main_branches),
    ("plan_repository_order", node_plan_repository_order),
    ("assess_scope_and_domains", node_assess_scope_and_domains),
    ("analyze_repositories", node_analyze_repositories),
    ("interview_user", node_interview_user),
    ("refine_features", node_refine_features),
    ("build_navigation_index", node_build_navigation_index),
    ("run_knowledge_lint", node_run_knowledge_lint),
    ("validate_final", node_validate_final),
    ("finalize_progress", node_finalize_progress),
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


def build_graph() -> StateGraph:
    graph = StateGraph(InitArchState)

    for node_name, node_fn in _LINEAR_NODES:
        graph.add_node(node_name, node_fn)
    graph.add_node("handle_error", node_handle_error)

    graph.add_edge(START, "define_scope")

    for node_name, _ in _LINEAR_NODES[:-1]:
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
