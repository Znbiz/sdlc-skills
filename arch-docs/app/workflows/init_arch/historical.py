from __future__ import annotations

import calendar
import datetime as dt
import pathlib
import subprocess

import pydantic

from app.settings import GatewaySettings, get_gateway_settings
from app.workflows.init_arch.audit import WorkflowAuditService, get_workflow_audit_service
from app.workflows.init_arch.domain import (
    AnalysisTargetCommitStatus,
    AuditActor,
    CommitRangeStatus,
    EventType,
    RepositoryExecution,
    WorkflowEventRecord,
    WorkflowSessionRecord,
)


class HistoricalPrepResult(pydantic.BaseModel):
    session: WorkflowSessionRecord
    summary: str = ""


class HistoricalPrepService:
    def __init__(
        self,
        audit_service: WorkflowAuditService | None = None,
        settings: GatewaySettings | None = None,
    ) -> None:
        self._audit_service = audit_service or get_workflow_audit_service()
        self._settings = settings or get_gateway_settings()

    async def refresh_main_branches(
        self,
        session: WorkflowSessionRecord,
        *,
        workspace_dir: str,
    ) -> HistoricalPrepResult:
        repositories: list[RepositoryExecution] = []
        self._record_event(session, EventType.GUARD_COMMAND_REQUESTED, command="refresh_main_branches")
        for repository in session.repositories:
            facts = self._read_repository_facts(repository.repository_name, workspace_dir=workspace_dir)
            repositories.append(
                repository.model_copy(
                    update={
                        "created_at": repository.created_at or facts["created_at"],
                        "main_branch": facts["main_branch"],
                        "remote_head_commit": facts["remote_head_commit"],
                    }
                )
            )

        updated_session = session.model_copy(update={"repositories": repositories})
        self._record_event(
            updated_session,
            EventType.GUARD_COMMAND_APPLIED,
            command="refresh_main_branches",
            repository_count=str(len(repositories)),
        )
        return HistoricalPrepResult(
            session=updated_session,
            summary=f"Refreshed repository metadata for {len(repositories)} repositories",
        )

    async def plan_repository_order(self, session: WorkflowSessionRecord) -> HistoricalPrepResult:
        in_scope_repositories = list(session.repositories)
        if not in_scope_repositories:
            raise ValueError("historical prep requires at least one repository")

        missing_created_at = [
            repository.repository_name for repository in in_scope_repositories if repository.created_at is None
        ]
        if missing_created_at:
            raise ValueError(
                "historical prep requires created_at for every repository: " + ", ".join(missing_created_at)
            )

        ordered_repositories = sorted(
            in_scope_repositories,
            key=lambda repository: (repository.created_at or dt.date.max, repository.repository_name),
        )
        anchor_repository = ordered_repositories[0]
        anchor_created_at = anchor_repository.created_at
        if anchor_created_at is None:
            raise ValueError("historical prep requires created_at for anchor repository")
        snapshot_at = self._add_months(
            anchor_created_at,
            self._settings.workflows.init.historical_window_months,
        )

        updated_repositories = [
            repository.model_copy(
                update={
                    "analysis_target_date": snapshot_at,
                    "analysis_target_commit": "",
                    "analysis_target_commit_status": AnalysisTargetCommitStatus.PENDING,
                    "previous_analysis_target_commit": "",
                    "window_start_commit": "",
                    "window_end_commit": "",
                    "commit_range": "",
                    "commit_range_status": CommitRangeStatus.NOT_STARTED,
                    "diff_stat_summary": "",
                    "commit_log_summary": "",
                    "changed_paths": [],
                    "renamed_paths": [],
                    "deleted_paths": [],
                    "temporal_delta_note": "",
                }
            )
            for repository in in_scope_repositories
        ]
        updated_session = session.model_copy(
            update={
                "repositories": updated_repositories,
                "historical_analysis": session.historical_analysis.model_copy(
                    update={
                        "anchor_repository_name": anchor_repository.repository_name,
                        "anchor_created_at": anchor_created_at,
                        "previous_snapshot_at": None,
                        "current_snapshot_at": snapshot_at,
                        "ordered_repository_names": [repository.repository_name for repository in ordered_repositories],
                        "prep_notes": (
                            f"anchor={anchor_repository.repository_name}; "
                            f"snapshot_at={snapshot_at.isoformat()}; "
                            f"window_months={self._settings.workflows.init.historical_window_months}"
                        ),
                    }
                ),
            }
        )
        self._record_event(updated_session, EventType.GUARD_COMMAND_REQUESTED, command="plan_repository_order")
        self._record_event(
            updated_session,
            EventType.GUARD_COMMAND_APPLIED,
            command="plan_repository_order",
            anchor_repository=anchor_repository.repository_name,
            anchor_created_at=anchor_created_at.isoformat(),
            snapshot_at=snapshot_at.isoformat(),
        )
        return HistoricalPrepResult(
            session=updated_session,
            summary=(
                "Historical timeline planned: "
                f"anchor={anchor_repository.repository_name} "
                f"created_at={anchor_created_at.isoformat()} "
                f"snapshot_at={snapshot_at.isoformat()}"
            ),
        )

    async def resolve_target_commits(
        self,
        session: WorkflowSessionRecord,
        *,
        workspace_dir: str,
        checkout: bool = False,
    ) -> HistoricalPrepResult:
        snapshot_at = session.historical_analysis.current_snapshot_at
        if snapshot_at is None:
            raise ValueError("historical prep requires current_snapshot_at before commit resolution")

        resolved_count = 0
        missing_count = 0
        repositories: list[RepositoryExecution] = []
        for repository in session.repositories:
            repo_path = self._repository_path(repository.repository_name, workspace_dir=workspace_dir)
            commit_sha = self._resolve_commit_for_repository(
                repository,
                workspace_dir=workspace_dir,
                snapshot_at=snapshot_at,
            )
            if commit_sha:
                baseline_commit, baseline_status, baseline_note = self.resolve_temporal_baseline(
                    repository,
                    workspace_dir=workspace_dir,
                    snapshot_at=snapshot_at,
                    previous_snapshot_at=session.historical_analysis.previous_snapshot_at,
                )
                commit_range, range_status, range_note = self.build_commit_range(
                    repo_path=repo_path,
                    window_start_commit=baseline_commit,
                    window_end_commit=commit_sha,
                )
                diff_stat_summary = ""
                changed_paths: list[str] = []
                renamed_paths: list[str] = []
                deleted_paths: list[str] = []
                commit_log_summary = ""
                temporal_note = baseline_note or range_note
                final_range_status = range_status if baseline_status is not CommitRangeStatus.BASELINE_MISSING else baseline_status

                if final_range_status in {
                    CommitRangeStatus.RANGE_RESOLVED,
                    CommitRangeStatus.NO_CHANGES,
                }:
                    diff_stat_summary = self.collect_diff_summary(repo_path, commit_range)
                    changed_paths, renamed_paths, deleted_paths = self.collect_changed_paths(repo_path, commit_range)
                    commit_log_summary = self.collect_commit_log_summary(repo_path, commit_range)
                    final_range_status = CommitRangeStatus.DIFF_COLLECTED if commit_range else CommitRangeStatus.NO_CHANGES

                if checkout:
                    self._checkout_commit(repo_path, commit_sha)
                status = AnalysisTargetCommitStatus.CHECKED_OUT if checkout else AnalysisTargetCommitStatus.RESOLVED
                repositories.append(
                    repository.model_copy(
                        update={
                            "analysis_target_date": snapshot_at,
                            "analysis_target_commit": commit_sha,
                            "analysis_target_commit_status": status,
                            "previous_analysis_target_commit": baseline_commit,
                            "window_start_commit": baseline_commit,
                            "window_end_commit": commit_sha,
                            "commit_range": commit_range,
                            "commit_range_status": final_range_status,
                            "diff_stat_summary": diff_stat_summary,
                            "commit_log_summary": commit_log_summary,
                            "changed_paths": changed_paths,
                            "renamed_paths": renamed_paths,
                            "deleted_paths": deleted_paths,
                            "temporal_delta_note": temporal_note,
                        }
                    )
                )
                resolved_count += 1
            else:
                repositories.append(
                    repository.model_copy(
                        update={
                            "analysis_target_date": snapshot_at,
                            "analysis_target_commit": "",
                            "analysis_target_commit_status": AnalysisTargetCommitStatus.MISSING,
                            "window_end_commit": "",
                            "commit_range": "",
                            "commit_range_status": CommitRangeStatus.BASELINE_MISSING,
                            "diff_stat_summary": "",
                            "commit_log_summary": "",
                            "changed_paths": [],
                            "renamed_paths": [],
                            "deleted_paths": [],
                            "temporal_delta_note": "No commit available for the current snapshot date.",
                        }
                    )
                )
                missing_count += 1

        updated_session = session.model_copy(update={"repositories": repositories})
        self._record_event(updated_session, EventType.GUARD_COMMAND_REQUESTED, command="resolve_target_commits")
        self._record_event(
            updated_session,
            EventType.GUARD_COMMAND_APPLIED,
            command="resolve_target_commits",
            snapshot_at=snapshot_at.isoformat(),
            resolved=str(resolved_count),
            missing=str(missing_count),
        )
        return HistoricalPrepResult(
            session=updated_session,
            summary=(
                f"Resolved historical commits for snapshot {snapshot_at.isoformat()}: "
                f"resolved={resolved_count}, missing={missing_count}"
            ),
        )

    def resolve_temporal_baseline(
        self,
        repository: RepositoryExecution,
        *,
        workspace_dir: str,
        snapshot_at: dt.date,
        previous_snapshot_at: dt.date | None,
    ) -> tuple[str, CommitRangeStatus, str]:
        del snapshot_at

        if previous_snapshot_at is not None:
            if repository.previous_analysis_target_commit:
                return repository.previous_analysis_target_commit, CommitRangeStatus.RANGE_RESOLVED, ""
            return "", CommitRangeStatus.BASELINE_MISSING, "Previous snapshot commit is unavailable for this repository."

        try:
            first_commit = self._read_first_commit(repository, workspace_dir=workspace_dir)
        except (ValueError, FileNotFoundError):
            return "", CommitRangeStatus.BASELINE_MISSING, "First repository commit is unavailable for this repository."
        if not first_commit:
            return "", CommitRangeStatus.BASELINE_MISSING, "First repository commit is unavailable for this repository."
        return first_commit, CommitRangeStatus.RANGE_RESOLVED, ""

    def build_commit_range(
        self,
        *,
        repo_path: pathlib.Path,
        window_start_commit: str,
        window_end_commit: str,
    ) -> tuple[str, CommitRangeStatus, str]:
        if not window_end_commit:
            return "", CommitRangeStatus.BASELINE_MISSING, "Window end commit is unavailable."
        if not window_start_commit:
            return "", CommitRangeStatus.BASELINE_MISSING, "Temporal baseline commit is unavailable."
        if window_start_commit == window_end_commit:
            return "", CommitRangeStatus.NO_CHANGES, ""
        if not self._git_is_ancestor(repo_path, window_start_commit, window_end_commit):
            return "", CommitRangeStatus.INVALID_RANGE, "Window start commit is not an ancestor of the snapshot commit."
        return f"{window_start_commit}..{window_end_commit}", CommitRangeStatus.RANGE_RESOLVED, ""

    def collect_diff_summary(self, repo_path: pathlib.Path, commit_range: str) -> str:
        if not commit_range:
            return ""
        return self._run_git_command(
            repo_path,
            ["git", "diff", "--stat", commit_range],
            allow_empty=True,
        )

    def collect_changed_paths(self, repo_path: pathlib.Path, commit_range: str) -> tuple[list[str], list[str], list[str]]:
        if not commit_range:
            return [], [], []

        output = self._run_git_command(
            repo_path,
            ["git", "diff", "--name-status", commit_range],
            allow_empty=True,
        )
        changed_paths: list[str] = []
        renamed_paths: list[str] = []
        deleted_paths: list[str] = []
        for raw_line in output.splitlines():
            if not raw_line.strip():
                continue
            parts = raw_line.split("\t")
            status = parts[0]
            if status.startswith("R") and len(parts) >= 3:
                renamed_paths.append(f"{parts[1]} -> {parts[2]}")
                changed_paths.append(parts[2])
                continue
            if status == "D" and len(parts) >= 2:
                deleted_paths.append(parts[1])
                continue
            if len(parts) >= 2:
                changed_paths.append(parts[1])
        return changed_paths, renamed_paths, deleted_paths

    def collect_commit_log_summary(self, repo_path: pathlib.Path, commit_range: str) -> str:
        if not commit_range:
            return ""
        return self._run_git_command(
            repo_path,
            ["git", "log", "--oneline", commit_range],
            allow_empty=True,
        )

    def _read_repository_facts(self, repository_name: str, *, workspace_dir: str) -> dict[str, dt.date | str]:
        repo_path = self._repository_path(repository_name, workspace_dir=workspace_dir)
        main_branch = self._run_git_command(
            repo_path,
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD", "--short"],
        ).removeprefix("origin/")
        remote_head_commit = self._run_git_command(repo_path, ["git", "rev-parse", f"origin/{main_branch or 'HEAD'}"])
        created_at_raw = self._run_git_command(
            repo_path,
            ["git", "log", "--reverse", "--date=short", "--format=%cd", main_branch or "HEAD"],
        ).splitlines()[0]
        return {
            "main_branch": main_branch,
            "remote_head_commit": remote_head_commit,
            "created_at": dt.date.fromisoformat(created_at_raw),
        }

    def _resolve_commit_for_repository(
        self,
        repository: RepositoryExecution,
        *,
        workspace_dir: str,
        snapshot_at: dt.date,
    ) -> str:
        repo_path = self._repository_path(repository.repository_name, workspace_dir=workspace_dir)
        before_value = f"{snapshot_at.isoformat()} 23:59:59"
        return self._run_git_command(
            repo_path,
            ["git", "rev-list", "-1", f"--before={before_value}", repository.main_branch or "HEAD"],
            allow_empty=True,
        )

    def _read_first_commit(self, repository: RepositoryExecution, *, workspace_dir: str) -> str:
        repo_path = self._repository_path(repository.repository_name, workspace_dir=workspace_dir)
        first_commits = self._run_git_command(
            repo_path,
            ["git", "rev-list", "--max-parents=0", repository.main_branch or "HEAD"],
            allow_empty=True,
        )
        return first_commits.splitlines()[0] if first_commits else ""

    def _git_is_ancestor(self, repo_path: pathlib.Path, start_commit: str, end_commit: str) -> bool:
        completed = subprocess.run(  # noqa: S603
            ["git", "merge-base", "--is-ancestor", start_commit, end_commit],
            cwd=repo_path,
            check=False,
            capture_output=True,
            text=True,
        )
        return completed.returncode == 0

    def _checkout_commit(self, repo_path: pathlib.Path, commit_sha: str) -> None:
        self._run_git_command(repo_path, ["git", "checkout", commit_sha])

    def _repository_path(self, repository_name: str, *, workspace_dir: str) -> pathlib.Path:
        temp_repo_path = pathlib.Path(workspace_dir) / ".temp" / repository_name
        if temp_repo_path.exists():
            return temp_repo_path
        return pathlib.Path(workspace_dir) / repository_name

    def _run_git_command(self, repo_path: pathlib.Path, command: list[str], *, allow_empty: bool = False) -> str:
        completed = subprocess.run(  # noqa: S603
            command,
            cwd=repo_path,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise ValueError(f"git command failed for {repo_path}: {detail}")
        output = completed.stdout.strip()
        if not output and not allow_empty:
            raise ValueError(f"git command returned empty output for {repo_path}: {' '.join(command)}")
        return output

    def _record_event(self, session: WorkflowSessionRecord, event_type: EventType, **payload: str) -> None:
        self._audit_service.record(
            WorkflowEventRecord(
                event_type=event_type,
                actor=AuditActor.SERVICE,
                session_id=session.session_id,
                step_id=session.current_step,
                payload=payload,
            )
        )

    @staticmethod
    def _add_months(source_date: dt.date, months: int) -> dt.date:
        month_index = source_date.month - 1 + months
        year = source_date.year + month_index // 12
        month = month_index % 12 + 1
        day = min(source_date.day, calendar.monthrange(year, month)[1])
        return dt.date(year, month, day)


_historical_prep_service: HistoricalPrepService | None = None


def get_historical_prep_service() -> HistoricalPrepService:
    global _historical_prep_service  # noqa: PLW0603
    if _historical_prep_service is None:
        _historical_prep_service = HistoricalPrepService(audit_service=get_workflow_audit_service())
    return _historical_prep_service
