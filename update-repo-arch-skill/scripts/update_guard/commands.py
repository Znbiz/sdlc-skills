"""Command implementations for the update_guard CLI."""

from __future__ import annotations

from pathlib import Path

from .commit_consistency import validate_commit_consistency
from .definitions import SIGNAL_CATEGORY_INDEX, STEP_DEFINITIONS, STEP_INDEX
from .models import (
    default_progress,
    default_repository,
    find_category,
    find_cascade_impact,
    find_repository,
    load_progress,
    normalize_repository,
    now_iso,
    save_progress,
    step_by_id,
)
from .status import print_status
from .validation import validate_progress


def _require_clean(progress: dict, allow_dirty: bool) -> None:
    if allow_dirty:
        return
    errors = validate_progress(progress)
    if errors:
        joined = "\n  - ".join(errors)
        raise SystemExit(
            "Progress file has validation errors; fix them or pass --allow-dirty:\n  - "
            + joined
        )


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def init_command(args) -> int:
    path = Path(args.output)
    if path.exists() and not args.force:
        raise SystemExit(f"{path} already exists. Use --force to overwrite.")
    progress = default_progress(args.arch_repo_path, args.analyst)
    save_progress(path, progress)
    print(f"Created {path}")
    return 0


# ---------------------------------------------------------------------------
# validate / status
# ---------------------------------------------------------------------------


def validate_command(args) -> int:
    progress = load_progress(Path(args.progress))
    errors = validate_progress(progress)
    if not errors:
        print("OK: no validation errors")
        return 0
    print(f"FOUND {len(errors)} validation error(s):")
    for error in errors:
        print(f"  - {error}")
    return 1


def status_command(args) -> int:
    progress = load_progress(Path(args.progress))
    print_status(progress)
    return 0


# ---------------------------------------------------------------------------
# repo
# ---------------------------------------------------------------------------


def repo_command(args) -> int:
    path = Path(args.progress)
    progress = load_progress(path)
    root = progress["update_progress"]
    actions = [args.register, args.start, args.set_diff, args.complete]
    if sum(bool(a) for a in actions) != 1:
        raise SystemExit("repo command requires exactly one of: --register, --start, --set-diff, --complete")

    if args.register:
        repositories = root.setdefault("repositories", [])
        if any(repo.get("name") == args.name for repo in repositories):
            raise SystemExit(f"Repository already registered: {args.name}")
        repo = default_repository(args.name)
        repo.update(
            {
                "repository_url": args.repository_url or "",
                "local_path": args.local_path or "",
                "main_branch": args.main_branch or "",
                "previous_baseline_commit": args.previous_baseline_commit or "",
            }
        )
        if args.position == "prepend":
            repositories.insert(0, repo)
        else:
            repositories.append(repo)
        ordered = root.setdefault("repository_execution", {}).setdefault(
            "ordered_repository_names", []
        )
        if args.position == "prepend":
            ordered.insert(0, args.name)
        else:
            ordered.append(args.name)
        save_progress(path, progress)
        print(f"Registered repository: {args.name}")
        return 0

    repo = find_repository(progress, args.name)
    normalize_repository(repo)

    if args.start:
        current_step_id = root["workflow"]["current_step_id"]
        if current_step_id not in {"triage_repositories", "targeted_deep_analysis"}:
            raise SystemExit(
                "repo --start is only allowed during triage_repositories or "
                f"targeted_deep_analysis (current step: {current_step_id})"
            )
        repo["repo_status"] = "in_progress"
        root["repository_execution"]["current_repository"] = args.name
        if args.notes:
            repo["notes"] = args.notes
        save_progress(path, progress)
        print(f"Started repository: {args.name}")
        return 0

    if args.set_diff:
        if not args.classification:
            raise SystemExit("--set-diff requires --classification")
        if args.new_baseline_commit:
            repo["new_baseline_commit"] = args.new_baseline_commit
        repo["diff_classification"] = args.classification
        if args.stat_summary:
            repo["diff_stat_summary"] = args.stat_summary
        if args.commit_log_summary:
            repo["commit_log_summary"] = args.commit_log_summary
        if args.baseline_invalid:
            repo["baseline_valid"] = False
        if args.classification == "none":
            repo["repo_status"] = "skipped_no_changes"
            ordered = root["repository_execution"]
            if args.name not in ordered.get("completed_repository_names", []):
                ordered.setdefault("completed_repository_names", []).append(args.name)
        if args.notes:
            repo["notes"] = args.notes
        save_progress(path, progress)
        print(f"Set diff classification for {args.name}: {args.classification}")
        return 0

    if args.complete:
        open_categories = [
            category.get("category")
            for category in repo.get("signal_categories", [])
            if category.get("status") not in {"completed", "blocked"}
        ]
        if open_categories:
            raise SystemExit(
                f"Cannot complete repository {args.name}: open signal_categories "
                + ", ".join(open_categories)
            )
        repo["repo_status"] = "completed"
        if args.notes:
            repo["notes"] = args.notes
        completed = root["repository_execution"].setdefault("completed_repository_names", [])
        if args.name not in completed:
            completed.append(args.name)
        if root["repository_execution"].get("current_repository") == args.name:
            root["repository_execution"]["current_repository"] = ""
        save_progress(path, progress)
        print(f"Completed repository: {args.name}")
        return 0

    return 1


