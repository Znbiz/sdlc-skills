"""CLI command implementations."""

from __future__ import annotations

import argparse
from pathlib import Path

from .contracts import validate_contracts_dir
from .definitions import (
    CHECKLIST_INDEX,
    REPOSITORY_CHECKLIST_DEFINITIONS,
    STEP_INDEX,
)
from .models import (
    default_repo_domain_map,
    default_repository_checklist,
    default_progress,
    find_repository,
    load_progress,
    normalize_repo_domain_map,
    normalize_repository,
    now_iso,
    repositories_in_scope,
    save_progress,
)
from .status import print_status
from .validation import validate_progress


def init_command(args: argparse.Namespace) -> int:
    path = Path(args.output)
    if path.exists() and not args.force:
        raise SystemExit(f"{path} already exists. Use --force to overwrite it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = default_progress(args.product, args.scope, args.analyst)
    save_progress(path, data)
    print(f"Initialized progress file: {path}")
    return 0


def validate_command(args: argparse.Namespace) -> int:
    progress = load_progress(Path(args.progress))
    errors = validate_progress(progress)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("OK: progress file is consistent with enforced workflow.")
    return 0


def status_command(args: argparse.Namespace) -> int:
    progress = load_progress(Path(args.progress))
    print_status(progress)
    return 0


def advance_command(args: argparse.Namespace) -> int:
    path = Path(args.progress)
    progress = load_progress(path)
    errors = validate_progress(progress)
    if errors and not args.allow_dirty:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    root = progress["analysis_progress"]
    workflow = root["workflow"]
    steps = workflow["steps"]
    repo_execution = root.setdefault(
        "repository_execution",
        {
            "ordered_repository_names": [],
            "current_repository": "",
            "completed_repository_names": [],
        },
    )

    current_id = workflow["current_step_id"]
    current_idx = STEP_INDEX[current_id]

    if args.step and args.step != current_id:
        raise SystemExit(
            f"Current step is {current_id}. To advance it, omit --step or pass --step {current_id}."
        )

    if current_id == "analyze_repositories":
        incomplete = [
            repo.get("name")
            for repo in repositories_in_scope(progress)
            if repo.get("analysis_status") != "completed"
        ]
        if incomplete:
            raise SystemExit(
                "Cannot complete analyze_repositories while in-scope repositories remain "
                "unfinished: " + ", ".join(incomplete)
            )
        if repo_execution.get("current_repository"):
            raise SystemExit(
                "Cannot complete analyze_repositories while current_repository is still set."
            )
    if current_id == "assess_scope_and_domains":
        unassessed = [
            repo.get("name")
            for repo in repositories_in_scope(progress)
            if not repo.get("domain_map", {}).get("assessed_at")
        ]
        if unassessed:
            raise SystemExit(
                "Cannot complete assess_scope_and_domains while repositories remain unassessed: "
                + ", ".join(unassessed)
            )

    steps[current_idx]["status"] = "completed"
    steps[current_idx]["completed_at"] = now_iso()
    if args.note:
        steps[current_idx]["notes"] = args.note
    root["current_position"]["last_completed_step"] = current_id

    if current_idx + 1 < len(steps):
        next_id = steps[current_idx + 1]["id"]
        steps[current_idx + 1]["status"] = "in_progress"
        workflow["current_step_id"] = next_id
        root["current_position"]["current_step"] = next_id
    else:
        workflow["current_step_id"] = current_id
        root["current_position"]["current_step"] = current_id
        root["status"] = "completed"

    if args.repository is not None:
        root["current_position"]["current_repository"] = args.repository
    if args.resume_hint:
        root["resume_hint"] = args.resume_hint

    save_progress(path, progress)
    print(
        f"Completed step {current_id}. "
        f"Current step: {root['current_position']['current_step']}"
    )
    return 0


def register_repo_command(args: argparse.Namespace) -> int:
    path = Path(args.progress)
    progress = load_progress(path)
    root = progress["analysis_progress"]
    repositories = root.setdefault("repositories", [])
    repo_execution = root.setdefault(
        "repository_execution",
        {
            "ordered_repository_names": [],
            "current_repository": "",
            "completed_repository_names": [],
        },
    )

    if any(repo.get("name") == args.name for repo in repositories):
        raise SystemExit(f"Repository already registered: {args.name}")

    repositories.append(
        {
            "name": args.name,
            "role": args.role,
            "repository_url": args.repository_url,
            "in_scope": args.in_scope,
            "requested_from_user": args.requested_from_user,
            "source_type": args.source_type,
            "local_path": args.local_path,
            "main_branch": args.main_branch,
            "analyzed_commit": "",
            "remote_head_commit": "",
            "remote_status": args.remote_status,
            "analysis_status": "not_started",
            "notes": args.notes or "",
            "domain_map": default_repo_domain_map(),
            "analysis_checklist": default_repository_checklist(),
        }
    )
    if args.position == "append":
        repo_execution.setdefault("ordered_repository_names", []).append(args.name)
    else:
        repo_execution.setdefault("ordered_repository_names", []).insert(0, args.name)

    save_progress(path, progress)
    print(f"Registered repository: {args.name}")
    return 0


def start_repo_command(args: argparse.Namespace) -> int:
    path = Path(args.progress)
    progress = load_progress(path)
    errors = validate_progress(progress)
    if errors and not args.allow_dirty:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    root = progress["analysis_progress"]
    workflow = root["workflow"]
    if workflow.get("current_step_id") != "analyze_repositories":
        raise SystemExit("start-repo is allowed only during analyze_repositories step.")

    repo_execution = root["repository_execution"]
    ordered_names = repo_execution.get("ordered_repository_names") or []
    if args.name not in ordered_names:
        raise SystemExit(
            f"Repository {args.name} is not present in repository_execution.ordered_repository_names."
        )

    current_name = repo_execution.get("current_repository") or ""
    if current_name and current_name != args.name:
        raise SystemExit(
            f"Repository {current_name} is already in progress. Complete it before starting another."
        )

    repo = find_repository(progress, args.name)
    normalize_repository(repo)
    if repo.get("in_scope") is not True:
        raise SystemExit(f"Repository {args.name} is not marked in_scope=true.")
    if repo.get("analysis_status") == "completed":
        raise SystemExit(f"Repository {args.name} is already completed.")

    completed_names = set(repo_execution.get("completed_repository_names") or [])
    expected_name = next((name for name in ordered_names if name not in completed_names), None)
    if expected_name != args.name:
        raise SystemExit(
            f"Repository traversal order violation: expected {expected_name}, got {args.name}."
        )

    repo["analysis_status"] = "in_progress"
    if args.notes:
        repo["notes"] = args.notes
    repo_execution["current_repository"] = args.name
    root["current_position"]["current_repository"] = args.name
    root["resume_hint"] = f"Continue repository analysis from {args.name}"

    save_progress(path, progress)
    print(f"Started repository: {args.name}")
    return 0


def complete_repo_command(args: argparse.Namespace) -> int:
    path = Path(args.progress)
    progress = load_progress(path)
    root = progress["analysis_progress"]
    workflow = root["workflow"]
    if workflow.get("current_step_id") != "analyze_repositories":
        raise SystemExit("complete-repo is allowed only during analyze_repositories step.")

    repo_execution = root["repository_execution"]
    current_name = repo_execution.get("current_repository") or ""
    if current_name != args.name:
        raise SystemExit(
            f"Current repository is {current_name or '<empty>'}, cannot complete {args.name}."
        )

    repo = find_repository(progress, args.name)
    normalize_repository(repo)
    missing = []
    if not repo.get("main_branch"):
        missing.append("main_branch")
    if not repo.get("analyzed_commit"):
        missing.append("analyzed_commit")
    if not repo.get("remote_head_commit"):
        missing.append("remote_head_commit")
    if missing:
        raise SystemExit(
            f"Repository {args.name} cannot be completed without fields: {', '.join(missing)}"
        )
    open_checklist = [
        item_id
        for item_id, _title in REPOSITORY_CHECKLIST_DEFINITIONS
        if repo.get("analysis_checklist", {}).get(item_id, {}).get("status") != "completed"
    ]
    if open_checklist:
        raise SystemExit(
            f"Repository {args.name} cannot be completed while checklist items remain open: "
            + ", ".join(open_checklist)
        )

    dm = repo.get("domain_map") or {}
    if dm.get("strategy") == "per_domain":
        incomplete_domains = [
            d.get("id")
            for d in (dm.get("domains") or [])
            if d.get("analysis_status") != "completed"
        ]
        if incomplete_domains:
            raise SystemExit(
                f"Repository {args.name} cannot be completed with strategy=per_domain "
                "while domains remain incomplete: "
                + ", ".join(str(x) for x in incomplete_domains)
            )

    repo["analysis_status"] = "completed"
    if args.notes:
        repo["notes"] = args.notes
    completed = repo_execution.setdefault("completed_repository_names", [])
    if args.name not in completed:
        completed.append(args.name)
    repo_execution["current_repository"] = ""
    root["current_position"]["current_repository"] = ""

    remaining = [
        name
        for name in repo_execution.get("ordered_repository_names") or []
        if name not in set(completed)
    ]
    root["resume_hint"] = (
        f"Next repository: {remaining[0]}" if remaining else "All repositories analyzed"
    )

    save_progress(path, progress)
    print(f"Completed repository: {args.name}")
    return 0


def update_repo_checklist_command(args: argparse.Namespace) -> int:
    path = Path(args.progress)
    progress = load_progress(path)
    repo = find_repository(progress, args.name)
    normalize_repository(repo)
    if args.item not in CHECKLIST_INDEX:
        raise SystemExit(f"Unknown checklist item: {args.item}")
    item = repo["analysis_checklist"][args.item]
    item["status"] = args.status
    if args.notes is not None:
        item["notes"] = args.notes
    if repo.get("analysis_status") == "not_started":
        repo["analysis_status"] = "in_progress"
    save_progress(path, progress)
    print(f"Updated checklist item {args.item} for repository: {args.name}")
    return 0


def repo_command(args: argparse.Namespace) -> int:
    action_count = sum(
        [
            bool(args.register),
            bool(args.start),
            bool(args.complete),
            bool(args.checklist_item),
        ]
    )
    if action_count != 1:
        raise SystemExit(
            "repo command requires exactly one action: "
            "--register, --start, --checklist-item, or --complete."
        )

    if args.register:
        if not args.role:
            raise SystemExit("repo --register requires --role.")
        if not args.repository_url:
            raise SystemExit("repo --register requires --repository-url.")
        register_args = argparse.Namespace(
            progress=args.progress,
            name=args.name,
            role=args.role,
            repository_url=args.repository_url,
            source_type=args.source_type,
            local_path=args.local_path,
            main_branch=args.main_branch,
            remote_status=args.remote_status,
            notes=args.notes,
            position=args.position,
            in_scope=args.in_scope,
            requested_from_user=args.requested_from_user,
        )
        return register_repo_command(register_args)

    if args.start:
        start_args = argparse.Namespace(
            progress=args.progress,
            name=args.name,
            notes=args.notes,
            allow_dirty=args.allow_dirty,
        )
        return start_repo_command(start_args)

    if args.complete:
        complete_args = argparse.Namespace(
            progress=args.progress,
            name=args.name,
            notes=args.notes,
        )
        return complete_repo_command(complete_args)

    if not args.checklist_status:
        raise SystemExit("repo --checklist-item requires --checklist-status.")
    checklist_args = argparse.Namespace(
        progress=args.progress,
        name=args.name,
        item=args.checklist_item,
        status=args.checklist_status,
        notes=args.notes,
    )
    return update_repo_checklist_command(checklist_args)


def domain_command(args: argparse.Namespace) -> int:
    action_count = sum(
        [
            bool(args.assess),
            bool(args.register),
            bool(args.add_subdomain),
            bool(args.start),
            bool(args.complete),
        ]
    )
    if action_count != 1:
        raise SystemExit(
            "domain command requires exactly one action: "
            "--assess, --register, --add-subdomain, --start, or --complete."
        )
    if not args.repo:
        raise SystemExit("domain command requires --repo <repository-name>.")

    path = Path(args.progress)
    progress = load_progress(path)
    root = progress["analysis_progress"]
    repo = find_repository(progress, args.repo)
    normalize_repo_domain_map(repo)
    domain_map: dict = repo["domain_map"]
    domains: list[dict] = domain_map["domains"]
    domain_exec: dict = domain_map["domain_execution"]

    if args.assess:
        domain_map["assessed_at"] = now_iso()
        domain_map["strategy"] = args.strategy
        if args.volume_class:
            domain_map["volume_class"] = args.volume_class
        if args.total_files is not None:
            domain_map["total_files_estimate"] = args.total_files
        save_progress(path, progress)
        print(
            f"[{args.repo}] Volume assessment recorded: strategy={args.strategy}, "
            f"volume_class={args.volume_class}, total_files={args.total_files}"
        )
        return 0

    if args.register:
        if not args.domain_id:
            raise SystemExit("domain --register requires --domain-id.")
        if not args.name:
            raise SystemExit("domain --register requires --name.")
        if any(d.get("id") == args.domain_id for d in domains):
            raise SystemExit(f"[{args.repo}] Domain already registered: {args.domain_id}")
        path_list = [p.strip() for p in args.paths.split(",")] if args.paths else []
        signal_list = [args.signal] if args.signal else []
        domains.append(
            {
                "id": args.domain_id,
                "name": args.name,
                "description": args.description or "",
                "subdomains": [],
                "paths": path_list,
                "source_signals": signal_list,
                "analysis_status": "not_started",
                "analysis_notes": "",
            }
        )
        ordered = domain_exec.setdefault("ordered_domain_ids", [])
        if args.domain_id not in ordered:
            ordered.append(args.domain_id)
        save_progress(path, progress)
        print(f"[{args.repo}] Registered domain: {args.domain_id} ({args.name})")
        return 0

    if args.add_subdomain:
        if not args.domain_id:
            raise SystemExit("domain --add-subdomain requires --domain-id.")
        if not args.subdomain_id:
            raise SystemExit("domain --add-subdomain requires --subdomain-id.")
        if not args.subdomain_name:
            raise SystemExit("domain --add-subdomain requires --subdomain-name.")
        domain = next((d for d in domains if d.get("id") == args.domain_id), None)
        if not domain:
            raise SystemExit(f"[{args.repo}] Domain not found: {args.domain_id}")
        subdomains: list[dict] = domain.setdefault("subdomains", [])
        if any(sd.get("id") == args.subdomain_id for sd in subdomains):
            raise SystemExit(
                f"[{args.repo}] Subdomain {args.subdomain_id} already exists "
                f"in domain {args.domain_id}"
            )
        subdomains.append({"id": args.subdomain_id, "name": args.subdomain_name})
        save_progress(path, progress)
        print(f"[{args.repo}] Added subdomain {args.subdomain_id} to domain {args.domain_id}")
        return 0

    if args.start:
        if not args.domain_id:
            raise SystemExit("domain --start requires --domain-id.")
        domain = next((d for d in domains if d.get("id") == args.domain_id), None)
        if not domain:
            raise SystemExit(f"[{args.repo}] Domain not found: {args.domain_id}")
        current = domain_exec.get("current_domain_id") or ""
        if current and current != args.domain_id:
            raise SystemExit(
                f"[{args.repo}] Domain {current} is already in progress. "
                "Complete it before starting another."
            )
        ordered = domain_exec.get("ordered_domain_ids") or []
        completed = set(domain_exec.get("completed_domain_ids") or [])
        expected = next((did for did in ordered if did not in completed), None)
        if expected != args.domain_id:
            raise SystemExit(
                f"[{args.repo}] Domain traversal order violation: "
                f"expected {expected}, got {args.domain_id}."
            )
        domain["analysis_status"] = "in_progress"
        domain_exec["current_domain_id"] = args.domain_id
        root.setdefault("current_position", {})["current_domain"] = args.domain_id
        save_progress(path, progress)
        print(f"[{args.repo}] Started domain analysis: {args.domain_id}")
        return 0

    # --complete
    if not args.domain_id:
        raise SystemExit("domain --complete requires --domain-id.")
    domain = next((d for d in domains if d.get("id") == args.domain_id), None)
    if not domain:
        raise SystemExit(f"[{args.repo}] Domain not found: {args.domain_id}")
    if domain_exec.get("current_domain_id") != args.domain_id:
        raise SystemExit(
            f"[{args.repo}] Domain {args.domain_id} is not the current domain in progress."
        )
    domain["analysis_status"] = "completed"
    if args.notes:
        domain["analysis_notes"] = args.notes
    domain_exec["current_domain_id"] = ""
    completed_list: list = domain_exec.setdefault("completed_domain_ids", [])
    if args.domain_id not in completed_list:
        completed_list.append(args.domain_id)
    root.setdefault("current_position", {})["current_domain"] = ""
    ordered = domain_exec.get("ordered_domain_ids") or []
    remaining = [did for did in ordered if did not in set(completed_list)]
    root["resume_hint"] = (
        f"[{args.repo}] Next domain: {remaining[0]}"
        if remaining
        else f"[{args.repo}] All domains analyzed"
    )
    save_progress(path, progress)
    print(f"[{args.repo}] Completed domain analysis: {args.domain_id}")
    return 0


def validate_contracts_command(args: argparse.Namespace) -> int:
    contracts_dir = Path(args.contracts_dir)
    errors = validate_contracts_dir(contracts_dir)

    sync_count = len(list(contracts_dir.glob("*-sync.yml"))) if contracts_dir.exists() else 0
    async_count = len(list(contracts_dir.glob("*-async.yml"))) if contracts_dir.exists() else 0
    print(f"Contracts directory: {contracts_dir}")
    print(f"Files found: {sync_count} sync (OpenAPI), {async_count} async (AsyncAPI)")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"OK: all {sync_count + async_count} contract file(s) are valid.")
    return 0
