from __future__ import annotations

import typing

from app.workflows.init_arch.domain import CommitRangeStatus, RepositoryExecution, StepId, classify_diff_severity
from app.workflows.init_arch.state import InitArchState
from app.workflows.shared_assets import get_workflow_asset_loader

_EXPANDED_DIFF_CONTEXT_STEPS: typing.Final[frozenset[str]] = frozenset({"analyze_repositories"})
_MAX_COMPACT_CHANGED_PATHS: typing.Final[int] = 10
_RELEASE_NOTES_STEP_VALUE: typing.Final[str] = "generate_release_notes"
_NOT_APPLICABLE_RELEASE_NOTES_BLOCK: typing.Final[str] = "(не применимо для этого шага)"

_WORKFLOW_ASSET_NAMESPACE = "init_arch"
_SKILL_MD_RELATIVE_PATH = "SKILL.md"
_CLONE_REPOSITORIES_STEP_VALUE: typing.Final[str] = "clone_repositories"

STEP_TO_REFERENCE: typing.Final[dict[str, str]] = {
    "define_scope": "",
    "request_repository_list": "",
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
    "generate_release_notes": "references/checklist-release-notes.md",
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


def _load_shared_asset(relative_path: str) -> str:
    try:
        return get_workflow_asset_loader().read_text(_WORKFLOW_ASSET_NAMESPACE, relative_path)
    except FileNotFoundError:
        return ""


def _load_skill_md() -> str:
    global _SKILL_MD_CACHE  # noqa: PLW0603
    if not _SKILL_MD_CACHE:
        _SKILL_MD_CACHE = _load_shared_asset(_SKILL_MD_RELATIVE_PATH) or "(skill not found)"
    return _SKILL_MD_CACHE


def _format_path_list(paths: list[str], *, expanded: bool) -> str:
    if not paths:
        return "нет"
    if expanded or len(paths) <= _MAX_COMPACT_CHANGED_PATHS:
        return "\n".join(f"- {path}" for path in paths)
    shown = "\n".join(f"- {path}" for path in paths[:_MAX_COMPACT_CHANGED_PATHS])
    return f"{shown}\n- ... и ещё {len(paths) - _MAX_COMPACT_CHANGED_PATHS} путей"


def _build_temporal_delta_block(repository: RepositoryExecution | None, *, expanded: bool) -> str:
    if repository is None:
        return "Нет активного репозитория в работе — temporal delta недоступна для этого шага."

    if repository.commit_range_status is CommitRangeStatus.NOT_STARTED:
        return "Temporal delta для этого репозитория ещё не построена (historical prep не выполнялся)."

    status_notes: dict[CommitRangeStatus, str] = {
        CommitRangeStatus.NO_CHANGES: (
            "За период изменений в репозитории не было (snapshot commit совпадает с baseline)."
        ),
        CommitRangeStatus.BASELINE_MISSING: (
            "Baseline недоступен (первое окно или репозиторий появился позже) — "
            "delta не построена, доступен только snapshot state."
        ),
        CommitRangeStatus.INVALID_RANGE: (
            "Commit range невалиден (переписанная история/force-push) — "
            "не полагайся на diff, работай только со snapshot state."
        ),
    }

    lines = [
        f"Snapshot date: {repository.analysis_target_date or '—'}",
        f"Snapshot commit: {repository.analysis_target_commit or '—'}",
        f"Window start commit (baseline): {repository.window_start_commit or '—'}",
        f"Window end commit: {repository.window_end_commit or '—'}",
        f"Commit range: {repository.commit_range or '—'}",
        f"Commit range status: {repository.commit_range_status.value}",
    ]
    note = status_notes.get(repository.commit_range_status)
    if note:
        lines.append(note)

    lines.extend(
        [
            "",
            "Commit log summary:",
            repository.commit_log_summary or "нет",
            "",
            "Diff stat summary:",
            repository.diff_stat_summary or "нет",
            "",
            "Изменённые пути:",
            _format_path_list(repository.changed_paths, expanded=expanded),
            "Переименованные пути:",
            _format_path_list(repository.renamed_paths, expanded=expanded),
            "Удалённые пути:",
            _format_path_list(repository.deleted_paths, expanded=expanded),
        ]
    )
    if repository.temporal_delta_note:
        lines.extend(["", f"Заметка: {repository.temporal_delta_note}"])
    return "\n".join(lines)


def _build_release_notes_context_block(state: InitArchState) -> str:
    session = state["session"]
    historical = session.historical_analysis
    lines = [
        f"Window index: {historical.window_index}",
        f"Previous snapshot: {historical.previous_snapshot_at or '—'}",
        f"Current snapshot: {historical.current_snapshot_at or '—'}",
        "",
        "Репозитории в этом окне:",
    ]
    for repository in session.repositories:
        lines.extend(
            [
                "",
                f"### {repository.repository_name}",
                f"Commit range: {repository.commit_range or '—'}",
                f"Commit range status: {repository.commit_range_status.value}",
                f"Diff severity: {classify_diff_severity(repository).value}",
                "Diff stat summary:",
                repository.diff_stat_summary or "нет",
                "Commit log summary:",
                repository.commit_log_summary or "нет",
                "Изменённые пути:",
                _format_path_list(repository.changed_paths, expanded=False),
            ]
        )
        if repository.temporal_delta_note:
            lines.append(f"Заметка: {repository.temporal_delta_note}")

    artifacts_this_window = [
        artifact for artifact in session.artifacts if artifact.last_updated_window_index == historical.window_index
    ]
    lines.extend(["", "Артефакты, изменённые в этом окне:"])
    if artifacts_this_window:
        lines.extend(f"- {artifact.artifact_path} ({artifact.artifact_kind})" for artifact in artifacts_this_window)
    else:
        lines.append("нет")

    open_questions = [question for question in session.open_questions if question.status == "open"]
    lines.extend(["", "Открытые вопросы:"])
    if open_questions:
        lines.extend(f"- {question.question_id}: {question.question_text}" for question in open_questions)
    else:
        lines.append("нет")

    return "\n".join(lines)


def _build_repository_list_block(state: InitArchState) -> str:
    raw_workspace_dir = state.get("raw_workspace_dir", f"{state['workspace_dir']}/.temp")
    lines: list[str] = []
    for repository in state["session"].repositories:
        target_path = f"{raw_workspace_dir}/{repository.repository_name}"
        if repository.repository_url:
            lines.append(f"- {repository.repository_name}: clone `{repository.repository_url}` -> `{target_path}`")
        else:
            lines.append(
                f"- {repository.repository_name}: URL не указан, "
                f"репозиторий должен уже присутствовать локально по пути `{target_path}`"
            )
    return "\n".join(lines) if lines else "(список репозиториев пуст)"


def build_step_prompt(step_id: StepId | str, state: InitArchState, checklist_item_id: str = "") -> str:
    step_value = step_id.value if isinstance(step_id, StepId) else step_id
    skill_md = _load_skill_md()
    reference_path_rel = STEP_TO_REFERENCE.get(step_value, "")
    if step_value == "analyze_repositories" and checklist_item_id:
        reference_path_rel = CHECKLIST_ITEM_TO_REFERENCE.get(checklist_item_id, "")

    reference_text = _load_shared_asset(reference_path_rel) if reference_path_rel else ""

    completed = ", ".join(step.value for step in state["session"].completed_steps) or "нет"
    current_repository = next(
        (repo for repo in state["session"].repositories if repo.analysis_status == "in_progress"),
        None,
    )
    current_repo = current_repository.repository_name if current_repository is not None else "—"
    temporal_delta_block = _build_temporal_delta_block(
        current_repository, expanded=step_value in _EXPANDED_DIFF_CONTEXT_STEPS
    )
    release_notes_block = (
        _build_release_notes_context_block(state)
        if step_value == _RELEASE_NOTES_STEP_VALUE
        else _NOT_APPLICABLE_RELEASE_NOTES_BLOCK
    )
    clone_instruction = (
        "Для каждого репозитория из раздела «Список репозиториев» с указанным URL выполни "
        "`git clone <url> <целевой путь>`. Если URL не указан, репозиторий уже должен существовать "
        "локально по целевому пути — просто убедись, что он там есть.\n"
        if step_value == _CLONE_REPOSITORIES_STEP_VALUE
        else ""
    )
    open_questions = (
        "\n".join(
            f"- {question.question_id} [{question.status}]: {question.question_text}"
            + (f" | answer: {question.answer_text}" if question.answer_text else "")
            for question in state["session"].open_questions
        )
        or "нет"
    )
    raw_workspace_dir = state.get("raw_workspace_dir", f"{state['workspace_dir']}/.temp")
    repository_list_block = (
        _build_repository_list_block(state)
        if step_value == _CLONE_REPOSITORIES_STEP_VALUE
        else _NOT_APPLICABLE_RELEASE_NOTES_BLOCK
    )

    return f"""# Контекст навыка

{skill_md}

---

# Текущее задание

Шаг: `{step_value}`
Продукт: {state["session"].product_name}
Контур анализа: {state["session"].analysis_scope}
Рабочий каталог: {state["workspace_dir"]}
Raw layer: {raw_workspace_dir}
Архитектурный репозиторий: {state["arch_repo_dir"]}
Текущий репозиторий: {current_repo}
Завершённые шаги: {completed}
Открытые вопросы:
{open_questions}

---

# Список репозиториев

{repository_list_block}

---

# Temporal delta текущего окна

{temporal_delta_block}

---

# Контекст release notes для текущего окна

{release_notes_block}

---

# Reference-чеклист для этого шага

{reference_text or "(нет дополнительного reference — следуй SKILL.md)"}

---

# Инструкции

Выполни шаг `{step_value}` строго по reference-чеклисту выше.
{clone_instruction}Сначала изучи Temporal delta текущего окна выше — commit range, commit log и diff stat —
и только затем при необходимости читай итоговое состояние файлов в raw checkout-слое.
Работай только с файлами внутри {state["workspace_dir"]}.
Raw checkout-слой расположен в {raw_workspace_dir}; используй его только для чтения/checkout исходников.
Все knowledge-артефакты и synthesis-результаты пиши только в {state["arch_repo_dir"]}.
Сервис оркестрирует workflow и сам управляет progress state.
Если нужен progress bridge, его путь: {state["progress_file_path"]}; не используй его как источник решений.
Разделяй выводы: какие из них опираются на temporal delta (diff), а какие — на итоговое snapshot-состояние.
Выведи краткий структурированный JSON-отчёт о выполненных действиях в формате:
{{
  "completed_actions": ["..."],
  "created_artifacts": ["..."],
  "open_questions_found": ["..."],
  "diff_based_findings": ["..."],
  "snapshot_based_findings": ["..."],
  "notes": "..."
}}
"""
