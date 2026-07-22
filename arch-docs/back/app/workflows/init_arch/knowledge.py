from __future__ import annotations

import datetime as dt
import difflib
import pathlib
from typing import Final

import pydantic
import yaml

from app.services.text_sanitization import truncate_text
from app.settings import get_gateway_settings
from app.workflows.init_arch.audit import WorkflowAuditService, get_workflow_audit_service
from app.workflows.init_arch.domain import (
    ArtifactRecord,
    AuditActor,
    EventType,
    StepId,
    WorkflowEventRecord,
    WorkflowSessionRecord,
    register_artifact,
)
from app.workflows.init_arch.knowledge_runtime import (
    build_compile_report_stub,
    build_knowledge_log_stub,
    build_navigation_index,
    compile_knowledge_graph,
    graph_blocking_issues,
    run_knowledge_lint,
)
from app.workflows.shared_assets import WorkflowAssetLoader, get_workflow_asset_loader

_ARTIFACT_SNAPSHOT_DIRNAME: Final[str] = ".artifact-snapshots"

_ROOT_ARTIFACT_PATHS: Final[tuple[str, ...]] = (
    "features-index.md",
    "glossary.md",
    "open-questions.md",
    "wiki/index.md",
    "wiki/log.md",
    "wiki/maps/compile-report.md",
)
_DIRECTORY_PATHS: Final[tuple[str, ...]] = (
    "features",
    "architecture",
    "architecture/integrations",
    "architecture/contracts",
    "architecture/storage",
    "architecture/structure",
    "release-notes",
    "wiki",
    "wiki/maps",
)
_ARTIFACT_KINDS: Final[dict[str, str]] = {
    "features-index.md": "features_index",
    "glossary.md": "glossary",
    "open-questions.md": "open_questions",
    "wiki/index.md": "navigation_index",
    "wiki/log.md": "knowledge_log",
    "wiki/maps/compile-report.md": "compile_report",
    "architecture/domain-map.yaml": "domain_map",
}
_ARCHITECTURE_TEMPLATE_ASSETS: Final[dict[str, str]] = {
    "architecture/hld.md": "architecture/hld-template.md",
    "architecture/security.md": "architecture/security-template.md",
    "architecture/risks.md": "architecture/risks-template.md",
    "architecture/tech-stack.md": "architecture/tech-stack-template.md",
    "architecture/roles-and-permissions.md": "architecture/roles-and-permissions-template.md",
    "architecture/domain-entities.md": "architecture/domain-entities-template.md",
    "architecture/integrations-overview.md": "architecture/integrations-overview-template.md",
    "architecture/constraints.md": "architecture/constraints-template.md",
    "architecture/requirements.md": "architecture/requirements-template.md",
    "architecture/landscape.yaml": "architecture/landscape-template.yaml",
}


class KnowledgeArtifactResult(pydantic.BaseModel):
    session: WorkflowSessionRecord
    summary: str = ""
    written_artifacts: list[str] = pydantic.Field(default_factory=list)
    lint_issues: list[str] = pydantic.Field(default_factory=list)


