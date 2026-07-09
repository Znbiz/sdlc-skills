from unittest.mock import AsyncMock, MagicMock, patch

from app.workflows.init_arch import checkpointer as cp_module
from app.workflows.init_arch.checkpointer import get_checkpointer
from app.workflows.init_arch.domain import STEP_DEFINITIONS
from app.workflows.init_arch.graph import _LINEAR_STEP_IDS, _route_after_node, build_graph, compile_graph
from app.workflows.init_arch.state import InitArchState


def _make_state(**kwargs) -> InitArchState:
    base = InitArchState(
        product_name="P",
        analysis_scope="full",
        workspace_dir="/w",
        arch_repo_dir="/w/arch",
        engine_name="claude",
        timeout_seconds=60,
        progress_file_path="/w/arch/p.yaml",
        current_step_id="define_scope",
        current_repo_name="",
        completed_steps=[],
        repo_list=[],
        domain_strategy="",
        open_questions=[],
        answered_questions=[],
        pending_user_question="",
        last_cli_output="",
        last_guard_output="",
        step_error=None,
        retry_count=0,
    )
    base.update(kwargs)  # type: ignore[arg-type]
    return base


def test_build_graph_has_all_nodes():
    graph = build_graph()
    node_names = list(graph.nodes.keys())
    expected_nodes = [
        "define_scope",
        "request_repository_list",
        "prepare_temp_workspace",
        "clone_repositories",
        "refresh_main_branches",
        "plan_repository_order",
        "assess_scope_and_domains",
        "analyze_repositories",
        "interview_user",
        "refine_features",
        "build_navigation_index",
        "run_knowledge_lint",
        "validate_final",
        "finalize_progress",
        "handle_error",
    ]
    for node in expected_nodes:
        assert node in node_names


def test_linear_steps_follow_domain_definitions():
    expected = [definition.step_id for definition in STEP_DEFINITIONS]
    assert expected == _LINEAR_STEP_IDS


def test_compile_graph_returns_compiled():
    compiled = compile_graph()
    assert compiled is not None


def test_compile_graph_with_in_memory_checkpointer():
    from langgraph.checkpoint.memory import MemorySaver

    compiled = compile_graph(checkpointer=MemorySaver())
    assert compiled is not None


def test_route_after_node_no_error_goes_to_next():
    route = _route_after_node("define_scope")
    state = _make_state(step_error=None)
    assert route(state) == "request_repository_list"


def test_route_after_node_error_with_retries_returns_same():
    route = _route_after_node("define_scope")
    state = _make_state(step_error="some err", retry_count=1)
    assert route(state) == "define_scope"


def test_route_after_node_error_max_retries_goes_to_handle_error():
    route = _route_after_node("define_scope")
    state = _make_state(step_error="some err", retry_count=3)
    assert route(state) == "handle_error"


def test_route_after_last_node_goes_to_end():
    route = _route_after_node("validate_final")
    state = _make_state(step_error=None)
    assert route(state) == "finalize_progress"


async def test_get_checkpointer_returns_cached():
    original = cp_module._checkpointer
    cp_module._checkpointer = None
    try:
        mock_saver = MagicMock()
        mock_saver.setup = AsyncMock()

        with (
            patch("app.workflows.init_arch.checkpointer.asyncpg.connect", new_callable=AsyncMock) as mock_connect,
            patch("app.workflows.init_arch.checkpointer.AsyncPostgresSaver") as mock_cls,
            patch("app.workflows.init_arch.checkpointer.GatewaySettings") as mock_settings,
        ):
            mock_settings.return_value.database_url = "postgresql+asyncpg://user:pass@localhost/db"
            mock_connect.return_value = MagicMock()
            mock_cls.return_value = mock_saver

            result1 = await get_checkpointer()
            result2 = await get_checkpointer()

        assert result1 is result2
        mock_connect.assert_called_once()
    finally:
        cp_module._checkpointer = original
