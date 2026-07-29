from __future__ import annotations

import asyncio
import pathlib
import typing

from langchain_core.tools import StructuredTool, tool

_DEFAULT_SHELL_TIMEOUT_SECONDS: typing.Final[float] = 120.0


class ToolBoundaryError(Exception):
    pass


def _resolve_within_roots(candidate_path: str, allowed_roots: list[pathlib.Path]) -> pathlib.Path:
    """Resolve `candidate_path` and confirm it falls under at least one of `allowed_roots`.

    Relative paths are resolved against the first allowed root (the task's `workspace_dir`).
    `Path.resolve()` collapses `..` and symlinks before the containment check, so neither can be
    used to escape the allowed roots - see
    arch-docs/docs/spec/2026-07-25-langgraph-api-agent-runner.md, section 3.
    """
    candidate = pathlib.Path(candidate_path)
    if not candidate.is_absolute():
        candidate = allowed_roots[0] / candidate
    resolved = candidate.resolve()
    for root in allowed_roots:
        if resolved.is_relative_to(root):
            return resolved
    allowed_display = ", ".join(str(root) for root in allowed_roots)
    msg = f"Path '{candidate_path}' resolves outside allowed roots: {allowed_display}"
    raise ToolBoundaryError(msg)


def _make_read_file_tool(allowed_roots: list[pathlib.Path]) -> StructuredTool:
    @tool
    def read_file(path: str) -> str:
        """Read the full text contents of a file inside the workspace."""
        try:
            target = _resolve_within_roots(path, allowed_roots)
        except ToolBoundaryError as exc:
            return f"Error: {exc}"
        if not target.is_file():
            return f"Error: file not found: {target}"
        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Error: {exc}"

    return read_file


def _make_write_file_tool(allowed_roots: list[pathlib.Path]) -> StructuredTool:
    @tool
    def write_file(path: str, content: str) -> str:
        """Write text content to a file inside the workspace, creating parent directories as needed."""
        try:
            target = _resolve_within_roots(path, allowed_roots)
        except ToolBoundaryError as exc:
            return f"Error: {exc}"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return f"Error: {exc}"
        return f"Wrote {len(content)} characters to {target}"

    return write_file


def _make_list_directory_tool(allowed_roots: list[pathlib.Path]) -> StructuredTool:
    @tool
    def list_directory(path: str = ".") -> list[str]:
        """List entries (files and directories) directly inside a directory in the workspace."""
        try:
            target = _resolve_within_roots(path, allowed_roots)
        except ToolBoundaryError as exc:
            return [f"Error: {exc}"]
        if not target.is_dir():
            return [f"Error: not a directory: {target}"]
        return sorted(entry.name + ("/" if entry.is_dir() else "") for entry in target.iterdir())

    return list_directory


def _make_run_shell_tool(allowed_roots: list[pathlib.Path], shell_timeout_seconds: float) -> StructuredTool:
    @tool
    async def run_shell(command: str, timeout_seconds: float | None = None) -> dict[str, typing.Any]:
        """Run a shell command with the workspace as the current working directory.

        Arbitrary shell constructs (pipes, `&&`, redirects) are allowed - this matches the trust
        level already granted to codex/claude (`danger-full-access`/`bypassPermissions`); the
        container boundary is the security boundary, not the set of permitted commands. Covers git
        operations too, same as the CLI engines' own shell access (no separate git tool).
        """
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(allowed_roots[0]),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds or shell_timeout_seconds
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return {"stdout": "", "stderr": "Error: command timed out", "exit_code": -1}
        return {
            "stdout": stdout_bytes.decode(errors="replace"),
            "stderr": stderr_bytes.decode(errors="replace"),
            "exit_code": proc.returncode or 0,
        }

    return run_shell


def build_agent_tools(
    allowed_roots: list[str], *, shell_timeout_seconds: float = _DEFAULT_SHELL_TIMEOUT_SECONDS
) -> list[StructuredTool]:
    """Build the LangGraph agent's file/git/shell toolset, confined to `allowed_roots`.

    `allowed_roots[0]` is the task's `workspace_dir` and doubles as the shell's cwd; any further
    entries (e.g. `arch_repo_dir`) widen file access without changing where shell commands run.
    """
    resolved_roots = [pathlib.Path(root).resolve() for root in allowed_roots]
    return [
        _make_read_file_tool(resolved_roots),
        _make_write_file_tool(resolved_roots),
        _make_list_directory_tool(resolved_roots),
        _make_run_shell_tool(resolved_roots, shell_timeout_seconds),
    ]
