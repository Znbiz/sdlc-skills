#!/usr/bin/env python3
"""Guard rails for init-repo-arch-skill workflow.

This script turns the skill workflow into an explicit state machine:
- initializes a progress file with the required workflow steps
- prints current progress in a compact form
- validates that the agent is not skipping mandatory stages
- advances the workflow one step at a time
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any


STEP_DEFINITIONS = [
    (
        "define_scope",
        "Определить продукт, контур и границы анализа",
    ),
    (
        "request_repository_list",
        "Запросить у пользователя полный список репозиториев",
    ),
    (
        "prepare_temp_workspace",
        "Подготовить .temp и добавить его в .gitignore",
    ),
    (
        "clone_repositories",
        "Клонировать в .temp все репозитории из пользовательского списка",
    ),
    (
        "refresh_main_branches",
        "Для каждого репозитория зафиксировать main branch и commit SHA",
    ),
    (
        "check_test_repositories",
        "Проверить, не вынесены ли e2e или integration тесты в отдельный репозиторий",
    ),
    (
        "plan_repository_order",
        "Определить порядок обхода репозиториев",
    ),
    (
        "analyze_repositories",
        "Проанализировать репозитории и собрать технические факты",
    ),
    (
        "sync_architecture_artifacts",
        "Синхронизировать landscape, HLD, integrations, contracts, storage и tech-stack",
    ),
    (
        "validate_intermediate",
        "Провести промежуточную валидацию общей картины",
    ),
    (
        "collect_open_questions",
        "Собрать открытые вопросы и пробелы",
    ),
    (
        "interview_user",
        "Задать пользователю только вопросы по пробелам после анализа кода",
    ),
    (
        "refine_features",
        "Уточнить features и связанные артефакты по итогам интервью",
    ),
    (
        "validate_final",
        "Провести финальную валидацию артефактов",
    ),
    (
        "finalize_progress",
        "Зафиксировать итоговый статус анализа, пробелы и следующий шаг",
    ),
]

STEP_INDEX = {step_id: idx for idx, (step_id, _) in enumerate(STEP_DEFINITIONS)}

REPOSITORY_CHECKLIST_DEFINITIONS = [
    ("repository_characterization", "Определить тип и роль репозитория в системе"),
    ("entrypoints_and_interfaces", "Найти точки входа и внешние интерфейсы"),
    ("business_flow_orchestration", "Разобрать orchestration и бизнес-потоки"),
    ("configs_and_runtime", "Собрать конфиги и runtime-зависимости"),
    ("tech_stack_collection", "Собрать технологический стек → зафиксировать ЯП, runtime, framework, ORM, transport, broker clients, observability, security и архитектурно значимые SDK в architecture/tech-stack.md"),
    ("contracts_and_schemas", "Собрать контракты, DTO и схемы → создать contracts/<service>-sync.yml (HTTP/REST/gRPC) и contracts/<service>-async.yml (Kafka/AMQP/gRPC-stream); если нет — явно написать 'нет' в notes"),
    ("data_and_storage", "Разобрать storage, модели, миграции, topics и cache → создать architecture/storage/<service>.yml"),
    (
        "domain_entities",
        "Выделить ключевые бизнес-сущности, видимые пользователю/внешней системе: собрать поля с фронтенда и бэкенда, пометить backend_only поля → обновить architecture/domain-entities.md",
    ),
    ("integrations_and_dependencies", "Собрать интеграции и зависимости → создать architecture/integrations/<service>.md"),
    ("tests_and_behavior_evidence", "Собрать сильные подтверждения из integration/e2e/tests"),
    ("glossary_updates", "Обновить glossary по новым и неоднозначным терминам"),
    (
        "open_questions_review_and_updates",
        "Пересмотреть открытые вопросы и закрыть те, что подтверждаются новым репозиторием",
    ),
    ("feature_discovery_and_updates", "Выделить и обновить текущие features по новой информации"),
    ("features_index_updates", "Обновить корневой реестр фич"),
    ("roles_and_permissions_updates", "Обновить роли и матрицу функционала"),
    (
        "security_and_auth_updates",
        "Зафиксировать модель аутентификации и границы доверия → обновить architecture/security.md: механизмы аутентификации пользователей и сервисов, межсервисное доверие, чувствительные данные и шифрование; если данных нет — явно написать 'не удалось восстановить' в notes",
    ),
    ("deployment_and_operability", "Проверить deploy, observability и operability сигналы"),
    (
        "risks_and_tech_debt_updates",
        "Зафиксировать известные риски и технический долг → обновить architecture/risks.md: хрупкие места, EOL-зависимости, отсутствующие retry/circuit breakers, незащищённые эндпоинты, известные инциденты; если рисков не выявлено — явно написать 'рисков не выявлено' в notes",
    ),
    (
        "architecture_artifact_updates",
        "Обновить landscape, tech-stack, features; проверить наличие storage/<svc>.yml, integrations/<svc>.md, contracts/<svc>-sync.yml, contracts/<svc>-async.yml, обновлённого architecture/security.md и architecture/risks.md (или явную пометку в notes)",
    ),
    (
        "repository_consistency_review",
        "Финальная проверка согласованности артефактов репозитория перед закрытием: entrypoints ↔ contracts, contracts ↔ integrations, storage ↔ HLD, features ↔ entrypoints, domain-entities ↔ contracts+storage; исправить расхождения, зафиксировать итог в notes",
    ),
]

CHECKLIST_INDEX = {item_id: idx for idx, (item_id, _) in enumerate(REPOSITORY_CHECKLIST_DEFINITIONS)}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def default_workflow() -> dict:
    steps = []
    for index, (step_id, title) in enumerate(STEP_DEFINITIONS):
        steps.append(
            {
                "id": step_id,
                "title": title,
                "status": "in_progress" if index == 0 else "not_started",
                "completed_at": None,
                "notes": "",
            }
        )
    return {
        "enforcement_mode": "strict",
        "current_step_id": STEP_DEFINITIONS[0][0],
        "steps": steps,
    }


def default_progress(product: str, scope: str, analyst: str) -> dict:
    timestamp = now_iso()
    return {
        "analysis_progress": {
            "skill_name": "init-repo-arch-skill",
            "status": "in_progress",
            "product": product,
            "analysis_scope": scope,
            "started_at": timestamp,
            "updated_at": timestamp,
            "analyst": analyst,
            "workflow": default_workflow(),
            "current_position": {
                "current_step": STEP_DEFINITIONS[0][0],
                "current_repository": "",
                "last_completed_step": "",
            },
            "repository_execution": {
                "ordered_repository_names": [],
                "current_repository": "",
                "completed_repository_names": [],
            },
            "repositories": [],
            "artifacts": {
                "hld": {"status": "not_started", "path": ""},
                "landscape": {"status": "not_started", "path": ""},
                "integrations": {"status": "not_started", "path": ""},
                "contracts": {"status": "not_started", "path": ""},
                "storage": {"status": "not_started", "path": ""},
                "features": {"status": "not_started", "path": ""},
                "features_index": {"status": "not_started", "path": ""},
                "glossary": {"status": "not_started", "path": ""},
                "open_questions_file": {"status": "not_started", "path": ""},
                "roles_and_permissions": {"status": "not_started", "path": ""},
            },
            "validation": {
                "intermediate_status": "not_started",
                "final_status": "not_started",
                "last_validated_at": "",
                "issues": [],
            },
            "open_questions": [],
            "assumptions": [],
            "next_actions": [],
            "resume_hint": "",
        }
    }


def default_repository_checklist() -> dict:
    return {
        item_id: {
            "status": "not_started",
            "notes": "",
            "title": title,
        }
        for item_id, title in REPOSITORY_CHECKLIST_DEFINITIONS
    }


def load_progress(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        content = file.read().strip()
    try:
        data = json.loads(content) if content else {}
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"{path} is not machine-readable JSON/YAML-compatible content. "
            "Create the progress file via analysis_guard.py init or convert it to JSON."
        ) from exc
    if "analysis_progress" not in data:
        raise SystemExit(f"{path} does not contain top-level key 'analysis_progress'.")
    return data


def save_progress(path: Path, data: dict) -> None:
    data["analysis_progress"]["updated_at"] = now_iso()
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def get_steps(progress: dict) -> list[dict]:
    workflow = progress["analysis_progress"].setdefault("workflow", default_workflow())
    return workflow.setdefault("steps", copy.deepcopy(default_workflow()["steps"]))


def step_by_id(progress: dict, step_id: str) -> dict:
    for step in get_steps(progress):
        if step["id"] == step_id:
            return step
    raise SystemExit(f"Unknown step id in progress file: {step_id}")


def find_repository(progress: dict, repository_name: str) -> dict:
    repositories = progress["analysis_progress"].setdefault("repositories", [])
    for repo in repositories:
        if repo.get("name") == repository_name:
            return repo
    raise SystemExit(f"Repository not found in progress file: {repository_name}")


def normalize_repository(repo: dict) -> None:
    checklist = repo.setdefault("analysis_checklist", {})
    defaults = default_repository_checklist()
    for item_id, item_value in defaults.items():
        checklist.setdefault(item_id, item_value.copy())
        checklist[item_id].setdefault("status", "not_started")
        checklist[item_id].setdefault("notes", "")
        checklist[item_id].setdefault("title", item_value["title"])


def repositories_in_scope(progress: dict) -> list[dict]:
    repositories = progress["analysis_progress"].get("repositories") or []
    return [repo for repo in repositories if repo.get("in_scope") is True]


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

    if current_step_id:
        current_step = step_by_id(progress, current_step_id)
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
            if step_by_id(progress, required_step_id).get("status") != "completed":
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

    analyze_step = step_by_id(progress, "analyze_repositories")
    analyze_or_later = any(
        step.get("status") == "completed" for step in steps[STEP_INDEX["analyze_repositories"] :]
    ) or analyze_step.get("status") == "in_progress"
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

    if analyze_step.get("status") == "completed":
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

    sync_step = step_by_id(progress, "sync_architecture_artifacts")
    if sync_step.get("status") in {"in_progress", "completed"}:
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

    interview_step = step_by_id(progress, "interview_user")
    if interview_step.get("status") in {"in_progress", "completed"}:
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
        finalize_step = step_by_id(progress, "finalize_progress")
        if finalize_step.get("status") != "completed":
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
        marker = {
            "completed": "[x]",
            "in_progress": "[>]",
            "blocked": "[!]",
            "not_started": "[ ]",
        }.get(step["status"], "[?]")
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
            lines.append(
                f"  {marker} {name}: analysis_status={repo.get('analysis_status', '')}"
            )
            open_items = [
                item_id
                for item_id, _title in REPOSITORY_CHECKLIST_DEFINITIONS
                if repo.get("analysis_checklist", {}).get(item_id, {}).get("status") != "completed"
            ]
            if open_items:
                lines.append(f"      open_checklist: {', '.join(open_items)}")
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


def _load_yaml_file(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Return (parsed_data, error_message). Uses yaml if available, falls back to json."""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-untyped]  # noqa: PLC0415
        data: Any = yaml.safe_load(text)
    except ImportError:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return None, f"not valid YAML/JSON: {exc}"
    except Exception as exc:  # noqa: BLE001
        return None, f"YAML parse error: {exc}"
    if not isinstance(data, dict):
        return None, "top-level value is not a mapping"
    return data, None


