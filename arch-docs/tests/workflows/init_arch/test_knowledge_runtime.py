from __future__ import annotations

import datetime as dt
from pathlib import Path

from app.workflows.init_arch import knowledge_runtime as runtime


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _doc(
    relative_path: str,
    *,
    title: str = "Doc",
    document_type: str = "document",
    related: tuple[str, ...] = (),
    repositories: tuple[str, ...] = (),
    confidence: str = "unknown",
    domain: str = "",
    frontmatter: dict[str, object] | None = None,
) -> runtime.KnowledgeDocument:
    return runtime.KnowledgeDocument(
        relative_path=relative_path,
        title=title,
        document_type=document_type,
        frontmatter=frontmatter or {},
        body="# Body",
        outgoing_references=tuple(related),
        metadata_related=tuple(related),
        repositories=tuple(repositories),
        confidence=confidence,
        domain=domain,
    )


def test_build_navigation_index_renders_missing_sections_when_repo_is_empty(tmp_path: Path) -> None:
    arch_repo = tmp_path / "arch"
    (arch_repo / "wiki").mkdir(parents=True)

    content = runtime.build_navigation_index(arch_repo, "Svc", [])

    assert "не зарегистрированы" in content
    assert "Ключевые фичи: `не найдены`" in content
    assert "Интеграции по сервисам: `не найдены`" in content


def test_compile_knowledge_graph_collects_links_and_weak_pages(tmp_path: Path) -> None:
    arch_repo = tmp_path / "arch"
    _write(
        arch_repo / "features" / "auth.md",
        """---
title: Auth
type: feature
related:
  - architecture/security.md
repositories:
  - svc
confidence: high
---
# Auth
[Security](../architecture/security.md)
""",
    )
    _write(
        arch_repo / "architecture" / "security.md",
        """---
title: Security
type: security
related:
  - Auth
repositories:
  - svc
confidence: medium
---
# Security
[[Auth]]
""",
    )
    _write(arch_repo / "wiki" / "concepts" / "orphan.md", "# Orphan\n")
    _write(arch_repo / "wiki" / "index.md", "# Existing index\n")
    _write(arch_repo / "wiki" / "log.md", "# Log\n")

    result = runtime.compile_knowledge_graph(arch_repo)

    assert "features/auth.md" in result.index_content
    assert "architecture/security.md" in result.index_content
    assert "wiki/concepts/orphan.md" in result.weakly_linked_pages
    assert result.documents_with_frontmatter >= 2


def test_lint_feature_index_reports_missing_and_unindexed_files(tmp_path: Path) -> None:
    features_index = tmp_path / "features-index.md"
    features_index.write_text("[Auth](features/auth.md)\n[Ghost](features/ghost.md)\n", encoding="utf-8")
    feature_file = tmp_path / "features" / "billing.md"
    _write(feature_file, "# Billing\n")

    issues = runtime._lint_feature_index(features_index, [feature_file])

    assert any("ghost.md" in issue for issue in issues)
    assert any("billing.md" in issue for issue in issues)


def test_lint_traceability_accepts_frontmatter_sources_and_markers(tmp_path: Path) -> None:
    arch_repo = tmp_path / "arch"
    source_doc = arch_repo / "architecture" / "integrations" / "svc.md"
    _write(source_doc, "---\nsources:\n  - repo/path\n---\n# Integration\n")

    assert runtime._lint_traceability(source_doc, arch_repo) == []

    no_trace = arch_repo / "architecture" / "contracts" / "api.yml"
    _write(no_trace, "openapi: 3.1.0\n")

    issues = runtime._lint_traceability(no_trace, arch_repo)

    assert issues and "нет явной трассировки источников" in issues[0]


def test_lint_open_questions_with_graph_reports_multiple_resolution_issues(tmp_path: Path) -> None:
    arch_repo = tmp_path / "arch"
    _write(
        arch_repo / "open-questions.md",
        """
| ID | Follow-up ID | Контекст | Целевые артефакты | Статус | Нужен ответ пользователя | Обновление knowledge graph | Как закрыт или что нужно для закрытия |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Q-1 |  | ctx | `features/auth.md` | open | yes | no |  |
| Q-2 | F-2 | ctx |  | resolved | no | no | closed somehow |
| Q-3 | F-3 | ctx | `missing.md` | resolved | no | yes | closed |
| Q-4 | F-4 | ctx | `features/auth.md` | resolved | no | yes | closed |
""".strip(),
    )
    _write(arch_repo / "features" / "auth.md", "# Auth\n")
    doc = _doc("features/auth.md", related=(), frontmatter={"related": []})

    issues = runtime._lint_open_questions_with_graph(
        arch_repo / "open-questions.md",
        arch_repo,
        document_by_path={"features/auth.md": doc},
    )

    joined = "\n".join(issues)
    assert "Q-1" in joined
    assert "Q-2" in joined
    assert "Q-3" in joined
    assert "Q-4" in joined


