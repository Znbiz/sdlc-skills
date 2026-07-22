import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workflows.init_arch import nodes as nodes_module
from app.workflows.init_arch.domain import (
    AnalysisTargetCommitStatus,
    AuditActor,
    CommitRangeStatus,
    DomainDefinition,
    DomainStrategy,
    EventType,
    LlmTaskKind,
    LlmTaskResult,
    OpenQuestionRecord,
    RepositoryDomainAssessment,
    RepositoryExecution,
    StepId,
    VolumeClass,
    WorkflowSessionRecord,
)
from app.workflows.init_arch.guard import GuardOperationResult, InitArchGuardService
from app.workflows.init_arch.knowledge import KnowledgeArtifactResult
from app.workflows.init_arch.state import InitArchState


def _make_state(**kwargs) -> InitArchState:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="Prod",
        analysis_scope="full",
        repositories=[
            RepositoryExecution(
                repository_name="svc-a", analysis_target_commit_status=AnalysisTargetCommitStatus.PENDING
            )
        ],
    )
    base = InitArchState(
        session_id=session.session_id,
        session=session,
        workspace_dir="/workspace/repo",
        arch_repo_dir="/workspace/repo/arch-doc",
        engine_name="claude",
        timeout_seconds=60,
        progress_file_path="/workspace/repo/arch-doc/progress.yaml",
        last_llm_result=None,
        last_guard_output="",
        step_error=None,
        retry_count=0,
    )
    base.update(kwargs)  # type: ignore[arg-type]
    return base


async def test_node_define_scope_uses_guard_service_without_llm() -> None:
    state = _make_state()
    guard_service = MagicMock()
    audit_service = MagicMock()

    initialized_session = state["session"].model_copy()
    advanced_session = initialized_session.model_copy(
        update={"current_step": StepId.REQUEST_REPOSITORY_LIST, "completed_steps": [StepId.DEFINE_SCOPE]}
    )
    guard_service.init_progress = AsyncMock(return_value=GuardOperationResult(session=initialized_session))
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=advanced_session))

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_workflow_audit_service", return_value=audit_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service") as llm_service,
    ):
        result = await nodes_module.node_define_scope(state)

    assert result["current_step_id"] == "request_repository_list"
    assert result["session"].current_step is StepId.REQUEST_REPOSITORY_LIST
    assert result["last_llm_result"] is None
    llm_service.assert_not_called()
    guard_service.init_progress.assert_awaited_once()
    guard_service.advance_step.assert_awaited_once()
    recorded_events = [call.args[0] for call in audit_service.record.call_args_list]
    assert [event.event_type for event in recorded_events] == [
        EventType.WORKFLOW_STEP_STARTED,
        EventType.WORKFLOW_STEP_COMPLETED,
    ]
    assert all(event.actor is AuditActor.SERVICE for event in recorded_events)


async def test_node_request_repository_list_advances_when_repositories_exist() -> None:
    state = _make_state()
    guard_service = MagicMock()
    audit_service = MagicMock()
    advanced_session = state["session"].model_copy(
        update={
            "current_step": StepId.PREPARE_TEMP_WORKSPACE,
            "completed_steps": [StepId.DEFINE_SCOPE, StepId.REQUEST_REPOSITORY_LIST],
        }
    )
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=advanced_session))

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_workflow_audit_service", return_value=audit_service),
    ):
        result = await nodes_module.node_request_repository_list(state)

    assert result["current_step_id"] == "prepare_temp_workspace"


async def test_node_request_repository_list_wraps_advance_step_failure_in_step_error() -> None:
    state = _make_state()
    guard_service = MagicMock()
    audit_service = MagicMock()
    guard_service.advance_step = AsyncMock(side_effect=RuntimeError("guard blew up"))

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_workflow_audit_service", return_value=audit_service),
    ):
        result = await nodes_module.node_request_repository_list(state)

    assert result == {"step_error": "guard blew up", "retry_count": 1}
    recorded_events = [call.args[0] for call in audit_service.record.call_args_list]
    assert any(event.event_type == EventType.WORKFLOW_STEP_FAILED for event in recorded_events)


async def test_node_request_repository_list_interrupts_without_repositories() -> None:
    session = WorkflowSessionRecord(session_id="wf-1", product_name="Prod", analysis_scope="full")
    state = _make_state(session=session)
    with patch("app.workflows.init_arch.nodes.interrupt") as mock_interrupt:
        mock_interrupt.side_effect = Exception("interrupt called")
        with pytest.raises(Exception, match="interrupt called"):
            await nodes_module.node_request_repository_list(state)
        mock_interrupt.assert_called_once()


async def test_node_prepare_temp_workspace_creates_directories_without_llm(tmp_path) -> None:
    workspace_dir = tmp_path / "workspace"
    raw_workspace_dir = workspace_dir / ".temp"
    arch_repo_dir = workspace_dir / "arch-doc"
    state = _make_state(
        workspace_dir=str(workspace_dir),
        raw_workspace_dir=str(raw_workspace_dir),
        arch_repo_dir=str(arch_repo_dir),
    )
    guard_service = MagicMock()
    audit_service = MagicMock()
    advanced_session = state["session"].model_copy(
        update={
            "current_step": StepId.CLONE_REPOSITORIES,
            "completed_steps": [
                StepId.DEFINE_SCOPE,
                StepId.REQUEST_REPOSITORY_LIST,
                StepId.PREPARE_TEMP_WORKSPACE,
            ],
        }
    )
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=advanced_session))

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_workflow_audit_service", return_value=audit_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service") as llm_service,
    ):
        result = await nodes_module.node_prepare_temp_workspace(state)

    assert result["current_step_id"] == "clone_repositories"
    assert result["last_llm_result"] is None
    llm_service.assert_not_called()
    assert workspace_dir.is_dir()
    assert raw_workspace_dir.is_dir()
    assert arch_repo_dir.is_dir()
    recorded_events = [call.args[0] for call in audit_service.record.call_args_list]
    assert [event.event_type for event in recorded_events] == [
        EventType.WORKFLOW_STEP_STARTED,
        EventType.WORKFLOW_STEP_COMPLETED,
    ]


async def test_node_prepare_temp_workspace_wraps_advance_step_failure_in_step_error(tmp_path) -> None:
    workspace_dir = tmp_path / "workspace"
    state = _make_state(
        workspace_dir=str(workspace_dir),
        raw_workspace_dir=str(workspace_dir / ".temp"),
        arch_repo_dir=str(workspace_dir / "arch-doc"),
    )
    guard_service = MagicMock()
    audit_service = MagicMock()
    guard_service.advance_step = AsyncMock(side_effect=RuntimeError("guard blew up"))

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_workflow_audit_service", return_value=audit_service),
    ):
        result = await nodes_module.node_prepare_temp_workspace(state)

    assert result == {"step_error": "guard blew up", "retry_count": 1}
    recorded_events = [call.args[0] for call in audit_service.record.call_args_list]
    assert any(event.event_type == EventType.WORKFLOW_STEP_FAILED for event in recorded_events)


