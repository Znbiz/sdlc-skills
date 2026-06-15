"""Workflow integrity validation."""

from __future__ import annotations

from .definitions import (
    REPOSITORY_CHECKLIST_DEFINITIONS,
    STEP_INDEX,
)
from .models import normalize_repo_domain_map, normalize_repository, repositories_in_scope


def _find_step(progress: dict, step_id: str) -> dict | None:
    workflow = progress["analysis_progress"].get("workflow") or {}
    for step in workflow.get("steps") or []:
        if step.get("id") == step_id:
            return step
    return None


def validate_progress(progress: dict) -> list[str]:
    errors: list[str] = []
    root = progress["analysis_progress"]
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

    current_step = _find_step(progress, current_step_id) if current_step_id else None
    if current_step_id and current_step is None:
        errors.append(
            f"workflow.current_step_id references missing step object: {current_step_id}"
        )
    elif current_step:
        if current_step.get("status") not in {"in_progress", "blocked", "completed"}:
            errors.append(
                f"workflow.current_step_id points to {current_step_id}, "
                f"but its status is {current_step.get('status')}"
            )

    repositories = root.get("repositories") or []
    repo_execution = root.get("repository_execution") or {}
    ordered_repository_names = repo_execution.get("ordered_repository_names") or []
    current_repository = repo_execution.get("current_repository") or ""
    completed_repository_names = repo_execution.get("completed_repository_names") or []
    analyzed_repositories = [
        repo["name"]
        for repo in repositories
        if repo.get("analysis_status") in {"in_progress", "completed"}
    ]
    if analyzed_repositories:
        required_steps = [
            "request_repository_list",
            "prepare_temp_workspace",
            "clone_repositories",
            "refresh_main_branches",
        ]
        for required_step_id in required_steps:
            required_step = _find_step(progress, required_step_id)
            if not required_step or required_step.get("status") != "completed":
                errors.append(
                    "Repository analysis has started before mandatory setup step "
                    f"{required_step_id} was completed."
                )

    in_scope_names = [repo.get("name") for repo in repositories_in_scope(progress)]
    if ordered_repository_names:
        unknown_names = [
            name for name in ordered_repository_names if name not in in_scope_names
        ]
        if unknown_names:
            errors.append(
                "repository_execution.ordered_repository_names contains repositories "
                "outside in-scope set: " + ", ".join(unknown_names)
            )

    if current_repository and current_repository not in ordered_repository_names:
        errors.append(
            "repository_execution.current_repository must belong to ordered_repository_names."
        )

    for name in completed_repository_names:
        if name not in ordered_repository_names:
            errors.append(
                "repository_execution.completed_repository_names contains unknown repository: "
                f"{name}"
            )

    completed_set = set(completed_repository_names)
    for repo in repositories_in_scope(progress):
        normalize_repository(repo)
        name = repo.get("name")
        status = repo.get("analysis_status")
        if name in completed_set and status != "completed":
            errors.append(
                f"Repository {name} is marked completed in repository_execution but "
                f"analysis_status={status}."
            )

    analyze_step = _find_step(progress, "analyze_repositories")
    analyze_or_later = any(
        step.get("status") == "completed" for step in steps[STEP_INDEX["analyze_repositories"] :]
    ) or (analyze_step is not None and analyze_step.get("status") == "in_progress")
    if analyze_or_later:
        if not ordered_repository_names:
            errors.append(
                "Repository analysis phase requires repository_execution.ordered_repository_names."
            )
        elif ordered_repository_names != in_scope_names:
            errors.append(
                "ordered_repository_names must exactly match the in-scope repositories "
                "in the intended traversal order."
            )

    if analyze_step and analyze_step.get("status") == "completed":
        incomplete = [
            repo.get("name")
            for repo in repositories_in_scope(progress)
            if repo.get("analysis_status") != "completed"
        ]
        if incomplete:
            errors.append(
                "analyze_repositories cannot be completed until every in-scope repository "
                "is completed: " + ", ".join(incomplete)
            )

    for repo in repositories_in_scope(progress):
        checklist = repo.get("analysis_checklist") or {}
        incomplete_items = [
            item_id
            for item_id, _title in REPOSITORY_CHECKLIST_DEFINITIONS
            if checklist.get(item_id, {}).get("status") != "completed"
        ]
        if repo.get("analysis_status") == "completed" and incomplete_items:
            errors.append(
                f"Repository {repo.get('name')} is completed but checklist items remain open: "
                + ", ".join(incomplete_items)
            )

    assess_step = _find_step(progress, "assess_scope_and_domains")
    for repo in repositories_in_scope(progress):
        normalize_repo_domain_map(repo)
        dm = repo.get("domain_map") or {}
        dm_strategy = dm.get("strategy", "per_module")
        dm_domains = dm.get("domains") or []
        dm_exec = dm.get("domain_execution") or {}
        ordered_dids = dm_exec.get("ordered_domain_ids") or []
        completed_dids = set(dm_exec.get("completed_domain_ids") or [])
        current_did = dm_exec.get("current_domain_id") or ""
        registered_dids = {d.get("id") for d in dm_domains}
        repo_name = repo.get("name", "<unknown>")

        if assess_step and assess_step.get("status") == "completed" and not dm.get("assessed_at"):
            errors.append(
                f"Repository {repo_name}: assess_scope_and_domains is completed "
                "but repo domain_map.assessed_at is not set."
            )

        if dm_strategy == "per_domain" and dm.get("assessed_at") and not dm_domains:
            errors.append(
                f"Repository {repo_name}: domain_map.strategy=per_domain "
                "but domain_map.domains is empty."
            )

        unknown_ordered = [did for did in ordered_dids if did not in registered_dids]
        if unknown_ordered:
            errors.append(
                f"Repository {repo_name}: domain_execution.ordered_domain_ids contains "
                "unregistered domains: " + ", ".join(unknown_ordered)
            )

        unknown_completed = [did for did in completed_dids if did not in registered_dids]
        if unknown_completed:
            errors.append(
                f"Repository {repo_name}: domain_execution.completed_domain_ids contains "
                "unregistered domains: " + ", ".join(unknown_completed)
            )

        if current_did and current_did not in registered_dids:
            errors.append(
                f"Repository {repo_name}: domain_execution.current_domain_id "
                f"references unregistered domain: {current_did}"
            )

        if repo.get("analysis_status") == "completed" and dm_strategy == "per_domain":
            incomplete = [
                d.get("id") for d in dm_domains if d.get("analysis_status") != "completed"
            ]
            if incomplete:
                errors.append(
                    f"Repository {repo_name} is completed with strategy=per_domain "
                    "but domains remain incomplete: " + ", ".join(str(x) for x in incomplete)
                )

    sync_step = _find_step(progress, "sync_architecture_artifacts")
    if sync_step and sync_step.get("status") in {"in_progress", "completed"}:
        incomplete = [
            repo.get("name")
            for repo in repositories_in_scope(progress)
            if repo.get("analysis_status") != "completed"
        ]
        if incomplete:
            errors.append(
                "Cannot move to sync_architecture_artifacts before all repositories are analyzed: "
                + ", ".join(incomplete)
            )

    interview_step = _find_step(progress, "interview_user")
    if interview_step and interview_step.get("status") in {"in_progress", "completed"}:
        if root.get("validation", {}).get("intermediate_status") != "completed":
            errors.append(
                "interview_user cannot start before validation.intermediate_status=completed."
            )

    final_validation = root.get("validation", {}).get("final_status")
    if final_validation == "completed":
        missing = [
            artifact_name
            for artifact_name, artifact in (root.get("artifacts") or {}).items()
            if artifact.get("status") == "not_started"
        ]
        if missing:
            errors.append(
                "Final validation is marked completed while some artifacts were not started: "
                + ", ".join(sorted(missing))
            )

    if root.get("status") == "completed":
        finalize_step = _find_step(progress, "finalize_progress")
        if not finalize_step or finalize_step.get("status") != "completed":
            errors.append(
                "analysis_progress.status=completed requires finalize_progress step to be completed."
            )

    for question in root.get("open_questions") or []:
        status = question.get("status")
        if status not in {"open", "resolved", "deferred"}:
            errors.append(
                f"Open question {question.get('id', '<unknown>')} has invalid status: {status}"
            )
        if question.get("ask_user") and not question.get("question"):
            errors.append(
                f"Open question {question.get('id', '<unknown>')} has ask_user=true but empty question."
            )

    return errors
