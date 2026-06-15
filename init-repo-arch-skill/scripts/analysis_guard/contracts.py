"""Validation of OpenAPI and AsyncAPI contract files."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


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
