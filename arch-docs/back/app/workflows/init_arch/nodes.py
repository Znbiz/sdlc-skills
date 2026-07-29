from __future__ import annotations

import asyncio
import datetime as dt
import os
import pathlib
import shutil
import typing

import structlog
from langgraph.types import interrupt

from app.services.git_credentials import classify_git_access_failure, ensure_git_credentials_store
from app.services.repository_url import normalize_repository_url
from app.workflows.init_arch.audit import get_workflow_audit_service
from app.workflows.init_arch.domain import (
    AuditActor,
    DomainOperationError,
    EventType,
    LlmTaskKind,
    LlmTaskRequest,
    LlmTaskResult,
    RepositoryDomainAssessment,
    RepositoryExecution,
    StepId,
    WorkflowEventRecord,
    WorkflowSessionRecord,
    classify_diff_severity,
    domain_assessment_is_complete,
    next_pending_repository,
    pending_checklist_items,
)
from app.workflows.init_arch.domain.operations import StepFailureRecoveryAction, TemporalWindowConfirmationAction
from app.workflows.init_arch.domain.steps import STEP_DEFINITION_BY_ID
from app.workflows.init_arch.guard import get_guard_service
from app.workflows.init_arch.historical import HistoricalPrepResult, get_historical_prep_service
from app.workflows.init_arch.knowledge import get_knowledge_artifact_service
from app.workflows.init_arch.llm_worker import get_llm_worker_service
from app.workflows.init_arch.prompts import CHECKLIST_ITEM_TO_REFERENCE, build_step_prompt
from app.workflows.init_arch.state import InitArchState

logger = structlog.get_logger()

_GIT_CLONE_TIMEOUT_SECONDS: typing.Final[float] = 300.0

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


def _build_task_request(  # noqa: PLR0913
    state: InitArchState,
    step_id: StepId,
    *,
    task_kind: LlmTaskKind,
    checklist_item_id: str = "",
    checklist_item_ids: list[str] | None = None,
    repository_name: str = "",
    autofix_findings: list[str] | None = None,
) -> LlmTaskRequest:
    return LlmTaskRequest(
        session_id=state["session"].session_id,
        task_kind=task_kind,
        step_id=step_id,
        prompt_text=build_step_prompt(
            step_id,
            state,
            checklist_item_id=checklist_item_id,
            checklist_item_ids=checklist_item_ids,
            repository_name=repository_name,
            autofix_findings=autofix_findings,
        ),
        workspace_dir=state["workspace_dir"],
        extra_allowed_roots=[state["arch_repo_dir"]],
        timeout_seconds=state["timeout_seconds"],
        expected_schema_name="init_arch_v1",
        repository_name=repository_name,
    )


async def _run_step_worker(  # noqa: PLR0913
    state: InitArchState,
    step_id: StepId,
    *,
    task_kind: LlmTaskKind = LlmTaskKind.STEP_EXECUTION,
    checklist_item_id: str = "",
    checklist_item_ids: list[str] | None = None,
    repository_name: str = "",
    autofix_findings: list[str] | None = None,
):
    worker_service = get_llm_worker_service()
    request = _build_task_request(
        state,
        step_id,
        task_kind=task_kind,
        checklist_item_id=checklist_item_id,
        checklist_item_ids=checklist_item_ids,
        repository_name=repository_name,
        autofix_findings=autofix_findings,
    )
    return await worker_service.run_task(
        request, engine_name=state["engine_name"], provider_connection_id=state.get("provider_connection_id")
    )


def _raise_if_blocking(prefix: str, blocking_issues: list[str]) -> None:
    if blocking_issues:
        raise ValueError(f"{prefix}: " + "; ".join(blocking_issues))


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
    logger.info(
        "workflow.node.define_scope",
        workflow_id=state["session"].session_id,
        current_step=state["session"].current_step.value,
    )
    guard_service = get_guard_service()
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.DEFINE_SCOPE)
    try:
        init_result = await guard_service.init_progress(
            state["session"],
            progress_file_path=state["progress_file_path"],
        )
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
        last_guard_output=init_result.bridge_output,
    )


