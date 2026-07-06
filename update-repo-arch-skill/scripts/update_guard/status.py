"""Print current workflow status in compact human-readable form."""

from __future__ import annotations

from .models import find_repository, normalize_repository, repositories_all
from .validation import validate_progress

_STATUS_MARKER = {
    "completed": "[x]",
    "in_progress": "[>]",
    "blocked": "[!]",
    "not_started": "[ ]",
    "skipped_no_changes": "[-]",
}


def print_status(progress: dict) -> None:
    root = progress["update_progress"]
    workflow = root["workflow"]
    repo_execution = root.get("repository_execution") or {}
    current_step = workflow.get("current_step_id", "")
    if root.get("status") == "completed":
        current_step = "<completed>"
    lines = [
        f"arch_repo_path: {root.get('arch_repo_path', '')}",
        f"status: {root.get('status', '')}",
        f"current_step: {current_step}",
        f"current_repository: {repo_execution.get('current_repository', '')}",
        "",
        "workflow:",
    ]
    for step in workflow["steps"]:
        marker = _STATUS_MARKER.get(step["status"], "[?]")
        lines.append(f"  {marker} {step['id']}: {step['title']}")

    ordered_repository_names = repo_execution.get("ordered_repository_names") or []
    if ordered_repository_names:
        lines.extend(["", "repositories:"])
        completed_set = set(repo_execution.get("completed_repository_names") or [])
        for name in ordered_repository_names:
            repo = find_repository(progress, name)
            normalize_repository(repo)
            if name == repo_execution.get("current_repository"):
                marker = "[>]"
            elif name in completed_set:
                marker = _STATUS_MARKER.get(repo.get("repo_status"), "[x]")
            else:
                marker = "[ ]"
            classification = repo.get("diff_classification") or "?"
            lines.append(
                f"  {marker} {name}: repo_status={repo.get('repo_status', '')}"
                f"  diff={classification}"
            )
            open_categories = [
                category.get("category")
                for category in repo.get("signal_categories", [])
                if category.get("status") not in {"completed", "blocked"}
            ]
            if open_categories:
                lines.append(f"      open_categories: {', '.join(open_categories)}")

    cascade_impacts = root.get("cascade_impacts") or []
    if cascade_impacts:
        lines.extend(["", "cascade_impacts:"])
        for impact in cascade_impacts:
            marker = "[x]" if impact.get("status") == "completed" else "[ ]"
            lines.append(
                f"  {marker} {impact.get('source_repo')} -> {impact.get('target')}: "
                f"{impact.get('reason', '')}"
            )

    errors = validate_progress(progress)
    lines.extend(["", f"validation_errors: {len(errors)}"])
    for error in errors:
        lines.append(f"  - {error}")

    print("\n".join(lines))
