from __future__ import annotations

import pathlib
import typing

from app.workflows.init_arch.state import InitArchState

_SKILL_ROOT = pathlib.Path("/app/skills")

STEP_TO_REFERENCE: typing.Final[dict[str, str]] = {
    "define_scope": "",
    "request_repository_list": "",
    "prepare_temp_workspace": "",
    "clone_repositories": "",
    "refresh_main_branches": "",
    "plan_repository_order": "",
    "assess_scope_and_domains": "references/checklist-scope-and-domain-assessment.md",
    "analyze_repositories": "",
    "interview_user": "references/checklist-glossary-and-open-questions.md",
    "refine_features": "references/checklist-features-and-index.md",
    "build_navigation_index": "references/knowledge-workflow.md",
    "run_knowledge_lint": "references/knowledge-workflow.md",
    "validate_final": "references/checklist-repository-consistency-review.md",
    "finalize_progress": "",
}

CHECKLIST_ITEM_TO_REFERENCE: typing.Final[dict[str, str]] = {
    "repository_classification": "references/checklist-repository-classification.md",
    "repository_structure_mapping": "references/checklist-repository-structure-mapping.md",
    "entrypoints_and_interfaces": "references/checklist-entrypoints-and-interfaces.md",
    "business_flow_orchestration": "references/checklist-business-flow-orchestration.md",
    "configs_and_runtime": "references/checklist-configs-and-runtime.md",
    "tech_stack_collection": "references/checklist-tech-stack.md",
    "contracts_and_schemas": "references/checklist-contracts-and-schemas.md",
    "data_and_storage": "references/checklist-data-and-storage.md",
    "domain_entities": "references/checklist-domain-entities.md",
    "integrations_and_dependencies": "references/checklist-integrations-and-dependencies.md",
    "tests_and_behavior_evidence": "references/checklist-tests-and-behavior-evidence.md",
    "glossary_updates": "references/checklist-glossary-and-open-questions.md",
    "open_questions_review_and_updates": "references/checklist-glossary-and-open-questions.md",
    "feature_discovery_and_updates": "references/checklist-features-and-index.md",
    "features_index_updates": "references/checklist-features-and-index.md",
    "roles_and_permissions_updates": "references/checklist-roles-security-operability-risks.md",
    "security_and_auth_updates": "references/checklist-roles-security-operability-risks.md",
    "deployment_and_operability": "references/checklist-roles-security-operability-risks.md",
    "risks_and_tech_debt_updates": "references/checklist-roles-security-operability-risks.md",
    "architecture_artifact_updates": "references/checklist-architecture-artifact-updates.md",
    "repository_consistency_review": "references/checklist-repository-consistency-review.md",
}

_SKILL_MD_CACHE: str = ""


def _load_skill_md() -> str:
    global _SKILL_MD_CACHE  # noqa: PLW0603
    if not _SKILL_MD_CACHE:
        skill_md_path = _SKILL_ROOT / "init-repo-arch-skill/SKILL.md"
        _SKILL_MD_CACHE = skill_md_path.read_text() if skill_md_path.exists() else "(skill not found)"
    return _SKILL_MD_CACHE


def build_step_prompt(step_id: str, state: InitArchState, checklist_item_id: str = "") -> str:
    skill_md = _load_skill_md()
    reference_path_rel = STEP_TO_REFERENCE.get(step_id, "")
    if step_id == "analyze_repositories" and checklist_item_id:
        reference_path_rel = CHECKLIST_ITEM_TO_REFERENCE.get(checklist_item_id, "")

    reference_text = ""
    if reference_path_rel:
        ref_path = _SKILL_ROOT / f"init-repo-arch-skill/{reference_path_rel}"
        reference_text = ref_path.read_text() if ref_path.exists() else ""

    completed = ", ".join(state.get("completed_steps", [])) or "нет"
    current_repo = state.get("current_repo_name") or "—"

    return f"""# Контекст навыка

{skill_md}

---

# Текущее задание

Шаг: `{step_id}`
Продукт: {state["product_name"]}
Контур анализа: {state["analysis_scope"]}
Рабочий каталог: {state["workspace_dir"]}
Архитектурный репозиторий: {state["arch_repo_dir"]}
Текущий репозиторий: {current_repo}
Завершённые шаги: {completed}

---

# Reference-чеклист для этого шага

{reference_text or "(нет дополнительного reference — следуй SKILL.md)"}

---

# Инструкции

Выполни шаг `{step_id}` строго по reference-чеклисту выше.
Работай только с файлами внутри {state["workspace_dir"]}.
Все артефакты пиши в {state["arch_repo_dir"]}.
Путём к progress-файлу является {state["progress_file_path"]} — не трогай его напрямую,
он управляется через analysis_guard.py.
Выведи краткий структурированный JSON-отчёт о выполненных действиях в формате:
{{
  "completed_actions": ["..."],
  "created_artifacts": ["..."],
  "open_questions_found": ["..."],
  "notes": "..."
}}
"""
