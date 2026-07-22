from __future__ import annotations

import datetime

import sqlalchemy as sa
import sqlalchemy.ext.asyncio as async_sa

from app.db.models import (
    ArtifactEventModel,
    ConversationItemModel,
    ConversationModel,
    RequiredActionModel,
    WorkflowRunModel,
    WorkflowStepTransitionModel,
)
from app.services.workflow_registry import WorkflowRecord, WorkflowStatus
from app.workflows.init_arch.domain import EventType, WorkflowEventRecord, WorkflowSessionRecord


def _session_payload(session: WorkflowSessionRecord | None) -> dict | None:
    if session is None:
        return None
    return session.model_dump(mode="json")


def _build_required_actions(record: WorkflowRecord, *, conversation_id: str) -> list[RequiredActionModel]:
    actions: list[RequiredActionModel] = []
    seen_question_ids: set[str] = set()
    now = record.updated_at

    if record.pending_interrupt:
        question_id = record.pending_interrupt.get("question_id")
        if isinstance(question_id, str):
            seen_question_ids.add(question_id)
        actions.append(
            RequiredActionModel(
                conversation_id=conversation_id,
                workflow_id=record.workflow_id,
                action_type=str(record.pending_interrupt.get("interrupt_type", "user_input")),
                question_id=question_id if isinstance(question_id, str) else None,
                action_status="open",
                payload_json=dict(record.pending_interrupt),
                created_at=now,
                updated_at=now,
            )
        )

    if record.session is None:
        return actions

    for question in record.session.open_questions:
        if question.status == "closed" or question.question_id in seen_question_ids:
            continue
        actions.append(
            RequiredActionModel(
                conversation_id=conversation_id,
                workflow_id=record.workflow_id,
                action_type="user_question",
                question_id=question.question_id,
                action_status=question.status,
                payload_json=question.model_dump(mode="json"),
                created_at=now,
                updated_at=now,
            )
        )
    return actions


def _workflow_record_from_model(model: WorkflowRunModel) -> WorkflowRecord:
    session = None
    if model.session_payload is not None:
        session = WorkflowSessionRecord.model_validate(model.session_payload)

    return WorkflowRecord(
        workflow_id=model.workflow_id,
        conversation_id=model.conversation_id,
        workflow_status=WorkflowStatus(model.workflow_status),
        current_step_id=model.current_step_id,
        current_repo_name=model.current_repo_name,
        workspace_dir=model.workspace_dir,
        arch_repo_dir=model.arch_repo_dir,
        completed_steps=list(model.completed_steps or []),
        session=session,
        pending_interrupt=dict(model.pending_interrupt_payload) if model.pending_interrupt_payload else None,
        last_cli_output_snippet=model.last_cli_output_snippet,
        created_at=model.created_at,
        updated_at=model.updated_at,
        error_message=model.error_message,
    )


def _build_step_transition_model(
    record: WorkflowRecord,
    *,
    conversation_id: str,
    previous_step: str | None,
) -> WorkflowStepTransitionModel:
    return WorkflowStepTransitionModel(
        conversation_id=conversation_id,
        workflow_id=record.workflow_id,
        previous_step_id=previous_step,
        current_step_id=record.current_step_id,
        completed_steps=list(record.completed_steps),
        created_at=record.updated_at,
    )


def _build_artifact_event_model(
    event: WorkflowEventRecord,
    *,
    conversation_id: str,
) -> ArtifactEventModel | None:
    if event.event_type not in {EventType.ARTIFACT_WRITTEN, EventType.ARTIFACT_REJECTED}:
        return None

    artifact_path = event.payload.get("artifact_path")
    artifact_kind = event.payload.get("artifact_kind")
    if not isinstance(artifact_path, str) or not isinstance(artifact_kind, str):
        return None

    return ArtifactEventModel(
        conversation_id=conversation_id,
        workflow_id=event.session_id,
        event_type=event.event_type.value,
        actor=event.actor.value,
        step_id=event.step_id.value if event.step_id is not None else None,
        artifact_path=artifact_path,
        artifact_kind=artifact_kind,
        repository_name=event.repository_name or None,
        domain_id=event.domain_id or None,
        payload_json=event.model_dump(mode="json"),
    )