async def node_request_repository_list(state: InitArchState) -> dict[str, typing.Any]:
    logger.info(
        "workflow.node.request_repository_list",
        workflow_id=state["session"].session_id,
        current_step=state["session"].current_step.value,
    )
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.REQUEST_REPOSITORY_LIST)
    if state["session"].repositories:
        guard_service = get_guard_service()
        try:
            result = await guard_service.advance_step(
                state["session"],
                StepId.PREPARE_TEMP_WORKSPACE,
                progress_file_path=state["progress_file_path"],
                note=f"Репозитории: {', '.join(repo.repository_name for repo in state['session'].repositories)}",
            )
        except Exception as exc:  # noqa: BLE001
            _record_workflow_event(
                state,
                EventType.WORKFLOW_STEP_FAILED,
                step_id=StepId.REQUEST_REPOSITORY_LIST,
                error=str(exc),
            )
            return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
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


def _prepare_workspace_directories(state: InitArchState) -> list[str]:
    raw_workspace_dir = state.get("raw_workspace_dir") or f"{state['workspace_dir']}/.temp"
    directories = [state["workspace_dir"], raw_workspace_dir, state["arch_repo_dir"]]
    for directory in directories:
        pathlib.Path(directory).mkdir(parents=True, exist_ok=True)
    return directories


async def node_prepare_temp_workspace(state: InitArchState) -> dict[str, typing.Any]:
    logger.info(
        "workflow.node.prepare_temp_workspace",
        workflow_id=state["session"].session_id,
        current_step=state["session"].current_step.value,
    )
    guard_service = get_guard_service()
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.PREPARE_TEMP_WORKSPACE)
    try:
        created_directories = _prepare_workspace_directories(state)
        result = await guard_service.advance_step(
            state["session"],
            StepId.CLONE_REPOSITORIES,
            progress_file_path=state["progress_file_path"],
            note=f"Prepared workspace directories: {', '.join(created_directories)}",
        )
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_FAILED,
            step_id=StepId.PREPARE_TEMP_WORKSPACE,
            error=str(exc),
        )
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    _record_workflow_event(
        state,
        EventType.WORKFLOW_STEP_COMPLETED,
        step_id=StepId.PREPARE_TEMP_WORKSPACE,
        next_step=result.session.current_step.value,
    )
    return _session_update_payload(result.session, last_guard_output=result.bridge_output)


def _validate_repository_name(repository_name: str) -> None:
    if not repository_name or repository_name in {".", ".."} or "/" in repository_name or "\\" in repository_name:
        msg = f"invalid repository_name for filesystem path: {repository_name!r}"
        raise ValueError(msg)


