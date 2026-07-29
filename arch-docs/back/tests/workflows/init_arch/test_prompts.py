import datetime as dt
from unittest.mock import patch

from app.workflows.init_arch import prompts as prompts_module
from app.workflows.init_arch.domain import (
    ArtifactRecord,
    CommitRangeStatus,
    DomainDefinition,
    DomainStrategy,
    RepositoryExecution,
    StepId,
    VolumeClass,
    WorkflowSessionRecord,
)
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


def test_build_step_prompt_analyze_repositories_merges_multiple_checklist_items(tmp_path):
    references_dir = tmp_path / "init_arch" / "references"
    references_dir.mkdir(parents=True)
    (references_dir / "checklist-repository-classification.md").write_text("CLASSIFICATION REFERENCE")
    (references_dir / "checklist-tech-stack.md").write_text("TECH STACK REFERENCE")
    (tmp_path / "init_arch" / "SKILL.md").write_text("SKILL")

    with patch.object(
        prompts_module, "get_workflow_asset_loader", return_value=WorkflowAssetLoader(tmp_path), create=True
    ):
        result = build_step_prompt(
            "analyze_repositories",
            _make_state(),
            checklist_item_ids=["repository_classification", "tech_stack_collection"],
        )

    assert "CLASSIFICATION REFERENCE" in result
    assert "TECH STACK REFERENCE" in result
    assert "completed_checklist_items" in result
    assert "обработай КАЖДЫЙ из них" in result


def test_build_step_prompt_uses_explicit_repository_name_over_in_progress_scan():
    # Regression: node_assess_scope_and_domains processes every repository in one Python loop inside a
    # single physical graph node, calling start_repository() (sets analysis_status="in_progress") for
    # each one in turn without ever demoting the previous repo back off "in_progress" (that only
    # happens later, in analyze_repositories's complete_repository()). By the second repository in the
    # loop, *two* repos are simultaneously "in_progress", and the old `next(repo for repo in ... if
    # analysis_status == "in_progress")` scan always returned the *first* one ever set - every call
    # after the first got prompted with the wrong repository's context (confirmed on a real run: the
    # LLM's response for repo "back-server" was actually analyzing "mobile-app", because the prompt's
    # own "Текущий репозиторий" line said so). Passing repository_name explicitly bypasses the
    # ambiguous status scan entirely.
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="MyProduct",
        analysis_scope="full",
        repositories=[
            RepositoryExecution(repository_name="mobile-app", analysis_status="in_progress"),
            RepositoryExecution(repository_name="back-server", analysis_status="in_progress"),
        ],
    )
    state = _make_state(session=session)

    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("assess_scope_and_domains", state, repository_name="back-server")

    assert "Текущий репозиторий: back-server" in result
    assert "Текущий репозиторий: mobile-app" not in result


def test_build_step_prompt_no_reference_fallback():
    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("define_scope", _make_state())
    assert "нет дополнительного reference" in result


def test_build_step_prompt_release_notes_block_not_applicable_for_other_steps():
    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("define_scope", _make_state())

    assert "(не применимо для этого шага)" in result


def test_build_step_prompt_autofix_findings_not_applicable_when_absent():
    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("run_knowledge_lint", _make_state())

    assert "# Найденные проблемы для исправления" in result
    assert "(не применимо для этого шага)" in result
    assert "Правь только файлы, упомянутые" not in result


def test_build_step_prompt_autofix_findings_rendered_as_list():
    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt(
            "run_knowledge_lint",
            _make_state(),
            autofix_findings=["ERROR: missing related reference a -> b", "ERROR: quality gate failed"],
        )

    assert "- ERROR: missing related reference a -> b" in result
    assert "- ERROR: quality gate failed" in result
    assert "Правь только файлы, упомянутые" in result


def test_build_step_prompt_includes_domain_assessment_contract_for_its_step():
    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("assess_scope_and_domains", _make_state())

    assert "domain_assessment" in result
    assert "per_module|per_domain" in result


def test_build_step_prompt_omits_domain_assessment_contract_for_other_steps():
    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("define_scope", _make_state())

    assert "per_module|per_domain" not in result


def test_build_step_prompt_domain_context_not_applicable_for_other_steps():
    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("refine_features", _make_state())

    assert "# Домены репозитория" in result
    domain_section = result.split("# Домены репозитория")[1].split("---")[0]
    assert "(не применимо для этого шага)" in domain_section


def test_build_step_prompt_domain_context_no_active_repository():
    state = _make_state()
    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("analyze_repositories", state)

    domain_section = result.split("# Домены репозитория")[1].split("---")[0]
    assert "Нет активного репозитория в работе — домены недоступны" in domain_section


def test_build_step_prompt_domain_context_not_yet_assessed():
    repo = RepositoryExecution(repository_name="svc-a", analysis_status="in_progress")
    state = _make_state()
    state["session"] = state["session"].model_copy(update={"repositories": [repo]})

    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("analyze_repositories", state)

    domain_section = result.split("# Домены репозитория")[1].split("---")[0]
    assert "ещё не выполнена" in domain_section


