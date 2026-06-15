"""Print current workflow status in compact human-readable form."""

from __future__ import annotations

from .definitions import REPOSITORY_CHECKLIST_DEFINITIONS
from .models import find_repository, normalize_repository
from .validation import validate_progress

_STATUS_MARKER = {
    "completed": "[x]",
    "in_progress": "[>]",
    "blocked": "[!]",
    "not_started": "[ ]",
}


def print_status(progress: dict) -> None:
    root = progress["analysis_progress"]
    workflow = root["workflow"]
    repo_execution = root.get("repository_execution") or {}
    pending_user_questions = [
        question
        for question in (root.get("open_questions") or [])
        if question.get("status") == "open" and question.get("ask_user") is True
    ]
    lines = [
        f"product: {root.get('product', '')}",
        f"status: {root.get('status', '')}",
        f"current_step: {workflow.get('current_step_id', '')}",
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
                marker = "[x]"
            else:
                marker = "[ ]"
            dm = repo.get("domain_map") or {}
            dm_strategy = dm.get("strategy", "per_module")
            volume_tag = (
                f"  vol:{dm.get('volume_class', '?')}" if dm.get("assessed_at") else ""
            )
            lines.append(
                f"  {marker} {name}: analysis_status={repo.get('analysis_status', '')}"
                f"  strategy={dm_strategy}{volume_tag}"
            )
            open_items = [
                item_id
                for item_id, _title in REPOSITORY_CHECKLIST_DEFINITIONS
                if repo.get("analysis_checklist", {}).get(item_id, {}).get("status") != "completed"
            ]
            if open_items:
                lines.append(f"      open_checklist: {', '.join(open_items)}")
            if dm.get("assessed_at") and dm_strategy == "per_domain":
                dm_exec = dm.get("domain_execution") or {}
                completed_dids = set(dm_exec.get("completed_domain_ids") or [])
                current_did = dm_exec.get("current_domain_id") or ""
                for d in (dm.get("domains") or []):
                    did = d.get("id", "")
                    if did == current_did:
                        dmarker = "[>]"
                    elif did in completed_dids:
                        dmarker = "[x]"
                    else:
                        dmarker = "[ ]"
                    lines.append(
                        f"      {dmarker} domain/{did}: {d.get('name', '')} "
                        f"[{d.get('analysis_status', '')}]"
                    )
                    for sd in d.get("subdomains") or []:
                        lines.append(
                            f"          subdomain/{sd.get('id', '')}: {sd.get('name', '')}"
                        )

    if pending_user_questions:
        lines.extend(["", "questions_for_user:"])
        for question in pending_user_questions:
            repo_part = f" [{question.get('repository')}]" if question.get("repository") else ""
            blocking_level = question.get("blocking_level", "important")
            asked_marker = "asked" if question.get("asked_to_user") else "not_asked"
            lines.append(
                f"  - ({blocking_level}, {asked_marker}) {question.get('id', '<no-id>')}{repo_part}: "
                f"{question.get('question', '')}"
            )

    errors = validate_progress(progress)
    lines.extend(["", f"validation_errors: {len(errors)}"])
    for error in errors:
        lines.append(f"  - {error}")

    print("\n".join(lines))
