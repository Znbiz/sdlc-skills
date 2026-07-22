from __future__ import annotations

import pydantic

from app.workflows.init_arch.domain.models import StepId


class StepDefinition(pydantic.BaseModel):
    step_id: StepId
    title: str
    required_previous_steps: list[StepId] = pydantic.Field(default_factory=list)
    uses_llm_worker: bool = True
    requires_historical_prep: bool = False
    allows_user_pause: bool = False


STEP_DEFINITIONS: tuple[StepDefinition, ...] = (
    StepDefinition(step_id=StepId.DEFINE_SCOPE, title="Define scope", uses_llm_worker=False),
    StepDefinition(
        step_id=StepId.REQUEST_REPOSITORY_LIST,
        title="Request repository list",
        required_previous_steps=[StepId.DEFINE_SCOPE],
        uses_llm_worker=False,
        allows_user_pause=True,
    ),
    StepDefinition(
        step_id=StepId.PREPARE_TEMP_WORKSPACE,
        title="Prepare temp workspace",
        required_previous_steps=[StepId.REQUEST_REPOSITORY_LIST],
        uses_llm_worker=False,
    ),
    StepDefinition(
        step_id=StepId.CLONE_REPOSITORIES,
        title="Clone repositories",
        required_previous_steps=[StepId.PREPARE_TEMP_WORKSPACE],
        uses_llm_worker=False,
    ),
    StepDefinition(
        step_id=StepId.REFRESH_MAIN_BRANCHES,
        title="Refresh main branches",
        required_previous_steps=[StepId.CLONE_REPOSITORIES],
        uses_llm_worker=False,
    ),
    StepDefinition(
        step_id=StepId.PLAN_REPOSITORY_ORDER,
        title="Plan repository order",
        required_previous_steps=[StepId.REFRESH_MAIN_BRANCHES],
        uses_llm_worker=False,
    ),
    StepDefinition(
        step_id=StepId.ASSESS_SCOPE_AND_DOMAINS,
        title="Assess scope and domains",
        required_previous_steps=[StepId.PLAN_REPOSITORY_ORDER],
        requires_historical_prep=True,
    ),
    StepDefinition(
        step_id=StepId.ANALYZE_REPOSITORIES,
        title="Analyze repositories",
        required_previous_steps=[StepId.ASSESS_SCOPE_AND_DOMAINS],
        requires_historical_prep=True,
    ),
    StepDefinition(
        step_id=StepId.INTERVIEW_USER,
        title="Interview user",
        required_previous_steps=[StepId.ANALYZE_REPOSITORIES],
        allows_user_pause=True,
    ),
    StepDefinition(
        step_id=StepId.REFINE_FEATURES,
        title="Refine features",
        required_previous_steps=[StepId.INTERVIEW_USER],
    ),
    StepDefinition(
        # uses_llm_worker=True (default) is conditional: the node only calls the LLM worker when the
        # deterministic compile step finds a blocking graph issue that needs an autofix pass.
        step_id=StepId.BUILD_NAVIGATION_INDEX,
        title="Build navigation index",
        required_previous_steps=[StepId.REFINE_FEATURES],
    ),
    StepDefinition(
        # uses_llm_worker=True is conditional, same as BUILD_NAVIGATION_INDEX above: only called when the
        # deterministic lint finds a blocking issue that needs an autofix pass.
        step_id=StepId.RUN_KNOWLEDGE_LINT,
        title="Run knowledge lint",
        required_previous_steps=[StepId.BUILD_NAVIGATION_INDEX],
    ),
    StepDefinition(
        step_id=StepId.VALIDATE_FINAL,
        title="Validate final output",
        required_previous_steps=[StepId.RUN_KNOWLEDGE_LINT],
        uses_llm_worker=False,
    ),
    StepDefinition(
        step_id=StepId.GENERATE_RELEASE_NOTES,
        title="Generate release notes",
        required_previous_steps=[StepId.VALIDATE_FINAL],
    ),
    StepDefinition(
        step_id=StepId.CONFIRM_NEXT_TEMPORAL_WINDOW,
        title="Confirm next temporal window",
        required_previous_steps=[StepId.GENERATE_RELEASE_NOTES],
        uses_llm_worker=False,
        allows_user_pause=True,
    ),
    StepDefinition(
        step_id=StepId.FINALIZE_PROGRESS,
        title="Finalize progress",
        required_previous_steps=[StepId.CONFIRM_NEXT_TEMPORAL_WINDOW],
        uses_llm_worker=False,
    ),
)


STEP_DEFINITION_BY_ID = {definition.step_id: definition for definition in STEP_DEFINITIONS}


# Человекочитаемые названия шагов для SSE/UI (см. arch-docs/docs/spec/2026-07-22-realtime-workflow-observability.md).
# Ключ — строковое значение StepId (не сам enum): `step_started` в SSE и `WorkflowRecord.current_step_id`
# оперируют строками, в том числе "analyze_repositories_item" — физическим графовым узлом внутри
# StepId.ANALYZE_REPOSITORIES, не отдельным StepId (см. init-graph-reference.md, нода 8).
STEP_LABELS_RU: dict[str, str] = {
    StepId.DEFINE_SCOPE.value: "Определение области анализа",
    StepId.REQUEST_REPOSITORY_LIST.value: "Запрос списка репозиториев",
    StepId.PREPARE_TEMP_WORKSPACE.value: "Подготовка рабочей директории",
    StepId.CLONE_REPOSITORIES.value: "Клонирование репозиториев",
    StepId.REFRESH_MAIN_BRANCHES.value: "Обновление main-веток",
    StepId.PLAN_REPOSITORY_ORDER.value: "Планирование порядка анализа",
    StepId.ASSESS_SCOPE_AND_DOMAINS.value: "Оценка объёма и доменов репозитория",
    StepId.ANALYZE_REPOSITORIES.value: "Анализ репозиториев",
    "analyze_repositories_item": "Анализ репозитория (пункт чеклиста)",
    StepId.INTERVIEW_USER.value: "Интервью с пользователем",
    StepId.REFINE_FEATURES.value: "Описание фич продукта",
    StepId.BUILD_NAVIGATION_INDEX.value: "Сборка навигационного индекса",
    StepId.RUN_KNOWLEDGE_LINT.value: "Проверка целостности документации",
    StepId.VALIDATE_FINAL.value: "Финальная проверка консистентности",
    StepId.GENERATE_RELEASE_NOTES.value: "Генерация release notes",
    StepId.CONFIRM_NEXT_TEMPORAL_WINDOW.value: "Подтверждение следующего временного окна",
    StepId.FINALIZE_PROGRESS.value: "Завершение прогона",
    StepId.DONE.value: "Готово",
}


def step_label_ru(step_id: str) -> str:
    return STEP_LABELS_RU.get(step_id, step_id)
