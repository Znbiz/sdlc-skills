from __future__ import annotations

import datetime as dt
import typing

import structlog
from langgraph.types import interrupt

from app.workflows.init_arch.audit import get_workflow_audit_service
from app.workflows.init_arch.domain import (
    AuditActor,
    EventType,
    LlmTaskKind,
    LlmTaskRequest,
    StepId,
    WorkflowEventRecord,
    classify_diff_severity,
    route_checklist_items,
)
from app.workflows.init_arch.domain.operations import TemporalWindowConfirmationAction
from app.workflows.init_arch.guard import get_guard_service
from app.workflows.init_arch.historical import HistoricalPrepResult, get_historical_prep_service
from app.workflows.init_arch.knowledge import get_knowledge_artifact_service
from app.workflows.init_arch.llm_worker import get_llm_worker_service
from app.workflows.init_arch.prompts import CHECKLIST_ITEM_TO_REFERENCE, build_step_prompt
from app.workflows.init_arch.state import InitArchState

logger = structlog.get_logger()

_MAX_RETRY: typing.Final[int] = 3


def _session_update_payload(
    session,
    *,
    last_llm_result=None,
    last_guard_output: str = "",
) -> dict[str, typing.Any]:
    current_repository = next(
        (repo.repository_name for repo in session.repositories if repo.analysis_status == "in_progress"),
        "",
    )
    return {
        "session": session,
        "session_id": session.session_id,
        "current_step_id": session.current_step.value,
        "completed_steps": [step.value for step in session.completed_steps],
        "current_repo_name": current_repository,
        "last_llm_result": last_llm_result,
        "last_cli_output": "" if last_llm_result is None else last_llm_result.raw_output,
        "last_guard_output": last_guard_output,
        "step_error": None,
        "retry_count": 0,
    }


def _build_task_request(
    state: InitArchState,
    step_id: StepId,
    *,
    task_kind: LlmTaskKind,
    checklist_item_id: str = "",
    repository_name: str = "",
) -> LlmTaskRequest:
    return LlmTaskRequest(
        session_id=state["session"].session_id,
        task_kind=task_kind,
        step_id=step_id,
        prompt_text=build_step_prompt(step_id, state, checklist_item_id=checklist_item_id),
        workspace_dir=state["workspace_dir"],
        timeout_seconds=state["timeout_seconds"],
        expected_schema_name="init_arch_v1",
        repository_name=repository_name,
    )


async def _run_step_worker(
    state: InitArchState,
    step_id: StepId,
    *,
    task_kind: LlmTaskKind = LlmTaskKind.STEP_EXECUTION,
    checklist_item_id: str = "",
    repository_name: str = "",
):
    worker_service = get_llm_worker_service()
    request = _build_task_request(
        state,
        step_id,
        task_kind=task_kind,
        checklist_item_id=checklist_item_id,
        repository_name=repository_name,
    )
    return await worker_service.run_task(request, engine_name=state["engine_name"])


def _record_workflow_event(
    state: InitArchState,
    event_type: EventType,
    *,
    step_id: StepId,
    repository_name: str = "",
    **payload: str,
) -> None:
    get_workflow_audit_service().record(
        WorkflowEventRecord(
            event_type=event_type,
            actor=AuditActor.SERVICE,
            session_id=state["session"].session_id,
            step_id=step_id,
            repository_name=repository_name,
            payload=payload,
        )
    )


async def node_define_scope(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.define_scope")
    guard_service = get_guard_service()
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.DEFINE_SCOPE)
    try:
        init_result = await guard_service.init_progress(
            state["session"],
            progress_file_path=state["progress_file_path"],
        )
        llm_result = await _run_step_worker(state, StepId.DEFINE_SCOPE)
        advance_result = await guard_service.advance_step(
            init_result.session,
            StepId.REQUEST_REPOSITORY_LIST,
            progress_file_path=state["progress_file_path"],
            note="Scope определён через LangGraph",
        )
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_FAILED,
            step_id=StepId.DEFINE_SCOPE,
            error=str(exc),
        )
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    _record_workflow_event(
        state,
        EventType.WORKFLOW_STEP_COMPLETED,
        step_id=StepId.DEFINE_SCOPE,
        next_step=advance_result.session.current_step.value,
    )
    return _session_update_payload(
        advance_result.session,
        last_llm_result=llm_result,
        last_guard_output=init_result.bridge_output,
    )


