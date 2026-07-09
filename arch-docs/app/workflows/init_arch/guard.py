from __future__ import annotations

import pydantic

from app.workflows.init_arch.audit import WorkflowAuditService, get_workflow_audit_service
from app.workflows.init_arch.domain import (
    AuditActor,
    EventType,
    OpenQuestionRecord,
    RepositoryExecution,
    StepId,
    WorkflowEventRecord,
    WorkflowSessionRecord,
    advance_step,
    close_question,
    finalize_session,
    mark_checklist_item,
    open_question,
    record_answer,
    register_repository,
)


class GuardOperationResult(pydantic.BaseModel):
    session: WorkflowSessionRecord
    bridge_output: str = ""


class InitArchGuardService:
    def __init__(self, audit_service: WorkflowAuditService | None = None) -> None:
        self._audit_service = audit_service or get_workflow_audit_service()

    async def init_progress(self, session: WorkflowSessionRecord, *, progress_file_path: str) -> GuardOperationResult:
        self._record_guard_event(
            session,
            EventType.GUARD_COMMAND_REQUESTED,
            command="init",
            progress_file_path=progress_file_path,
        )
        self._record_guard_event(
            session,
            EventType.GUARD_COMMAND_APPLIED,
            command="init",
            progress_file_path=progress_file_path,
        )
        return GuardOperationResult(
            session=session,
            bridge_output=f"Initialized workflow for {session.product_name}",
        )

    async def advance_step(
        self,
        session: WorkflowSessionRecord,
        next_step: StepId,
        *,
        progress_file_path: str,
        note: str = "",
    ) -> GuardOperationResult:
        updated_session = advance_step(session, next_step)
        self._record_guard_event(
            session,
            EventType.GUARD_COMMAND_REQUESTED,
            command="advance",
            target_step=next_step.value,
            progress_file_path=progress_file_path,
        )
        self._record_guard_event(
            updated_session,
            EventType.GUARD_COMMAND_APPLIED,
            command="advance",
            current_step=updated_session.current_step.value,
            progress_file_path=progress_file_path,
        )
        summary = f"Advanced workflow to {updated_session.current_step.value}"
        if note:
            summary = f"{summary}: {note}"
        return GuardOperationResult(session=updated_session, bridge_output=summary)

    def register_repository_sync(
        self, session: WorkflowSessionRecord, repository: RepositoryExecution
    ) -> WorkflowSessionRecord:
        return register_repository(session, repository)

    async def start_repository(
        self, session: WorkflowSessionRecord, *, repository_name: str, progress_file_path: str
    ) -> GuardOperationResult:
        repositories = []
        for repository in session.repositories:
            if repository.repository_name == repository_name:
                repositories.append(repository.model_copy(update={"analysis_status": "in_progress"}))
            else:
                repositories.append(repository)
        self._record_guard_event(
            session,
            EventType.GUARD_COMMAND_REQUESTED,
            command="repo_start",
            repository_name=repository_name,
            progress_file_path=progress_file_path,
        )
        updated_session = session.model_copy(update={"repositories": repositories})
        self._record_guard_event(
            updated_session,
            EventType.GUARD_COMMAND_APPLIED,
            command="repo_start",
            repository_name=repository_name,
            progress_file_path=progress_file_path,
        )
        return GuardOperationResult(
            session=updated_session,
            bridge_output=f"Started repository {repository_name}",
        )

    async def complete_repository_item(
        self,
        session: WorkflowSessionRecord,
        *,
        repository_name: str,
        item_id: str,
        progress_file_path: str,
    ) -> GuardOperationResult:
        updated_session = mark_checklist_item(session, repository_name=repository_name, item_id=item_id)
        self._record_guard_event(
            session,
            EventType.GUARD_COMMAND_REQUESTED,
            command="repo_checklist_item",
            repository_name=repository_name,
            item_id=item_id,
            progress_file_path=progress_file_path,
        )
        self._record_guard_event(
            updated_session,
            EventType.GUARD_COMMAND_APPLIED,
            command="repo_checklist_item",
            repository_name=repository_name,
            item_id=item_id,
            progress_file_path=progress_file_path,
        )
        return GuardOperationResult(
            session=updated_session,
            bridge_output=f"Completed checklist item {item_id} for {repository_name}",
        )

    async def complete_repository(
        self, session: WorkflowSessionRecord, *, repository_name: str, progress_file_path: str
    ) -> GuardOperationResult:
        repositories = []
        for repository in session.repositories:
            if repository.repository_name == repository_name:
                repositories.append(repository.model_copy(update={"analysis_status": "completed"}))
            else:
                repositories.append(repository)
        self._record_guard_event(
            session,
            EventType.GUARD_COMMAND_REQUESTED,
            command="repo_complete",
            repository_name=repository_name,
            progress_file_path=progress_file_path,
        )
        updated_session = session.model_copy(update={"repositories": repositories})
        self._record_guard_event(
            updated_session,
            EventType.GUARD_COMMAND_APPLIED,
            command="repo_complete",
            repository_name=repository_name,
            progress_file_path=progress_file_path,
        )
        return GuardOperationResult(
            session=updated_session,
            bridge_output=f"Completed repository {repository_name}",
        )

    async def record_user_answer(
        self,
        session: WorkflowSessionRecord,
        *,
        question_id: str,
        answer_text: str,
        progress_file_path: str,
    ) -> GuardOperationResult:
        updated_session = record_answer(session, question_id=question_id, answer_text=answer_text)
        self._record_guard_event(
            session,
            EventType.GUARD_COMMAND_REQUESTED,
            command="record_user_answer",
            question_id=question_id,
            progress_file_path=progress_file_path,
        )
        self._record_guard_event(
            updated_session,
            EventType.GUARD_COMMAND_APPLIED,
            command="record_user_answer",
            question_id=question_id,
            progress_file_path=progress_file_path,
        )
        self._audit_service.record(
            WorkflowEventRecord(
                event_type=EventType.USER_ANSWER_RECORDED,
                actor=AuditActor.USER,
                session_id=updated_session.session_id,
                step_id=updated_session.current_step,
                payload={"question_id": question_id},
            )
        )
        return GuardOperationResult(
            session=updated_session,
            bridge_output=f"Recorded answer for {question_id}",
        )

    async def register_open_questions(
        self,
        session: WorkflowSessionRecord,
        *,
        question_texts: list[str],
        repository_name: str = "",
        progress_file_path: str,
    ) -> GuardOperationResult:
        normalized_questions = [question_text.strip() for question_text in question_texts if question_text.strip()]
        if not normalized_questions:
            return GuardOperationResult(session=session, bridge_output="No open questions to register")

        updated_session = session
        existing_texts = {question.question_text for question in session.open_questions}
        next_index = self._next_question_index(session)
        added_question_ids: list[str] = []

        self._record_guard_event(
            session,
            EventType.GUARD_COMMAND_REQUESTED,
            command="open_questions_register",
            repository_name=repository_name,
            progress_file_path=progress_file_path,
        )
        for question_text in normalized_questions:
            if question_text in existing_texts:
                continue
            question = OpenQuestionRecord(
                question_id=f"Q-{next_index}",
                question_text=question_text,
                related_repositories=[repository_name] if repository_name else [],
            )
            next_index += 1
            existing_texts.add(question_text)
            updated_session = open_question(updated_session, question)
            added_question_ids.append(question.question_id)
            self._audit_service.record(
                WorkflowEventRecord(
                    event_type=EventType.USER_QUESTION_OPENED,
                    actor=AuditActor.SERVICE,
                    session_id=updated_session.session_id,
                    step_id=updated_session.current_step,
                    repository_name=repository_name,
                    payload={"question_id": question.question_id, "question_text": question.question_text},
                )
            )

        self._record_guard_event(
            updated_session,
            EventType.GUARD_COMMAND_APPLIED,
            command="open_questions_register",
            repository_name=repository_name,
            progress_file_path=progress_file_path,
        )
        summary = f"Registered {len(added_question_ids)} open questions"
        if repository_name:
            summary = f"{summary} for {repository_name}"
        return GuardOperationResult(session=updated_session, bridge_output=summary)

    async def close_user_question(
        self,
        session: WorkflowSessionRecord,
        *,
        question_id: str,
        progress_file_path: str,
    ) -> GuardOperationResult:
        updated_session = close_question(session, question_id=question_id)
        self._record_guard_event(
            session,
            EventType.GUARD_COMMAND_REQUESTED,
            command="close_user_question",
            question_id=question_id,
            progress_file_path=progress_file_path,
        )
        self._record_guard_event(
            updated_session,
            EventType.GUARD_COMMAND_APPLIED,
            command="close_user_question",
            question_id=question_id,
            progress_file_path=progress_file_path,
        )
        return GuardOperationResult(
            session=updated_session,
            bridge_output=f"Closed question {question_id}",
        )

    async def finalize_progress(
        self, session: WorkflowSessionRecord, *, progress_file_path: str
    ) -> GuardOperationResult:
        self._record_guard_event(
            session,
            EventType.GUARD_COMMAND_REQUESTED,
            command="finalize",
            progress_file_path=progress_file_path,
        )
        updated_session = finalize_session(session)
        self._record_guard_event(
            updated_session,
            EventType.GUARD_COMMAND_APPLIED,
            command="finalize",
            progress_file_path=progress_file_path,
        )
        return GuardOperationResult(
            session=updated_session,
            bridge_output="Finalized workflow session",
        )

    async def run_validation(
        self, session: WorkflowSessionRecord, *, progress_file_path: str
    ) -> GuardOperationResult:
        self._record_guard_event(
            session,
            EventType.GUARD_COMMAND_REQUESTED,
            command="validate",
            progress_file_path=progress_file_path,
        )
        self._record_guard_event(
            session,
            EventType.GUARD_COMMAND_APPLIED,
            command="validate",
            progress_file_path=progress_file_path,
        )
        return GuardOperationResult(
            session=session,
            bridge_output=f"Validation passed for {session.current_step.value}",
        )

    def _record_guard_event(
        self,
        session: WorkflowSessionRecord,
        event_type: EventType,
        repository_name: str = "",
        domain_id: str = "",
        **payload: str,
    ) -> None:
        self._audit_service.record(
            WorkflowEventRecord(
                event_type=event_type,
                actor=AuditActor.SERVICE,
                session_id=session.session_id,
                step_id=session.current_step,
                repository_name=repository_name,
                domain_id=domain_id,
                payload=payload,
            )
        )

    @staticmethod
    def _next_question_index(session: WorkflowSessionRecord) -> int:
        max_question_number = 0
        for question in session.open_questions:
            if not question.question_id.startswith("Q-"):
                continue
            try:
                max_question_number = max(max_question_number, int(question.question_id[2:]))
            except ValueError:
                continue
        return max_question_number + 1


_guard_service: InitArchGuardService | None = None


def get_guard_service() -> InitArchGuardService:
    global _guard_service  # noqa: PLW0603
    if _guard_service is None:
        _guard_service = InitArchGuardService(audit_service=get_workflow_audit_service())
    return _guard_service
