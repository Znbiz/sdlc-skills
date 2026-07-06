from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workflows.init_arch import nodes as nodes_module
from app.workflows.init_arch.nodes import _run_cli
from app.workflows.init_arch.state import InitArchState


def _make_state(**kwargs) -> InitArchState:
    base = InitArchState(
        product_name="Prod",
        analysis_scope="full",
        workspace_dir="/workspace/repo",
        arch_repo_dir="/workspace/repo/arch-doc",
        engine_name="claude",
        timeout_seconds=60,
        progress_file_path="/workspace/repo/arch-doc/progress.yaml",
        current_step_id="define_scope",
        current_repo_name="",
        completed_steps=[],
        repo_list=["svc-a"],
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


@pytest.fixture
def mock_guard():
    with patch("app.workflows.init_arch.nodes.run_guard", new_callable=AsyncMock, return_value="guard_ok") as m:
        yield m


@pytest.fixture
def mock_cli():
    with patch("app.workflows.init_arch.nodes._run_cli", new_callable=AsyncMock, return_value='{"completed_actions": []}') as m:
        yield m


async def test_node_define_scope_success(mock_guard, mock_cli):
    state = _make_state()
    result = await nodes_module.node_define_scope(state)
    assert result["current_step_id"] == "request_repository_list"
    assert "define_scope" in result["completed_steps"]
    assert result["step_error"] is None


async def test_node_define_scope_error(mock_guard):
    mock_guard.side_effect = RuntimeError("guard failed")
    state = _make_state()
    result = await nodes_module.node_define_scope(state)
    assert result["step_error"] == "guard failed"
    assert result["retry_count"] == 1


async def test_node_request_repository_list_with_repos(mock_guard):
    state = _make_state(repo_list=["svc-a", "svc-b"])
    result = await nodes_module.node_request_repository_list(state)
    assert result["current_step_id"] == "prepare_temp_workspace"
    assert result["step_error"] is None


async def test_node_request_repository_list_interrupt():
    state = _make_state(repo_list=[])
    with patch("app.workflows.init_arch.nodes.interrupt") as mock_interrupt:
        mock_interrupt.side_effect = Exception("interrupt called")
        with pytest.raises(Exception, match="interrupt called"):
            await nodes_module.node_request_repository_list(state)
        mock_interrupt.assert_called_once()


async def test_node_prepare_temp_workspace_success(mock_guard, mock_cli):
    state = _make_state()
    result = await nodes_module.node_prepare_temp_workspace(state)
    assert result["current_step_id"] == "clone_repositories"
    assert result["step_error"] is None


async def test_node_clone_repositories_success(mock_guard, mock_cli):
    state = _make_state()
    result = await nodes_module.node_clone_repositories(state)
    assert result["current_step_id"] == "refresh_main_branches"


async def test_node_clone_repositories_error(mock_cli):
    with patch("app.workflows.init_arch.nodes.run_guard", new_callable=AsyncMock, side_effect=RuntimeError("err")):
        state = _make_state(retry_count=0)
        result = await nodes_module.node_clone_repositories(state)
    assert result["retry_count"] == 1


async def test_node_refresh_main_branches_success(mock_guard, mock_cli):
    state = _make_state()
    result = await nodes_module.node_refresh_main_branches(state)
    assert result["current_step_id"] == "plan_repository_order"


async def test_node_plan_repository_order_success(mock_guard, mock_cli):
    state = _make_state()
    result = await nodes_module.node_plan_repository_order(state)
    assert result["current_step_id"] == "assess_scope_and_domains"


async def test_node_assess_scope_and_domains_single_repo(mock_guard, mock_cli):
    state = _make_state(repo_list=["svc-a"])
    result = await nodes_module.node_assess_scope_and_domains(state)
    assert result["domain_strategy"] == "per_module"
    assert result["current_step_id"] == "analyze_repositories"


async def test_node_assess_scope_and_domains_multi_repo(mock_guard, mock_cli):
    state = _make_state(repo_list=["svc-a", "svc-b"])
    result = await nodes_module.node_assess_scope_and_domains(state)
    assert result["domain_strategy"] == "per_domain"


async def test_node_analyze_repositories_success(mock_guard, mock_cli):
    state = _make_state(repo_list=["svc-a"])
    result = await nodes_module.node_analyze_repositories(state)
    assert result["current_step_id"] == "interview_user"
    assert result["step_error"] is None


async def test_node_analyze_repositories_error(mock_guard):
    with patch("app.workflows.init_arch.nodes._run_cli", new_callable=AsyncMock, side_effect=RuntimeError("cli err")):
        state = _make_state(repo_list=["svc-a"], retry_count=1)
        result = await nodes_module.node_analyze_repositories(state)
    assert result["retry_count"] == 2


async def test_node_interview_user_no_questions(mock_guard):
    state = _make_state(open_questions=[], answered_questions=[])
    result = await nodes_module.node_interview_user(state)
    assert result["current_step_id"] == "refine_features"


async def test_node_interview_user_all_answered(mock_guard):
    state = _make_state(open_questions=["q1", "q2"], answered_questions=["q1", "q2"])
    result = await nodes_module.node_interview_user(state)
    assert result["current_step_id"] == "refine_features"


async def test_node_interview_user_interrupt():
    state = _make_state(open_questions=["What is X?"], answered_questions=[])
    with patch("app.workflows.init_arch.nodes.interrupt") as mock_interrupt:
        mock_interrupt.side_effect = Exception("interrupt")
        with pytest.raises(Exception, match="interrupt"):
            await nodes_module.node_interview_user(state)
        mock_interrupt.assert_called_once()


async def test_node_refine_features_success(mock_guard, mock_cli):
    state = _make_state()
    result = await nodes_module.node_refine_features(state)
    assert result["current_step_id"] == "build_navigation_index"


async def test_node_build_navigation_index_success(mock_guard, mock_cli):
    state = _make_state()
    result = await nodes_module.node_build_navigation_index(state)
    assert result["current_step_id"] == "run_knowledge_lint"


async def test_node_run_knowledge_lint_success(mock_guard, mock_cli):
    state = _make_state()
    result = await nodes_module.node_run_knowledge_lint(state)
    assert result["current_step_id"] == "validate_final"


async def test_node_validate_final_success(mock_guard, mock_cli):
    state = _make_state()
    result = await nodes_module.node_validate_final(state)
    assert result["current_step_id"] == "finalize_progress"


async def test_node_finalize_progress_success(mock_guard):
    state = _make_state()
    result = await nodes_module.node_finalize_progress(state)
    assert result["current_step_id"] == "done"


async def test_node_finalize_progress_error():
    with patch("app.workflows.init_arch.nodes.run_guard", new_callable=AsyncMock, side_effect=RuntimeError("finalize failed")):
        state = _make_state(retry_count=0)
        result = await nodes_module.node_finalize_progress(state)
    assert result["retry_count"] == 1


async def test_node_handle_error_logs_and_returns():
    state = _make_state(step_error="test error", retry_count=3)
    result = await nodes_module.node_handle_error(state)
    assert result == {}


class TestRunCli:
    def _make_mock_proc(self, returncode: int, stdout: bytes, stderr: bytes) -> MagicMock:
        mock_proc = MagicMock()
        mock_proc.returncode = returncode
        mock_proc.communicate = AsyncMock(return_value=(stdout, stderr))
        return mock_proc

    async def test_claude_success(self) -> None:
        state = _make_state(engine_name="claude")
        mock_proc = self._make_mock_proc(0, b"claude output", b"")
        with patch("app.workflows.init_arch.nodes.asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
            result = await _run_cli(state, "test prompt")
        assert result == "claude output"

    async def test_codex_success(self) -> None:
        state = _make_state(engine_name="codex")
        mock_proc = self._make_mock_proc(0, b"codex output", b"")
        with patch("app.workflows.init_arch.nodes.asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
            result = await _run_cli(state, "test prompt")
        assert result == "codex output"

    async def test_nonzero_exit_raises(self) -> None:
        state = _make_state(engine_name="claude")
        mock_proc = self._make_mock_proc(1, b"", b"error message")
        with patch("app.workflows.init_arch.nodes.asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
            with pytest.raises(RuntimeError, match="error message"):
                await _run_cli(state, "test prompt")


async def test_node_prepare_temp_workspace_error(mock_cli):
    with patch("app.workflows.init_arch.nodes.run_guard", new_callable=AsyncMock, side_effect=RuntimeError("ws err")):
        state = _make_state(retry_count=0)
        result = await nodes_module.node_prepare_temp_workspace(state)
    assert result["retry_count"] == 1


async def test_node_refresh_main_branches_error(mock_cli):
    with patch("app.workflows.init_arch.nodes.run_guard", new_callable=AsyncMock, side_effect=RuntimeError("refresh err")):
        state = _make_state(retry_count=2)
        result = await nodes_module.node_refresh_main_branches(state)
    assert result["retry_count"] == 3


async def test_node_plan_repository_order_error(mock_cli):
    with patch("app.workflows.init_arch.nodes.run_guard", new_callable=AsyncMock, side_effect=RuntimeError("plan err")):
        state = _make_state(retry_count=0)
        result = await nodes_module.node_plan_repository_order(state)
    assert result["step_error"] == "plan err"


async def test_node_assess_scope_error(mock_cli):
    with patch("app.workflows.init_arch.nodes.run_guard", new_callable=AsyncMock, side_effect=RuntimeError("assess err")):
        state = _make_state(retry_count=0)
        result = await nodes_module.node_assess_scope_and_domains(state)
    assert result["step_error"] == "assess err"


async def test_node_refine_features_error(mock_cli):
    with patch("app.workflows.init_arch.nodes.run_guard", new_callable=AsyncMock, side_effect=RuntimeError("refine err")):
        state = _make_state(retry_count=0)
        result = await nodes_module.node_refine_features(state)
    assert result["step_error"] == "refine err"


async def test_node_build_navigation_index_error(mock_cli):
    with patch("app.workflows.init_arch.nodes.run_guard", new_callable=AsyncMock, side_effect=RuntimeError("nav err")):
        state = _make_state(retry_count=0)
        result = await nodes_module.node_build_navigation_index(state)
    assert result["step_error"] == "nav err"


async def test_node_run_knowledge_lint_error(mock_cli):
    with patch("app.workflows.init_arch.nodes.run_guard", new_callable=AsyncMock, side_effect=RuntimeError("lint err")):
        state = _make_state(retry_count=0)
        result = await nodes_module.node_run_knowledge_lint(state)
    assert result["step_error"] == "lint err"


async def test_node_validate_final_error(mock_cli):
    with patch("app.workflows.init_arch.nodes.run_guard", new_callable=AsyncMock, side_effect=RuntimeError("validate err")):
        state = _make_state(retry_count=0)
        result = await nodes_module.node_validate_final(state)
    assert result["step_error"] == "validate err"
