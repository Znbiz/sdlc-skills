from __future__ import annotations

from app.workflows.init_arch.domain.models import (
    AnalysisTargetCommitStatus,
    ArtifactRecord,
    OpenQuestionRecord,
    RepositoryExecution,
    StepId,
    WorkflowSessionRecord,
    WorkflowStatus,
)
from app.workflows.init_arch.domain.steps import STEP_DEFINITION_BY_ID


class DomainOperationError(ValueError):
    pass


def start_session(*, session_id: str, product_name: str, analysis_scope: str) -> WorkflowSessionRecord:
    return WorkflowSessionRecord(session_id=session_id, product_name=product_name, analysis_scope=analysis_scope)


def advance_step(session: WorkflowSessionRecord, next_step: StepId) -> WorkflowSessionRecord:
    definition = STEP_DEFINITION_BY_ID[next_step]
    completed_steps = list(session.completed_steps)

    if session.current_step not in completed_steps and session.current_step is not StepId.DONE:
        completed_steps.append(session.current_step)

    missing_previous_steps = [step for step in definition.required_previous_steps if step not in completed_steps]
    if missing_previous_steps:
        raise DomainOperationError(f"required_previous_steps not completed: {missing_previous_steps}")

    if definition.requires_historical_prep and not historical_prep_is_complete(session):
        raise DomainOperationError("historical prep must be completed before this step")

    return session.model_copy(
        update={
            "current_step": next_step,
            "completed_steps": completed_steps,
            "status": WorkflowStatus.IN_PROGRESS,
        }
    )


def fail_step(session: WorkflowSessionRecord) -> WorkflowSessionRecord:
    return session.model_copy(update={"status": WorkflowStatus.FAILED})


def open_question(session: WorkflowSessionRecord, question: OpenQuestionRecord) -> WorkflowSessionRecord:
    return session.model_copy(
        update={
            "status": WorkflowStatus.WAITING_FOR_USER,
            "open_questions": [*session.open_questions, question],
        }
    )


def record_answer(session: WorkflowSessionRecord, *, question_id: str, answer_text: str) -> WorkflowSessionRecord:
    updated_questions: list[OpenQuestionRecord] = []
    found = False
    for question in session.open_questions:
        if question.question_id == question_id:
            updated_questions.append(question.model_copy(update={"status": "answered", "answer_text": answer_text}))
            found = True
        else:
            updated_questions.append(question)

    if not found:
        raise DomainOperationError(f"open question not found: {question_id}")

    return session.model_copy(update={"status": WorkflowStatus.IN_PROGRESS, "open_questions": updated_questions})


def close_question(session: WorkflowSessionRecord, *, question_id: str) -> WorkflowSessionRecord:
    updated_questions: list[OpenQuestionRecord] = []
    found = False
    for question in session.open_questions:
        if question.question_id == question_id:
            updated_questions.append(question.model_copy(update={"status": "closed"}))
            found = True
        else:
            updated_questions.append(question)

    if not found:
        raise DomainOperationError(f"open question not found: {question_id}")

    has_remaining_open_questions = any(question.status == "open" for question in updated_questions)
    return session.model_copy(
        update={
            "status": WorkflowStatus.WAITING_FOR_USER if has_remaining_open_questions else WorkflowStatus.IN_PROGRESS,
            "open_questions": updated_questions,
        }
    )


def register_repository(session: WorkflowSessionRecord, repository: RepositoryExecution) -> WorkflowSessionRecord:
    repositories = [repo for repo in session.repositories if repo.repository_name != repository.repository_name]
    repositories.append(repository)
    return session.model_copy(update={"repositories": repositories})


def register_artifact(
    session: WorkflowSessionRecord,
    *,
    artifact: ArtifactRecord,
) -> WorkflowSessionRecord:
    artifacts = [item for item in session.artifacts if item.artifact_path != artifact.artifact_path]
    artifacts.append(artifact)
    artifacts.sort(key=lambda item: item.artifact_path)
    return session.model_copy(update={"artifacts": artifacts})


def mark_checklist_item(session: WorkflowSessionRecord, *, repository_name: str, item_id: str) -> WorkflowSessionRecord:
    repositories: list[RepositoryExecution] = []
    found = False
    for repository in session.repositories:
        if repository.repository_name == repository_name:
            found = True
            completed = list(repository.checklist_items_completed)
            if item_id not in completed:
                completed.append(item_id)
            repositories.append(repository.model_copy(update={"checklist_items_completed": completed}))
        else:
            repositories.append(repository)

    if not found:
        raise DomainOperationError(f"repository not found: {repository_name}")

    return session.model_copy(update={"repositories": repositories})


def finalize_session(session: WorkflowSessionRecord) -> WorkflowSessionRecord:
    completed_steps = list(session.completed_steps)
    if session.current_step not in completed_steps and session.current_step is not StepId.DONE:
        completed_steps.append(session.current_step)
    return session.model_copy(
        update={
            "current_step": StepId.DONE,
            "completed_steps": completed_steps,
            "status": WorkflowStatus.COMPLETED,
        }
    )


def historical_prep_is_complete(session: WorkflowSessionRecord) -> bool:
    repositories = list(session.repositories)
    historical = session.historical_analysis

    if not repositories:
        return False
    if not historical.anchor_repository_name or historical.anchor_created_at is None or historical.current_snapshot_at is None:
        return False

    expected_order = [
        repository.repository_name
        for repository in sorted(
            repositories,
            key=lambda repository: (
                repository.created_at or __import__("datetime").date.max,
                repository.repository_name,
            ),
        )
    ]
    if not historical.ordered_repository_names or historical.ordered_repository_names != expected_order:
        return False

    allowed_statuses = {
        AnalysisTargetCommitStatus.RESOLVED,
        AnalysisTargetCommitStatus.CHECKED_OUT,
        AnalysisTargetCommitStatus.MISSING,
    }
    return all(
        repository.created_at is not None
        and repository.analysis_target_date == historical.current_snapshot_at
        and repository.analysis_target_commit_status in allowed_statuses
        for repository in repositories
    )