async def _run_git_clone(repository_url: str, target_path: pathlib.Path) -> None:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    proc = await asyncio.create_subprocess_exec(
        "git",
        "clone",
        repository_url,
        str(target_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        _, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=_GIT_CLONE_TIMEOUT_SECONDS)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        msg = f"git clone timed out after {_GIT_CLONE_TIMEOUT_SECONDS}s for {repository_url}"
        raise RuntimeError(msg) from None
    if proc.returncode != 0:
        stderr_text = stderr_bytes.decode(errors="replace").strip()
        access_status = classify_git_access_failure(stderr_text)
        detail = stderr_text or f"git exited with code {proc.returncode}"
        msg = f"git clone failed for {repository_url} ({access_status.value}): {detail}"
        raise RuntimeError(msg)


async def _clone_repositories(session: WorkflowSessionRecord, *, raw_workspace_dir: str) -> str:
    """Clone each repository into `raw_workspace_dir/<repository_name>`.

    `raw_workspace_dir` (`workspace_dir/.temp/`, see `_resolve_init_arch_paths()` in
    init_arch_workflow.py) is a project-level artifact shared across every run of this
    conversation, not scoped to this particular `workflow_id`. A checkout with a known
    `repository_url` is therefore always deleted and re-cloned fresh, rather than reused as-is -
    a leftover local checkout from an earlier run would otherwise have stale remote-tracking refs
    (`refresh_main_branches()` reads `origin/<branch>` as of clone time, there is no fetch step)
    and could still be mid-checkout at some historical commit from that earlier run's analysis.
    Only repositories with no `repository_url` at all (nothing to re-clone from) reuse whatever
    checkout is already on disk.
    """
    await ensure_git_credentials_store()
    cloned: list[str] = []
    reused: list[str] = []
    for repository in session.repositories:
        repository_name = repository.repository_name
        _validate_repository_name(repository_name)
        target_path = pathlib.Path(raw_workspace_dir) / repository_name

        if not repository.repository_url:
            if not target_path.exists():
                msg = f"repository {repository_name!r} has no repository_url and no existing checkout at {target_path}"
                raise ValueError(msg)
            reused.append(repository_name)
            continue

        if target_path.exists():
            shutil.rmtree(target_path)
        # Re-normalize at clone time, not just when the entry was added to the conversation -
        # the host's registered connection (see app/services/git_connections.py) can have
        # changed since, and a stale URL from before that change would fail to authenticate.
        clone_url = await normalize_repository_url(repository.repository_url)
        await _run_git_clone(clone_url, target_path)
        cloned.append(repository_name)

    summary_parts = []
    if cloned:
        summary_parts.append(f"cloned: {', '.join(cloned)}")
    if reused:
        summary_parts.append(f"reused existing checkout: {', '.join(reused)}")
    return "; ".join(summary_parts) if summary_parts else "no repositories to clone"


async def node_clone_repositories(state: InitArchState) -> dict[str, typing.Any]:
    logger.info(
        "workflow.node.clone_repositories",
        workflow_id=state["session"].session_id,
        current_step=state["session"].current_step.value,
    )
    guard_service = get_guard_service()
    raw_workspace_dir = state.get("raw_workspace_dir") or f"{state['workspace_dir']}/.temp"
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.CLONE_REPOSITORIES)
    try:
        clone_summary = await _clone_repositories(state["session"], raw_workspace_dir=raw_workspace_dir)
        result = await guard_service.advance_step(
            state["session"],
            StepId.REFRESH_MAIN_BRANCHES,
            progress_file_path=state["progress_file_path"],
            note=clone_summary,
        )
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_FAILED,
            step_id=StepId.CLONE_REPOSITORIES,
            error=str(exc),
        )
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    _record_workflow_event(
        state,
        EventType.WORKFLOW_STEP_COMPLETED,
        step_id=StepId.CLONE_REPOSITORIES,
        next_step=result.session.current_step.value,
    )
    return _session_update_payload(result.session, last_guard_output=clone_summary)


async def node_refresh_main_branches(state: InitArchState) -> dict[str, typing.Any]:
    logger.info(
        "workflow.node.refresh_main_branches",
        workflow_id=state["session"].session_id,
        current_step=state["session"].current_step.value,
    )
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
    logger.info(
        "workflow.node.plan_repository_order",
        workflow_id=state["session"].session_id,
        current_step=state["session"].current_step.value,
    )
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


def _require_domain_assessment(llm_result: LlmTaskResult, repository_name: str) -> RepositoryDomainAssessment:
    if llm_result.domain_assessment is None:
        msg = f"missing domain assessment for repository {repository_name!r}"
        raise DomainOperationError(msg)
    return llm_result.domain_assessment


def _require_domain_assessment_complete(session: WorkflowSessionRecord) -> None:
    if not domain_assessment_is_complete(session):
        msg = "domain assessment incomplete after processing all repositories"
        raise DomainOperationError(msg)


