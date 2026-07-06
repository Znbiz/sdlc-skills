"""Cross-check commits recorded in landscape.yaml and architecture/structure/<repo>.yml."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _load_yaml_file(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Return (parsed_data, error_message). Uses yaml if available, falls back to json/ruby."""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-untyped]  # noqa: PLC0415

        data: Any = yaml.safe_load(text)
    except ImportError:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            ruby = shutil.which("ruby")
            if not ruby:
                return None, f"not valid YAML/JSON: {exc}"
            try:
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
                    input=text,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            except Exception as ruby_exc:  # noqa: BLE001
                return None, f"not valid YAML/JSON: {exc}; ruby fallback failed: {ruby_exc}"
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                return None, f"not valid YAML/JSON: {exc}; ruby fallback failed: {detail}"
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError as ruby_json_exc:
                return None, f"ruby fallback returned invalid JSON: {ruby_json_exc}"
    except Exception as exc:  # noqa: BLE001
        return None, f"YAML parse error: {exc}"
    if not isinstance(data, dict):
        return None, "top-level value is not a mapping"
    return data, None


def _is_unfilled(value: str) -> bool:
    """Template placeholders look like '<commit-sha>' and were never filled in."""
    return not value or (value.startswith("<") and value.endswith(">"))


def validate_commit_consistency(arch_repo_path: Path) -> list[str]:
    """Verify that landscape.yaml head_commit matches architecture/structure/<repo>.yml analyzed_commit.

    Both files independently record the commit a service was last analyzed at
    (see checklist-architecture-artifact-updates.md). They drift apart when one
    is updated without the other; this catches that before it reaches the user.
    """
    errors: list[str] = []
    landscape_path = arch_repo_path / "architecture" / "landscape.yaml"
    structure_dir = arch_repo_path / "architecture" / "structure"

    if not landscape_path.exists():
        return [f"{landscape_path}: not found"]

    landscape_data, parse_error = _load_yaml_file(landscape_path)
    if parse_error:
        return [f"{landscape_path.name}: {parse_error}"]
    assert landscape_data is not None

    services = ((landscape_data.get("entities") or {}).get("services")) or []
    if not services:
        return [f"{landscape_path.name}: entities.services is empty"]

    for service in services:
        service_id = service.get("id") or service.get("name")
        if not service_id:
            errors.append(f"{landscape_path.name}: service entry without id/name")
            continue

        head_commit = str(
            (service.get("repository_state") or {}).get("head_commit") or ""
        ).strip()

        structure_path = structure_dir / f"{service_id}.yml"
        if not structure_path.exists():
            errors.append(
                f"{service_id}: architecture/structure/{service_id}.yml not found "
                "(required by repository_structure_mapping)"
            )
            continue

        structure_data, structure_error = _load_yaml_file(structure_path)
        if structure_error:
            errors.append(f"architecture/structure/{structure_path.name}: {structure_error}")
            continue
        assert structure_data is not None

        analyzed_commit = str(
            (structure_data.get("repo_structure_map") or {}).get("analyzed_commit") or ""
        ).strip()

        if _is_unfilled(head_commit):
            errors.append(f"{service_id}: landscape.yaml repository_state.head_commit is not filled in")
            continue
        if _is_unfilled(analyzed_commit):
            errors.append(
                f"{service_id}: architecture/structure/{service_id}.yml analyzed_commit is not filled in"
            )
            continue
        if head_commit != analyzed_commit:
            errors.append(
                f"{service_id}: commit mismatch — landscape.yaml head_commit={head_commit} "
                f"vs architecture/structure/{service_id}.yml analyzed_commit={analyzed_commit}"
            )

    return errors
