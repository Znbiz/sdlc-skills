import datetime as dt
from unittest.mock import patch

from app.workflows.init_arch import prompts as prompts_module
from app.workflows.init_arch.domain import CommitRangeStatus, RepositoryExecution, StepId, WorkflowSessionRecord
from app.workflows.init_arch.prompts import build_step_prompt
from app.workflows.init_arch.state import InitArchState
from app.workflows.shared_assets.loader import WorkflowAssetLoader


def _make_state(**kwargs) -> InitArchState:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="MyProduct",
        analysis_scope="full",
        repositories=[RepositoryExecution(repository_name="svc-a")],
    )
    defaults = InitArchState(
        session_id=session.session_id,
        session=session,
        workspace_dir="/workspace/repo",
        arch_repo_dir="/workspace/repo/arch-doc",
        engine_name="claude",
        timeout_seconds=300,
        progress_file_path="/workspace/repo/arch-doc/progress.yaml",
        last_llm_result=None,
        last_guard_output="",
        step_error=None,
        retry_count=0,
    )
    defaults.update(kwargs)  # type: ignore[arg-type]
    return defaults


def test_build_step_prompt_contains_step_id():
    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL CONTENT"):
        result = build_step_prompt("define_scope", _make_state())
    assert "define_scope" in result
    assert "SKILL CONTENT" in result


def test_build_step_prompt_with_reference(tmp_path):
    ref_file = tmp_path / "init_arch" / "references" / "checklist-scope-and-domain-assessment.md"
    ref_file.parent.mkdir(parents=True)
    ref_file.write_text("REFERENCE CONTENT")
    skill_file = tmp_path / "init_arch" / "SKILL.md"
    skill_file.write_text("SKILL")

    with (
        patch.object(
            prompts_module,
            "get_workflow_asset_loader",
            return_value=WorkflowAssetLoader(tmp_path),
            create=True,
        ),
    ):
        result = build_step_prompt("assess_scope_and_domains", _make_state())
    assert "REFERENCE CONTENT" in result


def test_build_step_prompt_analyze_repositories_uses_checklist_item(tmp_path):
    ref_file = tmp_path / "init_arch" / "references" / "checklist-repository-classification.md"
    ref_file.parent.mkdir(parents=True)
    ref_file.write_text("CLASSIFICATION REFERENCE")
    skill_file = tmp_path / "init_arch" / "SKILL.md"
    skill_file.write_text("SKILL")

    with (
        patch.object(
            prompts_module,
            "get_workflow_asset_loader",
            return_value=WorkflowAssetLoader(tmp_path),
            create=True,
        ),
    ):
        result = build_step_prompt("analyze_repositories", _make_state(), checklist_item_id="repository_classification")
    assert "CLASSIFICATION REFERENCE" in result


def test_build_step_prompt_no_reference_fallback():
    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("define_scope", _make_state())
    assert "нет дополнительного reference" in result


def test_build_step_prompt_includes_completed_steps():
    state = _make_state()
    state["session"] = state["session"].model_copy(
        update={"completed_steps": [StepId.DEFINE_SCOPE, StepId.REQUEST_REPOSITORY_LIST]}
    )
    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("prepare_temp_workspace", state)
    assert "define_scope" in result
    assert "request_repository_list" in result


def test_build_step_prompt_no_active_repository_has_no_delta():
    state = _make_state()
    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("define_scope", state)
    assert "Нет активного репозитория в работе" in result


def test_build_step_prompt_includes_temporal_delta_for_active_repository():
    repo = RepositoryExecution(
        repository_name="svc-a",
        analysis_status="in_progress",
        analysis_target_date=dt.date(2026, 1, 1),
        analysis_target_commit="abc123",
        window_start_commit="baseline000",
        window_end_commit="abc123",
        commit_range="baseline000..abc123",
        commit_range_status=CommitRangeStatus.DIFF_COLLECTED,
        commit_log_summary="abc123 fix bug",
        diff_stat_summary="1 file changed",
        changed_paths=["app/main.py"],
        renamed_paths=[],
        deleted_paths=["app/old.py"],
        temporal_delta_note="важное замечание",
    )
    state = _make_state()
    state["session"] = state["session"].model_copy(update={"repositories": [repo]})

    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("assess_scope_and_domains", state)

    assert "abc123" in result
    assert "baseline000..abc123" in result
    assert "diff_collected" in result
    assert "app/main.py" in result
    assert "app/old.py" in result
    assert "важное замечание" in result
    assert "Сначала изучи Temporal delta" in result


def test_build_step_prompt_not_started_status_has_placeholder_note():
    repo = RepositoryExecution(
        repository_name="svc-a",
        analysis_status="in_progress",
        commit_range_status=CommitRangeStatus.NOT_STARTED,
    )
    state = _make_state()
    state["session"] = state["session"].model_copy(update={"repositories": [repo]})

    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("define_scope", state)

    assert "ещё не построена" in result


def test_build_step_prompt_no_changes_status_has_explanatory_note():
    repo = RepositoryExecution(
        repository_name="svc-a",
        analysis_status="in_progress",
        commit_range_status=CommitRangeStatus.NO_CHANGES,
    )
    state = _make_state()
    state["session"] = state["session"].model_copy(update={"repositories": [repo]})

    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("assess_scope_and_domains", state)

    assert "изменений в репозитории не было" in result


def test_build_step_prompt_compact_changed_paths_truncated_for_non_expanded_step():
    repo = RepositoryExecution(
        repository_name="svc-a",
        analysis_status="in_progress",
        commit_range_status=CommitRangeStatus.DIFF_COLLECTED,
        commit_range="a..b",
        changed_paths=[f"app/file_{i}.py" for i in range(15)],
    )
    state = _make_state()
    state["session"] = state["session"].model_copy(update={"repositories": [repo]})

    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("define_scope", state)

    assert "и ещё 5 путей" in result


def test_build_step_prompt_expanded_changed_paths_full_for_analyze_repositories():
    repo = RepositoryExecution(
        repository_name="svc-a",
        analysis_status="in_progress",
        commit_range_status=CommitRangeStatus.DIFF_COLLECTED,
        commit_range="a..b",
        changed_paths=[f"app/file_{i}.py" for i in range(15)],
    )
    state = _make_state()
    state["session"] = state["session"].model_copy(update={"repositories": [repo]})

    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("analyze_repositories", state)

    assert "и ещё" not in result
    assert "app/file_14.py" in result


def test_load_skill_md_caches_result(tmp_path):
    skill_file = tmp_path / "init_arch" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text("CACHED SKILL")
    prompts_module._SKILL_MD_CACHE = ""

    with patch.object(
        prompts_module,
        "get_workflow_asset_loader",
        return_value=WorkflowAssetLoader(tmp_path),
        create=True,
    ):
        first = prompts_module._load_skill_md()
        second = prompts_module._load_skill_md()

    assert first == "CACHED SKILL"
    assert second == "CACHED SKILL"
    prompts_module._SKILL_MD_CACHE = ""


def test_load_skill_md_missing_file():
    prompts_module._SKILL_MD_CACHE = ""
    with patch.object(
        prompts_module,
        "get_workflow_asset_loader",
        return_value=WorkflowAssetLoader(__import__("pathlib").Path("/nonexistent")),
        create=True,
    ):
        result = prompts_module._load_skill_md()
    assert "not found" in result
    prompts_module._SKILL_MD_CACHE = ""
