import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workflows.init_arch import nodes as nodes_module
from app.workflows.init_arch.domain import (
    AnalysisTargetCommitStatus,
    AuditActor,
    EventType,
    LlmTaskKind,
    LlmTaskResult,
    OpenQuestionRecord,
    RepositoryExecution,
    StepId,
    WorkflowSessionRecord,
)
from app.workflows.init_arch.guard import GuardOperationResult
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


async def test_node_define_scope_uses_guard_and_worker_services() -> None:
    state = _make_state()
    guard_service = MagicMock()
    llm_service = MagicMock()
    audit_service = MagicMock()

    initialized_session = state["session"].model_copy()
    advanced_session = initialized_session.model_copy(
        update={"current_step": StepId.REQUEST_REPOSITORY_LIST, "completed_steps": [StepId.DEFINE_SCOPE]}
    )
    guard_service.init_progress = AsyncMock(return_value=GuardOperationResult(session=initialized_session))
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=advanced_session))
    llm_service.run_task = AsyncMock(
        return_value=LlmTaskResult(task_kind=LlmTaskKind.STEP_EXECUTION, step_id=StepId.DEFINE_SCOPE)
    )

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service", return_value=llm_service),
        patch("app.workflows.init_arch.nodes.get_workflow_audit_service", return_value=audit_service),
    ):
        result = await nodes_module.node_define_scope(state)

    assert result["current_step_id"] == "request_repository_list"
    assert result["session"].current_step is StepId.REQUEST_REPOSITORY_LIST
    llm_service.run_task.assert_awaited_once()
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


async def test_node_request_repository_list_interrupts_without_repositories() -> None:
    session = WorkflowSessionRecord(session_id="wf-1", product_name="Prod", analysis_scope="full")
    state = _make_state(session=session)
    with patch("app.workflows.init_arch.nodes.interrupt") as mock_interrupt:
        mock_interrupt.side_effect = Exception("interrupt called")
        with pytest.raises(Exception, match="interrupt called"):
            await nodes_module.node_request_repository_list(state)
        mock_interrupt.assert_called_once()


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


async def test_node_analyze_repositories_uses_typed_services() -> None:
    repository = RepositoryExecution(
        repository_name="svc-a", analysis_target_commit_status=AnalysisTargetCommitStatus.PENDING
    )
    session = WorkflowSessionRecord(
        session_id="wf-1", product_name="Prod", analysis_scope="full", repositories=[repository]
    )
    state = _make_state(session=session)
    guard_service = MagicMock()
    knowledge_service = MagicMock()
    llm_service = MagicMock()

    running_session = session.model_copy(
        update={
            "historical_analysis": session.historical_analysis.model_copy(
                update={"ordered_repository_names": ["svc-a"]}
            ),
            "current_step": StepId.ANALYZE_REPOSITORIES,
        }
    )
    completed_repo_session = running_session.model_copy()
    questioned_session = completed_repo_session.model_copy(
        update={"open_questions": [OpenQuestionRecord(question_id="Q-1", question_text="What protocol is exposed?")]}
    )
    next_session = running_session.model_copy(
        update={"current_step": StepId.INTERVIEW_USER, "completed_steps": [StepId.ANALYZE_REPOSITORIES]}
    )
    guard_service.start_repository = AsyncMock(return_value=GuardOperationResult(session=running_session))
    guard_service.complete_repository_item = AsyncMock(
        return_value=GuardOperationResult(session=completed_repo_session)
    )
    guard_service.complete_repository = AsyncMock(return_value=GuardOperationResult(session=questioned_session))
    guard_service.register_open_questions = AsyncMock(return_value=GuardOperationResult(session=questioned_session))
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=next_session))
    knowledge_service.sync_open_questions = AsyncMock(
        return_value=KnowledgeArtifactResult(session=questioned_session, summary="synced")
    )
    llm_service.run_task = AsyncMock(
        side_effect=[
            *[
                LlmTaskResult(
                    task_kind=LlmTaskKind.REPOSITORY_CHECKLIST_ITEM,
                    step_id=StepId.ANALYZE_REPOSITORIES,
                )
                for _ in range(len(nodes_module.CHECKLIST_ITEM_TO_REFERENCE) - 1)
            ],
            LlmTaskResult(
                task_kind=LlmTaskKind.REPOSITORY_CHECKLIST_ITEM,
                step_id=StepId.ANALYZE_REPOSITORIES,
                open_questions_found=["What protocol is exposed?"],
            ),
        ]
    )

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_knowledge_artifact_service", return_value=knowledge_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service", return_value=llm_service),
    ):
        result = await nodes_module.node_analyze_repositories(state)

    assert result["current_step_id"] == "interview_user"
    assert llm_service.run_task.await_count == len(nodes_module.CHECKLIST_ITEM_TO_REFERENCE)
    guard_service.start_repository.assert_awaited_once()
    guard_service.complete_repository.assert_awaited_once()
    guard_service.register_open_questions.assert_awaited()
    knowledge_service.sync_open_questions.assert_awaited_once()


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


def test_extract_question_answer_validates_and_normalizes_input() -> None:
    assert nodes_module._extract_question_answer({"answer": "  REST  "}) == "REST"

    with pytest.raises(ValueError, match="non-empty answer"):
        nodes_module._extract_question_answer({"answer": "   "})


async def test_node_handle_error_returns_empty_payload() -> None:
    result = await nodes_module.node_handle_error(_make_state(step_error="boom", retry_count=2))

    assert result == {}