async def node_request_repository_list(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.request_repository_list")
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.REQUEST_REPOSITORY_LIST)
    if state["session"].repositories:
        guard_service = get_guard_service()
        result = await guard_service.advance_step(
            state["session"],
            StepId.PREPARE_TEMP_WORKSPACE,
            progress_file_path=state["progress_file_path"],
            note=f"Репозитории: {', '.join(repo.repository_name for repo in state['session'].repositories)}",
        )
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_COMPLETED,
            step_id=StepId.REQUEST_REPOSITORY_LIST,
            next_step=result.session.current_step.value,
        )
        return _session_update_payload(
            result.session,
            last_guard_output=result.bridge_output,
        )

    interrupt(
        {
            "interrupt_type": "user_input",
            "field": "repo_list",
            "question": "Укажите список репозиториев для анализа (имена через запятую или JSON-массив)",
        }
    )
    return {}


async def _simple_llm_step(state: InitArchState, current_step: StepId, next_step: StepId) -> dict[str, typing.Any]:
    guard_service = get_guard_service()
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=current_step)
    try:
        llm_result = await _run_step_worker(state, current_step)
        result = await guard_service.advance_step(
            state["session"],
            next_step,
            progress_file_path=state["progress_file_path"],
        )
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_FAILED,
            step_id=current_step,
            error=str(exc),
        )
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    _record_workflow_event(
        state,
        EventType.WORKFLOW_STEP_COMPLETED,
        step_id=current_step,
        next_step=result.session.current_step.value,
    )
    return _session_update_payload(
        result.session,
        last_llm_result=llm_result,
        last_guard_output=result.bridge_output,
    )


async def node_prepare_temp_workspace(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.prepare_temp_workspace")
    return await _simple_llm_step(state, StepId.PREPARE_TEMP_WORKSPACE, StepId.CLONE_REPOSITORIES)


async def node_clone_repositories(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.clone_repositories")
    return await _simple_llm_step(state, StepId.CLONE_REPOSITORIES, StepId.REFRESH_MAIN_BRANCHES)


async def node_refresh_main_branches(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.refresh_main_branches")
    guard_service = get_guard_service()
    historical_service = get_historical_prep_service()
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.REFRESH_MAIN_BRANCHES)
    try:
        historical_result = await historical_service.refresh_main_branches(
            state["session"],
            workspace_dir=state["workspace_dir"],
        )
        result = await guard_service.advance_step(
            historical_result.session,
            StepId.PLAN_REPOSITORY_ORDER,
            progress_file_path=state["progress_file_path"],
            note=historical_result.summary,
        )
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_FAILED,
            step_id=StepId.REFRESH_MAIN_BRANCHES,
            error=str(exc),
        )
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    _record_workflow_event(
        state,
        EventType.WORKFLOW_STEP_COMPLETED,
        step_id=StepId.REFRESH_MAIN_BRANCHES,
        next_step=result.session.current_step.value,
    )
    return _session_update_payload(result.session, last_guard_output=historical_result.summary)


async def node_plan_repository_order(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.plan_repository_order")
    guard_service = get_guard_service()
    historical_service = get_historical_prep_service()
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.PLAN_REPOSITORY_ORDER)
    try:
        planned_result: HistoricalPrepResult = await historical_service.plan_repository_order(state["session"])
        resolved_result: HistoricalPrepResult = await historical_service.resolve_target_commits(
            planned_result.session,
            workspace_dir=state["workspace_dir"],
            checkout=True,
        )
        result = await guard_service.advance_step(
            resolved_result.session,
            StepId.ASSESS_SCOPE_AND_DOMAINS,
            progress_file_path=state["progress_file_path"],
            note=f"{planned_result.summary}; {resolved_result.summary}",
        )
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_FAILED,
            step_id=StepId.PLAN_REPOSITORY_ORDER,
            error=str(exc),
        )
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    _record_workflow_event(
        state,
        EventType.WORKFLOW_STEP_COMPLETED,
        step_id=StepId.PLAN_REPOSITORY_ORDER,
        next_step=result.session.current_step.value,
    )
    return _session_update_payload(result.session, last_guard_output=resolved_result.summary)


