from __future__ import annotations

import typing

from app.workflows.init_arch.domain import (
    CommitRangeStatus,
    DomainStrategy,
    RepositoryExecution,
    StepId,
    classify_diff_severity,
)
from app.workflows.init_arch.state import InitArchState
from app.workflows.shared_assets import get_workflow_asset_loader

_EXPANDED_DIFF_CONTEXT_STEPS: typing.Final[frozenset[str]] = frozenset({"analyze_repositories"})
_MAX_COMPACT_CHANGED_PATHS: typing.Final[int] = 10
_RELEASE_NOTES_STEP_VALUE: typing.Final[str] = "generate_release_notes"
_ANALYZE_REPOSITORIES_STEP_VALUE: typing.Final[str] = "analyze_repositories"
_NOT_APPLICABLE_BLOCK: typing.Final[str] = "(не применимо для этого шага)"
_DOMAIN_ASSESSMENT_STEP_VALUE: typing.Final[str] = "assess_scope_and_domains"
_DOMAIN_ASSESSMENT_CONTRACT_BLOCK: typing.Final[str] = """
Дополнительно для этого шага верни top-level поле `domain_assessment` (для остальных шагов это поле не
заполняется и игнорируется):
{
  "domain_assessment": {
    "volume_class": "small|medium|large|xlarge",
    "strategy": "per_module|per_domain",
    "domains": [
      {"domain_id": "...", "name": "...", "paths": ["..."], "signal": "...", "subdomains": []}
    ]
  }
}
Если strategy=per_module, оставь "domains": []. Это поле обязательно для этого шага — без него шаг не
сможет продвинуться дальше."""

_WORKFLOW_ASSET_NAMESPACE = "init_arch"
_SKILL_MD_RELATIVE_PATH = "SKILL.md"