def _validate_openapi_structure(data: dict[str, Any], path: Path) -> list[str]:
    errors: list[str] = []
    has_openapi3 = "openapi" in data and str(data["openapi"]).startswith("3")
    has_swagger2 = "swagger" in data and str(data["swagger"]).startswith("2")
    if not has_openapi3 and not has_swagger2:
        errors.append(
            f"{path.name}: missing 'openapi' (3.x) or 'swagger' (2.x) version field"
        )
    info = data.get("info")
    if not isinstance(info, dict):
        errors.append(f"{path.name}: 'info' section is missing or not a mapping")
    else:
        for field in ("title", "version"):
            if not info.get(field):
                errors.append(f"{path.name}: info.{field} is missing or empty")
    if "paths" not in data and not errors:
        errors.append(f"{path.name}: 'paths' section is missing (required by OpenAPI)")
    return errors


def _validate_asyncapi_structure(data: dict[str, Any], path: Path) -> list[str]:
    errors: list[str] = []
    version_str = str(data.get("asyncapi", ""))
    if not version_str:
        errors.append(f"{path.name}: missing 'asyncapi' version field")
    info = data.get("info")
    if not isinstance(info, dict):
        errors.append(f"{path.name}: 'info' section is missing or not a mapping")
    else:
        for field in ("title", "version"):
            if not info.get(field):
                errors.append(f"{path.name}: info.{field} is missing or empty")
    major = int(version_str.split(".")[0]) if version_str and version_str[0].isdigit() else 2
    if major >= 3:
        has_channels = "channels" in data or "operations" in data
    else:
        has_channels = "channels" in data
    if not has_channels and not errors:
        errors.append(
            f"{path.name}: 'channels' section is missing (required by AsyncAPI {version_str})"
        )
    return errors