async def node_assess_scope_and_domains(state: InitArchState) -> dict[str, typing.Any]:
    logger.info(
        "workflow.node.assess_scope_and_domains",
        workflow_id=state["session"].session_id,
        current_step=state["session"].current_step.value,
    )
    guard_service = get_guard_service()
    knowledge_service = get_knowledge_artifact_service()
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.ASSESS_SCOPE_AND_DOMAINS)
    session = state["session"]
    try:
        llm_result = None
        for repository in session.repositories:
            if repository.domain_strategy is not None:
                # Already assessed in a previous attempt of this node (retry) — do not re-spend an LLM call.
                continue

            start_result = await guard_service.start_repository(
                session,
                repository_name=repository.repository_name,
                progress_file_path=state["progress_file_path"],
            )
            session = start_result.session

            llm_result = await _run_step_worker(
                {**state, "session": session},
                StepId.ASSESS_SCOPE_AND_DOMAINS,
                repository_name=repository.repository_name,
            )
            assessment = _require_domain_assessment(llm_result, repository.repository_name)

            assess_result = await guard_service.assess_repository_domains(
                session,
                repository_name=repository.repository_name,
                assessment=assessment,
                progress_file_path=state["progress_file_path"],
            )
            session = assess_result.session

        _require_domain_assessment_complete(session)

        domain_map_result = await knowledge_service.write_domain_map(
            session,
            arch_repo_dir=state["arch_repo_dir"],
        )
        session = domain_map_result.session

        advance_result = await guard_service.advance_step(
            session,
            StepId.ANALYZE_REPOSITORIES,
            progress_file_path=state["progress_file_path"],
            note=domain_map_result.summary,
        )
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_FAILED,
            step_id=StepId.ASSESS_SCOPE_AND_DOMAINS,
            error=str(exc),
        )
        return {
            "session": session,
            "step_error": str(exc),
            "retry_count": state.get("retry_count", 0) + 1,
        }
    _record_workflow_event(
        state,
        EventType.WORKFLOW_STEP_COMPLETED,
        step_id=StepId.ASSESS_SCOPE_AND_DOMAINS,
        next_step=advance_result.session.current_step.value,
    )
    return _session_update_payload(
        advance_result.session,
        last_llm_result=llm_result,
        last_guard_output=advance_result.bridge_output,
    )