async def test_node_clone_repositories_clones_missing_and_skips_existing_checkouts(tmp_path) -> None:
    raw_workspace_dir = tmp_path / ".temp"
    existing_repo_dir = raw_workspace_dir / "svc-existing"
    (existing_repo_dir / ".git").mkdir(parents=True)

    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="Prod",
        analysis_scope="full",
        repositories=[
            RepositoryExecution(repository_name="svc-existing", repository_url="https://example.com/svc-existing.git"),
            RepositoryExecution(repository_name="svc-new", repository_url="https://example.com/svc-new.git"),
        ],
    )
    state = _make_state(session=session, raw_workspace_dir=str(raw_workspace_dir))
    guard_service = MagicMock()
    audit_service = MagicMock()
    advanced_session = session.model_copy(
        update={
            "current_step": StepId.REFRESH_MAIN_BRANCHES,
            "completed_steps": [
                StepId.DEFINE_SCOPE,
                StepId.REQUEST_REPOSITORY_LIST,
                StepId.PREPARE_TEMP_WORKSPACE,
                StepId.CLONE_REPOSITORIES,
            ],
        }
    )
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=advanced_session))

    async def fake_run_git_clone(repository_url, target_path):
        target_path.mkdir(parents=True)
        (target_path / ".git").mkdir()

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_workflow_audit_service", return_value=audit_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service") as llm_service,
        patch("app.workflows.init_arch.nodes.ensure_git_credentials_store", AsyncMock()),
        patch("app.workflows.init_arch.nodes._run_git_clone", side_effect=fake_run_git_clone) as run_git_clone,
    ):
        result = await nodes_module.node_clone_repositories(state)

    assert result["current_step_id"] == "refresh_main_branches"
    assert result["last_llm_result"] is None
    llm_service.assert_not_called()
    run_git_clone.assert_awaited_once_with("https://example.com/svc-new.git", raw_workspace_dir / "svc-new")
    assert (raw_workspace_dir / "svc-new" / ".git").is_dir()


async def test_node_clone_repositories_fails_when_url_missing_and_no_local_checkout(tmp_path) -> None:
    raw_workspace_dir = tmp_path / ".temp"
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="Prod",
        analysis_scope="full",
        repositories=[RepositoryExecution(repository_name="svc-a")],
    )
    state = _make_state(session=session, raw_workspace_dir=str(raw_workspace_dir))
    guard_service = MagicMock()
    audit_service = MagicMock()

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_workflow_audit_service", return_value=audit_service),
        patch("app.workflows.init_arch.nodes.ensure_git_credentials_store", AsyncMock()),
    ):
        result = await nodes_module.node_clone_repositories(state)

    assert result["retry_count"] == 1
    assert "svc-a" in result["step_error"]
    guard_service.advance_step.assert_not_called()
    recorded_events = [call.args[0] for call in audit_service.record.call_args_list]
    assert any(event.event_type == EventType.WORKFLOW_STEP_FAILED for event in recorded_events)


async def test_node_clone_repositories_wraps_git_clone_failure_in_step_error(tmp_path) -> None:
    raw_workspace_dir = tmp_path / ".temp"
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="Prod",
        analysis_scope="full",
        repositories=[RepositoryExecution(repository_name="svc-a", repository_url="https://example.com/svc-a.git")],
    )
    state = _make_state(session=session, raw_workspace_dir=str(raw_workspace_dir))
    guard_service = MagicMock()
    audit_service = MagicMock()

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_workflow_audit_service", return_value=audit_service),
        patch("app.workflows.init_arch.nodes.ensure_git_credentials_store", AsyncMock()),
        patch(
            "app.workflows.init_arch.nodes._run_git_clone",
            AsyncMock(
                side_effect=RuntimeError("git clone failed for https://example.com/svc-a.git (auth_failed): denied")
            ),
        ),
    ):
        result = await nodes_module.node_clone_repositories(state)

    assert result["retry_count"] == 1
    assert "auth_failed" in result["step_error"]
    guard_service.advance_step.assert_not_called()


def test_validate_repository_name_rejects_path_traversal() -> None:
    for invalid_name in ("", ".", "..", "a/b", "a\\b"):
        with pytest.raises(ValueError, match="invalid repository_name"):
            nodes_module._validate_repository_name(invalid_name)

    nodes_module._validate_repository_name("svc-a")


async def test_node_refresh_main_branches_uses_historical_service_without_llm() -> None:
    state = _make_state()
    guard_service = MagicMock()
    historical_service = MagicMock()
    refreshed_session = state["session"].model_copy(
        update={"repositories": [state["session"].repositories[0].model_copy(update={"main_branch": "main"})]}
    )
    next_session = refreshed_session.model_copy(
        update={
            "current_step": StepId.PLAN_REPOSITORY_ORDER,
            "completed_steps": [
                StepId.DEFINE_SCOPE,
                StepId.REQUEST_REPOSITORY_LIST,
                StepId.PREPARE_TEMP_WORKSPACE,
                StepId.CLONE_REPOSITORIES,
                StepId.REFRESH_MAIN_BRANCHES,
            ],
        }
    )
    historical_service.refresh_main_branches = AsyncMock(
        return_value=nodes_module.HistoricalPrepResult(session=refreshed_session)
    )
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=next_session))

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_historical_prep_service", return_value=historical_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service") as llm_service,
    ):
        result = await nodes_module.node_refresh_main_branches(state)

    assert result["current_step_id"] == "plan_repository_order"
    llm_service.assert_not_called()
    historical_service.refresh_main_branches.assert_awaited_once()


async def test_node_plan_repository_order_plans_and_resolves_historical_prep() -> None:
    state = _make_state()
    guard_service = MagicMock()
    historical_service = MagicMock()
    planned_session = state["session"].model_copy(
        update={
            "historical_analysis": state["session"].historical_analysis.model_copy(
                update={
                    "anchor_repository_name": "svc-a",
                    "anchor_created_at": None,
                    "current_snapshot_at": None,
                    "ordered_repository_names": ["svc-a"],
                }
            )
        }
    )
    resolved_session = planned_session.model_copy(
        update={
            "historical_analysis": planned_session.historical_analysis.model_copy(
                update={"anchor_created_at": dt.date(2024, 1, 1), "current_snapshot_at": dt.date(2024, 4, 1)}
            ),
            "repositories": [
                state["session"]
                .repositories[0]
                .model_copy(
                    update={
                        "created_at": dt.date(2024, 1, 1),
                        "analysis_target_date": dt.date(2024, 4, 1),
                        "analysis_target_commit": "abc123",
                        "analysis_target_commit_status": AnalysisTargetCommitStatus.RESOLVED,
                    }
                )
            ],
        }
    )
    next_session = resolved_session.model_copy(
        update={
            "current_step": StepId.ASSESS_SCOPE_AND_DOMAINS,
            "completed_steps": [
                StepId.DEFINE_SCOPE,
                StepId.REQUEST_REPOSITORY_LIST,
                StepId.PREPARE_TEMP_WORKSPACE,
                StepId.CLONE_REPOSITORIES,
                StepId.REFRESH_MAIN_BRANCHES,
                StepId.PLAN_REPOSITORY_ORDER,
            ],
        }
    )
    historical_service.plan_repository_order = AsyncMock(
        return_value=nodes_module.HistoricalPrepResult(session=planned_session, summary="planned")
    )
    historical_service.resolve_target_commits = AsyncMock(
        return_value=nodes_module.HistoricalPrepResult(session=resolved_session, summary="resolved")
    )
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=next_session))

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_historical_prep_service", return_value=historical_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service") as llm_service,
    ):
        result = await nodes_module.node_plan_repository_order(state)

    assert result["current_step_id"] == "assess_scope_and_domains"
    llm_service.assert_not_called()
    historical_service.plan_repository_order.assert_awaited_once()
    historical_service.resolve_target_commits.assert_awaited_once_with(
        planned_session,
        workspace_dir=state["workspace_dir"],
        checkout=True,
    )


