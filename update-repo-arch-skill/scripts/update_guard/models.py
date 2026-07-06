"""Progress data model: constructors, IO, and accessors."""

from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .definitions import STEP_DEFINITIONS


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Default constructors
# ---------------------------------------------------------------------------


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


def default_progress(arch_repo_path: str, analyst: str) -> dict:
    timestamp = now_iso()
    return {
        "update_progress": {
            "skill_name": "update-repo-arch-skill",
            "status": "in_progress",
            "arch_repo_path": arch_repo_path,
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
            "cascade_impacts": [],
            "validation": {
                "consistency_status": "not_started",
                "last_validated_at": "",
                "issues": [],
            },
            "update_run_summary": {
                "repos_with_no_changes": [],
                "repos_updated": [],
                "artifacts_touched": [],
                "new_gaps": [],
                "invalid_baseline_repos": [],
            },
            "next_actions": [],
            "resume_hint": "",
        }
    }


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------


def load_progress(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        content = file.read().strip()
    try:
        data = json.loads(content) if content else {}
    except json.JSONDecodeError:
        data = _load_yaml_compatible_content(path, content)
    if "update_progress" not in data:
        raise SystemExit(f"{path} does not contain top-level key 'update_progress'.")
    return data


def _load_yaml_compatible_content(path: Path, content: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-untyped]  # noqa: PLC0415

        data: Any = yaml.safe_load(content)
    except ImportError:
        ruby = shutil.which("ruby")
        if not ruby:
            raise SystemExit(
                f"{path} is not valid JSON, and PyYAML/Ruby are unavailable for YAML parsing."
            ) from None
        result = subprocess.run(
            [
                ruby,
                "-e",
                (
                    "require 'yaml'; require 'json'; require 'date'; "
                    "print JSON.generate("
                    "YAML.safe_load(ARGF.read, permitted_classes: [Time, Date], aliases: true)"
                    ")"
                ),
            ],
            input=content,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise SystemExit(f"{path} is not valid JSON/YAML content: {detail}") from None
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"{path} YAML fallback returned invalid JSON: {exc}"
            ) from exc
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"{path} is not valid JSON/YAML content: {exc}") from exc

    if not isinstance(data, dict):
        raise SystemExit(f"{path} must contain a top-level mapping/object.")
    return data


def save_progress(path: Path, data: dict) -> None:
    data["update_progress"]["updated_at"] = now_iso()
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


# ---------------------------------------------------------------------------
# Accessors and normalizers
# ---------------------------------------------------------------------------


def get_steps(progress: dict) -> list[dict]:
    workflow = progress["update_progress"].setdefault("workflow", default_workflow())
    return workflow.setdefault("steps", default_workflow()["steps"])


def step_by_id(progress: dict, step_id: str) -> dict:
    for step in get_steps(progress):
        if step["id"] == step_id:
            return step
    raise SystemExit(f"Unknown step id in progress file: {step_id}")


def find_repository(progress: dict, repository_name: str) -> dict:
    repositories = progress["update_progress"].setdefault("repositories", [])
    for repo in repositories:
        if repo.get("name") == repository_name:
            return repo
    raise SystemExit(f"Repository not found in progress file: {repository_name}")


def default_repository(name: str) -> dict:
    return {
        "name": name,
        "repository_url": "",
        "local_path": "",
        "main_branch": "",
        "previous_baseline_commit": "",
        "new_baseline_commit": "",
        "baseline_valid": True,
        "diff_classification": "",
        "diff_stat_summary": "",
        "commit_log_summary": "",
        "repo_status": "not_started",
        "signal_categories": [],
        "notes": "",
    }


def normalize_repository(repo: dict) -> None:
    defaults = default_repository(repo.get("name", ""))
    for key, value in defaults.items():
        repo.setdefault(key, value)
    for category in repo.get("signal_categories", []):
        category.setdefault("status", "not_started")
        category.setdefault("source_paths", [])
        category.setdefault("notes", "")


def find_category(repo: dict, category_id: str) -> dict | None:
    for category in repo.get("signal_categories", []):
        if category.get("category") == category_id:
            return category
    return None


def repositories_all(progress: dict) -> list[dict]:
    return progress["update_progress"].get("repositories") or []


def find_cascade_impact(progress: dict, source_repo: str, target: str) -> dict | None:
    for impact in progress["update_progress"].get("cascade_impacts") or []:
        if impact.get("source_repo") == source_repo and impact.get("target") == target:
            return impact
    return None
