from unittest.mock import patch

from app.workflows.init_arch import prompts as prompts_module
from app.workflows.init_arch.prompts import build_step_prompt
from app.workflows.init_arch.state import InitArchState


def _make_state(**kwargs) -> InitArchState:
    defaults = InitArchState(
        product_name="MyProduct",
        analysis_scope="full",
        workspace_dir="/workspace/repo",
        arch_repo_dir="/workspace/repo/arch-doc",
        engine_name="claude",
        timeout_seconds=300,
        progress_file_path="/workspace/repo/arch-doc/progress.yaml",
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
    defaults.update(kwargs)  # type: ignore[arg-type]
    return defaults


def test_build_step_prompt_contains_step_id():
    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL CONTENT"):
        result = build_step_prompt("define_scope", _make_state())
    assert "define_scope" in result
    assert "SKILL CONTENT" in result


def test_build_step_prompt_with_reference(tmp_path):
    ref_file = tmp_path / "init-repo-arch-skill" / "references" / "checklist-scope-and-domain-assessment.md"
    ref_file.parent.mkdir(parents=True)
    ref_file.write_text("REFERENCE CONTENT")

    with patch.object(prompts_module, "_SKILL_ROOT", tmp_path), \
         patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("assess_scope_and_domains", _make_state())
    assert "REFERENCE CONTENT" in result


def test_build_step_prompt_analyze_repositories_uses_checklist_item(tmp_path):
    ref_file = tmp_path / "init-repo-arch-skill" / "references" / "checklist-repository-classification.md"
    ref_file.parent.mkdir(parents=True)
    ref_file.write_text("CLASSIFICATION REFERENCE")

    with patch.object(prompts_module, "_SKILL_ROOT", tmp_path), \
         patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("analyze_repositories", _make_state(), checklist_item_id="repository_classification")
    assert "CLASSIFICATION REFERENCE" in result


def test_build_step_prompt_no_reference_fallback():
    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("define_scope", _make_state())
    assert "нет дополнительного reference" in result


def test_build_step_prompt_includes_completed_steps():
    state = _make_state(completed_steps=["define_scope", "request_repository_list"])
    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("prepare_temp_workspace", state)
    assert "define_scope" in result
    assert "request_repository_list" in result


def test_load_skill_md_caches_result(tmp_path):
    skill_file = tmp_path / "init-repo-arch-skill" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text("CACHED SKILL")
    prompts_module._SKILL_MD_CACHE = ""

    with patch.object(prompts_module, "_SKILL_ROOT", tmp_path):
        first = prompts_module._load_skill_md()
        second = prompts_module._load_skill_md()

    assert first == "CACHED SKILL"
    assert second == "CACHED SKILL"
    prompts_module._SKILL_MD_CACHE = ""


def test_load_skill_md_missing_file():
    prompts_module._SKILL_MD_CACHE = ""
    with patch.object(prompts_module, "_SKILL_ROOT", __import__("pathlib").Path("/nonexistent")):
        result = prompts_module._load_skill_md()
    assert "not found" in result
    prompts_module._SKILL_MD_CACHE = ""