async def test_node_plan_repository_order_blocks_when_checkout_done_but_temporal_delta_missing() -> None:
    """Checkout succeeded but temporal delta collection did not run.

    `analysis_target_commit_status=CHECKED_OUT`, but the temporal delta for this
    (non-first) window never made it past `RANGE_RESOLVED` — i.e. diff collection
    did not run. The real domain gate (`historical_prep_is_complete`) must refuse
    the transition to `assess_scope_and_domains`, and the node must surface that
    as `step_error` rather than advancing.
    """
    state = _make_state()
    historical_service = MagicMock()
    real_guard_service = InitArchGuardService(audit_service=MagicMock())

    planned_session = state["session"].model_copy(
        update={
            "current_step": StepId.PLAN_REPOSITORY_ORDER,
            "historical_analysis": state["session"].historical_analysis.model_copy(
                update={
                    "anchor_repository_name": "svc-a",
                    "anchor_created_at": None,
                    "previous_snapshot_at": dt.date(2024, 1, 1),
                    "current_snapshot_at": None,
                    "ordered_repository_names": ["svc-a"],
                }
            ),
        }
    )
    resolved_session = planned_session.model_copy(
        update={
            "historical_analysis": planned_session.historical_analysis.model_copy(
                update={"anchor_created_at": dt.date(2024, 1, 1), "current_snapshot_at": dt.date(2024, 4, 1)}
            ),
            "repositories": [
                state["session"]
                .repositories[0]
                .model_copy(
                    update={
                        "created_at": dt.date(2024, 1, 1),
                        "analysis_target_date": dt.date(2024, 4, 1),
                        "analysis_target_commit": "abc123",
                        "analysis_target_commit_status": AnalysisTargetCommitStatus.CHECKED_OUT,
                        "window_end_commit": "abc123",
                        "commit_range_status": CommitRangeStatus.RANGE_RESOLVED,
                    }
                )
            ],
        }
    )
    historical_service.plan_repository_order = AsyncMock(
        return_value=nodes_module.HistoricalPrepResult(session=planned_session, summary="planned")
    )
    historical_service.resolve_target_commits = AsyncMock(
        return_value=nodes_module.HistoricalPrepResult(session=resolved_session, summary="resolved")
    )

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=real_guard_service),
        patch("app.workflows.init_arch.nodes.get_historical_prep_service", return_value=historical_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service") as llm_service,
        patch("app.workflows.init_arch.nodes.get_workflow_audit_service", return_value=MagicMock()),
    ):
        result = await nodes_module.node_plan_repository_order(state)

    assert "step_error" in result
    assert result["step_error"] is not None
    assert "historical prep must be completed" in result["step_error"]
    llm_service.assert_not_called()


async def test_node_assess_scope_and_domains_persists_assessment_per_repository() -> None:
    repo_a = RepositoryExecution(repository_name="svc-a")
    repo_b = RepositoryExecution(repository_name="svc-b")
    session = WorkflowSessionRecord(
        session_id="wf-1", product_name="Prod", analysis_scope="full", repositories=[repo_a, repo_b]
    )
    state = _make_state(session=session)
    guard_service = MagicMock()
    knowledge_service = MagicMock()
    llm_service = MagicMock()

    started_session = session.model_copy()
    assessed_a_session = session.model_copy(
        update={
            "repositories": [
                repo_a.model_copy(
                    update={
                        "volume_class": VolumeClass.SMALL,
                        "domain_strategy": DomainStrategy.PER_MODULE,
                    }
                ),
                repo_b,
            ]
        }
    )
    assessed_b_session = assessed_a_session.model_copy(
        update={
            "repositories": [
                assessed_a_session.repositories[0],
                repo_b.model_copy(
                    update={
                        "volume_class": VolumeClass.LARGE,
                        "domain_strategy": DomainStrategy.PER_DOMAIN,
                        "domains": [DomainDefinition(domain_id="billing", name="Биллинг", paths=["apps/billing/"])],
                    }
                ),
            ]
        }
    )
    domain_map_session = assessed_b_session.model_copy()
    next_session = assessed_b_session.model_copy(
        update={"current_step": StepId.ANALYZE_REPOSITORIES, "completed_steps": [StepId.ASSESS_SCOPE_AND_DOMAINS]}
    )

    guard_service.start_repository = AsyncMock(return_value=GuardOperationResult(session=started_session))
    guard_service.assess_repository_domains = AsyncMock(
        side_effect=[
            GuardOperationResult(session=assessed_a_session),
            GuardOperationResult(session=assessed_b_session),
        ]
    )
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=next_session))
    knowledge_service.write_domain_map = AsyncMock(
        return_value=KnowledgeArtifactResult(session=domain_map_session, summary="wrote domain map")
    )
    llm_service.run_task = AsyncMock(
        side_effect=[
            LlmTaskResult(
                task_kind=LlmTaskKind.STEP_EXECUTION,
                step_id=StepId.ASSESS_SCOPE_AND_DOMAINS,
                domain_assessment=RepositoryDomainAssessment(
                    volume_class=VolumeClass.SMALL, strategy=DomainStrategy.PER_MODULE
                ),
            ),
            LlmTaskResult(
                task_kind=LlmTaskKind.STEP_EXECUTION,
                step_id=StepId.ASSESS_SCOPE_AND_DOMAINS,
                domain_assessment=RepositoryDomainAssessment(
                    volume_class=VolumeClass.LARGE,
                    strategy=DomainStrategy.PER_DOMAIN,
                    domains=[DomainDefinition(domain_id="billing", name="Биллинг", paths=["apps/billing/"])],
                ),
            ),
        ]
    )

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_knowledge_artifact_service", return_value=knowledge_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service", return_value=llm_service),
    ):
        result = await nodes_module.node_assess_scope_and_domains(state)

    assert result["current_step_id"] == "analyze_repositories"
    assert guard_service.start_repository.await_count == 2
    assert guard_service.assess_repository_domains.await_count == 2
    knowledge_service.write_domain_map.assert_awaited_once()
    first_call_kwargs = guard_service.assess_repository_domains.await_args_list[0].kwargs
    assert first_call_kwargs["repository_name"] == "svc-a"
    assert first_call_kwargs["assessment"].strategy is DomainStrategy.PER_MODULE
    second_call_kwargs = guard_service.assess_repository_domains.await_args_list[1].kwargs
    assert second_call_kwargs["repository_name"] == "svc-b"
    assert second_call_kwargs["assessment"].domains[0].domain_id == "billing"