async def node_assess_scope_and_domains(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.assess_scope_and_domains")
    return await _simple_llm_step(state, StepId.ASSESS_SCOPE_AND_DOMAINS, StepId.ANALYZE_REPOSITORIES)


async def node_analyze_repositories(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.analyze_repositories")
    guard_service = get_guard_service()
    knowledge_service = get_knowledge_artifact_service()
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.ANALYZE_REPOSITORIES)
    try:
        session = state["session"]
        llm_result = None
        for repository in session.repositories:
            start_result = await guard_service.start_repository(
                session,
                repository_name=repository.repository_name,
                progress_file_path=state["progress_file_path"],
            )
            session = start_result.session

            routed_item_ids = route_checklist_items(
                repository, all_checklist_item_ids=list(CHECKLIST_ITEM_TO_REFERENCE)
            )
            _record_workflow_event(
                state,
                EventType.DIFF_SIGNAL_ROUTED,
                step_id=StepId.ANALYZE_REPOSITORIES,
                repository_name=repository.repository_name,
                diff_severity=classify_diff_severity(repository).value,
                routed_items=str(len(routed_item_ids)),
                total_items=str(len(CHECKLIST_ITEM_TO_REFERENCE)),
            )

            for item_id in routed_item_ids:
                llm_result = await _run_step_worker(
                    {**state, "session": session},
                    StepId.ANALYZE_REPOSITORIES,
                    task_kind=LlmTaskKind.REPOSITORY_CHECKLIST_ITEM,
                    checklist_item_id=item_id,
                    repository_name=repository.repository_name,
                )
                item_result = await guard_service.complete_repository_item(
                    session,
                    repository_name=repository.repository_name,
                    item_id=item_id,
                    progress_file_path=state["progress_file_path"],
                )
                session = item_result.session
                if llm_result.open_questions_found:
                    question_result = await guard_service.register_open_questions(
                        session,
                        question_texts=llm_result.open_questions_found,
                        repository_name=repository.repository_name,
                        progress_file_path=state["progress_file_path"],
                    )
                    session = question_result.session

            complete_result = await guard_service.complete_repository(
                session,
                repository_name=repository.repository_name,
                progress_file_path=state["progress_file_path"],
            )
            session = complete_result.session

        if session.open_questions:
            sync_result = await knowledge_service.sync_open_questions(
                session,
                arch_repo_dir=state["arch_repo_dir"],
            )
            session = sync_result.session

        advance_result = await guard_service.advance_step(
            session,
            StepId.INTERVIEW_USER,
            progress_file_path=state["progress_file_path"],
        )
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_FAILED,
            step_id=StepId.ANALYZE_REPOSITORIES,
            error=str(exc),
        )
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    _record_workflow_event(
        state,
        EventType.WORKFLOW_STEP_COMPLETED,
        step_id=StepId.ANALYZE_REPOSITORIES,
        next_step=advance_result.session.current_step.value,
    )
    return _session_update_payload(
        advance_result.session,
        last_llm_result=llm_result,
        last_guard_output=advance_result.bridge_output,
    )


async def node_interview_user(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.interview_user")
    guard_service = get_guard_service()
    knowledge_service = get_knowledge_artifact_service()
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.INTERVIEW_USER)
    try:
        session = state["session"]
        llm_result = None
        while True:
            remaining = [question for question in session.open_questions if question.status == "open"]
            if not remaining:
                result = await guard_service.advance_step(
                    session,
                    StepId.REFINE_FEATURES,
                    progress_file_path=state["progress_file_path"],
                    note="Все вопросы закрыты",
                )
                _record_workflow_event(
                    state,
                    EventType.WORKFLOW_STEP_COMPLETED,
                    step_id=StepId.INTERVIEW_USER,
                    next_step=result.session.current_step.value,
                )
                return _session_update_payload(
                    result.session,
                    last_llm_result=llm_result,
                    last_guard_output=result.bridge_output,
                )

            current_question = remaining[0]
            resume_payload = interrupt(
                {
                    "interrupt_type": "user_question",
                    "question_id": current_question.question_id,
                    "question": current_question.question_text,
                    "remaining_count": len(remaining) - 1,
                }
            )
            answer_text = _extract_question_answer(resume_payload)
            answer_result = await guard_service.record_user_answer(
                session,
                question_id=current_question.question_id,
                answer_text=answer_text,
                progress_file_path=state["progress_file_path"],
            )
            llm_result = await _run_step_worker(
                {**state, "session": answer_result.session},
                StepId.INTERVIEW_USER,
                task_kind=LlmTaskKind.INTERVIEW_RECONCILIATION,
            )
            knowledge_result = await knowledge_service.collect_worker_artifacts(
                answer_result.session,
                step_id=StepId.INTERVIEW_USER,
                created_artifacts=llm_result.created_artifacts,
            )
            closed_result = await guard_service.close_user_question(
                knowledge_result.session,
                question_id=current_question.question_id,
                progress_file_path=state["progress_file_path"],
            )
            sync_result = await knowledge_service.sync_open_questions(
                closed_result.session,
                arch_repo_dir=state["arch_repo_dir"],
            )
            session = sync_result.session
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_FAILED,
            step_id=StepId.INTERVIEW_USER,
            error=str(exc),
        )
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}