# ---------------------------------------------------------------------------
# signal
# ---------------------------------------------------------------------------


def signal_command(args) -> int:
    path = Path(args.progress)
    progress = load_progress(path)
    repo = find_repository(progress, args.repo)
    normalize_repository(repo)

    if args.add_category:
        if args.category not in SIGNAL_CATEGORY_INDEX:
            raise SystemExit(f"Unknown category: {args.category}")
        if find_category(repo, args.category):
            raise SystemExit(f"Category already registered for {args.repo}: {args.category}")
        source_paths = [p.strip() for p in (args.source_paths or "").split(",") if p.strip()]
        repo.setdefault("signal_categories", []).append(
            {
                "category": args.category,
                "status": "not_started",
                "source_paths": source_paths,
                "notes": args.notes or "",
            }
        )
        save_progress(path, progress)
        print(f"Added category {args.category} to {args.repo}")
        return 0

    category = find_category(repo, args.category) if args.category else None
    if category is None:
        raise SystemExit(f"Category not registered for {args.repo}: {args.category}")
    category["status"] = args.status
    if args.notes:
        category["notes"] = args.notes
    save_progress(path, progress)
    print(f"Updated category {args.category} for {args.repo}: {args.status}")
    return 0


# ---------------------------------------------------------------------------
# cascade
# ---------------------------------------------------------------------------


def cascade_command(args) -> int:
    path = Path(args.progress)
    progress = load_progress(path)
    root = progress["update_progress"]

    if args.register:
        if find_cascade_impact(progress, args.source_repo, args.target):
            raise SystemExit(
                f"Cascade impact already registered: {args.source_repo} -> {args.target}"
            )
        root.setdefault("cascade_impacts", []).append(
            {
                "source_repo": args.source_repo,
                "target": args.target,
                "reason": args.reason or "",
                "status": "not_started",
                "notes": "",
            }
        )
        save_progress(path, progress)
        print(f"Registered cascade impact: {args.source_repo} -> {args.target}")
        return 0

    impact = find_cascade_impact(progress, args.source_repo, args.target)
    if impact is None:
        raise SystemExit(f"Cascade impact not found: {args.source_repo} -> {args.target}")
    impact["status"] = "completed"
    if args.notes:
        impact["notes"] = args.notes
    save_progress(path, progress)
    print(f"Completed cascade impact: {args.source_repo} -> {args.target}")
    return 0


# ---------------------------------------------------------------------------
# advance
# ---------------------------------------------------------------------------


def advance_command(args) -> int:
    path = Path(args.progress)
    progress = load_progress(path)
    root = progress["update_progress"]
    workflow = root["workflow"]
    current_step_id = workflow["current_step_id"]

    if args.step and args.step != current_step_id:
        raise SystemExit(
            f"--step={args.step} does not match current_step_id={current_step_id}"
        )

    current_step = step_by_id(progress, current_step_id)
    current_step["status"] = "completed"
    current_step["completed_at"] = now_iso()
    if args.note:
        current_step["notes"] = args.note

    current_index = STEP_INDEX[current_step_id]
    if current_index + 1 < len(STEP_DEFINITIONS):
        next_step_id = STEP_DEFINITIONS[current_index + 1][0]
        workflow["current_step_id"] = next_step_id
        step_by_id(progress, next_step_id)["status"] = "in_progress"
        root["current_position"]["current_step"] = next_step_id
    else:
        root["status"] = "completed"
    root["current_position"]["last_completed_step"] = current_step_id

    if args.repository is not None:
        root["repository_execution"]["current_repository"] = args.repository
    if args.resume_hint is not None:
        root["resume_hint"] = args.resume_hint

    _require_clean(progress, args.allow_dirty)
    save_progress(path, progress)
    print(f"Advanced past {current_step_id}. New current step: {workflow['current_step_id']}")
    return 0


# ---------------------------------------------------------------------------
# validate-commits
# ---------------------------------------------------------------------------


def validate_commits_command(args) -> int:
    arch_repo_path = Path(args.arch_repo_path)
    errors = validate_commit_consistency(arch_repo_path)

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("OK: landscape.yaml head_commit matches architecture/structure/<repo>.yml analyzed_commit for all services.")
    return 0