async def test_node_assess_scope_and_domains_blocks_when_llm_omits_assessment() -> None:
    repo_a = RepositoryExecution(repository_name="svc-a")
    session = WorkflowSessionRecord(
        session_id="wf-1", product_name="Prod", analysis_scope="full", repositories=[repo_a]
    )
    state = _make_state(session=session)
    guard_service = MagicMock()
    knowledge_service = MagicMock()
    llm_service = MagicMock()

    guard_service.start_repository = AsyncMock(return_value=GuardOperationResult(session=session))
    llm_service.run_task = AsyncMock(
        return_value=LlmTaskResult(
            task_kind=LlmTaskKind.STEP_EXECUTION,
            step_id=StepId.ASSESS_SCOPE_AND_DOMAINS,
            notes="забыл вернуть domain_assessment",
        )
    )

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_knowledge_artifact_service", return_value=knowledge_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service", return_value=llm_service),
    ):
        result = await nodes_module.node_assess_scope_and_domains(state)

    assert result["retry_count"] == 1
    assert "missing domain assessment" in result["step_error"]
    guard_service.assess_repository_domains.assert_not_called()
    guard_service.advance_step.assert_not_called()
    knowledge_service.write_domain_map.assert_not_called()


async def test_node_assess_scope_and_domains_preserves_partial_progress_on_failure() -> None:
    """A failure on the second repository must not discard the first repository's already-saved assessment.

    Returning `session` from the exception branch is what makes retry pick up only the
    repository that actually failed, instead of redoing the whole loop from scratch.
    """
    repo_a = RepositoryExecution(repository_name="svc-a")
    repo_b = RepositoryExecution(repository_name="svc-b")
    session = WorkflowSessionRecord(
        session_id="wf-1", product_name="Prod", analysis_scope="full", repositories=[repo_a, repo_b]
    )
    state = _make_state(session=session)
    guard_service = MagicMock()
    knowledge_service = MagicMock()
    llm_service = MagicMock()

    assessed_a_session = session.model_copy(
        update={
            "repositories": [
                repo_a.model_copy(
                    update={"volume_class": VolumeClass.SMALL, "domain_strategy": DomainStrategy.PER_MODULE}
                ),
                repo_b,
            ]
        }
    )

    guard_service.start_repository = AsyncMock(
        side_effect=lambda current_session, **_kwargs: GuardOperationResult(session=current_session)
    )
    guard_service.assess_repository_domains = AsyncMock(return_value=GuardOperationResult(session=assessed_a_session))
    llm_service.run_task = AsyncMock(
        side_effect=[
            LlmTaskResult(
                task_kind=LlmTaskKind.STEP_EXECUTION,
                step_id=StepId.ASSESS_SCOPE_AND_DOMAINS,
                domain_assessment=RepositoryDomainAssessment(
                    volume_class=VolumeClass.SMALL, strategy=DomainStrategy.PER_MODULE
                ),
            ),
            LlmTaskResult(
                task_kind=LlmTaskKind.STEP_EXECUTION,
                step_id=StepId.ASSESS_SCOPE_AND_DOMAINS,
                notes="забыл вернуть domain_assessment для svc-b",
            ),
        ]
    )

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_knowledge_artifact_service", return_value=knowledge_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service", return_value=llm_service),
    ):
        result = await nodes_module.node_assess_scope_and_domains(state)

    assert result["retry_count"] == 1
    assert "missing domain assessment for repository 'svc-b'" in result["step_error"]
    assert result["session"].repositories[0].domain_strategy is DomainStrategy.PER_MODULE
    assert result["session"].repositories[1].domain_strategy is None
    knowledge_service.write_domain_map.assert_not_called()


async def test_node_assess_scope_and_domains_skips_already_assessed_repository_on_retry() -> None:
    repo_a = RepositoryExecution(
        repository_name="svc-a", volume_class=VolumeClass.SMALL, domain_strategy=DomainStrategy.PER_MODULE
    )
    repo_b = RepositoryExecution(repository_name="svc-b")
    session = WorkflowSessionRecord(
        session_id="wf-1", product_name="Prod", analysis_scope="full", repositories=[repo_a, repo_b]
    )
    state = _make_state(session=session)
    guard_service = MagicMock()
    knowledge_service = MagicMock()
    llm_service = MagicMock()

    assessed_b_session = session.model_copy(
        update={
            "repositories": [
                repo_a,
                repo_b.model_copy(
                    update={"volume_class": VolumeClass.LARGE, "domain_strategy": DomainStrategy.PER_DOMAIN}
                ),
            ]
        }
    )
    next_session = assessed_b_session.model_copy(
        update={"current_step": StepId.ANALYZE_REPOSITORIES, "completed_steps": [StepId.ASSESS_SCOPE_AND_DOMAINS]}
    )

    guard_service.start_repository = AsyncMock(return_value=GuardOperationResult(session=session))
    guard_service.assess_repository_domains = AsyncMock(return_value=GuardOperationResult(session=assessed_b_session))
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=next_session))
    knowledge_service.write_domain_map = AsyncMock(
        return_value=KnowledgeArtifactResult(session=assessed_b_session, summary="wrote domain map")
    )
    llm_service.run_task = AsyncMock(
        return_value=LlmTaskResult(
            task_kind=LlmTaskKind.STEP_EXECUTION,
            step_id=StepId.ASSESS_SCOPE_AND_DOMAINS,
            domain_assessment=RepositoryDomainAssessment(
                volume_class=VolumeClass.LARGE, strategy=DomainStrategy.PER_DOMAIN
            ),
        )
    )

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_knowledge_artifact_service", return_value=knowledge_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service", return_value=llm_service),
    ):
        result = await nodes_module.node_assess_scope_and_domains(state)

    assert result["current_step_id"] == "analyze_repositories"
    guard_service.start_repository.assert_awaited_once_with(
        session, repository_name="svc-b", progress_file_path=state["progress_file_path"]
    )
    llm_service.run_task.assert_awaited_once()
    guard_service.assess_repository_domains.assert_awaited_once()
    assert guard_service.assess_repository_domains.await_args.kwargs["repository_name"] == "svc-b"


def test_require_domain_assessment_complete_raises_on_incomplete_session() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="Prod",
        analysis_scope="full",
        repositories=[RepositoryExecution(repository_name="svc-a")],
    )

    with pytest.raises(nodes_module.DomainOperationError, match="incomplete"):
        nodes_module._require_domain_assessment_complete(session)