async def node_analyze_repositories(state: InitArchState) -> dict[str, typing.Any]:
    """Repo-loop entry: pick the next repository still pending analysis, or finish the step.

    Persist/resume granularity for the repo x checklist-item loop lives at the graph level (see
    `node_analyze_repositories_item` and `graph.py`'s `_route_after_analyze_repositories*`), not inside a
    single node's Python loop — see 2026-07-21-analyze-repositories-per-item-nodes.md.
    """
    logger.info(
        "workflow.node.analyze_repositories",
        workflow_id=state["session"].session_id,
        current_step=state["session"].current_step.value,
    )
    guard_service = get_guard_service()
    knowledge_service = get_knowledge_artifact_service()
    session = state["session"]
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.ANALYZE_REPOSITORIES)
    try:
        repository = next_pending_repository(session)
        if repository is None:
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
            _record_workflow_event(
                state,
                EventType.WORKFLOW_STEP_COMPLETED,
                step_id=StepId.ANALYZE_REPOSITORIES,
                next_step=advance_result.session.current_step.value,
            )
            return _session_update_payload(advance_result.session, last_guard_output=advance_result.bridge_output)

        if repository.analysis_status == "pending":
            start_result = await guard_service.start_repository(
                session,
                repository_name=repository.repository_name,
                progress_file_path=state["progress_file_path"],
            )
            session = start_result.session
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_FAILED,
            step_id=StepId.ANALYZE_REPOSITORIES,
            error=str(exc),
        )
        return {"session": session, "step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    return _session_update_payload(session)


def _require_in_progress_repository(session: WorkflowSessionRecord) -> RepositoryExecution:
    repository = next((repo for repo in session.repositories if repo.analysis_status == "in_progress"), None)
    if repository is None:
        msg = "analyze_repositories_item: no in-progress repository in session"
        raise DomainOperationError(msg)
    return repository


def _require_checklist_progress(
    repository: RepositoryExecution, *, requested_item_ids: list[str], completed_item_ids: list[str]
) -> None:
    if not completed_item_ids:
        msg = (
            f"analyze_repositories: LLM call for {repository.repository_name!r} reported no completed "
            f"checklist items out of {len(requested_item_ids)} requested ({requested_item_ids})"
        )
        raise DomainOperationError(msg)


async def node_analyze_repositories_item(state: InitArchState) -> dict[str, typing.Any]:
    """Process every pending checklist item of the current in-progress repository in one LLM call.

    Historically (see 2026-07-21-analyze-repositories-per-item-nodes.md) this issued one LLM-agent call
    per checklist item, so the Postgres checkpoint written after every node by `_drive_graph_stream()`
    captured progress at item granularity. Merged into one call per repository on 2026-07-26 (see
    2026-07-26-analyze-repositories-merge-checklist-items.md): the per-item design paid for a full
    repository re-exploration (list_directory/read_file from scratch, no memory carried between calls)
    on every single item - for a ~20-item checklist that is ~20x the exploration cost for one
    repository, and was the dominant cost of a slow `analyze_repositories` step. Accepted trade-off:
    a crash/failure inside this one call now costs the whole repository's remaining items, not just
    one - the same `_MAX_RETRY` bound retries the whole batch instead of a single item.

    `completed_checklist_items` in the LLM's own JSON report is what keeps this honest despite the
    merge: only items the model itself claims to have addressed get marked complete via
    `complete_repository_item` below - a call is never blindly trusted to have finished everything it
    was asked for. If it reports none, that's treated as a step failure (not a silent no-op), so the
    existing retry/interrupt path catches it instead of looping forever with no progress and no error.
    `created_artifacts` still goes through `collect_worker_artifacts()` (structure/diff verification),
    which analyze_repositories never called until this change - it works from the same self-reported
    list, not an independent filesystem scan, so it verifies what the model says it wrote, not whether
    every checklist item's expected artifact actually exists.
    """
    guard_service = get_guard_service()
    knowledge_service = get_knowledge_artifact_service()
    session = state["session"]
    llm_result = None
    bridge_output = ""
    try:
        repository = _require_in_progress_repository(session)
        item_ids = pending_checklist_items(repository, all_checklist_item_ids=list(CHECKLIST_ITEM_TO_REFERENCE))
        if not item_ids:
            complete_result = await guard_service.complete_repository(
                session,
                repository_name=repository.repository_name,
                progress_file_path=state["progress_file_path"],
            )
            return _session_update_payload(complete_result.session, last_guard_output=complete_result.bridge_output)

        _record_workflow_event(
            state,
            EventType.DIFF_SIGNAL_ROUTED,
            step_id=StepId.ANALYZE_REPOSITORIES,
            repository_name=repository.repository_name,
            diff_severity=classify_diff_severity(repository).value,
            routed_items=str(len(item_ids)),
            total_items=str(len(CHECKLIST_ITEM_TO_REFERENCE)),
        )
        llm_result = await _run_step_worker(
            {**state, "session": session},
            StepId.ANALYZE_REPOSITORIES,
            task_kind=LlmTaskKind.REPOSITORY_CHECKLIST_ITEM,
            checklist_item_ids=item_ids,
            repository_name=repository.repository_name,
        )

        completed_item_ids = [item_id for item_id in item_ids if item_id in llm_result.completed_checklist_items]
        _require_checklist_progress(repository, requested_item_ids=item_ids, completed_item_ids=completed_item_ids)

        for item_id in completed_item_ids:
            item_result = await guard_service.complete_repository_item(
                session,
                repository_name=repository.repository_name,
                item_id=item_id,
                progress_file_path=state["progress_file_path"],
            )
            session = item_result.session
            bridge_output = item_result.bridge_output

        if llm_result.created_artifacts:
            artifact_result = await knowledge_service.collect_worker_artifacts(
                session,
                step_id=StepId.ANALYZE_REPOSITORIES,
                created_artifacts=llm_result.created_artifacts,
                arch_repo_dir=state["arch_repo_dir"],
            )
            session = artifact_result.session

        if llm_result.open_questions_found:
            question_result = await guard_service.register_open_questions(
                session,
                question_texts=llm_result.open_questions_found,
                repository_name=repository.repository_name,
                progress_file_path=state["progress_file_path"],
            )
            session = question_result.session
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_FAILED,
            step_id=StepId.ANALYZE_REPOSITORIES,
            error=str(exc),
        )
        return {"session": session, "step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    return _session_update_payload(
        session,
        last_llm_result=llm_result,
        last_guard_output=bridge_output,
    )


