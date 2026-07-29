from __future__ import annotations

import json
import pathlib
import typing
import uuid  # noqa: TC003 - used at runtime as a parameter annotation, not just for type checking

_CATALOG_DIR: typing.Final = pathlib.Path("~/.config/llm-provider-catalogs").expanduser()

# Codex CLI (>=0.144) ships built-in metadata only for OpenAI's own models. Any other model
# (e.g. a self-hosted/third-party model behind an OpenAI-compatible gateway) falls back to
# generic metadata, which sends a `local_shell`-native shell tool and other OpenAI-only tool
# types the gateway can reject outright (whole request 400s before any tool is even called).
# `-c model_catalog_json=<path>` (task_runner._external_provider_overrides) points Codex at a
# catalog entry that forces the plain function-calling-compatible tool variants instead.
# Every field below is required by Codex's catalog parser (found by iterating
# "missing field `x`" errors against a running codex binary) - there is no partial/merge mode.
_APPLY_PATCH_TOOL_TYPE: typing.Final[str] = "freeform"
_SHELL_TYPE: typing.Final[str] = "shell_command"


def _catalog_file(connection_id: uuid.UUID) -> pathlib.Path:
    return _CATALOG_DIR / f"{connection_id}.catalog.json"


def _build_catalog(model: str) -> dict[str, typing.Any]:
    return {
        "models": [
            {
                "slug": model,
                "display_name": model,
                "context_window": 128_000,
                "max_output_tokens": 8_192,
                "apply_patch_tool_type": _APPLY_PATCH_TOOL_TYPE,
                "shell_type": _SHELL_TYPE,
                "supported_reasoning_levels": [],
                "visibility": "list",
                "supported_in_api": True,
                "priority": 0,
                "base_instructions": "You are a helpful coding agent.",
                "supports_reasoning_summaries": False,
                "support_verbosity": False,
                "truncation_policy": {"mode": "tokens", "limit": 100_000},
                "supports_parallel_tool_calls": False,
                "experimental_supported_tools": [],
            }
        ]
    }


def ensure_llm_provider_model_catalog(connection_id: uuid.UUID, model: str) -> str:
    """Write (or refresh) the Codex model-catalog file for one external connection, return its path."""
    _CATALOG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    catalog_file = _catalog_file(connection_id)
    catalog_file.write_text(json.dumps(_build_catalog(model)))
    return str(catalog_file)
