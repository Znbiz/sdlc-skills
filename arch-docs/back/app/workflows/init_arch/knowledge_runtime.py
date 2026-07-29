"""Navigation index, metadata parsing, lint, and compile helpers."""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.workflows.init_arch.architecture_lint import lint_architecture_artifacts

TRACEABILITY_MARKERS: Final[tuple[str, ...]] = (
    "Источники",
    "sources:",
    "x-traceability:",
    "Подтверждающие артефакты",
)
FRONTMATTER_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "title",
        "type",
        "sources",
        "related",
        "created",
        "updated",
        "confidence",
        "domain",
        "repositories",
    }
)
VALID_CONFIDENCE: Final[frozenset[str]] = frozenset({"high", "medium", "low", "unknown"})
KNOWLEDGE_LOG_ENTRY_PREFIX: Final = "## Запись:"
CODE_PATH_ROOTS: Final[frozenset[str]] = frozenset(
    {
        "api",
        "app",
        "cmd",
        "configs",
        "db",
        "deploy",
        "internal",
        "migrations",
        "pages",
        "pkg",
        "proto",
        "schemas",
        "scripts",
        "services",
        "src",
        "terraform",
        "tests",
    }
)
ARTIFACT_REFERENCE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:(?:\]\((?:\./|\.\./)?)|`)([^)`\s]+?\.(?:md|ya?ml))(?:\)|`)",
)
CODE_PATH_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"`([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.\-/\[\]]+)+)`",
)
MARKDOWN_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
WIKILINK_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[\[([^\]]+)\]\]")
FRONTMATTER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\A---\n(?P<body>.*?)\n---\n?",
    re.DOTALL,
)
DATE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INDEX_REQUIRED_SECTIONS: Final[tuple[str, ...]] = (
    "## Что читать первым",
    "## Артефакты по типам",
    "## Related Artifacts",
    "## Graph Gaps",
    "## Quality Gates",
    "## Compile Rules",
)
COMPILE_REPORT_REQUIRED_SECTIONS: Final[tuple[str, ...]] = (
    "## Summary",
    "## Coverage",
    "## Quality Gates",
    "## Unresolved References",
    "## Weakly Linked Pages",
    "## Link Graph",
    "## Document Metadata",
)
MIN_FRONTMATTER_COVERAGE: Final[float] = 0.5
MIN_RELATED_COVERAGE: Final[float] = 0.5


@dataclass(frozen=True)
class LayoutPaths:
    mode: str
    navigation_root: Path
    index_path: Path
    log_path: Path
    compile_report_path: Path


@dataclass(frozen=True)
class KnowledgeDocument:
    relative_path: str
    title: str
    document_type: str
    frontmatter: dict[str, object]
    body: str
    outgoing_references: tuple[str, ...]
    metadata_related: tuple[str, ...]
    repositories: tuple[str, ...]
    confidence: str
    domain: str


@dataclass(frozen=True)
class CompileResult:
    layout_paths: LayoutPaths
    index_content: str
    compile_report_content: str
    unresolved_references: tuple[str, ...]
    weakly_linked_pages: tuple[str, ...]
    total_documents: int
    documents_requiring_metadata: int
    documents_with_frontmatter: int
    documents_with_related: int


def resolve_layout_paths(arch_repo_path: Path) -> LayoutPaths:
    navigation_root = arch_repo_path / "wiki"
    return LayoutPaths(
        mode="wiki",
        navigation_root=navigation_root,
        index_path=navigation_root / "index.md",
        log_path=navigation_root / "log.md",
        compile_report_path=navigation_root / "maps" / "compile-report.md",
    )


def build_navigation_index(
    arch_repo_path: Path,
    product: str,
    repositories: list[dict],
) -> str:
    layout_paths = resolve_layout_paths(arch_repo_path)
    feature_files = sorted((arch_repo_path / "features").glob("*.md"))
    integration_files = sorted((arch_repo_path / "architecture" / "integrations").glob("*.md"))
    contract_files = sorted((arch_repo_path / "architecture" / "contracts").glob("*.yml"))
    storage_files = sorted((arch_repo_path / "architecture" / "storage").glob("*.yml"))

    repo_names = [repo.get("name", "") for repo in repositories if repo.get("name")]
    completed_repos = [
        repo.get("name", "") for repo in repositories if repo.get("analysis_status") == "completed" and repo.get("name")
    ]
    primary_index_name = "wiki/index.md"

    lines = [
        f"# Индекс знаний по системе {product}",
        "",
        "Этот файл собран `analysis_guard index` и служит короткой точкой входа в knowledge-слой.",
        "",
        "## Что читать первым",
        "",
        "1. `AGENTS.md` — operational entrypoint и правила работы с knowledge-слоем.",
        f"2. `{primary_index_name}` — навигация по уже собранным артефактам.",
        "3. Нужный детальный артефакт из разделов ниже.",
        "",
        "## Обзор системы",
        "",
        f"- Краткое описание продукта: `{product}`",
        f"- Текущий статус покрытия: завершено репозиториев `{len(completed_repos)}` из `{len(repo_names)}`",
        f"- Основные репозитории в scope: {', '.join(f'`{name}`' for name in repo_names) if repo_names else 'не зарегистрированы'}",
        "",
        "## Фичи",
        "",
        f"- [Реестр фич]({_render_relative_link(layout_paths, arch_repo_path, 'features-index.md')}) — короткий список всех выделенных capability.",
    ]

    if feature_files:
        lines.append("- Ключевые фичи:")
        for feature_file in feature_files:
            feature_relative_path = feature_file.relative_to(arch_repo_path).as_posix()
            lines.append(
                f"  - [{feature_file.stem}]({_render_relative_link(layout_paths, arch_repo_path, feature_relative_path)}) — детальное описание capability"
            )
    else:
        lines.append("- Ключевые фичи: `не найдены`")

    update_rule = (
        "Обновляй `wiki/index.md` при появлении новых артефактов в "
        "`features/`, `architecture/`, `glossary.md` или `open-questions.md`."
    )

    lines.extend(
        [
            "",
            "## Архитектура",
            "",
            _link_or_missing(
                layout_paths, arch_repo_path, "architecture/hld.md", "HLD", "общий обзор системы и основных потоков"
            ),
            _link_or_missing(
                layout_paths,
                arch_repo_path,
                "architecture/landscape.yaml",
                "Ландшафт сервисов",
                "машиночитаемая карта сервисов и зависимостей",
            ),
            _link_or_missing(
                layout_paths,
                arch_repo_path,
                "architecture/tech-stack.md",
                "Технологический стек",
                "ЯП, фреймворки, transport, observability",
            ),
            _link_or_missing(
                layout_paths,
                arch_repo_path,
                "architecture/roles-and-permissions.md",
                "Роли и доступы",
                "роли пользователей и границы функционала",
            ),
            _link_or_missing(
                layout_paths,
                arch_repo_path,
                "architecture/security.md",
                "Безопасность",
                "auth, trust boundaries, чувствительные данные",
            ),
            _link_or_missing(
                layout_paths, arch_repo_path, "architecture/risks.md", "Риски", "известные architectural gaps и техдолг"
            ),
            "",
            "## Интеграции, контракты и данные",
            "",
            _link_or_missing(
                layout_paths,
                arch_repo_path,
                "architecture/integrations-overview.md",
                "Обзор интеграций",
                "входящие и исходящие интеграции по сервисам",
            ),
        ]
    )

    if integration_files:
        lines.append("- Интеграции по сервисам:")
        for integration_file in integration_files:
            integration_relative_path = integration_file.relative_to(arch_repo_path).as_posix()
            lines.append(
                f"  - [{integration_file.stem}]({_render_relative_link(layout_paths, arch_repo_path, integration_relative_path)}) — детализация интеграций сервиса"
            )
    else:
        lines.append("- Интеграции по сервисам: `не найдены`")

    lines.append("- Контракты:")
    if contract_files:
        for contract_file in contract_files:
            contract_relative_path = contract_file.relative_to(arch_repo_path).as_posix()
            lines.append(f"  - `{_render_relative_link(layout_paths, arch_repo_path, contract_relative_path)}`")
    else:
        lines.append("  - `не найдены`")

    lines.append("- Хранилища:")
    if storage_files:
        for storage_file in storage_files:
            storage_relative_path = storage_file.relative_to(arch_repo_path).as_posix()
            lines.append(f"  - `{_render_relative_link(layout_paths, arch_repo_path, storage_relative_path)}`")
    else:
        lines.append("  - `не найдены`")

    log_description = "append-only журнал `wiki/log.md` с противоречиями и follow-up"
    lines.extend(
        [
            "",
            "## Термины и открытые вопросы",
            "",
            _link_or_missing(
                layout_paths, arch_repo_path, "glossary.md", "Глоссарий", "продуктовые и технические термины"
            ),
            _link_or_missing(
                layout_paths,
                arch_repo_path,
                "open-questions.md",
                "Открытые вопросы",
                "gaps, которые не удалось закрыть из кода",
            ),
            "",
            "## Support-репозитории",
            "",
            _link_or_missing(
                layout_paths,
                arch_repo_path,
                "architecture/support-repositories.md",
                "Support repositories",
                "библиотеки, infra и test-repo, которые не оформляются как продуктовые фичи",
            ),
            "",
            "## Knowledge log",
            "",
            _link_or_missing(
                layout_paths,
                arch_repo_path,
                layout_paths.log_path.relative_to(arch_repo_path).as_posix(),
                "Журнал knowledge-обновлений",
                log_description,
            ),
            "",
            "## Правило обновления",
            "",
            update_rule,
            "",
        ]
    )
    return "\n".join(lines)


def build_knowledge_log_stub() -> str:
    today = dt.datetime.now(dt.UTC).date().isoformat()
    return "\n".join(
        [
            "# Knowledge Log",
            "",
            "Этот журнал ведётся в формате append-only. Новые записи добавляй последовательно.",
            "",
            f"{KNOWLEDGE_LOG_ENTRY_PREFIX} {today}",
            "",
            "### Что обновлено",
            "",
            "- Создан navigation layer knowledge-слоя",
            "",
            "### Какие факты или выводы добавлены",
            "",
            "- `<краткое описание нового подтверждённого знания>`",
            "",
            "### Противоречия и пробелы",
            "",
            "- `<что не удалось подтвердить>`",
            "",
            "### Follow-up",
            "",
            "- `<что нужно проверить дальше>`",
            "",
            "### Источники",
            "",
            "- `<repo-name/path/to/file>`",
            "",
        ]
    )


def build_compile_report_stub() -> str:
    return "\n".join(
        [
            "# Compile Report",
            "",
            "Этот отчёт подготовлен bootstrap-командой. Полная диагностика появится после `analysis_guard compile`.",
            "",
            "## Summary",
            "",
            "- Layout mode: `wiki`",
            "- Документов просканировано: `0`",
            "- Документов с frontmatter: `0`",
            "- Неразрешённых ссылок: `0`",
            "- Weakly linked pages: `0`",
            "",
            "## Coverage",
            "",
            "- Frontmatter coverage: `pending`",
            "- Related metadata coverage: `pending`",
            "",
            "## Quality Gates",
            "",
            "- Required sections gate: `pending`",
            "- Frontmatter coverage gate: `pending`",
            "- Related coverage gate: `pending`",
            "",
            "## Unresolved References",
            "",
            "- `не собран`",
            "",
            "## Weakly Linked Pages",
            "",
            "- `не собран`",
            "",
            "## Link Graph",
            "",
            "- `не собран`",
            "",
            "## Document Metadata",
            "",
            "- `не собран`",
            "",
        ]
    )


def run_knowledge_lint(arch_repo_path: Path) -> list[str]:
    issues: list[str] = []
    layout_paths = resolve_layout_paths(arch_repo_path)

    if layout_paths.index_path.exists():
        issues.extend(_lint_markdown_links(layout_paths.index_path, arch_repo_path))
    else:
        issues.append(f"ERROR: отсутствует {layout_paths.index_path.relative_to(arch_repo_path)}")

    feature_files = sorted((arch_repo_path / "features").glob("*.md")) if (arch_repo_path / "features").exists() else []
    issues.extend(_lint_feature_index(arch_repo_path / "features-index.md", feature_files))

    integrations_dir = arch_repo_path / "architecture" / "integrations"
    contracts_dir = arch_repo_path / "architecture" / "contracts"
    storage_dir = arch_repo_path / "architecture" / "storage"
    for artifact_path in _iter_knowledge_artifacts(integrations_dir, contracts_dir, storage_dir):
        issues.extend(_lint_traceability(artifact_path, arch_repo_path))

    compile_result = compile_knowledge_graph(arch_repo_path)
    documents = _collect_knowledge_documents(arch_repo_path, layout_paths)
    document_by_path = {document.relative_path: document for document in documents}

    issues.extend(
        _lint_open_questions_with_graph(
            arch_repo_path / "open-questions.md",
            arch_repo_path,
            document_by_path=document_by_path,
        )
    )
    issues.extend(_lint_knowledge_log(layout_paths.log_path, arch_repo_path))
    issues.extend(
        _lint_graph_awareness(
            arch_repo_path=arch_repo_path,
            layout_paths=layout_paths,
            compile_result=compile_result,
            documents=documents,
        )
    )
    if layout_paths.compile_report_path.exists():
        issues.extend(
            _lint_compile_output_sections(
                layout_paths.index_path,
                arch_repo_path,
                INDEX_REQUIRED_SECTIONS,
            )
        )
        issues.extend(
            _lint_compile_output_sections(
                layout_paths.compile_report_path,
                arch_repo_path,
                COMPILE_REPORT_REQUIRED_SECTIONS,
            )
        )

    for markdown_path in _iter_markdown_documents_for_lint(arch_repo_path, layout_paths):
        issues.extend(_lint_unprefixed_paths(markdown_path, arch_repo_path))
        issues.extend(_lint_frontmatter(markdown_path, arch_repo_path))

    issues.extend(lint_architecture_artifacts(arch_repo_path))

    return issues


def compile_knowledge_graph(arch_repo_path: Path) -> CompileResult:
    layout_paths = resolve_layout_paths(arch_repo_path)
    documents = _collect_knowledge_documents(arch_repo_path, layout_paths)
    document_by_path = {document.relative_path: document for document in documents}
    document_by_title = {document.title: document for document in documents if document.title}

    resolved_edges: dict[str, set[str]] = {document.relative_path: set() for document in documents}
    incoming_edges: dict[str, set[str]] = {document.relative_path: set() for document in documents}
    unresolved_references: list[str] = []

    for document in documents:
        for reference in document.outgoing_references:
            resolved_path = _resolve_document_reference(
                source_path=document.relative_path,
                reference=reference,
                arch_repo_path=arch_repo_path,
                document_by_path=document_by_path,
                document_by_title=document_by_title,
            )
            if resolved_path is None:
                unresolved_references.append(f"{document.relative_path} -> {reference}")
                continue
            if resolved_path not in document_by_path:
                # Reference points to a real file on disk (e.g. `_resolve_document_reference()`'s
                # `candidate_path.exists()` branch matched a non-markdown artifact under
                # `architecture/contracts/`|`architecture/storage/`, a *.yml contract/schema, not a
                # KnowledgeDocument) - a legitimate link, not a broken one, so it must not be counted
                # as unresolved. But `resolved_edges`/`incoming_edges` are keyed by KnowledgeDocument
                # relative_path only (line ~464-465) - indexing `incoming_edges[resolved_path]` for a
                # path that was never a dict key raised a bare KeyError here (confirmed on a real
                # `build_navigation_index` run where a markdown doc linked to a generated
                # `architecture/contracts/<repo>-sync.yml`).
                continue
            resolved_edges[document.relative_path].add(resolved_path)
            incoming_edges[resolved_path].add(document.relative_path)

    weakly_linked_pages = sorted(
        document.relative_path
        for document in documents
        if document.relative_path
        not in {
            layout_paths.index_path.relative_to(arch_repo_path).as_posix(),
            layout_paths.log_path.relative_to(arch_repo_path).as_posix(),
        }
        and not resolved_edges[document.relative_path]
        and not incoming_edges[document.relative_path]
    )

    index_content = _build_compiled_wiki_index(
        arch_repo_path=arch_repo_path,
        layout_paths=layout_paths,
        documents=documents,
        resolved_edges=resolved_edges,
        unresolved_references=sorted(set(unresolved_references)),
        weakly_linked_pages=weakly_linked_pages,
    )
    compile_report_content = _build_compile_report(
        arch_repo_path=arch_repo_path,
        layout_paths=layout_paths,
        documents=documents,
        resolved_edges=resolved_edges,
        incoming_edges=incoming_edges,
        unresolved_references=sorted(set(unresolved_references)),
        weakly_linked_pages=weakly_linked_pages,
    )

    metadata_documents = [document for document in documents if _requires_graph_metadata(document)]
    documents_with_frontmatter = sum(1 for document in metadata_documents if document.frontmatter)
    documents_with_related = sum(1 for document in metadata_documents if document.metadata_related)
    return CompileResult(
        layout_paths=layout_paths,
        index_content=index_content,
        compile_report_content=compile_report_content,
        unresolved_references=tuple(sorted(set(unresolved_references))),
        weakly_linked_pages=tuple(weakly_linked_pages),
        total_documents=len(documents),
        documents_requiring_metadata=len(metadata_documents),
        documents_with_frontmatter=documents_with_frontmatter,
        documents_with_related=documents_with_related,
    )


def _build_compiled_wiki_index(
    arch_repo_path: Path,
    layout_paths: LayoutPaths,
    documents: list[KnowledgeDocument],
    resolved_edges: dict[str, set[str]],
    unresolved_references: list[str],
    weakly_linked_pages: list[str],
) -> str:
    grouped_documents: dict[str, list[KnowledgeDocument]] = {}
    for document in documents:
        grouped_documents.setdefault(document.document_type, []).append(document)

    lines = [
        "# Wiki Index",
        "",
        "Этот файл собран `analysis_guard compile` по frontmatter, markdown links и metadata `related`.",
        "",
        "## Что читать первым",
        "",
        "1. `AGENTS.md` — правила работы с knowledge-слоем.",
        "2. `wiki/index.md` — текущая карта собранных артефактов и связей.",
        "3. `wiki/maps/compile-report.md` — диагностика качества knowledge graph.",
        "",
        "## Артефакты по типам",
        "",
    ]

    for document_type in sorted(grouped_documents):
        lines.append(f"### {document_type}")
        lines.append("")
        for document in sorted(grouped_documents[document_type], key=lambda item: item.title.lower()):
            relative_link = _render_relative_link(layout_paths, arch_repo_path, document.relative_path)
            metadata_tags = _build_metadata_tag_line(document)
            lines.append(f"- [{document.title}]({relative_link}){metadata_tags}")
        lines.append("")

    lines.extend(["## Related Artifacts", ""])
    for document in sorted(documents, key=lambda item: item.title.lower()):
        related_targets = sorted(resolved_edges[document.relative_path])
        if not related_targets:
            continue
        rendered_targets = ", ".join(f"`{target}`" for target in related_targets)
        lines.append(f"- `{document.relative_path}` -> {rendered_targets}")
    if lines[-1] == "":
        lines.append("- `не найдены`")
    lines.append("")

    lines.extend(["## Graph Gaps", ""])
    if unresolved_references:
        lines.append("- Missing related references:")
        for item in unresolved_references:
            lines.append(f"  - `{item}`")
    else:
        lines.append("- Missing related references: `не найдены`")

    if weakly_linked_pages:
        lines.append("- Weakly linked pages:")
        for item in weakly_linked_pages:
            lines.append(f"  - `{item}`")
    else:
        lines.append("- Weakly linked pages: `не найдены`")
    lines.append("")

    lines.extend(["## Quality Gates", ""])
    lines.extend(
        _build_quality_gate_lines(
            documents_requiring_metadata=sum(1 for document in documents if _requires_graph_metadata(document)),
            documents_with_frontmatter=sum(
                1 for document in documents if _requires_graph_metadata(document) and document.frontmatter
            ),
            documents_with_related=sum(
                1 for document in documents if _requires_graph_metadata(document) and document.metadata_related
            ),
        )
    )
    lines.append("")

    lines.extend(
        [
            "## Compile Rules",
            "",
            "- Navigation layer строится из frontmatter, markdown links и metadata `related`.",
            "- `wiki/index.md`, `wiki/log.md` и `wiki/maps/compile-report.md` являются основными wiki-артефактами.",
            "",
        ]
    )
    return "\n".join(lines)


def _build_compile_report(
    arch_repo_path: Path,
    layout_paths: LayoutPaths,
    documents: list[KnowledgeDocument],
    resolved_edges: dict[str, set[str]],
    incoming_edges: dict[str, set[str]],
    unresolved_references: list[str],
    weakly_linked_pages: list[str],
) -> str:
    metadata_documents = [document for document in documents if _requires_graph_metadata(document)]
    documents_with_frontmatter = sum(1 for document in metadata_documents if document.frontmatter)
    documents_with_related = sum(1 for document in metadata_documents if document.metadata_related)
    lines = [
        "# Compile Report",
        "",
        "Этот отчёт собран `analysis_guard compile` и показывает текущее состояние knowledge graph.",
        "",
        "## Summary",
        "",
        f"- Layout mode: `{layout_paths.mode}`",
        f"- Документов просканировано: `{len(documents)}`",
        f"- Документов с frontmatter: `{documents_with_frontmatter}`",
        f"- Неразрешённых ссылок: `{len(unresolved_references)}`",
        f"- Weakly linked pages: `{len(weakly_linked_pages)}`",
        "",
        "## Coverage",
        "",
        (
            f"- Frontmatter coverage: `{documents_with_frontmatter}/{len(metadata_documents)}` "
            f"({_format_ratio(documents_with_frontmatter, len(metadata_documents))})"
        ),
        (
            f"- Related metadata coverage: `{documents_with_related}/{documents_with_frontmatter}` "
            f"({_format_ratio(documents_with_related, documents_with_frontmatter)})"
        ),
        "",
        "## Quality Gates",
        "",
    ]
    lines.extend(
        _build_quality_gate_lines(
            documents_requiring_metadata=len(metadata_documents),
            documents_with_frontmatter=documents_with_frontmatter,
            documents_with_related=documents_with_related,
        )
    )
    lines.extend(
        [
            "",
            "## Unresolved References",
            "",
        ]
    )
    if unresolved_references:
        for item in unresolved_references:
            lines.append(f"- `{item}`")
    else:
        lines.append("- `не найдены`")

    lines.extend(["", "## Weakly Linked Pages", ""])
    if weakly_linked_pages:
        for item in weakly_linked_pages:
            lines.append(f"- `{item}`")
    else:
        lines.append("- `не найдены`")

    lines.extend(["", "## Link Graph", ""])
    for document in sorted(documents, key=lambda item: item.relative_path):
        outgoing = ", ".join(f"`{item}`" for item in sorted(resolved_edges[document.relative_path])) or "`нет`"
        incoming = ", ".join(f"`{item}`" for item in sorted(incoming_edges[document.relative_path])) or "`нет`"
        lines.append(f"- `{document.relative_path}`")
        lines.append(f"  outgoing: {outgoing}")
        lines.append(f"  incoming: {incoming}")

    lines.extend(["", "## Document Metadata", ""])
    for document in sorted(documents, key=lambda item: item.relative_path):
        lines.append(
            f"- `{document.relative_path}`: type=`{document.document_type}`, confidence=`{document.confidence}`, domain=`{document.domain or 'n/a'}`"
        )
    lines.append("")
    return "\n".join(lines)


def _build_metadata_tag_line(document: KnowledgeDocument) -> str:
    tags: list[str] = []
    if document.domain:
        tags.append(f"domain: `{document.domain}`")
    if document.confidence:
        tags.append(f"confidence: `{document.confidence}`")
    if document.repositories:
        tags.append("repos: " + ", ".join(f"`{repository}`" for repository in document.repositories))
    if not tags:
        return ""
    return " — " + "; ".join(tags)


def _lint_feature_index(features_index_path: Path, feature_files: list[Path]) -> list[str]:
    issues: list[str] = []
    if features_index_path.exists():
        indexed_feature_links = _extract_feature_links(features_index_path.read_text(encoding="utf-8"))
        feature_names = {feature_file.name for feature_file in feature_files}
        missing_files = sorted(link for link in indexed_feature_links if link not in feature_names)
        for missing_file in missing_files:
            issues.append(f"ERROR: features-index.md ссылается на отсутствующий файл features/{missing_file}")
        unindexed_files = sorted(
            feature_name for feature_name in feature_names if feature_name not in indexed_feature_links
        )
        for unindexed_file in unindexed_files:
            issues.append(f"WARN: файл features/{unindexed_file} не упомянут в features-index.md")
    elif feature_files:
        issues.append("ERROR: есть feature-файлы, но отсутствует features-index.md")
    return issues


def _lint_traceability(artifact_path: Path, arch_repo_path: Path) -> list[str]:
    content = artifact_path.read_text(encoding="utf-8")
    frontmatter, _body = _parse_frontmatter(content)
    has_sources = bool(frontmatter.get("sources")) if frontmatter else False
    if has_sources or _has_traceability_markers(content):
        return []
    return [(f"ERROR: в {artifact_path.relative_to(arch_repo_path)} нет явной трассировки источников")]


def _lint_open_questions(open_questions_path: Path, arch_repo_path: Path) -> list[str]:
    return _lint_open_questions_with_graph(
        open_questions_path=open_questions_path,
        arch_repo_path=arch_repo_path,
        document_by_path={},
    )


def _lint_open_questions_with_graph(
    open_questions_path: Path,
    arch_repo_path: Path,
    document_by_path: dict[str, KnowledgeDocument],
) -> list[str]:
    if not open_questions_path.exists():
        return []

    issues: list[str] = []
    table_rows = _parse_markdown_table(open_questions_path.read_text(encoding="utf-8"))
    for row in table_rows:
        status_value = row.get("Статус", "").strip().lower()
        question_id = row.get("ID", "<без-id>").strip()
        target_artifact_refs = _extract_open_question_target_artifacts(row)
        follow_up_id = row.get("Follow-up ID", "").strip() or row.get("Follow-upID", "").strip()
        knowledge_graph_updated = row.get("Обновление knowledge graph", "").strip().lower()

        if (
            status_value == "open"
            and row.get("Нужен ответ пользователя", "").strip().lower() == "yes"
            and not follow_up_id
        ):
            issues.append(f"WARN: open-вопрос {question_id} с требуемым ответом пользователя не содержит Follow-up ID")

        if status_value != "resolved":
            continue

        closure_text = row.get("Как закрыт или что нужно для закрытия", "").strip()
        context_text = row.get("Контекст", "").strip()
        if not closure_text:
            issues.append(f"ERROR: resolved-вопрос {question_id} в open-questions.md не содержит описания закрытия")
            continue

        artifact_refs = target_artifact_refs or _extract_artifact_references(f"{context_text} {closure_text}")
        if not artifact_refs:
            issues.append(f"ERROR: resolved-вопрос {question_id} в open-questions.md не ссылается на целевой артефакт")
            continue

        for artifact_ref in artifact_refs:
            artifact_path = arch_repo_path / artifact_ref
            if not artifact_path.exists():
                issues.append(
                    f"ERROR: resolved-вопрос {question_id} ссылается на отсутствующий артефакт {artifact_ref}"
                )
                continue
            if knowledge_graph_updated == "yes":
                document = document_by_path.get(artifact_ref)
                artifact_content = artifact_path.read_text(encoding="utf-8")
                if question_id not in artifact_content and not _document_contains_question_reference(
                    document, question_id
                ):
                    issues.append(f"ERROR: resolved-вопрос {question_id} не отражён в артефакте {artifact_ref}")
    return issues


def graph_blocking_issues(compile_result: CompileResult) -> list[str]:
    """Blocking (``ERROR:``) issues derivable from the compiled graph alone.

    Reused by both `build_navigation_index` (step 11, checked right after compiling, before the
    graph has been written to disk) and `run_knowledge_lint` (step 12, via `_lint_graph_awareness`)
    so the two steps never define the same quality-gate thresholds twice.
    """
    issues: list[str] = []
    issues.extend(_lint_missing_related_references(compile_result.unresolved_references))
    issues.extend(_lint_compile_quality_gates(compile_result))
    return issues


def _lint_graph_awareness(
    arch_repo_path: Path,
    layout_paths: LayoutPaths,
    compile_result: CompileResult,
    documents: list[KnowledgeDocument],
) -> list[str]:
    issues: list[str] = []
    issues.extend(graph_blocking_issues(compile_result))
    issues.extend(_lint_orphan_pages(compile_result.weakly_linked_pages))
    issues.extend(_lint_stale_low_confidence_pages(documents))
    issues.extend(_lint_repository_domain_conflicts(documents))
    issues.extend(
        _lint_wiki_compile_drift(
            arch_repo_path=arch_repo_path,
            layout_paths=layout_paths,
            compile_result=compile_result,
        )
    )
    return issues


def _lint_missing_related_references(unresolved_references: tuple[str, ...]) -> list[str]:
    issues: list[str] = []
    for item in unresolved_references:
        issues.append(f"ERROR: missing related reference {item}")
    return issues


def _lint_orphan_pages(weakly_linked_pages: tuple[str, ...]) -> list[str]:
    issues: list[str] = []
    for item in weakly_linked_pages:
        issues.append(f"WARN: orphan page без входящих и исходящих ссылок: {item}")
    return issues


def _lint_stale_low_confidence_pages(documents: list[KnowledgeDocument]) -> list[str]:
    issues: list[str] = []
    today = dt.datetime.now(dt.UTC).date()
    for document in documents:
        if document.confidence != "low":
            continue
        updated_value = document.frontmatter.get("updated")
        if not isinstance(updated_value, str) or not DATE_PATTERN.match(updated_value):
            continue
        updated_date = dt.date.fromisoformat(updated_value)
        age_days = (today - updated_date).days
        if age_days >= 90:
            issues.append(
                f"DEBT: low-confidence страница давно не обновлялась: {document.relative_path} (age_days={age_days})"
            )
    return issues


def _lint_repository_domain_conflicts(documents: list[KnowledgeDocument]) -> list[str]:
    issues: list[str] = []
    repository_domains: dict[str, set[str]] = {}
    for document in documents:
        if not document.domain:
            continue
        for repository_name in document.repositories:
            repository_domains.setdefault(repository_name, set()).add(document.domain)

    for repository_name, domains in sorted(repository_domains.items()):
        if len(domains) <= 1:
            continue
        issues.append(
            "DEBT: обнаружено несколько domain-меток для одного репозитория "
            f"{repository_name}: {', '.join(sorted(domains))}"
        )
    return issues


def _lint_wiki_compile_drift(
    arch_repo_path: Path,
    layout_paths: LayoutPaths,
    compile_result: CompileResult,
) -> list[str]:
    issues: list[str] = []
    if not layout_paths.compile_report_path.exists():
        return issues

    if layout_paths.index_path.exists():
        current_index = layout_paths.index_path.read_text(encoding="utf-8").rstrip()
        expected_index = compile_result.index_content.rstrip()
        if current_index != expected_index:
            issues.append("ERROR: wiki/index.md не синхронизирован с compile output")

    if layout_paths.compile_report_path.exists():
        current_report = layout_paths.compile_report_path.read_text(encoding="utf-8").rstrip()
        expected_report = compile_result.compile_report_content.rstrip()
        if current_report != expected_report:
            issues.append("ERROR: wiki/maps/compile-report.md не синхронизирован с compile output")
    return issues


def _lint_compile_output_sections(
    artifact_path: Path,
    arch_repo_path: Path,
    required_sections: tuple[str, ...],
) -> list[str]:
    if not artifact_path.exists():
        return []

    content = artifact_path.read_text(encoding="utf-8")
    issues: list[str] = []
    for section in required_sections:
        if section not in content:
            issues.append(
                f"ERROR: {artifact_path.relative_to(arch_repo_path)} не содержит обязательную секцию `{section}`"
            )
    return issues


def _lint_compile_quality_gates(compile_result: CompileResult) -> list[str]:
    issues: list[str] = []
    frontmatter_coverage = _ratio(
        compile_result.documents_with_frontmatter,
        compile_result.documents_requiring_metadata,
    )
    if compile_result.documents_requiring_metadata and frontmatter_coverage < MIN_FRONTMATTER_COVERAGE:
        issues.append(
            "ERROR: compile quality gate не пройден: frontmatter coverage "
            f"{compile_result.documents_with_frontmatter}/{compile_result.documents_requiring_metadata} "
            f"({_format_ratio(compile_result.documents_with_frontmatter, compile_result.documents_requiring_metadata)}) "
            f"ниже порога {MIN_FRONTMATTER_COVERAGE:.0%}"
        )

    related_coverage = _ratio(
        compile_result.documents_with_related,
        compile_result.documents_with_frontmatter,
    )
    if compile_result.documents_with_frontmatter and related_coverage < MIN_RELATED_COVERAGE:
        issues.append(
            "ERROR: compile quality gate не пройден: related coverage "
            f"{compile_result.documents_with_related}/{compile_result.documents_with_frontmatter} "
            f"({_format_ratio(compile_result.documents_with_related, compile_result.documents_with_frontmatter)}) "
            f"ниже порога {MIN_RELATED_COVERAGE:.0%}"
        )
    return issues


def _lint_knowledge_log(log_path: Path, arch_repo_path: Path) -> list[str]:
    if not log_path.exists():
        return [f"WARN: отсутствует {log_path.relative_to(arch_repo_path)}"]

    issues: list[str] = []
    log_content = log_path.read_text(encoding="utf-8").strip()
    if not log_content:
        return [f"ERROR: {log_path.relative_to(arch_repo_path)} пуст"]

    entry_matches = list(re.finditer(rf"(?m)^({re.escape(KNOWLEDGE_LOG_ENTRY_PREFIX)} .+)$", log_content))
    if not entry_matches:
        return [
            f"WARN: {log_path.relative_to(arch_repo_path)} не содержит ни одной записи формата '{KNOWLEDGE_LOG_ENTRY_PREFIX} YYYY-MM-DD'"
        ]

    for index, match in enumerate(entry_matches):
        entry_header = match.group(1)
        section_start = match.end()
        section_end = entry_matches[index + 1].start() if index + 1 < len(entry_matches) else len(log_content)
        section_content = log_content[section_start:section_end].strip()
        if not section_content:
            issues.append(f"ERROR: {entry_header} не содержит содержимого")
            continue
        if "- " not in section_content:
            issues.append(f"WARN: {entry_header} не содержит ни одного bullet-пункта")
    return issues


def _lint_unprefixed_paths(markdown_path: Path, arch_repo_path: Path) -> list[str]:
    content = markdown_path.read_text(encoding="utf-8")
    issues: list[str] = []
    for suspicious_path in _find_unprefixed_repo_paths(content):
        issues.append(
            f"WARN: {markdown_path.relative_to(arch_repo_path)} содержит путь без явного префикса репозитория: {suspicious_path}"
        )
    return issues


def _lint_markdown_links(path: Path, root: Path) -> list[str]:
    content = path.read_text(encoding="utf-8")
    issues: list[str] = []
    for match in MARKDOWN_LINK_PATTERN.finditer(content):
        target = match.group(1).strip()
        if target.startswith(("http://", "https://", "#")):
            continue
        normalized = (path.parent / target).resolve()
        if not normalized.exists():
            issues.append(f"ERROR: {path.relative_to(root)} содержит битую ссылку на {target}")
    return issues


def _lint_frontmatter(markdown_path: Path, arch_repo_path: Path) -> list[str]:
    content = markdown_path.read_text(encoding="utf-8")
    frontmatter, _body = _parse_frontmatter(content)
    if not frontmatter:
        return []

    issues: list[str] = []
    path_label = markdown_path.relative_to(arch_repo_path)
    for key in frontmatter:
        if key not in FRONTMATTER_FIELDS:
            issues.append(f"WARN: {path_label} содержит неизвестное поле frontmatter `{key}`")

    for key in ("sources", "related", "repositories"):
        value = frontmatter.get(key)
        if value is None:
            continue
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            issues.append(f"ERROR: {path_label} содержит некорректное поле frontmatter `{key}`; ожидается список строк")

    for key in ("title", "type", "confidence", "domain"):
        value = frontmatter.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            issues.append(f"ERROR: {path_label} содержит некорректное поле frontmatter `{key}`; ожидается строка")

    confidence_value = frontmatter.get("confidence")
    if isinstance(confidence_value, str) and confidence_value not in VALID_CONFIDENCE:
        issues.append(f"ERROR: {path_label} содержит неизвестное значение confidence `{confidence_value}`")

    for key in ("created", "updated"):
        value = frontmatter.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not DATE_PATTERN.match(value):
            issues.append(f"ERROR: {path_label} содержит некорректное поле frontmatter `{key}`; ожидается YYYY-MM-DD")

    return issues


def _collect_knowledge_documents(arch_repo_path: Path, layout_paths: LayoutPaths) -> list[KnowledgeDocument]:
    documents: list[KnowledgeDocument] = []
    for markdown_path in _iter_markdown_documents_for_compile(arch_repo_path, layout_paths):
        content = markdown_path.read_text(encoding="utf-8")
        frontmatter, body = _parse_frontmatter(content)
        document_type = _infer_document_type(markdown_path, arch_repo_path, frontmatter)
        title = _extract_document_title(markdown_path, frontmatter, body)
        related = _normalize_string_list(frontmatter.get("related")) if frontmatter else []
        outgoing = _extract_outgoing_references(markdown_path, arch_repo_path, body, related)
        repositories = _normalize_string_list(frontmatter.get("repositories")) if frontmatter else []
        confidence = str(frontmatter.get("confidence", "unknown")) if frontmatter else "unknown"
        domain = str(frontmatter.get("domain", "")) if frontmatter else ""
        documents.append(
            KnowledgeDocument(
                relative_path=markdown_path.relative_to(arch_repo_path).as_posix(),
                title=title,
                document_type=document_type,
                frontmatter=frontmatter,
                body=body,
                outgoing_references=tuple(outgoing),
                metadata_related=tuple(related),
                repositories=tuple(repositories),
                confidence=confidence,
                domain=domain,
            )
        )
    return documents


def _extract_document_title(markdown_path: Path, frontmatter: dict[str, object], body: str) -> str:
    if frontmatter.get("title"):
        return str(frontmatter["title"])

    for line in body.splitlines():
        stripped_line = line.strip()
        if stripped_line.startswith("# "):
            return stripped_line[2:].strip()
    return markdown_path.stem


def _extract_outgoing_references(
    markdown_path: Path,
    arch_repo_path: Path,
    body: str,
    related: list[str],
) -> list[str]:
    references: list[str] = []
    for match in MARKDOWN_LINK_PATTERN.finditer(body):
        target = match.group(1).strip()
        if target.startswith(("http://", "https://", "#")):
            continue
        normalized = _normalize_reference(markdown_path, arch_repo_path, target)
        references.append(normalized)
    for match in WIKILINK_PATTERN.finditer(body):
        references.append(match.group(1).strip())
    references.extend(related)
    deduped_references = []
    seen_references: set[str] = set()
    for reference in references:
        if reference in seen_references:
            continue
        deduped_references.append(reference)
        seen_references.add(reference)
    return deduped_references


def _resolve_document_reference(
    source_path: str,
    reference: str,
    arch_repo_path: Path,
    document_by_path: dict[str, KnowledgeDocument],
    document_by_title: dict[str, KnowledgeDocument],
) -> str | None:
    if reference in document_by_path:
        return reference
    if reference in document_by_title:
        return document_by_title[reference].relative_path

    candidate_path = arch_repo_path / reference
    if candidate_path.exists():
        return candidate_path.relative_to(arch_repo_path).as_posix()

    source_parent = Path(source_path).parent
    normalized_candidate = (source_parent / reference).as_posix()
    if normalized_candidate in document_by_path:
        return normalized_candidate

    title_candidate = reference.strip()
    if title_candidate in document_by_title:
        return document_by_title[title_candidate].relative_path
    return None


def _iter_knowledge_artifacts(*directories: Path) -> list[Path]:
    result: list[Path] = []
    for directory in directories:
        if directory.exists():
            result.extend(sorted(path for path in directory.iterdir() if path.is_file()))
    return result


def _iter_markdown_documents_for_lint(arch_repo_path: Path, layout_paths: LayoutPaths) -> list[Path]:
    documents = [
        path for path in arch_repo_path.rglob("*.md") if ".git" not in path.parts and path.name != "compile-report.md"
    ]
    return sorted(documents)


def _iter_markdown_documents_for_compile(arch_repo_path: Path, layout_paths: LayoutPaths) -> list[Path]:
    excluded_paths = {
        layout_paths.index_path.resolve(),
        layout_paths.log_path.resolve(),
    }

    documents = [
        path
        for path in arch_repo_path.rglob("*.md")
        if ".git" not in path.parts and path.resolve() not in excluded_paths and path.name != "compile-report.md"
    ]
    return sorted(documents)


def _parse_frontmatter(content: str) -> tuple[dict[str, object], str]:
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        return {}, content

    frontmatter_body = match.group("body")
    parsed_frontmatter = _parse_simple_yaml_mapping(frontmatter_body)
    body = content[match.end() :]
    return parsed_frontmatter, body


def _parse_simple_yaml_mapping(content: str) -> dict[str, object]:
    result: dict[str, object] = {}
    current_key = ""
    list_values: list[str] = []

    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        stripped_line = line.strip()
        if stripped_line.startswith("#"):
            continue

        if stripped_line.startswith("- "):
            if not current_key:
                continue
            list_values.append(_strip_wrapping_quotes(stripped_line[2:].strip()))
            result[current_key] = list_values.copy()
            continue

        if ":" not in line:
            continue

        key, raw_value = line.split(":", 1)
        current_key = key.strip()
        list_values = []
        normalized_value = raw_value.strip()
        if not normalized_value:
            result[current_key] = []
            continue
        result[current_key] = _strip_wrapping_quotes(normalized_value)
    return result


def _strip_wrapping_quotes(value: str) -> str:
    normalized = value.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
        return normalized[1:-1]
    return normalized


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _infer_document_type(
    markdown_path: Path,
    arch_repo_path: Path,
    frontmatter: dict[str, object],
) -> str:
    if isinstance(frontmatter.get("type"), str):
        return str(frontmatter["type"])

    relative_path = markdown_path.relative_to(arch_repo_path).as_posix()
    if relative_path.startswith("features/"):
        return "feature"
    if relative_path.startswith("architecture/integrations/"):
        return "integration"
    if relative_path == "architecture/hld.md":
        return "hld"
    if relative_path == "architecture/security.md":
        return "security"
    if relative_path == "architecture/risks.md":
        return "risk"
    if relative_path == "architecture/requirements.md":
        return "requirements"
    if relative_path == "glossary.md":
        return "glossary"
    if relative_path == "open-questions.md":
        return "open-question-register"
    if relative_path.startswith("wiki/concepts/"):
        return "concept"
    if relative_path.startswith("wiki/summaries/"):
        return "summary"
    return "document"


def _extract_feature_links(content: str) -> set[str]:
    links = set()
    for match in re.finditer(r"\]\((?:\./)?features/([^)]+\.md)\)", content):
        links.add(match.group(1))
    return links


def _has_traceability_markers(content: str) -> bool:
    return any(marker in content for marker in TRACEABILITY_MARKERS)


def _find_unprefixed_repo_paths(content: str) -> set[str]:
    results: set[str] = set()
    for match in CODE_PATH_PATTERN.finditer(content):
        candidate = match.group(1)
        first_segment = candidate.split("/", 1)[0]
        if first_segment not in CODE_PATH_ROOTS:
            continue
        results.add(candidate)
    return results


def _parse_markdown_table(content: str) -> list[dict[str, str]]:
    stripped_lines = [line.strip() for line in content.splitlines() if line.strip()]
    header_line = next((line for line in stripped_lines if line.startswith("|")), "")
    if not header_line:
        return []

    header_index = stripped_lines.index(header_line)
    if header_index + 1 >= len(stripped_lines):
        return []

    separator_line = stripped_lines[header_index + 1]
    if not separator_line.startswith("|"):
        return []

    headers = _split_markdown_row(header_line)
    rows: list[dict[str, str]] = []
    for line in stripped_lines[header_index + 2 :]:
        if not line.startswith("|"):
            continue
        values = _split_markdown_row(line)
        if len(values) != len(headers):
            continue
        rows.append(dict(zip(headers, values, strict=True)))
    return rows


def _split_markdown_row(line: str) -> list[str]:
    return [_normalize_markdown_cell(part) for part in line.strip().strip("|").split("|")]


def _extract_artifact_references(text: str) -> set[str]:
    references: set[str] = set()
    for match in ARTIFACT_REFERENCE_PATTERN.finditer(text):
        normalized = match.group(1).removeprefix("./").removeprefix("../")
        references.add(normalized)
    return references


def _normalize_markdown_cell(value: str) -> str:
    normalized = value.strip()
    if normalized.startswith("`") and normalized.endswith("`") and len(normalized) >= 2:
        return normalized[1:-1].strip()
    return normalized


def _extract_open_question_target_artifacts(row: dict[str, str]) -> set[str]:
    target_cells = [
        row.get("Целевые артефакты", "").strip(),
        row.get("Target Artifacts", "").strip(),
    ]
    references: set[str] = set()
    for target_cell in target_cells:
        if not target_cell:
            continue
        references.update(_extract_artifact_references(target_cell))
        for raw_part in target_cell.split(","):
            normalized_part = raw_part.strip().removeprefix("./")
            if normalized_part.endswith((".md", ".yml", ".yaml")):
                references.add(normalized_part)
    return references


def _document_contains_question_reference(
    document: KnowledgeDocument | None,
    question_id: str,
) -> bool:
    if document is None:
        return False
    related_values = set(document.metadata_related)
    return question_id in related_values or f"question:{question_id}" in related_values


def _requires_graph_metadata(document: KnowledgeDocument) -> bool:
    relative_path = document.relative_path
    return (
        relative_path.startswith("features/")
        or relative_path.startswith("architecture/integrations/")
        or relative_path == "architecture/hld.md"
        or relative_path == "architecture/requirements.md"
        or relative_path == "architecture/security.md"
        or relative_path == "architecture/risks.md"
        or relative_path.startswith("wiki/concepts/")
        or relative_path.startswith("wiki/summaries/")
    )


def _build_quality_gate_lines(
    documents_requiring_metadata: int,
    documents_with_frontmatter: int,
    documents_with_related: int,
) -> list[str]:
    frontmatter_ratio = _ratio(documents_with_frontmatter, documents_requiring_metadata)
    related_ratio = _ratio(documents_with_related, documents_with_frontmatter)
    return [
        (
            "- Required sections gate: `pass` "
            "- `wiki/index.md` и `wiki/maps/compile-report.md` должны содержать обязательные секции."
        ),
        (
            f"- Frontmatter coverage gate: `{_gate_status(frontmatter_ratio, MIN_FRONTMATTER_COVERAGE, documents_requiring_metadata > 0)}` "
            f"- `{documents_with_frontmatter}/{documents_requiring_metadata}` "
            f"({_format_ratio(documents_with_frontmatter, documents_requiring_metadata)}); порог `>={MIN_FRONTMATTER_COVERAGE:.0%}`."
        ),
        (
            f"- Related coverage gate: `{_gate_status(related_ratio, MIN_RELATED_COVERAGE, documents_with_frontmatter > 0)}` "
            f"- `{documents_with_related}/{documents_with_frontmatter}` "
            f"({_format_ratio(documents_with_related, documents_with_frontmatter)}); порог `>={MIN_RELATED_COVERAGE:.0%}`."
        ),
    ]


def _gate_status(ratio: float, threshold: float, is_applicable: bool) -> str:
    if not is_applicable:
        return "n/a"
    return "pass" if ratio >= threshold else "fail"


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _format_ratio(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "n/a"
    return f"{(numerator / denominator):.0%}"


def _link_or_missing(
    layout_paths: LayoutPaths,
    arch_repo_path: Path,
    relative_path: str,
    label: str,
    description: str,
) -> str:
    if (arch_repo_path / relative_path).exists():
        target_link = _render_relative_link(layout_paths, arch_repo_path, relative_path)
        return f"- [{label}]({target_link}) — {description}."
    return f"- {label}: `не найдено` — {description}."


def _render_relative_link(layout_paths: LayoutPaths, arch_repo_path: Path, target_relative_path: str) -> str:
    target_absolute_path = arch_repo_path / target_relative_path
    relative_link = os.path.relpath(target_absolute_path, layout_paths.navigation_root)
    return Path(relative_link).as_posix()


def _normalize_reference(markdown_path: Path, arch_repo_path: Path, target: str) -> str:
    normalized_path = (markdown_path.parent / target).resolve()
    try:
        return normalized_path.relative_to(arch_repo_path.resolve()).as_posix()
    except ValueError:
        return target