def _try_openapi_spec_validator(path: Path) -> list[str]:
    try:
        from openapi_spec_validator import validate  # noqa: PLC0415
        from openapi_spec_validator.readers import read_from_filename  # noqa: PLC0415
        spec, base_uri = read_from_filename(str(path))
        validate(spec, spec_url=base_uri)
        return []
    except ImportError:
        return []
    except Exception as exc:  # noqa: BLE001
        return [f"{path.name}: openapi-spec-validator: {exc}"]


def _try_asyncapi_cli(path: Path) -> list[str]:
    import subprocess  # noqa: PLC0415
    try:
        result = subprocess.run(
            ["asyncapi", "validate", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            return [f"{path.name}: asyncapi CLI: {detail}"]
        return []
    except FileNotFoundError:
        return []
    except Exception as exc:  # noqa: BLE001
        return [f"{path.name}: asyncapi CLI error: {exc}"]


def validate_contracts_dir(contracts_dir: Path) -> list[str]:
    """Validate all *-sync.yml and *-async.yml files in contracts_dir."""
    if not contracts_dir.exists():
        return [f"contracts directory not found: {contracts_dir}"]

    errors: list[str] = []
    sync_files = sorted(contracts_dir.glob("*-sync.yml"))
    async_files = sorted(contracts_dir.glob("*-async.yml"))

    if not sync_files and not async_files:
        errors.append(
            f"no contract files found in {contracts_dir} "
            "(expected *-sync.yml and/or *-async.yml)"
        )
        return errors

    for file_path in sync_files:
        data, parse_error = _load_yaml_file(file_path)
        if parse_error:
            errors.append(f"{file_path.name}: {parse_error}")
            continue
        assert data is not None
        errors.extend(_validate_openapi_structure(data, file_path))
        errors.extend(_try_openapi_spec_validator(file_path))

    for file_path in async_files:
        data, parse_error = _load_yaml_file(file_path)
        if parse_error:
            errors.append(f"{file_path.name}: {parse_error}")
            continue
        assert data is not None
        errors.extend(_validate_asyncapi_structure(data, file_path))
        errors.extend(_try_asyncapi_cli(file_path))

    return errors


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a new progress file")
    init_parser.add_argument("--output", required=True)
    init_parser.add_argument("--product", required=True)
    init_parser.add_argument("--scope", required=True)
    init_parser.add_argument("--analyst", default="codex")
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(func=init_command)

    validate_parser = subparsers.add_parser(
        "validate", help="Validate workflow integrity and mandatory prerequisites"
    )
    validate_parser.add_argument("--progress", required=True)
    validate_parser.set_defaults(func=validate_command)

    status_parser = subparsers.add_parser("status", help="Print current workflow status")
    status_parser.add_argument("--progress", required=True)
    status_parser.set_defaults(func=status_command)

    repo_parser = subparsers.add_parser(
        "repo",
        help=(
            "Unified repository workflow command: register repo, start repo analysis, "
            "update checklist item, or complete repo"
        ),
    )
    repo_parser.add_argument("--progress", required=True)
    repo_parser.add_argument("--name", required=True)
    repo_parser.add_argument("--notes")
    repo_parser.add_argument("--register", action="store_true")
    repo_parser.add_argument("--start", action="store_true")
    repo_parser.add_argument("--complete", action="store_true")
    repo_parser.add_argument("--checklist-item", choices=sorted(CHECKLIST_INDEX))
    repo_parser.add_argument(
        "--checklist-status",
        choices=["not_started", "in_progress", "completed", "blocked"],
        default="completed",
    )
    repo_parser.add_argument("--role")
    repo_parser.add_argument("--repository-url")
    repo_parser.add_argument("--source-type", default="temp_clone")
    repo_parser.add_argument("--local-path", default="")
    repo_parser.add_argument("--main-branch", default="")
    repo_parser.add_argument("--remote-status", default="не удалось проверить")
    repo_parser.add_argument("--position", choices=["append", "prepend"], default="append")
    repo_parser.add_argument("--in-scope", action="store_true", default=True)
    repo_parser.add_argument("--requested-from-user", action="store_true", default=True)
    repo_parser.add_argument("--allow-dirty", action="store_true")
    repo_parser.set_defaults(func=repo_command)

    register_repo_parser = subparsers.add_parser(
        "register-repo", help="Register repository and append it to enforced traversal order"
    )
    register_repo_parser.add_argument("--progress", required=True)
    register_repo_parser.add_argument("--name", required=True)
    register_repo_parser.add_argument("--role", required=True)
    register_repo_parser.add_argument("--repository-url", required=True)
    register_repo_parser.add_argument("--source-type", default="temp_clone")
    register_repo_parser.add_argument("--local-path", default="")
    register_repo_parser.add_argument("--main-branch", default="")
    register_repo_parser.add_argument("--remote-status", default="не удалось проверить")
    register_repo_parser.add_argument("--notes")
    register_repo_parser.add_argument("--position", choices=["append", "prepend"], default="append")
    register_repo_parser.add_argument("--in-scope", action="store_true", default=True)
    register_repo_parser.add_argument("--requested-from-user", action="store_true", default=True)
    register_repo_parser.set_defaults(func=register_repo_command)

    start_repo_parser = subparsers.add_parser(
        "start-repo", help="Start next repository in the enforced traversal order"
    )
    start_repo_parser.add_argument("--progress", required=True)
    start_repo_parser.add_argument("--name", required=True)
    start_repo_parser.add_argument("--notes")
    start_repo_parser.add_argument("--allow-dirty", action="store_true")
    start_repo_parser.set_defaults(func=start_repo_command)

    complete_repo_parser = subparsers.add_parser(
        "complete-repo", help="Complete current repository after required metadata is filled"
    )
    complete_repo_parser.add_argument("--progress", required=True)
    complete_repo_parser.add_argument("--name", required=True)
    complete_repo_parser.add_argument("--notes")
    complete_repo_parser.set_defaults(func=complete_repo_command)

    checklist_parser = subparsers.add_parser(
        "update-repo-checklist",
        help="Update a detailed repository-analysis checklist item",
    )
    checklist_parser.add_argument("--progress", required=True)
    checklist_parser.add_argument("--name", required=True)
    checklist_parser.add_argument("--item", required=True, choices=sorted(CHECKLIST_INDEX))
    checklist_parser.add_argument(
        "--status",
        required=True,
        choices=["not_started", "in_progress", "completed", "blocked"],
    )
    checklist_parser.add_argument("--notes")
    checklist_parser.set_defaults(func=update_repo_checklist_command)

    advance_parser = subparsers.add_parser(
        "advance", help="Mark current step completed and move to the next step"
    )
    advance_parser.add_argument("--progress", required=True)
    advance_parser.add_argument("--step")
    advance_parser.add_argument("--note")
    advance_parser.add_argument("--repository")
    advance_parser.add_argument("--resume-hint")
    advance_parser.add_argument("--allow-dirty", action="store_true")
    advance_parser.set_defaults(func=advance_command)

    contracts_parser = subparsers.add_parser(
        "validate-contracts",
        help=(
            "Validate OpenAPI (*-sync.yml) and AsyncAPI (*-async.yml) contract files "
            "in a contracts directory"
        ),
    )
    contracts_parser.add_argument(
        "--contracts-dir",
        required=True,
        help="Path to directory containing *-sync.yml and *-async.yml files",
    )
    contracts_parser.set_defaults(func=validate_contracts_command)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
