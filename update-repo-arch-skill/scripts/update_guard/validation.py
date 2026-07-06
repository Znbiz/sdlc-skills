"""Workflow integrity validation."""

from __future__ import annotations

from .definitions import DIFF_CLASSIFICATIONS, ITEM_STATUSES, REPO_STATUSES, STEP_INDEX
from .models import normalize_repository, repositories_all


def _find_step(progress: dict, step_id: str) -> dict | None:
    workflow = progress["update_progress"].get("workflow") or {}
    for step in workflow.get("steps") or []:
        if step.get("id") == step_id:
            return step
    return None


def validate_progress(progress: dict) -> list[str]:
    errors: list[str] = []
    root = progress["update_progress"]
    workflow = root.get("workflow") or {}
    steps = workflow.get("steps") or []

    if not steps:
        return ["workflow.steps is empty"]

    in_progress = [step["id"] for step in steps if step.get("status") == "in_progress"]
    if len(in_progress) > 1:
        errors.append(
            f"Only one workflow step may be in_progress, found: {', '.join(in_progress)}"
        )

    seen_not_completed = False
    for step in steps:
        status = step.get("status")
        if status not in {"not_started", "in_progress", "completed", "blocked"}:
            errors.append(f"Step {step.get('id')} has invalid status: {status}")
            continue
        if status != "completed":
            seen_not_completed = True
        elif seen_not_completed:
            errors.append(
                f"Step {step.get('id')} is completed after a non-completed step. "
                "Workflow must move forward without gaps."
            )

    current_step_id = workflow.get("current_step_id")
    if current_step_id and current_step_id not in STEP_INDEX:
        errors.append(f"Unknown workflow.current_step_id: {current_step_id}")

    repositories = repositories_all(progress)
    repo_execution = root.get("repository_execution") or {}
    ordered_repository_names = repo_execution.get("ordered_repository_names") or []
    current_repository = repo_execution.get("current_repository") or ""
    completed_repository_names = repo_execution.get("completed_repository_names") or []

    known_names = {repo.get("name") for repo in repositories}
    unknown_ordered = [name for name in ordered_repository_names if name not in known_names]
    if unknown_ordered:
        errors.append(
            "repository_execution.ordered_repository_names references unregistered "
            "repositories: " + ", ".join(unknown_ordered)
        )

    if current_repository and current_repository not in ordered_repository_names:
        errors.append(
            "repository_execution.current_repository must belong to ordered_repository_names."
        )

    for name in completed_repository_names:
        if name not in ordered_repository_names:
            errors.append(
                "repository_execution.completed_repository_names contains unknown "
                f"repository: {name}"
            )

    completed_set = set(completed_repository_names)
    for repo in repositories:
        normalize_repository(repo)
        name = repo.get("name")
        status = repo.get("repo_status")
        if status not in REPO_STATUSES:
            errors.append(f"Repository {name} has invalid repo_status: {status}")
        if name in completed_set and status not in {"completed", "skipped_no_changes"}:
            errors.append(
                f"Repository {name} is marked completed in repository_execution but "
                f"repo_status={status}."
            )
        diff_classification = repo.get("diff_classification")
        if diff_classification and diff_classification not in DIFF_CLASSIFICATIONS:
            errors.append(
                f"Repository {name} has invalid diff_classification: {diff_classification}"
            )
        for category in repo.get("signal_categories", []):
            cat_status = category.get("status")
            if cat_status not in ITEM_STATUSES:
                errors.append(
                    f"Repository {name} category {category.get('category')} has invalid "
                    f"status: {cat_status}"
                )

    triage_step = _find_step(progress, "triage_repositories")
    if triage_step and triage_step.get("status") == "completed":
        missing_classification = [
            repo.get("name")
            for repo in repositories
            if not repo.get("diff_classification")
        ]
        if missing_classification:
            errors.append(
                "triage_repositories is completed but some repositories have no "
                "diff_classification: " + ", ".join(missing_classification)
            )

    signal_step = _find_step(progress, "signal_mapping")
    if signal_step and signal_step.get("status") == "completed":
        missing_signals = [
            repo.get("name")
            for repo in repositories
            if repo.get("diff_classification") == "significant"
            and not repo.get("signal_categories")
        ]
        if missing_signals:
            errors.append(
                "signal_mapping is completed but repositories classified as 'significant' "
                "have no signal_categories registered: " + ", ".join(missing_signals)
            )

    deep_step = _find_step(progress, "targeted_deep_analysis")
    if deep_step and deep_step.get("status") == "completed":
        incomplete = []
        for repo in repositories:
            open_categories = [
                category.get("category")
                for category in repo.get("signal_categories", [])
                if category.get("status") not in {"completed", "blocked"}
            ]
            if open_categories:
                incomplete.append(f"{repo.get('name')}: {', '.join(open_categories)}")
        if incomplete:
            errors.append(
                "targeted_deep_analysis cannot be completed while open signal_categories "
                "remain: " + "; ".join(incomplete)
            )

    cascade_step = _find_step(progress, "cascade_check")
    if cascade_step and cascade_step.get("status") == "completed":
        open_impacts = [
            f"{impact.get('source_repo')} -> {impact.get('target')}"
            for impact in root.get("cascade_impacts") or []
            if impact.get("status") != "completed"
        ]
        if open_impacts:
            errors.append(
                "cascade_check cannot be completed while cascade_impacts remain open: "
                + "; ".join(open_impacts)
            )

    if root.get("status") == "completed":
        finalize_step = _find_step(progress, "finalize_update")
        if not finalize_step or finalize_step.get("status") != "completed":
            errors.append(
                "update_progress.status=completed requires finalize_update step to be completed."
            )

    return errors
