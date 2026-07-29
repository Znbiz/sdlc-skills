from __future__ import annotations

import pathlib

import pytest

from app.services.langgraph_agent_tools import ToolBoundaryError, _resolve_within_roots, build_agent_tools


class TestResolveWithinRoots:
    def test_relative_path_resolves_against_first_root(self, tmp_path: pathlib.Path) -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        resolved = _resolve_within_roots("sub/file.txt", [root])
        assert resolved == (root / "sub" / "file.txt").resolve()

    def test_absolute_path_inside_root_is_accepted(self, tmp_path: pathlib.Path) -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        target = root / "file.txt"
        resolved = _resolve_within_roots(str(target), [root])
        assert resolved == target.resolve()

    def test_path_escaping_all_roots_raises(self, tmp_path: pathlib.Path) -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        with pytest.raises(ToolBoundaryError):
            _resolve_within_roots("../../etc/passwd", [root])

    def test_symlink_escaping_root_raises(self, tmp_path: pathlib.Path) -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (root / "escape").symlink_to(outside)
        with pytest.raises(ToolBoundaryError):
            _resolve_within_roots("escape/secret.txt", [root])

    def test_path_inside_second_root_is_accepted(self, tmp_path: pathlib.Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        arch_repo = tmp_path / "arch-repo"
        arch_repo.mkdir()
        resolved = _resolve_within_roots(str(arch_repo / "doc.md"), [workspace, arch_repo])
        assert resolved == (arch_repo / "doc.md").resolve()


class TestReadFileTool:
    async def test_reads_existing_file(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
        read_file, _write_file, _list_directory, _run_shell = build_agent_tools([str(tmp_path)])
        result = await read_file.ainvoke({"path": "a.txt"})
        assert result == "hello"

    async def test_missing_file_returns_error_text_not_exception(self, tmp_path: pathlib.Path) -> None:
        read_file, _write_file, _list_directory, _run_shell = build_agent_tools([str(tmp_path)])
        result = await read_file.ainvoke({"path": "missing.txt"})
        assert result.startswith("Error:")

    async def test_path_outside_roots_returns_error_text_not_exception(self, tmp_path: pathlib.Path) -> None:
        read_file, _write_file, _list_directory, _run_shell = build_agent_tools([str(tmp_path)])
        result = await read_file.ainvoke({"path": "../../etc/passwd"})
        assert result.startswith("Error:")

    async def test_os_error_returns_error_text_not_exception(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
        read_file, _write_file, _list_directory, _run_shell = build_agent_tools([str(tmp_path)])

        def _raise_os_error(*_args, **_kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr(pathlib.Path, "read_text", _raise_os_error)
        result = await read_file.ainvoke({"path": "a.txt"})
        assert result == "Error: permission denied"


class TestWriteFileTool:
    async def test_writes_file_and_creates_parent_dirs(self, tmp_path: pathlib.Path) -> None:
        _read_file, write_file, _list_directory, _run_shell = build_agent_tools([str(tmp_path)])
        result = await write_file.ainvoke({"path": "nested/dir/b.txt", "content": "content"})
        assert "Wrote" in result
        assert (tmp_path / "nested" / "dir" / "b.txt").read_text(encoding="utf-8") == "content"

    async def test_path_outside_roots_returns_error_and_does_not_write(self, tmp_path: pathlib.Path) -> None:
        _read_file, write_file, _list_directory, _run_shell = build_agent_tools([str(tmp_path)])
        result = await write_file.ainvoke({"path": "../escape.txt", "content": "x"})
        assert result.startswith("Error:")
        assert not (tmp_path.parent / "escape.txt").exists()

    async def test_os_error_returns_error_text_not_exception(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _read_file, write_file, _list_directory, _run_shell = build_agent_tools([str(tmp_path)])

        def _raise_os_error(*_args, **_kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(pathlib.Path, "write_text", _raise_os_error)
        result = await write_file.ainvoke({"path": "b.txt", "content": "x"})
        assert result == "Error: disk full"


class TestListDirectoryTool:
    async def test_lists_files_and_directories_sorted_with_trailing_slash(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "b.txt").write_text("x", encoding="utf-8")
        (tmp_path / "a_dir").mkdir()
        _read_file, _write_file, list_directory, _run_shell = build_agent_tools([str(tmp_path)])
        result = await list_directory.ainvoke({"path": "."})
        assert result == ["a_dir/", "b.txt"]

    async def test_not_a_directory_returns_error(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "file.txt").write_text("x", encoding="utf-8")
        _read_file, _write_file, list_directory, _run_shell = build_agent_tools([str(tmp_path)])
        result = await list_directory.ainvoke({"path": "file.txt"})
        assert result[0].startswith("Error:")

    async def test_path_outside_roots_returns_error_text_not_exception(self, tmp_path: pathlib.Path) -> None:
        _read_file, _write_file, list_directory, _run_shell = build_agent_tools([str(tmp_path)])
        result = await list_directory.ainvoke({"path": "../../etc"})
        assert result[0].startswith("Error:")


class TestRunShellTool:
    async def test_runs_command_with_workspace_as_cwd(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "marker.txt").write_text("x", encoding="utf-8")
        _read_file, _write_file, _list_directory, run_shell = build_agent_tools([str(tmp_path)])
        result = await run_shell.ainvoke({"command": "ls"})
        assert result["exit_code"] == 0
        assert "marker.txt" in result["stdout"]
        assert result["stderr"] == ""

    async def test_nonzero_exit_code_is_reported_not_raised(self, tmp_path: pathlib.Path) -> None:
        _read_file, _write_file, _list_directory, run_shell = build_agent_tools([str(tmp_path)])
        result = await run_shell.ainvoke({"command": "exit 7"})
        assert result["exit_code"] == 7

    async def test_command_timeout_is_reported_not_raised(self, tmp_path: pathlib.Path) -> None:
        _read_file, _write_file, _list_directory, run_shell = build_agent_tools(
            [str(tmp_path)], shell_timeout_seconds=0.05
        )
        result = await run_shell.ainvoke({"command": "sleep 5"})
        assert result["exit_code"] == -1
        assert "timed out" in result["stderr"]