async def test_node_analyze_repositories_advances_to_interview_user_without_pending_repository() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="Prod",
        analysis_scope="full",
        current_step=StepId.ANALYZE_REPOSITORIES,
        repositories=[RepositoryExecution(repository_name="svc-a", analysis_status="completed")],
    )
    state = _make_state(session=session)
    guard_service = MagicMock()
    knowledge_service = MagicMock()
    next_session = session.model_copy(
        update={"current_step": StepId.INTERVIEW_USER, "completed_steps": [StepId.ANALYZE_REPOSITORIES]}
    )
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=next_session))
    guard_service.start_repository = AsyncMock()
    knowledge_service.sync_open_questions = AsyncMock()

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_knowledge_artifact_service", return_value=knowledge_service),
    ):
        result = await nodes_module.node_analyze_repositories(state)

    assert result["current_step_id"] == "interview_user"
    guard_service.advance_step.assert_awaited_once_with(
        session, StepId.INTERVIEW_USER, progress_file_path=state["progress_file_path"]
    )
    guard_service.start_repository.assert_not_awaited()
    knowledge_service.sync_open_questions.assert_not_awaited()


async def test_node_analyze_repositories_syncs_open_questions_before_advancing() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="Prod",
        analysis_scope="full",
        current_step=StepId.ANALYZE_REPOSITORIES,
        repositories=[RepositoryExecution(repository_name="svc-a", analysis_status="completed")],
        open_questions=[OpenQuestionRecord(question_id="Q-1", question_text="What protocol is exposed?")],
    )
    state = _make_state(session=session)
    guard_service = MagicMock()
    knowledge_service = MagicMock()
    synced_session = session.model_copy()
    next_session = synced_session.model_copy(update={"current_step": StepId.INTERVIEW_USER})
    knowledge_service.sync_open_questions = AsyncMock(
        return_value=KnowledgeArtifactResult(session=synced_session, summary="synced")
    )
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=next_session))

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_knowledge_artifact_service", return_value=knowledge_service),
    ):
        result = await nodes_module.node_analyze_repositories(state)

    assert result["current_step_id"] == "interview_user"
    knowledge_service.sync_open_questions.assert_awaited_once_with(session, arch_repo_dir=state["arch_repo_dir"])
    guard_service.advance_step.assert_awaited_once_with(
        synced_session, StepId.INTERVIEW_USER, progress_file_path=state["progress_file_path"]
    )


async def test_node_analyze_repositories_starts_pending_repository_without_advancing() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="Prod",
        analysis_scope="full",
        current_step=StepId.ANALYZE_REPOSITORIES,
        repositories=[RepositoryExecution(repository_name="svc-a", analysis_status="pending")],
    )
    state = _make_state(session=session)
    guard_service = MagicMock()
    started_session = session.model_copy(
        update={"repositories": [session.repositories[0].model_copy(update={"analysis_status": "in_progress"})]}
    )
    guard_service.start_repository = AsyncMock(return_value=GuardOperationResult(session=started_session))
    guard_service.advance_step = AsyncMock()

    with patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service):
        result = await nodes_module.node_analyze_repositories(state)

    guard_service.start_repository.assert_awaited_once_with(
        session, repository_name="svc-a", progress_file_path=state["progress_file_path"]
    )
    guard_service.advance_step.assert_not_awaited()
    assert result["session"] is started_session
    assert result["current_step_id"] == StepId.ANALYZE_REPOSITORIES.value


async def test_node_analyze_repositories_resumes_in_progress_repository_without_restarting_it() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="Prod",
        analysis_scope="full",
        current_step=StepId.ANALYZE_REPOSITORIES,
        repositories=[RepositoryExecution(repository_name="svc-a", analysis_status="in_progress")],
    )
    state = _make_state(session=session)
    guard_service = MagicMock()
    guard_service.start_repository = AsyncMock()

    with patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service):
        result = await nodes_module.node_analyze_repositories(state)

    guard_service.start_repository.assert_not_awaited()
    assert result["session"] is session


async def test_node_analyze_repositories_returns_partial_session_on_error() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="Prod",
        analysis_scope="full",
        current_step=StepId.ANALYZE_REPOSITORIES,
        repositories=[RepositoryExecution(repository_name="svc-a", analysis_status="pending")],
    )
    state = _make_state(session=session)
    guard_service = MagicMock()
    guard_service.start_repository = AsyncMock(side_effect=RuntimeError("guard boom"))

    with patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service):
        result = await nodes_module.node_analyze_repositories(state)

    assert result["session"] is session
    assert result["step_error"] == "guard boom"
    assert result["retry_count"] == 1


async def test_node_analyze_repositories_item_processes_next_pending_item() -> None:
    repository = RepositoryExecution(
        repository_name="svc-a",
        analysis_target_commit_status=AnalysisTargetCommitStatus.PENDING,
        analysis_status="in_progress",
    )
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="Prod",
        analysis_scope="full",
        current_step=StepId.ANALYZE_REPOSITORIES,
        repositories=[repository],
    )
    state = _make_state(session=session)
    guard_service = MagicMock()
    llm_service = MagicMock()
    audit_service = MagicMock()

    first_item_id = next(iter(nodes_module.CHECKLIST_ITEM_TO_REFERENCE))
    item_completed_session = session.model_copy(
        update={
            "repositories": [repository.model_copy(update={"checklist_items_completed": [first_item_id]})],
        }
    )
    guard_service.complete_repository_item = AsyncMock(
        return_value=GuardOperationResult(session=item_completed_session, bridge_output="done")
    )
    llm_service.run_task = AsyncMock(
        return_value=LlmTaskResult(task_kind=LlmTaskKind.REPOSITORY_CHECKLIST_ITEM, step_id=StepId.ANALYZE_REPOSITORIES)
    )

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service", return_value=llm_service),
        patch("app.workflows.init_arch.nodes.get_workflow_audit_service", return_value=audit_service),
    ):
        result = await nodes_module.node_analyze_repositories_item(state)

    llm_service.run_task.assert_awaited_once()
    guard_service.complete_repository_item.assert_awaited_once_with(
        session, repository_name="svc-a", item_id=first_item_id, progress_file_path=state["progress_file_path"]
    )
    assert result["session"] is item_completed_session
    routed_events = [
        call.args[0]
        for call in audit_service.record.call_args_list
        if call.args[0].event_type is EventType.DIFF_SIGNAL_ROUTED
    ]
    assert len(routed_events) == 1
    assert routed_events[0].payload["routed_items"] == "1"


