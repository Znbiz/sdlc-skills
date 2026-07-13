from __future__ import annotations

from typing import TYPE_CHECKING

from app.workflows.init_arch import architecture_lint

if TYPE_CHECKING:
    from pathlib import Path


def _write(tmp_path: Path, relative_path: str, body: str) -> Path:
    target_path = tmp_path / relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(body, encoding="utf-8")
    return target_path


def test_lint_required_sections_reports_missing_file(tmp_path: Path) -> None:
    issues = architecture_lint._lint_required_sections(tmp_path, "architecture/hld.md", ("## X",))

    assert issues == ["ERROR: отсутствует architecture/hld.md"]


def test_lint_required_sections_reports_each_missing_heading(tmp_path: Path) -> None:
    _write(tmp_path, "architecture/hld.md", "# HLD\n\n## Обзор текущей архитектуры\n\nтекст\n")

    issues = architecture_lint._lint_required_sections(
        tmp_path, "architecture/hld.md", architecture_lint.ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS["architecture/hld.md"]
    )

    assert "ERROR: architecture/hld.md не содержит обязательную секцию `## Контекстная диаграмма`" in issues
    assert "ERROR: architecture/hld.md не содержит обязательную секцию `## Обзор текущей архитектуры`" not in issues


def test_lint_required_sections_passes_when_all_present(tmp_path: Path) -> None:
    required_sections = architecture_lint.ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS["architecture/risks.md"]
    body = "# Риски\n\n" + "\n\n".join(f"{section}\n\nтекст" for section in required_sections)
    _write(tmp_path, "architecture/risks.md", body)

    issues = architecture_lint._lint_required_sections(tmp_path, "architecture/risks.md", required_sections)

    assert issues == []


def test_lint_architecture_artifacts_reports_all_nine_missing_files(tmp_path: Path) -> None:
    issues = architecture_lint.lint_architecture_artifacts(tmp_path)

    for relative_path in architecture_lint.ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS:
        assert f"ERROR: отсутствует {relative_path}" in issues