async def upsert_workflow_run(session: async_sa.AsyncSession, record: WorkflowRecord) -> None:
    conversation_id = record.conversation_id or record.workflow_id
    conversation = await session.get(ConversationModel, conversation_id)
    if conversation is None:
        conversation = ConversationModel(
            conversation_id=conversation_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        session.add(conversation)
    else:
        conversation.updated_at = record.updated_at

    existing = await session.get(WorkflowRunModel, record.workflow_id)
    previous_status = existing.workflow_status if existing is not None else None
    previous_step = existing.current_step_id if existing is not None else None
    previous_interrupt = (
        dict(existing.pending_interrupt_payload) if existing and existing.pending_interrupt_payload else None
    )

    if existing is None:
        existing = WorkflowRunModel(
            workflow_id=record.workflow_id,
            conversation_id=conversation_id,
            workflow_name="init_arch",
            workflow_status=str(record.workflow_status),
            current_step_id=record.current_step_id,
            current_repo_name=record.current_repo_name,
            workspace_dir=record.workspace_dir,
            arch_repo_dir=record.arch_repo_dir,
            completed_steps=list(record.completed_steps),
            session_payload=_session_payload(record.session),
            pending_interrupt_payload=dict(record.pending_interrupt) if record.pending_interrupt else None,
            last_cli_output_snippet=record.last_cli_output_snippet,
            error_message=record.error_message,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        session.add(existing)
        is_new_workflow_run = True
    else:
        existing.conversation_id = conversation_id
        existing.workflow_status = str(record.workflow_status)
        existing.current_step_id = record.current_step_id
        existing.current_repo_name = record.current_repo_name
        existing.workspace_dir = record.workspace_dir
        existing.arch_repo_dir = record.arch_repo_dir
        existing.completed_steps = list(record.completed_steps)
        existing.session_payload = _session_payload(record.session)
        existing.pending_interrupt_payload = dict(record.pending_interrupt) if record.pending_interrupt else None
        existing.last_cli_output_snippet = record.last_cli_output_snippet
        existing.error_message = record.error_message
        existing.updated_at = record.updated_at
        is_new_workflow_run = False

    # Явный flush перед добавлением зависимых ConversationItemModel/WorkflowStepTransitionModel:
    # без relationship() между моделями autoflush не гарантирует порядок вставки
    # conversation/workflow_runs раньше conversation_items и падает по FK.
    await session.flush()

    if is_new_workflow_run:
        session.add(
            ConversationItemModel(
                conversation_id=conversation_id,
                workflow_id=record.workflow_id,
                item_kind="run_started",
                actor="service",
                step_id=record.current_step_id,
                payload_json={
                    "workflow_status": str(record.workflow_status),
                    "current_step_id": record.current_step_id,
                },
                created_at=record.created_at,
            )
        )

    if previous_step != record.current_step_id:
        session.add(_build_step_transition_model(record, conversation_id=conversation_id, previous_step=previous_step))
        session.add(
            ConversationItemModel(
                conversation_id=conversation_id,
                workflow_id=record.workflow_id,
                item_kind="step_transition",
                actor="service",
                step_id=record.current_step_id,
                payload_json={
                    "previous_step_id": previous_step,
                    "current_step_id": record.current_step_id,
                    "completed_steps": list(record.completed_steps),
                },
                created_at=record.updated_at,
            )
        )

    if previous_status != str(record.workflow_status):
        session.add(
            ConversationItemModel(
                conversation_id=conversation_id,
                workflow_id=record.workflow_id,
                item_kind="workflow_status_changed",
                actor="service",
                step_id=record.current_step_id,
                payload_json={
                    "previous_status": previous_status,
                    "workflow_status": str(record.workflow_status),
                    "error_message": record.error_message,
                },
                created_at=record.updated_at,
            )
        )

    if previous_interrupt != record.pending_interrupt:
        session.add(
            ConversationItemModel(
                conversation_id=conversation_id,
                workflow_id=record.workflow_id,
                item_kind="required_action_snapshot",
                actor="service",
                step_id=record.current_step_id,
                payload_json={"pending_interrupt": record.pending_interrupt},
                created_at=record.updated_at,
            )
        )

    await session.execute(sa.delete(RequiredActionModel).where(RequiredActionModel.workflow_id == record.workflow_id))
    for action in _build_required_actions(record, conversation_id=conversation_id):
        session.add(action)

    await session.commit()


async def append_workflow_event(session: async_sa.AsyncSession, event: WorkflowEventRecord) -> None:
    if not event.session_id:
        return

    workflow = await session.get(WorkflowRunModel, event.session_id)
    conversation_id = workflow.conversation_id if workflow is not None else event.session_id

    conversation = await session.get(ConversationModel, conversation_id)
    if conversation is None:
        conversation = ConversationModel(
            conversation_id=conversation_id,
            created_at=datetime.datetime.now(datetime.timezone.utc),
            updated_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(conversation)
    else:
        conversation.updated_at = datetime.datetime.now(datetime.timezone.utc)

    session.add(
        ConversationItemModel(
            conversation_id=conversation_id,
            workflow_id=event.session_id,
            item_kind=event.event_type.value,
            actor=event.actor.value,
            step_id=event.step_id.value if event.step_id is not None else None,
            payload_json=event.model_dump(mode="json"),
        )
    )
    artifact_event = _build_artifact_event_model(event, conversation_id=conversation_id)
    if artifact_event is not None:
        session.add(artifact_event)
    await session.commit()


async def get_workflow_run(session: async_sa.AsyncSession, workflow_id: str) -> WorkflowRecord | None:
    model = await session.get(WorkflowRunModel, workflow_id)
    if model is None:
        return None
    return _workflow_record_from_model(model)


async def delete_workflow_run(session: async_sa.AsyncSession, workflow_id: str) -> bool:
    """Delete a `workflow_runs` row - used by `restart_init_arch_workflow()`.

    `conversation_items`/`required_actions`/`workflow_step_transitions`/`artifact_events` all FK to
    `workflow_runs.workflow_id` with `ondelete="CASCADE"` (see db/models.py), so this one delete
    wipes the entire event/timeline/artifact history for the run too. It does *not* touch
    `conversations` (the parent, not a child, of `workflow_runs`) - the caller keeps the same
    conversation/URL. `cli_tasks` has no such FK and needs `delete_cli_tasks_for_workflow()`
    separately (task_repo.py). Returns True if a row existed and was deleted.
    """
    result = await session.execute(sa.delete(WorkflowRunModel).where(WorkflowRunModel.workflow_id == workflow_id))
    await session.commit()
    return result.rowcount > 0


async def create_conversation(
    session: async_sa.AsyncSession,
    *,
    conversation_id: str,
    created_at: datetime.datetime | None = None,
) -> ConversationModel:
    conversation = await session.get(ConversationModel, conversation_id)
    if conversation is not None:
        return conversation

    now = created_at or datetime.datetime.now(datetime.timezone.utc)
    conversation = ConversationModel(
        conversation_id=conversation_id,
        created_at=now,
        updated_at=now,
    )
    session.add(conversation)
    await session.commit()
    return conversation


async def get_conversation(
    session: async_sa.AsyncSession,
    conversation_id: str,
) -> ConversationModel | None:
    return await session.get(ConversationModel, conversation_id)


async def list_workflow_runs_for_conversation(
    session: async_sa.AsyncSession,
    *,
    conversation_id: str,
) -> list[WorkflowRecord]:
    result = await session.execute(
        sa.select(WorkflowRunModel)
        .where(WorkflowRunModel.conversation_id == conversation_id)
        .order_by(WorkflowRunModel.updated_at.desc(), WorkflowRunModel.created_at.desc())
    )
    return [_workflow_record_from_model(model) for model in result.scalars()]


async def list_required_actions(
    session: async_sa.AsyncSession,
    *,
    workflow_id: str,
) -> list[RequiredActionModel]:
    result = await session.execute(
        sa.select(RequiredActionModel)
        .where(RequiredActionModel.workflow_id == workflow_id)
        .order_by(RequiredActionModel.created_at.asc(), RequiredActionModel.question_id.asc().nulls_last())
    )
    return list(result.scalars())


async def list_conversation_items(
    session: async_sa.AsyncSession,
    *,
    workflow_id: str | None = None,
    conversation_id: str | None = None,
) -> list[ConversationItemModel]:
    if workflow_id is None and conversation_id is None:
        return []

    query = sa.select(ConversationItemModel)
    if workflow_id is not None:
        query = query.where(ConversationItemModel.workflow_id == workflow_id)
    if conversation_id is not None:
        query = query.where(ConversationItemModel.conversation_id == conversation_id)
    result = await session.execute(
        query.order_by(ConversationItemModel.created_at.asc(), ConversationItemModel.item_id.asc())
    )
    return list(result.scalars())


async def mark_running_workflows_failed(session: async_sa.AsyncSession) -> int:
    now = datetime.datetime.now(datetime.timezone.utc)
    result = await session.execute(
        sa.update(WorkflowRunModel)
        .where(WorkflowRunModel.workflow_status == str(WorkflowStatus.RUNNING))
        .values(
            workflow_status=str(WorkflowStatus.FAILED),
            error_message="Service restarted",
            updated_at=now,
        )
        .returning(WorkflowRunModel.workflow_id, WorkflowRunModel.conversation_id, WorkflowRunModel.current_step_id)
    )
    rows = list(result.fetchall())
    for workflow_id, conversation_id, current_step_id in rows:
        session.add(
            ConversationItemModel(
                conversation_id=conversation_id,
                workflow_id=workflow_id,
                item_kind="workflow_status_changed",
                actor="service",
                step_id=current_step_id,
                payload_json={
                    "previous_status": str(WorkflowStatus.RUNNING),
                    "workflow_status": str(WorkflowStatus.FAILED),
                    "error_message": "Service restarted",
                },
                created_at=now,
            )
        )
    await session.commit()
    return len(rows)