async def test_node_analyze_repositories_item_registers_open_questions_from_llm_result() -> None:
    repository = RepositoryExecution(
        repository_name="svc-a",
        analysis_target_commit_status=AnalysisTargetCommitStatus.PENDING,
        analysis_status="in_progress",
    )
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="Prod",
        analysis_scope="full",
        current_step=StepId.ANALYZE_REPOSITORIES,
        repositories=[repository],
    )
    state = _make_state(session=session)
    guard_service = MagicMock()
    llm_service = MagicMock()

    first_item_id = next(iter(nodes_module.CHECKLIST_ITEM_TO_REFERENCE))
    item_completed_session = session.model_copy(
        update={
            "repositories": [repository.model_copy(update={"checklist_items_completed": [first_item_id]})],
        }
    )
    questioned_session = item_completed_session.model_copy(
        update={"open_questions": [OpenQuestionRecord(question_id="Q-1", question_text="What protocol is exposed?")]}
    )
    guard_service.complete_repository_item = AsyncMock(
        return_value=GuardOperationResult(session=item_completed_session)
    )
    guard_service.register_open_questions = AsyncMock(return_value=GuardOperationResult(session=questioned_session))
    llm_service.run_task = AsyncMock(
        return_value=LlmTaskResult(
            task_kind=LlmTaskKind.REPOSITORY_CHECKLIST_ITEM,
            step_id=StepId.ANALYZE_REPOSITORIES,
            open_questions_found=["What protocol is exposed?"],
        )
    )

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service", return_value=llm_service),
    ):
        result = await nodes_module.node_analyze_repositories_item(state)

    guard_service.register_open_questions.assert_awaited_once_with(
        item_completed_session,
        question_texts=["What protocol is exposed?"],
        repository_name="svc-a",
        progress_file_path=state["progress_file_path"],
    )
    assert result["session"] is questioned_session


async def test_node_analyze_repositories_item_routes_reduced_checklist_for_no_changes_window() -> None:
    repository = RepositoryExecution(
        repository_name="svc-a",
        analysis_target_commit_status=AnalysisTargetCommitStatus.CHECKED_OUT,
        commit_range_status=CommitRangeStatus.NO_CHANGES,
        analysis_status="in_progress",
    )
    session = WorkflowSessionRecord(
        session_id="wf-1", product_name="Prod", analysis_scope="full", repositories=[repository]
    )
    state = _make_state(session=session)
    guard_service = MagicMock()
    llm_service = MagicMock()
    audit_service = MagicMock()

    item_completed_session = session.model_copy(
        update={
            "repositories": [
                repository.model_copy(update={"checklist_items_completed": ["repository_consistency_review"]})
            ],
        }
    )
    guard_service.complete_repository_item = AsyncMock(
        return_value=GuardOperationResult(session=item_completed_session)
    )
    llm_service.run_task = AsyncMock(
        return_value=LlmTaskResult(task_kind=LlmTaskKind.REPOSITORY_CHECKLIST_ITEM, step_id=StepId.ANALYZE_REPOSITORIES)
    )

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service", return_value=llm_service),
        patch("app.workflows.init_arch.nodes.get_workflow_audit_service", return_value=audit_service),
    ):
        result = await nodes_module.node_analyze_repositories_item(state)

    assert result["session"] is item_completed_session
    llm_service.run_task.assert_awaited_once()
    guard_service.complete_repository_item.assert_awaited_once_with(
        session,
        repository_name="svc-a",
        item_id="repository_consistency_review",
        progress_file_path=state["progress_file_path"],
    )
    routed_events = [
        call.args[0]
        for call in audit_service.record.call_args_list
        if call.args[0].event_type is EventType.DIFF_SIGNAL_ROUTED
    ]
    assert len(routed_events) == 1
    assert routed_events[0].repository_name == "svc-a"
    assert routed_events[0].payload["diff_severity"] == "no_signal"
    assert routed_events[0].payload["routed_items"] == "1"


async def test_node_analyze_repositories_item_completes_repository_when_no_items_remain() -> None:
    all_items = list(nodes_module.CHECKLIST_ITEM_TO_REFERENCE)
    repository = RepositoryExecution(
        repository_name="svc-a",
        analysis_target_commit_status=AnalysisTargetCommitStatus.PENDING,
        analysis_status="in_progress",
        checklist_items_completed=all_items,
    )
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="Prod",
        analysis_scope="full",
        repositories=[repository],
    )
    state = _make_state(session=session)
    guard_service = MagicMock()
    llm_service = MagicMock()
    completed_repo_session = session.model_copy(
        update={"repositories": [repository.model_copy(update={"analysis_status": "completed"})]}
    )
    guard_service.complete_repository = AsyncMock(
        return_value=GuardOperationResult(session=completed_repo_session, bridge_output="repo done")
    )

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service", return_value=llm_service),
    ):
        result = await nodes_module.node_analyze_repositories_item(state)

    llm_service.run_task.assert_not_called()
    guard_service.complete_repository.assert_awaited_once_with(
        session, repository_name="svc-a", progress_file_path=state["progress_file_path"]
    )
    assert result["session"] is completed_repo_session


async def test_node_analyze_repositories_item_reports_step_error_without_in_progress_repository() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="Prod",
        analysis_scope="full",
        repositories=[RepositoryExecution(repository_name="svc-a", analysis_status="pending")],
    )
    state = _make_state(session=session)

    result = await nodes_module.node_analyze_repositories_item(state)

    assert result["session"] is session
    assert result["step_error"] is not None
    assert "no in-progress repository" in result["step_error"]
    assert result["retry_count"] == 1


async def test_node_analyze_repositories_item_returns_partial_session_on_error() -> None:
    repository = RepositoryExecution(
        repository_name="svc-a",
        analysis_target_commit_status=AnalysisTargetCommitStatus.PENDING,
        analysis_status="in_progress",
    )
    session = WorkflowSessionRecord(
        session_id="wf-1", product_name="Prod", analysis_scope="full", repositories=[repository]
    )
    state = _make_state(session=session)
    llm_service = MagicMock()
    llm_service.run_task = AsyncMock(side_effect=RuntimeError("llm boom"))

    with patch("app.workflows.init_arch.nodes.get_llm_worker_service", return_value=llm_service):
        result = await nodes_module.node_analyze_repositories_item(state)

    assert result["session"] is session
    assert result["step_error"] == "llm boom"
    assert result["retry_count"] == 1


async def test_node_interview_user_interrupts_on_open_question() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="Prod",
        analysis_scope="full",
        open_questions=[OpenQuestionRecord(question_id="Q-1", question_text="What is X?")],
    )
    state = _make_state(session=session)
    with patch("app.workflows.init_arch.nodes.interrupt") as mock_interrupt:
        mock_interrupt.side_effect = KeyboardInterrupt("interrupt")
        with pytest.raises(KeyboardInterrupt, match="interrupt"):
            await nodes_module.node_interview_user(state)
        mock_interrupt.assert_called_once()