async def node_interview_user(state: InitArchState) -> dict[str, typing.Any]:
    logger.info(
        "workflow.node.interview_user",
        workflow_id=state["session"].session_id,
        current_step=state["session"].current_step.value,
    )
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
                arch_repo_dir=state["arch_repo_dir"],
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
    logger.info(
        "workflow.node.refine_features",
        workflow_id=state["session"].session_id,
        current_step=state["session"].current_step.value,
    )
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
            arch_repo_dir=state["arch_repo_dir"],
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
    logger.info(
        "workflow.node.build_navigation_index",
        workflow_id=state["session"].session_id,
        current_step=state["session"].current_step.value,
    )
    guard_service = get_guard_service()
    knowledge_service = get_knowledge_artifact_service()
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.BUILD_NAVIGATION_INDEX)
    llm_result = None
    try:
        compile_result = await knowledge_service.compile_navigation(
            state["session"],
            arch_repo_dir=state["arch_repo_dir"],
        )
        blocking_issues = compile_result.lint_issues
        if blocking_issues:
            llm_result = await _run_step_worker(
                {**state, "session": compile_result.session},
                StepId.BUILD_NAVIGATION_INDEX,
                task_kind=LlmTaskKind.KNOWLEDGE_LINT_AUTOFIX,
                autofix_findings=blocking_issues,
            )
            knowledge_result = await knowledge_service.collect_worker_artifacts(
                compile_result.session,
                step_id=StepId.BUILD_NAVIGATION_INDEX,
                created_artifacts=llm_result.created_artifacts,
                arch_repo_dir=state["arch_repo_dir"],
            )
            # Recompile over the (possibly fixed) documents so wiki/index.md + compile-report.md written
            # below reflect the post-autofix graph, not the stale pre-fix one.
            compile_result = await knowledge_service.compile_navigation(
                knowledge_result.session,
                arch_repo_dir=state["arch_repo_dir"],
            )
            blocking_issues = compile_result.lint_issues
        _raise_if_blocking("KNOWLEDGE_COMPILE_BLOCKED_AFTER_AUTOFIX", blocking_issues)
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
    return _session_update_payload(result.session, last_llm_result=llm_result, last_guard_output=result.bridge_output)


async def node_run_knowledge_lint(state: InitArchState) -> dict[str, typing.Any]:
    logger.info(
        "workflow.node.run_knowledge_lint",
        workflow_id=state["session"].session_id,
        current_step=state["session"].current_step.value,
    )
    guard_service = get_guard_service()
    knowledge_service = get_knowledge_artifact_service()
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.RUN_KNOWLEDGE_LINT)
    llm_result = None
    try:
        lint_result = await knowledge_service.lint_knowledge(
            state["session"],
            arch_repo_dir=state["arch_repo_dir"],
        )
        blocking_issues = [issue for issue in lint_result.lint_issues if issue.startswith("ERROR:")]
        if blocking_issues:
            llm_result = await _run_step_worker(
                {**state, "session": lint_result.session},
                StepId.RUN_KNOWLEDGE_LINT,
                task_kind=LlmTaskKind.KNOWLEDGE_LINT_AUTOFIX,
                autofix_findings=blocking_issues,
            )
            knowledge_result = await knowledge_service.collect_worker_artifacts(
                lint_result.session,
                step_id=StepId.RUN_KNOWLEDGE_LINT,
                created_artifacts=llm_result.created_artifacts,
                arch_repo_dir=state["arch_repo_dir"],
            )
            # Resync wiki/index.md + compile-report.md with the fixed documents before re-linting, otherwise
            # the drift check (_lint_wiki_compile_drift) would report a brand-new ERROR instead of the fix
            # actually clearing the original one.
            compile_result = await knowledge_service.compile_navigation(
                knowledge_result.session,
                arch_repo_dir=state["arch_repo_dir"],
            )
            lint_result = await knowledge_service.lint_knowledge(
                compile_result.session,
                arch_repo_dir=state["arch_repo_dir"],
            )
            blocking_issues = [issue for issue in lint_result.lint_issues if issue.startswith("ERROR:")]
        _raise_if_blocking("KNOWLEDGE_LINT_BLOCKED_AFTER_AUTOFIX", blocking_issues)
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
    return _session_update_payload(result.session, last_llm_result=llm_result, last_guard_output=result.bridge_output)