class KnowledgeArtifactService:
    def __init__(
        self,
        audit_service: WorkflowAuditService | None = None,
        asset_loader: WorkflowAssetLoader | None = None,
    ) -> None:
        self._audit_service = audit_service or get_workflow_audit_service()
        self._asset_loader = asset_loader or get_workflow_asset_loader()

    async def bootstrap_arch_repo(
        self,
        session: WorkflowSessionRecord,
        *,
        arch_repo_dir: str,
    ) -> KnowledgeArtifactResult:
        arch_repo_path = pathlib.Path(arch_repo_dir)
        for relative_path in _DIRECTORY_PATHS:
            (arch_repo_path / relative_path).mkdir(parents=True, exist_ok=True)

        written_artifacts: list[str] = []
        for relative_path, content in self._bootstrap_contents(session).items():
            target_path = arch_repo_path / relative_path
            if target_path.exists():
                continue
            target_path.write_text(content, encoding="utf-8")
            written_artifacts.append(relative_path)

        updated_session = self._register_artifacts(
            session,
            written_artifacts=written_artifacts,
            step_id=StepId.REFINE_FEATURES,
            source_refs=["service:knowledge_bootstrap"],
            arch_repo_dir=arch_repo_dir,
        )
        return KnowledgeArtifactResult(
            session=updated_session,
            summary=f"Bootstrapped knowledge layout with {len(written_artifacts)} artifacts",
            written_artifacts=written_artifacts,
        )

    async def collect_worker_artifacts(
        self,
        session: WorkflowSessionRecord,
        *,
        step_id: StepId,
        created_artifacts: list[str],
        arch_repo_dir: str,
    ) -> KnowledgeArtifactResult:
        normalized_paths = sorted({path for path in created_artifacts if path})
        updated_session = self._register_artifacts(
            session,
            written_artifacts=normalized_paths,
            step_id=step_id,
            source_refs=["llm_worker"],
            arch_repo_dir=arch_repo_dir,
        )
        return KnowledgeArtifactResult(
            session=updated_session,
            summary=f"Registered {len(normalized_paths)} worker artifacts",
            written_artifacts=normalized_paths,
        )

    async def compile_navigation(
        self,
        session: WorkflowSessionRecord,
        *,
        arch_repo_dir: str,
    ) -> KnowledgeArtifactResult:
        arch_repo_path = pathlib.Path(arch_repo_dir)
        compile_result = compile_knowledge_graph(arch_repo_path)
        compile_result.layout_paths.index_path.parent.mkdir(parents=True, exist_ok=True)
        compile_result.layout_paths.compile_report_path.parent.mkdir(parents=True, exist_ok=True)
        compile_result.layout_paths.index_path.write_text(compile_result.index_content, encoding="utf-8")
        compile_result.layout_paths.compile_report_path.write_text(
            compile_result.compile_report_content,
            encoding="utf-8",
        )

        written_artifacts = ["wiki/index.md", "wiki/maps/compile-report.md"]
        updated_session = self._register_artifacts(
            session,
            written_artifacts=written_artifacts,
            step_id=StepId.BUILD_NAVIGATION_INDEX,
            source_refs=["service:knowledge_compile"],
            arch_repo_dir=arch_repo_dir,
        )
        return KnowledgeArtifactResult(
            session=updated_session,
            summary=(
                "Compiled knowledge graph: "
                f"documents={compile_result.total_documents}, "
                f"unresolved={len(compile_result.unresolved_references)}, "
                f"weak_links={len(compile_result.weakly_linked_pages)}"
            ),
            written_artifacts=written_artifacts,
            lint_issues=graph_blocking_issues(compile_result),
        )

    async def write_domain_map(
        self,
        session: WorkflowSessionRecord,
        *,
        arch_repo_dir: str,
    ) -> KnowledgeArtifactResult:
        arch_repo_path = pathlib.Path(arch_repo_dir)
        domain_map_path = arch_repo_path / "architecture" / "domain-map.yaml"
        domain_map_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            repository.repository_name: {
                "volume_class": repository.volume_class.value if repository.volume_class else None,
                "strategy": repository.domain_strategy.value if repository.domain_strategy else None,
                "domains": [
                    {
                        "domain_id": domain.domain_id,
                        "name": domain.name,
                        "paths": domain.paths,
                        "signal": domain.signal,
                        "subdomains": domain.subdomains,
                    }
                    for domain in repository.domains
                ],
            }
            for repository in session.repositories
        }
        domain_map_path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")

        written_artifacts = ["architecture/domain-map.yaml"]
        updated_session = self._register_artifacts(
            session,
            written_artifacts=written_artifacts,
            step_id=StepId.ASSESS_SCOPE_AND_DOMAINS,
            source_refs=["service:domain_assessment"],
            arch_repo_dir=arch_repo_dir,
        )
        return KnowledgeArtifactResult(
            session=updated_session,
            summary=f"Wrote domain map for {len(payload)} repositories",
            written_artifacts=written_artifacts,
        )

    async def lint_knowledge(
        self,
        session: WorkflowSessionRecord,
        *,
        arch_repo_dir: str,
    ) -> KnowledgeArtifactResult:
        issues = run_knowledge_lint(pathlib.Path(arch_repo_dir))
        updated_session = self._register_artifacts(
            session,
            written_artifacts=[],
            step_id=StepId.RUN_KNOWLEDGE_LINT,
            source_refs=["service:knowledge_lint"],
            arch_repo_dir=arch_repo_dir,
        )
        return KnowledgeArtifactResult(
            session=updated_session,
            summary=f"Knowledge lint completed with {len(issues)} issues",
            lint_issues=issues,
        )

    async def sync_open_questions(
        self,
        session: WorkflowSessionRecord,
        *,
        arch_repo_dir: str,
    ) -> KnowledgeArtifactResult:
        arch_repo_path = pathlib.Path(arch_repo_dir)
        open_questions_path = arch_repo_path / "open-questions.md"
        open_questions_path.parent.mkdir(parents=True, exist_ok=True)
        open_questions_path.write_text(self._render_open_questions_markdown(session), encoding="utf-8")

        updated_session = self._register_artifacts(
            session,
            written_artifacts=["open-questions.md"],
            step_id=session.current_step,
            source_refs=["service:open_questions_sync"],
            arch_repo_dir=arch_repo_dir,
        )
        return KnowledgeArtifactResult(
            session=updated_session,
            summary=f"Synchronized {len(session.open_questions)} open questions",
            written_artifacts=["open-questions.md"],
        )

    def _bootstrap_contents(self, session: WorkflowSessionRecord) -> dict[str, str]:
        repositories = [
            {"name": repository.repository_name, "analysis_status": repository.analysis_status}
            for repository in session.repositories
        ]
        contents = {
            "features-index.md": self._load_asset("features-index-template.md"),
            "glossary.md": self._load_asset("architecture/glossary-template.md"),
            "open-questions.md": self._load_asset("open-questions-template.md"),
            "wiki/index.md": build_navigation_index(
                pathlib.Path(),
                session.product_name,
                repositories,
            ).replace("](./", "](../"),
            "wiki/log.md": build_knowledge_log_stub(),
            "wiki/maps/compile-report.md": build_compile_report_stub(),
        }
        for target_path, template_path in _ARCHITECTURE_TEMPLATE_ASSETS.items():
            contents[target_path] = self._load_asset(template_path)
        return contents

    def _load_asset(self, relative_path: str) -> str:
        return self._asset_loader.read_text("knowledge_base", relative_path)

    def _render_open_questions_markdown(self, session: WorkflowSessionRecord) -> str:
        lines = [
            "# Открытые Вопросы",
            "",
            (
                "| ID | Follow-up ID | Вопрос | Контекст | Связанный репозиторий | "
                "Целевые артефакты | Статус | Нужен ответ пользователя | Что уже известно | "
                "Обновление knowledge graph | Как закрыт или что нужно для закрытия |"
            ),
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for question in session.open_questions:
            related_repositories = ", ".join(question.related_repositories)
            target_artifacts = ", ".join(question.target_artifacts)
            status = "open" if question.status == "open" else "resolved"
            closure = question.answer_text if question.status != "open" else ""
            knowledge_graph_update = "yes" if question.target_artifacts else "no"
            lines.append(
                "| {question_id} | {follow_up_id} | {question_text} | {context} | {repositories} | "
                "{artifacts} | {status} | yes | {known} | {knowledge_graph_update} | {closure} |".format(
                    question_id=question.question_id,
                    follow_up_id=question.question_id,
                    question_text=self._escape_table_cell(question.question_text),
                    context=self._escape_table_cell("workflow interview loop"),
                    repositories=self._escape_table_cell(related_repositories),
                    artifacts=self._escape_table_cell(target_artifacts),
                    status=status,
                    known="",
                    knowledge_graph_update=knowledge_graph_update,
                    closure=self._escape_table_cell(closure),
                )
            )
        return "\n".join(lines) + "\n"

    def _register_artifacts(
        self,
        session: WorkflowSessionRecord,
        *,
        written_artifacts: list[str],
        step_id: StepId,
        source_refs: list[str],
        arch_repo_dir: str,
    ) -> WorkflowSessionRecord:
        arch_repo_path = pathlib.Path(arch_repo_dir)
        snapshot_dir = arch_repo_path.parent / _ARTIFACT_SNAPSHOT_DIRNAME
        updated_session = session
        today = dt.datetime.now(dt.UTC).date().isoformat()
        for artifact_path in written_artifacts:
            artifact = ArtifactRecord(
                artifact_path=artifact_path,
                artifact_kind=_ARTIFACT_KINDS.get(artifact_path, self._artifact_kind_from_path(artifact_path)),
                source_refs=[*source_refs, today],
                last_updated_step=step_id,
                last_updated_window_index=session.historical_analysis.window_index,
            )
            updated_session = register_artifact(updated_session, artifact=artifact)
            diff_text = self._diff_against_snapshot(arch_repo_path, snapshot_dir, artifact_path)
            self._audit_service.record(
                WorkflowEventRecord(
                    event_type=EventType.ARTIFACT_WRITTEN,
                    actor=AuditActor.SERVICE,
                    session_id=updated_session.session_id,
                    step_id=step_id,
                    payload={
                        "artifact_path": artifact_path,
                        "artifact_kind": artifact.artifact_kind,
                        "diff": diff_text,
                    },
                )
            )
        return updated_session

    @staticmethod
    def _diff_against_snapshot(arch_repo_path: pathlib.Path, snapshot_dir: pathlib.Path, artifact_path: str) -> str:
        current_path = arch_repo_path / artifact_path
        current_content = current_path.read_text(encoding="utf-8") if current_path.exists() else ""

        snapshot_path = snapshot_dir / artifact_path
        previous_content = snapshot_path.read_text(encoding="utf-8") if snapshot_path.exists() else ""

        diff_text = "".join(
            difflib.unified_diff(
                previous_content.splitlines(keepends=True),
                current_content.splitlines(keepends=True),
                fromfile=f"a/{artifact_path}",
                tofile=f"b/{artifact_path}",
            )
        )

        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(current_content, encoding="utf-8")

        settings = get_gateway_settings()
        return truncate_text(diff_text, max_chars=settings.audit.max_diff_chars)

    @staticmethod
    def _artifact_kind_from_path(artifact_path: str) -> str:
        path = pathlib.PurePosixPath(artifact_path)
        if path.parts[:1] == ("features",):
            return "feature"
        if path.parts[:1] == ("architecture",):
            return "architecture_artifact"
        if path.parts[:1] == ("release-notes",):
            return "release_notes"
        if path.parts[:1] == ("wiki",):
            return "navigation_artifact"
        return "knowledge_artifact"

    @staticmethod
    def _escape_table_cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", "<br>")


_knowledge_artifact_service: KnowledgeArtifactService | None = None


def get_knowledge_artifact_service() -> KnowledgeArtifactService:
    global _knowledge_artifact_service  # noqa: PLW0603
    if _knowledge_artifact_service is None:
        _knowledge_artifact_service = KnowledgeArtifactService()
    return _knowledge_artifact_service