async def test_node_interview_user_records_answer_and_advances_after_reconcile() -> None:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="Prod",
        analysis_scope="full",
        current_step=StepId.INTERVIEW_USER,
        completed_steps=[StepId.ANALYZE_REPOSITORIES],
        open_questions=[OpenQuestionRecord(question_id="Q-1", question_text="What is X?")],
    )
    state = _make_state(session=session)
    guard_service = MagicMock()
    knowledge_service = MagicMock()
    llm_service = MagicMock()

    answered_session = session.model_copy(
        update={
            "open_questions": [
                session.open_questions[0].model_copy(update={"status": "answered", "answer_text": "REST"})
            ]
        }
    )
    closed_session = answered_session.model_copy(
        update={"open_questions": [answered_session.open_questions[0].model_copy(update={"status": "closed"})]}
    )
    next_session = closed_session.model_copy(
        update={
            "current_step": StepId.REFINE_FEATURES,
            "completed_steps": [StepId.ANALYZE_REPOSITORIES, StepId.INTERVIEW_USER],
        }
    )
    guard_service.record_user_answer = AsyncMock(return_value=GuardOperationResult(session=answered_session))
    guard_service.close_user_question = AsyncMock(return_value=GuardOperationResult(session=closed_session))
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=next_session))
    knowledge_service.collect_worker_artifacts = AsyncMock(
        return_value=KnowledgeArtifactResult(session=answered_session, summary="registered")
    )
    knowledge_service.sync_open_questions = AsyncMock(
        return_value=KnowledgeArtifactResult(session=closed_session, summary="synced")
    )
    llm_service.run_task = AsyncMock(
        return_value=LlmTaskResult(
            task_kind=LlmTaskKind.INTERVIEW_RECONCILIATION,
            step_id=StepId.INTERVIEW_USER,
            created_artifacts=["open-questions.md"],
        )
    )

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_knowledge_artifact_service", return_value=knowledge_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service", return_value=llm_service),
        patch("app.workflows.init_arch.nodes.interrupt", return_value={"answer": "REST"}),
    ):
        result = await nodes_module.node_interview_user(state)

    assert result["current_step_id"] == "refine_features"
    guard_service.record_user_answer.assert_awaited_once()
    guard_service.close_user_question.assert_awaited_once()
    guard_service.advance_step.assert_awaited_once()
    knowledge_service.collect_worker_artifacts.assert_awaited_once()
    knowledge_service.sync_open_questions.assert_awaited_once()
    llm_service.run_task.assert_awaited_once()


async def test_node_refine_features_bootstraps_and_registers_worker_artifacts() -> None:
    state = _make_state()
    guard_service = MagicMock()
    knowledge_service = MagicMock()
    llm_service = MagicMock()

    bootstrapped_session = state["session"].model_copy()
    refined_session = bootstrapped_session.model_copy(
        update={
            "artifacts": [],
        }
    )
    next_session = refined_session.model_copy(
        update={
            "current_step": StepId.BUILD_NAVIGATION_INDEX,
            "completed_steps": [StepId.REFINE_FEATURES],
        }
    )
    knowledge_service.bootstrap_arch_repo = AsyncMock(
        return_value=KnowledgeArtifactResult(session=bootstrapped_session, summary="bootstrapped")
    )
    knowledge_service.collect_worker_artifacts = AsyncMock(
        return_value=KnowledgeArtifactResult(session=refined_session, summary="registered")
    )
    llm_service.run_task = AsyncMock(
        return_value=LlmTaskResult(
            task_kind=LlmTaskKind.KNOWLEDGE_SYNTHESIS,
            step_id=StepId.REFINE_FEATURES,
            created_artifacts=["features/service-a.md"],
        )
    )
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=next_session))

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_knowledge_artifact_service", return_value=knowledge_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service", return_value=llm_service),
    ):
        result = await nodes_module.node_refine_features(state)

    assert result["current_step_id"] == "build_navigation_index"
    knowledge_service.bootstrap_arch_repo.assert_awaited_once()
    knowledge_service.collect_worker_artifacts.assert_awaited_once()
    llm_service.run_task.assert_awaited_once()


async def test_node_build_navigation_index_uses_knowledge_service_without_llm() -> None:
    state = _make_state()
    guard_service = MagicMock()
    knowledge_service = MagicMock()
    compiled_session = state["session"].model_copy()
    next_session = compiled_session.model_copy(
        update={
            "current_step": StepId.RUN_KNOWLEDGE_LINT,
            "completed_steps": [StepId.BUILD_NAVIGATION_INDEX],
        }
    )
    knowledge_service.compile_navigation = AsyncMock(
        return_value=KnowledgeArtifactResult(session=compiled_session, summary="compiled")
    )
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=next_session))

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_knowledge_artifact_service", return_value=knowledge_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service") as llm_service,
    ):
        result = await nodes_module.node_build_navigation_index(state)

    assert result["current_step_id"] == "run_knowledge_lint"
    knowledge_service.compile_navigation.assert_awaited_once()
    llm_service.assert_not_called()


async def test_node_run_knowledge_lint_uses_knowledge_service_without_llm() -> None:
    state = _make_state()
    guard_service = MagicMock()
    knowledge_service = MagicMock()
    linted_session = state["session"].model_copy()
    next_session = linted_session.model_copy(
        update={
            "current_step": StepId.VALIDATE_FINAL,
            "completed_steps": [StepId.RUN_KNOWLEDGE_LINT],
        }
    )
    knowledge_service.lint_knowledge = AsyncMock(
        return_value=KnowledgeArtifactResult(session=linted_session, summary="lint clean")
    )
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=next_session))

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_knowledge_artifact_service", return_value=knowledge_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service") as llm_service,
    ):
        result = await nodes_module.node_run_knowledge_lint(state)

    assert result["current_step_id"] == "validate_final"
    knowledge_service.lint_knowledge.assert_awaited_once()
    llm_service.assert_not_called()


async def test_node_generate_release_notes_registers_artifact_and_advances() -> None:
    state = _make_state()
    guard_service = MagicMock()
    llm_service = MagicMock()
    knowledge_service = MagicMock()
    audit_service = MagicMock()

    llm_service.run_task = AsyncMock(
        return_value=LlmTaskResult(
            task_kind=LlmTaskKind.STEP_EXECUTION,
            step_id=StepId.GENERATE_RELEASE_NOTES,
            created_artifacts=["release-notes/window-0-2024-07-10.md"],
        )
    )
    registered_session = state["session"].model_copy()
    knowledge_service.collect_worker_artifacts = AsyncMock(
        return_value=KnowledgeArtifactResult(
            session=registered_session,
            written_artifacts=["release-notes/window-0-2024-07-10.md"],
        )
    )
    next_session = registered_session.model_copy(
        update={
            "current_step": StepId.CONFIRM_NEXT_TEMPORAL_WINDOW,
            "completed_steps": [StepId.GENERATE_RELEASE_NOTES],
        }
    )
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=next_session))

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service", return_value=llm_service),
        patch("app.workflows.init_arch.nodes.get_knowledge_artifact_service", return_value=knowledge_service),
        patch("app.workflows.init_arch.nodes.get_workflow_audit_service", return_value=audit_service),
    ):
        result = await nodes_module.node_generate_release_notes(state)

    assert result["current_step_id"] == "confirm_next_temporal_window"
    knowledge_service.collect_worker_artifacts.assert_awaited_once_with(
        state["session"],
        step_id=StepId.GENERATE_RELEASE_NOTES,
        created_artifacts=["release-notes/window-0-2024-07-10.md"],
    )
    guard_service.advance_step.assert_awaited_once()