async def node_validate_final(state: InitArchState) -> dict[str, typing.Any]:
    logger.info(
        "workflow.node.validate_final",
        workflow_id=state["session"].session_id,
        current_step=state["session"].current_step.value,
    )
    return await _simple_llm_step(state, StepId.VALIDATE_FINAL, StepId.GENERATE_RELEASE_NOTES)


async def node_generate_release_notes(state: InitArchState) -> dict[str, typing.Any]:
    logger.info(
        "workflow.node.generate_release_notes",
        workflow_id=state["session"].session_id,
        current_step=state["session"].current_step.value,
    )
    guard_service = get_guard_service()
    knowledge_service = get_knowledge_artifact_service()
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.GENERATE_RELEASE_NOTES)
    try:
        llm_result = await _run_step_worker(state, StepId.GENERATE_RELEASE_NOTES)
        knowledge_result = await knowledge_service.collect_worker_artifacts(
            state["session"],
            step_id=StepId.GENERATE_RELEASE_NOTES,
            created_artifacts=llm_result.created_artifacts,
            arch_repo_dir=state["arch_repo_dir"],
        )
        result = await guard_service.advance_step(
            knowledge_result.session,
            StepId.CONFIRM_NEXT_TEMPORAL_WINDOW,
            progress_file_path=state["progress_file_path"],
            note=knowledge_result.summary,
        )
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_FAILED,
            step_id=StepId.GENERATE_RELEASE_NOTES,
            error=str(exc),
        )
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    _record_workflow_event(
        state,
        EventType.WORKFLOW_STEP_COMPLETED,
        step_id=StepId.GENERATE_RELEASE_NOTES,
        next_step=result.session.current_step.value,
    )
    return _session_update_payload(
        result.session,
        last_llm_result=llm_result,
        last_guard_output=result.bridge_output,
    )


def _extract_window_confirmation_action(resume_payload: typing.Any) -> TemporalWindowConfirmationAction:
    action = resume_payload.get("action") if isinstance(resume_payload, dict) else resume_payload
    if action not in {"continue_to_next_window", "finish_temporal_analysis"}:
        raise ValueError(
            "resume payload for temporal_window_confirmation must contain action "
            "'continue_to_next_window' or 'finish_temporal_analysis'"
        )
    return typing.cast("TemporalWindowConfirmationAction", action)


def _extract_step_failure_recovery_action(resume_payload: typing.Any) -> StepFailureRecoveryAction:
    action = resume_payload.get("action") if isinstance(resume_payload, dict) else resume_payload
    if action not in {"retry", "abort"}:
        raise ValueError("resume payload for step_failed must contain action 'retry' or 'abort'")
    return typing.cast("StepFailureRecoveryAction", action)


async def node_confirm_next_temporal_window(state: InitArchState) -> dict[str, typing.Any]:
    logger.info(
        "workflow.node.confirm_next_temporal_window",
        workflow_id=state["session"].session_id,
        current_step=state["session"].current_step.value,
    )
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
    logger.info(
        "workflow.node.finalize_progress",
        workflow_id=state["session"].session_id,
        current_step=state["session"].current_step.value,
    )
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
    step_id = state["session"].current_step
    step_error = state.get("step_error")
    retry_count = state.get("retry_count", 0)
    logger.error(
        "workflow.node.error",
        step=step_id.value,
        error=step_error,
        retry_count=retry_count,
    )
    resume_payload = interrupt(
        {
            "interrupt_type": "step_failed",
            "step_id": step_id.value,
            "step_title": STEP_DEFINITION_BY_ID[step_id].title,
            "error": step_error,
            "retry_count": retry_count,
        }
    )
    action = _extract_step_failure_recovery_action(resume_payload)
    if action == "retry":
        logger.info("workflow.node.error.retry", step=step_id.value)
        return {"step_error": None, "retry_count": 0}
    logger.info("workflow.node.error.abort", step=step_id.value)
    return {"step_error": step_error, "retry_count": retry_count}
