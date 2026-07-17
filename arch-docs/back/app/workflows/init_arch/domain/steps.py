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
        step_id=StepId.BUILD_NAVIGATION_INDEX,
        title="Build navigation index",
        required_previous_steps=[StepId.REFINE_FEATURES],
    ),
    StepDefinition(
        step_id=StepId.RUN_KNOWLEDGE_LINT,
        title="Run knowledge lint",
        required_previous_steps=[StepId.BUILD_NAVIGATION_INDEX],
        uses_llm_worker=False,
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