async def test_node_finalize_progress_uses_guard_service() -> None:
    state = _make_state()
    guard_service = MagicMock()
    audit_service = MagicMock()
    finalized = state["session"].model_copy(update={"current_step": StepId.DONE})
    guard_service.finalize_progress = AsyncMock(return_value=GuardOperationResult(session=finalized))

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_workflow_audit_service", return_value=audit_service),
    ):
        result = await nodes_module.node_finalize_progress(state)

    assert result["current_step_id"] == "done"
    assert result["session"].current_step is StepId.DONE
    recorded_events = [call.args[0] for call in audit_service.record.call_args_list]
    assert [event.event_type for event in recorded_events] == [
        EventType.WORKFLOW_STEP_STARTED,
        EventType.WORKFLOW_STEP_COMPLETED,
    ]


async def test_node_confirm_next_temporal_window_advances_when_no_more_windows() -> None:
    state = _make_state()
    guard_service = MagicMock()
    historical_service = MagicMock()
    historical_service.compute_next_window = MagicMock(return_value=None)
    finalize_ready_session = state["session"].model_copy(update={"current_step": StepId.FINALIZE_PROGRESS})
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=finalize_ready_session))

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_historical_prep_service", return_value=historical_service),
        patch("app.workflows.init_arch.nodes.interrupt") as mock_interrupt,
    ):
        result = await nodes_module.node_confirm_next_temporal_window(state)

    assert result["current_step_id"] == "finalize_progress"
    mock_interrupt.assert_not_called()
    guard_service.advance_step.assert_awaited_once_with(
        state["session"],
        StepId.FINALIZE_PROGRESS,
        progress_file_path=state["progress_file_path"],
        note="No further temporal windows to analyze",
    )


async def test_node_confirm_next_temporal_window_continues_and_resets_repository_progress() -> None:
    state = _make_state()
    state["session"] = state["session"].model_copy(
        update={
            "repositories": [
                state["session"]
                .repositories[0]
                .model_copy(
                    update={"checklist_items_completed": ["repository_classification"], "analysis_status": "completed"}
                )
            ]
        }
    )
    guard_service = MagicMock()
    historical_service = MagicMock()
    historical_service.compute_next_window = MagicMock(return_value=dt.date(2024, 7, 10))
    guard_service.request_next_temporal_window = AsyncMock(return_value=GuardOperationResult(session=state["session"]))
    guard_service.confirm_next_temporal_window = AsyncMock(return_value=GuardOperationResult(session=state["session"]))
    refresh_ready_session = state["session"].model_copy(update={"current_step": StepId.REFRESH_MAIN_BRANCHES})
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=refresh_ready_session))

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_historical_prep_service", return_value=historical_service),
        patch("app.workflows.init_arch.nodes.interrupt", return_value={"action": "continue_to_next_window"}),
    ):
        result = await nodes_module.node_confirm_next_temporal_window(state)

    assert result["current_step_id"] == "refresh_main_branches"
    guard_service.confirm_next_temporal_window.assert_awaited_once()
    reset_session = guard_service.advance_step.call_args.args[0]
    assert reset_session.repositories[0].checklist_items_completed == []
    assert reset_session.repositories[0].analysis_status == "pending"
    assert guard_service.advance_step.call_args.args[1] is StepId.REFRESH_MAIN_BRANCHES


async def test_node_confirm_next_temporal_window_finishes_on_user_stop() -> None:
    state = _make_state()
    guard_service = MagicMock()
    historical_service = MagicMock()
    historical_service.compute_next_window = MagicMock(return_value=dt.date(2024, 7, 10))
    guard_service.request_next_temporal_window = AsyncMock(return_value=GuardOperationResult(session=state["session"]))
    guard_service.confirm_next_temporal_window = AsyncMock(return_value=GuardOperationResult(session=state["session"]))
    finalize_ready_session = state["session"].model_copy(update={"current_step": StepId.FINALIZE_PROGRESS})
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=finalize_ready_session))

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_historical_prep_service", return_value=historical_service),
        patch("app.workflows.init_arch.nodes.interrupt", return_value={"action": "finish_temporal_analysis"}),
    ):
        result = await nodes_module.node_confirm_next_temporal_window(state)

    assert result["current_step_id"] == "finalize_progress"
    guard_service.advance_step.assert_awaited_once_with(
        state["session"],
        StepId.FINALIZE_PROGRESS,
        progress_file_path=state["progress_file_path"],
        note="User stopped the temporal analysis loop",
    )


async def test_node_confirm_next_temporal_window_propagates_real_interrupt() -> None:
    state = _make_state()
    historical_service = MagicMock()
    historical_service.compute_next_window = MagicMock(return_value=dt.date(2024, 7, 10))

    with (
        patch("app.workflows.init_arch.nodes.get_historical_prep_service", return_value=historical_service),
        patch("app.workflows.init_arch.nodes.interrupt") as mock_interrupt,
    ):
        mock_interrupt.side_effect = KeyboardInterrupt("interrupt")
        with pytest.raises(KeyboardInterrupt, match="interrupt"):
            await nodes_module.node_confirm_next_temporal_window(state)
        mock_interrupt.assert_called_once()


def test_extract_window_confirmation_action_rejects_unknown_action() -> None:
    with pytest.raises(ValueError, match="continue_to_next_window"):
        nodes_module._extract_window_confirmation_action({"action": "not_a_real_action"})


def test_extract_question_answer_validates_and_normalizes_input() -> None:
    assert nodes_module._extract_question_answer({"answer": "  REST  "}) == "REST"

    with pytest.raises(ValueError, match="non-empty answer"):
        nodes_module._extract_question_answer({"answer": "   "})


async def test_node_handle_error_retry_resets_step_error_and_retry_count() -> None:
    state = _make_state(step_error="boom", retry_count=3)

    with patch("app.workflows.init_arch.nodes.interrupt", return_value={"action": "retry"}) as mock_interrupt:
        result = await nodes_module.node_handle_error(state)

    assert result == {"step_error": None, "retry_count": 0}
    interrupt_payload = mock_interrupt.call_args.args[0]
    assert interrupt_payload["interrupt_type"] == "step_failed"
    assert interrupt_payload["step_id"] == state["session"].current_step.value
    assert interrupt_payload["error"] == "boom"
    assert interrupt_payload["retry_count"] == 3


async def test_node_handle_error_abort_preserves_failure() -> None:
    state = _make_state(step_error="boom", retry_count=3)

    with patch("app.workflows.init_arch.nodes.interrupt", return_value={"action": "abort"}):
        result = await nodes_module.node_handle_error(state)

    assert result == {"step_error": "boom", "retry_count": 3}


def test_extract_step_failure_recovery_action_rejects_unknown_action() -> None:
    with pytest.raises(ValueError, match=r"retry.*abort"):
        nodes_module._extract_step_failure_recovery_action({"action": "not_a_real_action"})
