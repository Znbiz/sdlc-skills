import datetime as dt
from unittest.mock import MagicMock
from pathlib import Path

import pytest
from app.settings import GatewaySettings
from app.workflows.init_arch.domain import (
    AnalysisTargetCommitStatus,
    AuditActor,
    CommitRangeStatus,
    EventType,
    RepositoryExecution,
    WorkflowSessionRecord,
)
from app.workflows.init_arch.historical import HistoricalPrepService


def _make_session() -> WorkflowSessionRecord:
    return WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        repositories=[
            RepositoryExecution(repository_name="svc-b", created_at=dt.date(2024, 2, 15)),
            RepositoryExecution(repository_name="svc-a", created_at=dt.date(2024, 1, 10)),
        ],
    )


async def test_plan_repository_order_uses_window_months_from_settings() -> None:
    service = HistoricalPrepService(
        settings=GatewaySettings(
            auth_secret="secret",
            workflows={"init": {"historical_window_months": 6}},
        )
    )

    result = await service.plan_repository_order(_make_session())

    assert result.session.historical_analysis.current_snapshot_at == dt.date(2024, 7, 10)


async def test_plan_repository_order_sets_anchor_snapshot_and_repository_order() -> None:
    audit_service = MagicMock()
    service = HistoricalPrepService(audit_service=audit_service)

    result = await service.plan_repository_order(_make_session())

    assert result.session.historical_analysis.anchor_repository_name == "svc-a"
    assert result.session.historical_analysis.anchor_created_at == dt.date(2024, 1, 10)
    assert result.session.historical_analysis.current_snapshot_at == dt.date(2024, 4, 10)
    assert result.session.historical_analysis.ordered_repository_names == ["svc-a", "svc-b"]
    assert [repo.analysis_target_date for repo in result.session.repositories] == [
        dt.date(2024, 4, 10),
        dt.date(2024, 4, 10),
    ]
    assert all(
        repo.analysis_target_commit_status is AnalysisTargetCommitStatus.PENDING for repo in result.session.repositories
    )
    assert all(repo.commit_range_status is CommitRangeStatus.NOT_STARTED for repo in result.session.repositories)
    assert result.session.historical_analysis.previous_snapshot_at is None
    recorded_events = [call.args[0] for call in audit_service.record.call_args_list]
    assert [event.event_type for event in recorded_events] == [
        EventType.GUARD_COMMAND_REQUESTED,
        EventType.GUARD_COMMAND_APPLIED,
    ]
    assert all(event.actor is AuditActor.SERVICE for event in recorded_events)
    assert recorded_events[1].payload["anchor_repository"] == "svc-a"


async def test_resolve_target_commits_updates_statuses_and_commits() -> None:
    audit_service = MagicMock()
    service = HistoricalPrepService(audit_service=audit_service)
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        historical_analysis={
            "anchor_repository_name": "svc-a",
            "anchor_created_at": dt.date(2024, 1, 10),
            "current_snapshot_at": dt.date(2024, 4, 10),
            "ordered_repository_names": ["svc-a", "svc-b"],
        },
        repositories=[
            RepositoryExecution(
                repository_name="svc-a",
                created_at=dt.date(2024, 1, 10),
                main_branch="main",
                analysis_target_date=dt.date(2024, 4, 10),
                analysis_target_commit_status=AnalysisTargetCommitStatus.PENDING,
            ),
            RepositoryExecution(
                repository_name="svc-b",
                created_at=dt.date(2024, 2, 15),
                main_branch="main",
                analysis_target_date=dt.date(2024, 4, 10),
                analysis_target_commit_status=AnalysisTargetCommitStatus.PENDING,
            ),
        ],
    )

    service._resolve_commit_for_repository = MagicMock(side_effect=["abc123", ""])  # type: ignore[method-assign]

    result = await service.resolve_target_commits(session, workspace_dir="/workspace")

    assert result.session.repositories[0].analysis_target_commit == "abc123"
    assert result.session.repositories[0].analysis_target_commit_status is AnalysisTargetCommitStatus.RESOLVED
    assert result.session.repositories[1].analysis_target_commit == ""
    assert result.session.repositories[1].analysis_target_commit_status is AnalysisTargetCommitStatus.MISSING
    assert "resolved=1" in result.summary
    assert "missing=1" in result.summary


async def test_resolve_target_commits_can_checkout_snapshot_commit() -> None:
    service = HistoricalPrepService()
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="arch-docs",
        analysis_scope="full",
        historical_analysis={
            "anchor_repository_name": "svc-a",
            "anchor_created_at": dt.date(2024, 1, 10),
            "current_snapshot_at": dt.date(2024, 4, 10),
            "ordered_repository_names": ["svc-a"],
        },
        repositories=[
            RepositoryExecution(
                repository_name="svc-a",
                created_at=dt.date(2024, 1, 10),
                main_branch="main",
                analysis_target_date=dt.date(2024, 4, 10),
                analysis_target_commit_status=AnalysisTargetCommitStatus.PENDING,
            )
        ],
    )

    service._resolve_commit_for_repository = MagicMock(return_value="abc123")  # type: ignore[method-assign]
    service._checkout_commit = MagicMock()  # type: ignore[method-assign]

    result = await service.resolve_target_commits(session, workspace_dir="/workspace", checkout=True)

    assert result.session.repositories[0].analysis_target_commit_status is AnalysisTargetCommitStatus.CHECKED_OUT
    service._checkout_commit.assert_called_once()


async def test_refresh_main_branches_applies_repository_facts() -> None:
    service = HistoricalPrepService()
    session = WorkflowSessionRecord(
        session_id="wf-refresh",
        product_name="arch-docs",
        analysis_scope="full",
        repositories=[RepositoryExecution(repository_name="svc-a")],
    )
    service._read_repository_facts = MagicMock(  # type: ignore[method-assign]
        return_value={
            "created_at": dt.date(2024, 1, 10),
            "main_branch": "main",
            "remote_head_commit": "abc123",
        }
    )

    result = await service.refresh_main_branches(session, workspace_dir="/workspace")

    assert result.session.repositories[0].main_branch == "main"
    assert result.session.repositories[0].remote_head_commit == "abc123"


async def test_plan_repository_order_requires_created_at_for_anchor() -> None:
    service = HistoricalPrepService()
    session = WorkflowSessionRecord(
        session_id="wf-missing",
        product_name="arch-docs",
        analysis_scope="full",
        repositories=[RepositoryExecution(repository_name="svc-a")],
    )

    with pytest.raises(ValueError, match="created_at for every repository"):
        await service.plan_repository_order(session)


def test_run_git_command_supports_empty_and_raises_on_error(monkeypatch) -> None:
    service = HistoricalPrepService()

    class _Completed:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    monkeypatch.setattr(
        "app.workflows.init_arch.historical.subprocess.run",
        lambda *args, **kwargs: _Completed(0, stdout=""),
    )

    assert service._run_git_command(Path("/tmp"), ["git", "status"], allow_empty=True) == ""

    monkeypatch.setattr(
        "app.workflows.init_arch.historical.subprocess.run",
        lambda *args, **kwargs: _Completed(1, stderr="boom"),
    )

    with pytest.raises(ValueError, match="boom"):
        service._run_git_command(Path("/tmp"), ["git", "status"])