STEP_TO_REFERENCE: typing.Final[dict[str, str]] = {
    "define_scope": "",
    "request_repository_list": "",
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
    "deleted_functionality_cleanup": "references/checklist-deleted-functionality-cleanup.md",
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


def _build_domain_context_block(repository: RepositoryExecution | None) -> str:
    if repository is None:
        return "Нет активного репозитория в работе — домены недоступны для этого шага."

    if repository.domain_strategy is None:
        return (
            "Оценка объёма и доменов для этого репозитория ещё не выполнена "
            "(assess_scope_and_domains не прошёл для него)."
        )

    lines = [
        f"Volume class: {repository.volume_class.value if repository.volume_class else '—'}",
        f"Strategy: {repository.domain_strategy.value}",
    ]
    if repository.domain_strategy is DomainStrategy.PER_MODULE or not repository.domains:
        lines.append("Домены не выделены — анализируй репозиторий как единое целое.")
        return "\n".join(lines)

    lines.append("Домены:")
    for domain in repository.domains:
        paths = ", ".join(domain.paths) or "—"
        lines.append(f'- {domain.domain_id} "{domain.name}" (paths: {paths})')
        if domain.signal:
            lines.append(f"  signal: {domain.signal}")
        if domain.subdomains:
            lines.append(f"  subdomains: {', '.join(domain.subdomains)}")
    return "\n".join(lines)


def _build_autofix_findings_block(autofix_findings: list[str] | None) -> str:
    if not autofix_findings:
        return _NOT_APPLICABLE_BLOCK
    return "\n".join(f"- {finding}" for finding in autofix_findings)


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


def build_step_prompt(  # noqa: PLR0913
    step_id: StepId | str,
    state: InitArchState,
    checklist_item_id: str = "",
    *,
    checklist_item_ids: list[str] | None = None,
    repository_name: str = "",
    autofix_findings: list[str] | None = None,
) -> str:
    step_value = step_id.value if isinstance(step_id, StepId) else step_id
    skill_md = _load_skill_md()
    reference_path_rel = STEP_TO_REFERENCE.get(step_value, "")
    if step_value == "analyze_repositories" and checklist_item_id:
        reference_path_rel = CHECKLIST_ITEM_TO_REFERENCE.get(checklist_item_id, "")

    reference_text = _load_shared_asset(reference_path_rel) if reference_path_rel else ""

    # Merged-item call (node_analyze_repositories_item processes every pending checklist item of a
    # repository in one LLM call instead of one call per item - accepted 2026-07-26 trade-off: trades
    # per-item checkpoint granularity for not re-exploring the same repository from scratch per item,
    # see 2026-07-26-analyze-repositories-merge-checklist-items.md). Overrides the single-item
    # reference_text above with one section per item, each carrying its own reference checklist.
    if step_value == "analyze_repositories" and checklist_item_ids:
        reference_text = "\n\n".join(
            f"## Пункт чек-листа `{item_id}`\n\n"
            f"{_load_shared_asset(CHECKLIST_ITEM_TO_REFERENCE.get(item_id, '')) or '(нет reference для этого пункта)'}"
            for item_id in checklist_item_ids
        )

    completed = ", ".join(step.value for step in state["session"].completed_steps) or "нет"
    # Prefer the explicit repository_name the caller is actually working on over guessing from
    # analysis_status=="in_progress": that heuristic silently breaks for any node whose Python loop
    # processes several repositories in one physical graph node without demoting each one before
    # moving to the next (e.g. node_assess_scope_and_domains, see 2026-07-27 incident - repos after
    # the first all got prompted with the *first* repository's context, because start_repository()
    # never reset the previous repo back off "in_progress", leaving several simultaneously "true" for
    # this scan and `next()` always returning the earliest one in the list, regardless of which repo
    # the current LLM call is actually about). Falls back to the old scan only when no repository_name
    # is supplied (steps that aren't scoped to one repository at all).
    current_repository = (
        next((repo for repo in state["session"].repositories if repo.repository_name == repository_name), None)
        if repository_name
        else next((repo for repo in state["session"].repositories if repo.analysis_status == "in_progress"), None)
    )
    current_repo = current_repository.repository_name if current_repository is not None else "—"
    temporal_delta_block = _build_temporal_delta_block(
        current_repository, expanded=step_value in _EXPANDED_DIFF_CONTEXT_STEPS
    )
    release_notes_block = (
        _build_release_notes_context_block(state) if step_value == _RELEASE_NOTES_STEP_VALUE else _NOT_APPLICABLE_BLOCK
    )
    domain_context_block = (
        _build_domain_context_block(current_repository)
        if step_value == _ANALYZE_REPOSITORIES_STEP_VALUE
        else _NOT_APPLICABLE_BLOCK
    )
    domain_context_instruction = (
        "Используй границы доменов из раздела «Домены репозитория» выше как есть — они уже определены на "
        "шаге assess_scope_and_domains; не открывай их заново через find/ls.\n"
        if step_value == _ANALYZE_REPOSITORIES_STEP_VALUE
        else ""
    )
    autofix_instruction = (
        "Раздел «Найденные проблемы для исправления» выше — результат детерминированной проверки knowledge-слоя. "
        "Правь только файлы, упомянутые в этих issues, не трогай другие. "
        "Не редактируй wiki/index.md и wiki/maps/compile-report.md напрямую — они перезаписываются механически "
        "после твоего вызова, ручная правка потеряется.\n"
        if autofix_findings
        else ""
    )
    checklist_items_instruction = (
        "Пункты чек-листа для этого вызова перечислены выше, каждый под своим заголовком "
        "«Пункт чек-листа `...`» — обработай КАЖДЫЙ из них за этот один вызов, ни один не пропускай.\n"
        "В финальном JSON-отчёте обязательно заполни `completed_checklist_items` — список ID пунктов "
        '(например ["tech_stack_collection", "configs_and_runtime"]), которые ты реально выполнил и для '
        "которых записал/обновил артефакты. Не указывай ID пункта, который фактически не обработал — "
        "это поле сверяется механически с тем, что ты записал на диск, а не принимается декларативно.\n"
        if step_value == _ANALYZE_REPOSITORIES_STEP_VALUE and checklist_item_ids
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
    domain_assessment_instruction = (
        _DOMAIN_ASSESSMENT_CONTRACT_BLOCK if step_value == _DOMAIN_ASSESSMENT_STEP_VALUE else ""
    )
    autofix_findings_block = _build_autofix_findings_block(autofix_findings)

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

# Temporal delta текущего окна

{temporal_delta_block}

---

# Домены репозитория

{domain_context_block}

---

# Контекст release notes для текущего окна

{release_notes_block}

---

# Найденные проблемы для исправления

{autofix_findings_block}

---

# Reference-чеклист для этого шага

{reference_text or "(нет дополнительного reference — следуй SKILL.md)"}

---

# Инструкции

Выполни шаг `{step_value}` строго по reference-чеклисту выше.
Сначала изучи Temporal delta текущего окна выше — commit range, commit log и diff stat —
и только затем при необходимости читай итоговое состояние файлов в raw checkout-слое.
Работай только с файлами внутри {state["workspace_dir"]}.
Raw checkout-слой расположен в {raw_workspace_dir}; используй его только для чтения/checkout исходников.
Все knowledge-артефакты и synthesis-результаты пиши только в {state["arch_repo_dir"]}.
Сервис оркестрирует workflow и сам управляет progress state.
Если нужен progress bridge, его путь: {state["progress_file_path"]}; не используй его как источник решений.
Разделяй выводы: какие из них опираются на temporal delta (diff), а какие — на итоговое snapshot-состояние.
{domain_context_instruction}{autofix_instruction}{checklist_items_instruction}
Выведи краткий структурированный JSON-отчёт о выполненных действиях в формате:
{{
  "completed_actions": ["..."],
  "created_artifacts": ["..."],
  "open_questions_found": ["..."],
  "diff_based_findings": ["..."],
  "snapshot_based_findings": ["..."],
  "completed_checklist_items": ["..."],
  "notes": "..."
}}
Финальный ответ должен быть ТОЛЬКО этим JSON-объектом — без пояснений до или после, без markdown
```-ограждений. Любые пояснения/анализ помести внутрь поля "notes".
{domain_assessment_instruction}"""
