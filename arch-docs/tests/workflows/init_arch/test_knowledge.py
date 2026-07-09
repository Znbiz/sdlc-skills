from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.workflows.init_arch.domain import RepositoryExecution, StepId, WorkflowSessionRecord
from app.workflows.init_arch.domain import OpenQuestionRecord
from app.workflows.init_arch.knowledge import KnowledgeArtifactService
from app.workflows.shared_assets.loader import WorkflowAssetLoader


def _make_session() -> WorkflowSessionRecord:
    return WorkflowSessionRecord(
        session_id="wf-1",
        product_name="AI CLI Gateway Service",
        analysis_scope="full",
        repositories=[RepositoryExecution(repository_name="gateway-service", analysis_status="completed")],
    )


@pytest.mark.asyncio
async def test_bootstrap_arch_repo_scaffolds_required_artifacts(tmp_path: Path) -> None:
    asset_loader = WorkflowAssetLoader(
        Path("/Users/aanekraso2/github.com/znbiz/sdlc/arch-docs/app/workflows/shared_assets")
    )
    service = KnowledgeArtifactService(asset_loader=asset_loader)

    result = await service.bootstrap_arch_repo(_make_session(), arch_repo_dir=str(tmp_path / "arch-repo"))

    assert (tmp_path / "arch-repo" / "wiki" / "index.md").exists()
    assert (tmp_path / "arch-repo" / "wiki" / "log.md").exists()
    assert (tmp_path / "arch-repo" / "wiki" / "maps" / "compile-report.md").exists()
    assert (tmp_path / "arch-repo" / "features-index.md").exists()
    assert (tmp_path / "arch-repo" / "glossary.md").exists()
    assert result.session.artifacts
    assert any(artifact.artifact_path == "wiki/index.md" for artifact in result.session.artifacts)


@pytest.mark.asyncio
async def test_compile_navigation_writes_compiled_index_and_report(tmp_path: Path) -> None:
    fixture_root = Path("/Users/aanekraso2/github.com/znbiz/sdlc/init-repo-arch-skill/tests/fixtures/valid_arch_repo")
    arch_repo_dir = tmp_path / "arch-repo"
    shutil.copytree(fixture_root, arch_repo_dir)
    service = KnowledgeArtifactService()

    session = _make_session()
    result = await service.bootstrap_arch_repo(session, arch_repo_dir=str(arch_repo_dir))
    compiled = await service.compile_navigation(result.session, arch_repo_dir=str(arch_repo_dir))

    index_text = (arch_repo_dir / "wiki" / "index.md").read_text(encoding="utf-8")
    report_text = (arch_repo_dir / "wiki" / "maps" / "compile-report.md").read_text(encoding="utf-8")
    assert "## Артефакты по типам" in index_text
    assert "## Quality Gates" in report_text
    assert any(artifact.last_updated_step is StepId.BUILD_NAVIGATION_INDEX for artifact in compiled.session.artifacts)


@pytest.mark.asyncio
async def test_lint_knowledge_raises_on_blocking_issues(tmp_path: Path) -> None:
    service = KnowledgeArtifactService()
    arch_repo_dir = tmp_path / "arch-repo"
    arch_repo_dir.mkdir()
    (arch_repo_dir / "wiki").mkdir()
    (arch_repo_dir / "wiki" / "maps").mkdir()
    (arch_repo_dir / "features").mkdir()

    with pytest.raises(ValueError, match="knowledge lint failed"):
        await service.lint_knowledge(_make_session(), arch_repo_dir=str(arch_repo_dir))


@pytest.mark.asyncio
async def test_collect_worker_artifacts_deduplicates_paths() -> None:
    service = KnowledgeArtifactService()

    result = await service.collect_worker_artifacts(
        _make_session(),
        step_id=StepId.REFINE_FEATURES,
        created_artifacts=["wiki/index.md", "wiki/index.md", "features/auth.md"],
    )

    assert result.written_artifacts == ["features/auth.md", "wiki/index.md"]
    assert {artifact.artifact_path for artifact in result.session.artifacts} >= {"features/auth.md", "wiki/index.md"}


@pytest.mark.asyncio
async def test_sync_open_questions_writes_markdown_table(tmp_path: Path) -> None:
    service = KnowledgeArtifactService()
    session = _make_session().model_copy(
        update={
            "open_questions": [
                OpenQuestionRecord(
                    question_id="Q-1",
                    question_text="What API?",
                    related_repositories=["gateway-service"],
                    target_artifacts=["features/api.md"],
                )
            ]
        }
    )

    result = await service.sync_open_questions(session, arch_repo_dir=str(tmp_path / "arch"))

    content = (tmp_path / "arch" / "open-questions.md").read_text(encoding="utf-8")
    assert "Q-1" in content
    assert "features/api.md" in content
    assert result.written_artifacts == ["open-questions.md"]


@pytest.mark.asyncio
async def test_lint_knowledge_returns_non_blocking_issues(tmp_path: Path) -> None:
    service = KnowledgeArtifactService()
    arch_repo_dir = tmp_path / "arch"

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("app.workflows.init_arch.knowledge.run_knowledge_lint", lambda _path: ["WARN: gap"])
        result = await service.lint_knowledge(_make_session(), arch_repo_dir=str(arch_repo_dir))

    assert "Knowledge lint passed" in result.summary


@pytest.mark.asyncio
async def test_bootstrap_arch_repo_skips_existing_files(tmp_path: Path) -> None:
    service = KnowledgeArtifactService()
    arch_repo_dir = tmp_path / "arch"
    (arch_repo_dir / "wiki" / "maps").mkdir(parents=True)
    (arch_repo_dir / "wiki" / "index.md").write_text("existing", encoding="utf-8")

    result = await service.bootstrap_arch_repo(_make_session(), arch_repo_dir=str(arch_repo_dir))

    assert "wiki/index.md" not in result.written_artifacts


def test_shared_asset_loader_reads_vendored_template() -> None:
    loader = WorkflowAssetLoader(Path("/Users/aanekraso2/github.com/znbiz/sdlc/arch-docs/app/workflows/shared_assets"))

    content = loader.read_text("knowledge_base", "features-index-template.md")

    assert "# Реестр фич" in content