def test_build_step_prompt_domain_context_per_module_repository():
    repo = RepositoryExecution(
        repository_name="svc-a",
        analysis_status="in_progress",
        volume_class=VolumeClass.SMALL,
        domain_strategy=DomainStrategy.PER_MODULE,
    )
    state = _make_state()
    state["session"] = state["session"].model_copy(update={"repositories": [repo]})

    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("analyze_repositories", state)

    domain_section = result.split("# Домены репозитория")[1].split("---")[0]
    assert "Volume class: small" in domain_section
    assert "Strategy: per_module" in domain_section
    assert "Домены не выделены" in domain_section
    assert "Используй границы доменов из раздела «Домены репозитория»" in result


def test_build_step_prompt_domain_context_per_domain_repository_lists_domains():
    repo = RepositoryExecution(
        repository_name="svc-a",
        analysis_status="in_progress",
        volume_class=VolumeClass.LARGE,
        domain_strategy=DomainStrategy.PER_DOMAIN,
        domains=[
            DomainDefinition(
                domain_id="billing",
                name="Биллинг",
                paths=["apps/billing/", "apps/payments/"],
                signal="Отдельные Django-приложения",
                subdomains=["subscriptions"],
            ),
        ],
    )
    state = _make_state()
    state["session"] = state["session"].model_copy(update={"repositories": [repo]})

    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("analyze_repositories", state)

    domain_section = result.split("# Домены репозитория")[1].split("---")[0]
    assert "Strategy: per_domain" in domain_section
    assert 'billing "Биллинг" (paths: apps/billing/, apps/payments/)' in domain_section
    assert "signal: Отдельные Django-приложения" in domain_section
    assert "subdomains: subscriptions" in domain_section


def test_build_step_prompt_includes_completed_steps():
    state = _make_state()
    state["session"] = state["session"].model_copy(
        update={"completed_steps": [StepId.DEFINE_SCOPE, StepId.REQUEST_REPOSITORY_LIST]}
    )
    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("assess_scope_and_domains", state)
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


def test_build_step_prompt_release_notes_includes_all_repositories(tmp_path):
    ref_file = tmp_path / "init_arch" / "references" / "checklist-release-notes.md"
    ref_file.parent.mkdir(parents=True)
    ref_file.write_text("RELEASE NOTES REFERENCE")
    skill_file = tmp_path / "init_arch" / "SKILL.md"
    skill_file.write_text("SKILL")

    repo_a = RepositoryExecution(
        repository_name="svc-a",
        commit_range="a1..a2",
        commit_range_status=CommitRangeStatus.DIFF_COLLECTED,
        diff_stat_summary="3 files changed",
        commit_log_summary="a2 fix bug",
    )
    repo_b = RepositoryExecution(
        repository_name="svc-b",
        commit_range_status=CommitRangeStatus.NO_CHANGES,
    )
    state = _make_state()
    state["session"] = state["session"].model_copy(
        update={
            "repositories": [repo_a, repo_b],
            "historical_analysis": state["session"].historical_analysis.model_copy(
                update={"window_index": 1, "current_snapshot_at": dt.date(2020, 7, 1)}
            ),
        }
    )

    with patch.object(
        prompts_module,
        "get_workflow_asset_loader",
        return_value=WorkflowAssetLoader(tmp_path),
        create=True,
    ):
        result = build_step_prompt("generate_release_notes", state)

    assert "RELEASE NOTES REFERENCE" in result
    assert "Window index: 1" in result
    assert "svc-a" in result
    assert "svc-b" in result
    assert "a1..a2" in result
    assert "no_changes" in result


def test_build_step_prompt_release_notes_lists_artifacts_changed_this_window(tmp_path):
    ref_file = tmp_path / "init_arch" / "references" / "checklist-release-notes.md"
    ref_file.parent.mkdir(parents=True)
    ref_file.write_text("REF")
    skill_file = tmp_path / "init_arch" / "SKILL.md"
    skill_file.write_text("SKILL")

    state = _make_state()
    state["session"] = state["session"].model_copy(
        update={
            "historical_analysis": state["session"].historical_analysis.model_copy(update={"window_index": 1}),
            "artifacts": [
                ArtifactRecord(
                    artifact_path="architecture/hld.md",
                    artifact_kind="architecture_artifact",
                    last_updated_window_index=1,
                ),
                ArtifactRecord(
                    artifact_path="glossary.md",
                    artifact_kind="glossary",
                    last_updated_window_index=0,
                ),
            ],
        }
    )

    with patch.object(
        prompts_module,
        "get_workflow_asset_loader",
        return_value=WorkflowAssetLoader(tmp_path),
        create=True,
    ):
        result = build_step_prompt("generate_release_notes", state)

    assert "architecture/hld.md" in result
    assert "glossary.md" not in result