def _extract_question_answer(resume_payload: typing.Any) -> str:
    answer = resume_payload.get("answer") if isinstance(resume_payload, dict) else resume_payload
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("resume payload for user_question must contain a non-empty answer")
    return answer.strip()


async def node_refine_features(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.refine_features")
    guard_service = get_guard_service()
    knowledge_service = get_knowledge_artifact_service()
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.REFINE_FEATURES)
    try:
        bootstrap_result = await knowledge_service.bootstrap_arch_repo(
            state["session"],
            arch_repo_dir=state["arch_repo_dir"],
        )
        llm_result = await _run_step_worker({**state, "session": bootstrap_result.session}, StepId.REFINE_FEATURES)
        knowledge_result = await knowledge_service.collect_worker_artifacts(
            bootstrap_result.session,
            step_id=StepId.REFINE_FEATURES,
            created_artifacts=llm_result.created_artifacts,
        )
        result = await guard_service.advance_step(
            knowledge_result.session,
            StepId.BUILD_NAVIGATION_INDEX,
            progress_file_path=state["progress_file_path"],
            note=f"{bootstrap_result.summary}; {knowledge_result.summary}",
        )
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_FAILED,
            step_id=StepId.REFINE_FEATURES,
            error=str(exc),
        )
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    _record_workflow_event(
        state,
        EventType.WORKFLOW_STEP_COMPLETED,
        step_id=StepId.REFINE_FEATURES,
        next_step=result.session.current_step.value,
    )
    return _session_update_payload(
        result.session,
        last_llm_result=llm_result,
        last_guard_output=result.bridge_output,
    )


async def node_build_navigation_index(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.build_navigation_index")
    guard_service = get_guard_service()
    knowledge_service = get_knowledge_artifact_service()
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.BUILD_NAVIGATION_INDEX)
    try:
        compile_result = await knowledge_service.compile_navigation(
            state["session"],
            arch_repo_dir=state["arch_repo_dir"],
        )
        result = await guard_service.advance_step(
            compile_result.session,
            StepId.RUN_KNOWLEDGE_LINT,
            progress_file_path=state["progress_file_path"],
            note=compile_result.summary,
        )
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_FAILED,
            step_id=StepId.BUILD_NAVIGATION_INDEX,
            error=str(exc),
        )
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    _record_workflow_event(
        state,
        EventType.WORKFLOW_STEP_COMPLETED,
        step_id=StepId.BUILD_NAVIGATION_INDEX,
        next_step=result.session.current_step.value,
    )
    return _session_update_payload(result.session, last_guard_output=result.bridge_output)


async def node_run_knowledge_lint(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.run_knowledge_lint")
    guard_service = get_guard_service()
    knowledge_service = get_knowledge_artifact_service()
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.RUN_KNOWLEDGE_LINT)
    try:
        lint_result = await knowledge_service.lint_knowledge(
            state["session"],
            arch_repo_dir=state["arch_repo_dir"],
        )
        result = await guard_service.advance_step(
            lint_result.session,
            StepId.VALIDATE_FINAL,
            progress_file_path=state["progress_file_path"],
            note=lint_result.summary,
        )
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_FAILED,
            step_id=StepId.RUN_KNOWLEDGE_LINT,
            error=str(exc),
        )
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    _record_workflow_event(
        state,
        EventType.WORKFLOW_STEP_COMPLETED,
        step_id=StepId.RUN_KNOWLEDGE_LINT,
        next_step=result.session.current_step.value,
    )
    return _session_update_payload(result.session, last_guard_output=result.bridge_output)