def test_lint_graph_awareness_aggregates_quality_issues(tmp_path: Path) -> None:
    arch_repo = tmp_path / "arch"
    layout_paths = runtime.resolve_layout_paths(arch_repo)
    _write(layout_paths.compile_report_path, "stale report")
    _write(layout_paths.index_path, "stale index")
    doc = _doc(
        "features/auth.md",
        document_type="feature",
        repositories=("svc",),
        confidence="low",
        domain="payments",
        frontmatter={"updated": "2020-01-01"},
    )
    other = _doc(
        "architecture/security.md",
        document_type="security",
        repositories=("svc",),
        confidence="high",
        domain="security",
        frontmatter={"updated": "2026-01-01"},
    )
    compile_result = runtime.CompileResult(
        layout_paths=layout_paths,
        index_content="expected index",
        compile_report_content="expected report",
        unresolved_references=("a -> b",),
        weakly_linked_pages=("wiki/concepts/lone.md",),
        total_documents=2,
        documents_requiring_metadata=2,
        documents_with_frontmatter=0,
        documents_with_related=0,
    )

    issues = runtime._lint_graph_awareness(arch_repo, layout_paths, compile_result, [doc, other])

    joined = "\n".join(issues)
    assert "missing related reference" in joined
    assert "orphan page" in joined
    assert "low-confidence" in joined
    assert "несколько domain-меток" in joined
    assert "не синхронизирован" in joined
    assert "quality gate" in joined


def test_lint_knowledge_log_and_output_sections_report_errors(tmp_path: Path) -> None:
    arch_repo = tmp_path / "arch"
    log_path = arch_repo / "wiki" / "log.md"
    _write(log_path, "## Запись: 2026-07-09\n\ntext only\n")
    artifact_path = arch_repo / "wiki" / "index.md"
    _write(artifact_path, "# Index\n")

    log_issues = runtime._lint_knowledge_log(log_path, arch_repo)
    section_issues = runtime._lint_compile_output_sections(artifact_path, arch_repo, ("## Summary",))

    assert "bullet" in log_issues[0]
    assert "обязательную секцию" in section_issues[0]


def test_lint_markdown_links_unprefixed_paths_and_frontmatter_report_problems(tmp_path: Path) -> None:
    arch_repo = tmp_path / "arch"
    markdown = arch_repo / "wiki" / "concepts" / "page.md"
    _write(
        markdown,
        """---
title: 123
unknown: value
sources: broken
confidence: impossible
updated: yesterday
---
[Missing](missing.md)
`app/services/handler.py`
""",
    )

    link_issues = runtime._lint_markdown_links(markdown, arch_repo)
    path_issues = runtime._lint_unprefixed_paths(markdown, arch_repo)
    frontmatter_issues = runtime._lint_frontmatter(markdown, arch_repo)

    assert "битую ссылку" in link_issues[0]
    assert "явного префикса" in path_issues[0]
    assert any("unknown" in issue for issue in frontmatter_issues)
    assert any("confidence" in issue for issue in frontmatter_issues)


def test_parse_helpers_extract_references_and_table_rows() -> None:
    frontmatter, body = runtime._parse_frontmatter("---\ntitle: \"Auth\"\nrelated:\n  - wiki/x.md\n---\n# Body\n")
    refs = runtime._extract_outgoing_references(
        Path("/tmp/features/auth.md"),
        Path("/tmp"),
        "[Doc](../wiki/x.md)\n[[Security]]",
        ["wiki/y.md"],
    )
    rows = runtime._parse_markdown_table(
        "| A | B |\n| --- | --- |\n| `x` | ./doc.md |\n"
    )

    assert frontmatter["title"] == "Auth"
    assert body.startswith("# Body")
    assert refs == ["wiki/x.md", "Security", "wiki/y.md"]
    assert rows == [{"A": "x", "B": "./doc.md"}]


def test_reference_resolution_and_document_type_helpers(tmp_path: Path) -> None:
    arch_repo = tmp_path / "arch"
    _write(arch_repo / "features" / "auth.md", "# Auth\n")
    doc = _doc("features/auth.md", title="Auth")

    assert runtime._resolve_document_reference(
        "wiki/concepts/page.md",
        "features/auth.md",
        arch_repo,
        {"features/auth.md": doc},
        {"Auth": doc},
    ) == "features/auth.md"
    assert runtime._resolve_document_reference(
        "wiki/concepts/page.md",
        "Auth",
        arch_repo,
        {"features/auth.md": doc},
        {"Auth": doc},
    ) == "features/auth.md"
    assert runtime._infer_document_type(arch_repo / "glossary.md", arch_repo, {}) == "glossary"
    assert runtime._extract_open_question_target_artifacts({"Целевые артефакты": "`features/auth.md`, ./wiki/x.md"}) == {
        "features/auth.md",
        "wiki/x.md",
    }


def test_quality_gate_helpers_and_metadata_flags() -> None:
    doc = _doc("features/auth.md", document_type="feature")

    lines = runtime._build_quality_gate_lines(2, 1, 0)

    assert runtime._requires_graph_metadata(doc) is True
    assert runtime._gate_status(0.5, 0.5, True) == "pass"
    assert runtime._ratio(0, 0) == 0.0
    assert runtime._format_ratio(1, 2) == "50%"
    assert any("Frontmatter coverage gate" in line for line in lines)
