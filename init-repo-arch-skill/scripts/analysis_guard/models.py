"""Progress data model: constructors, IO, and accessors."""

from __future__ import annotations

import copy
import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .definitions import (
    REPOSITORY_CHECKLIST_DEFINITIONS,
    STEP_DEFINITIONS,
    STEP_INDEX,
)


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


def default_repo_domain_map() -> dict:
    """Per-repository domain decomposition. Empty until assess_scope_and_domains runs."""
    return {
        "assessed_at": None,
        "strategy": "per_module",
        "volume_class": None,
        "total_files_estimate": 0,
        "domains": [],
        "domain_execution": {
            "ordered_domain_ids": [],
            "current_domain_id": "",
            "completed_domain_ids": [],
        },
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
                "current_domain": "",
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
    if "analysis_progress" not in data:
        raise SystemExit(f"{path} does not contain top-level key 'analysis_progress'.")
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
    data["analysis_progress"]["updated_at"] = now_iso()
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


# ---------------------------------------------------------------------------
# Accessors and normalizers
# ---------------------------------------------------------------------------


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


def normalize_repo_domain_map(repo: dict) -> None:
    dm = repo.setdefault("domain_map", default_repo_domain_map())
    dm.setdefault("assessed_at", None)
    dm.setdefault("strategy", "per_module")
    dm.setdefault("volume_class", None)
    dm.setdefault("total_files_estimate", 0)
    dm.setdefault("domains", [])
    de = dm.setdefault(
        "domain_execution",
        {"ordered_domain_ids": [], "current_domain_id": "", "completed_domain_ids": []},
    )
    de.setdefault("ordered_domain_ids", [])
    de.setdefault("current_domain_id", "")
    de.setdefault("completed_domain_ids", [])


def normalize_repository(repo: dict) -> None:
    checklist = repo.setdefault("analysis_checklist", {})
    defaults = default_repository_checklist()
    for item_id, item_value in defaults.items():
        checklist.setdefault(item_id, item_value.copy())
        checklist[item_id].setdefault("status", "not_started")
        checklist[item_id].setdefault("notes", "")
        checklist[item_id].setdefault("title", item_value["title"])
    normalize_repo_domain_map(repo)


def repositories_in_scope(progress: dict) -> list[dict]:
    repositories = progress["analysis_progress"].get("repositories") or []
    return [repo for repo in repositories if repo.get("in_scope") is True]