async def node_validate_final(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.validate_final")
    return await _simple_llm_step(state, StepId.VALIDATE_FINAL, StepId.CONFIRM_NEXT_TEMPORAL_WINDOW)


def _extract_window_confirmation_action(resume_payload: typing.Any) -> TemporalWindowConfirmationAction:
    action = resume_payload.get("action") if isinstance(resume_payload, dict) else resume_payload
    if action not in {"continue_to_next_window", "finish_temporal_analysis"}:
        raise ValueError(
            "resume payload for temporal_window_confirmation must contain action "
            "'continue_to_next_window' or 'finish_temporal_analysis'"
        )
    return typing.cast("TemporalWindowConfirmationAction", action)


async def node_confirm_next_temporal_window(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.confirm_next_temporal_window")
    guard_service = get_guard_service()
    historical_service = get_historical_prep_service()
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.CONFIRM_NEXT_TEMPORAL_WINDOW)
    try:
        session = state["session"]
        next_snapshot_at = historical_service.compute_next_window(session, today=dt.datetime.now(dt.UTC).date())

        if next_snapshot_at is None:
            result = await guard_service.advance_step(
                session,
                StepId.FINALIZE_PROGRESS,
                progress_file_path=state["progress_file_path"],
                note="No further temporal windows to analyze",
            )
        else:
            resume_payload = interrupt(
                {
                    "interrupt_type": "temporal_window_confirmation",
                    "current_snapshot_at": (
                        session.historical_analysis.current_snapshot_at.isoformat()
                        if session.historical_analysis.current_snapshot_at
                        else None
                    ),
                    "next_snapshot_at": next_snapshot_at.isoformat(),
                    "window_index": session.historical_analysis.window_index,
                }
            )
            action = _extract_window_confirmation_action(resume_payload)
            requested_result = await guard_service.request_next_temporal_window(
                session,
                next_snapshot_at=next_snapshot_at,
                progress_file_path=state["progress_file_path"],
            )
            confirmed_result = await guard_service.confirm_next_temporal_window(
                requested_result.session,
                action=action,
                progress_file_path=state["progress_file_path"],
            )
            session = confirmed_result.session

            if action == "continue_to_next_window":
                reset_repositories = [
                    repository.model_copy(update={"checklist_items_completed": [], "analysis_status": "pending"})
                    for repository in session.repositories
                ]
                session = session.model_copy(update={"repositories": reset_repositories})
                result = await guard_service.advance_step(
                    session,
                    StepId.REFRESH_MAIN_BRANCHES,
                    progress_file_path=state["progress_file_path"],
                    note=f"Continuing temporal analysis for window {next_snapshot_at.isoformat()}",
                )
            else:
                result = await guard_service.advance_step(
                    session,
                    StepId.FINALIZE_PROGRESS,
                    progress_file_path=state["progress_file_path"],
                    note="User stopped the temporal analysis loop",
                )
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_FAILED,
            step_id=StepId.CONFIRM_NEXT_TEMPORAL_WINDOW,
            error=str(exc),
        )
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    _record_workflow_event(
        state,
        EventType.WORKFLOW_STEP_COMPLETED,
        step_id=StepId.CONFIRM_NEXT_TEMPORAL_WINDOW,
        next_step=result.session.current_step.value,
    )
    return _session_update_payload(result.session, last_guard_output=result.bridge_output)


async def node_finalize_progress(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.finalize_progress")
    guard_service = get_guard_service()
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.FINALIZE_PROGRESS)
    try:
        result = await guard_service.finalize_progress(
            state["session"],
            progress_file_path=state["progress_file_path"],
        )
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_FAILED,
            step_id=StepId.FINALIZE_PROGRESS,
            error=str(exc),
        )
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    _record_workflow_event(
        state,
        EventType.WORKFLOW_STEP_COMPLETED,
        step_id=StepId.FINALIZE_PROGRESS,
        next_step=result.session.current_step.value,
    )
    return _session_update_payload(
        result.session,
        last_guard_output=result.bridge_output,
    )


async def node_handle_error(state: InitArchState) -> dict[str, typing.Any]:
    logger.error(
        "workflow.node.error",
        step=state["session"].current_step.value,
        error=state.get("step_error"),
        retry_count=state.get("retry_count"),
    )
    return {}
