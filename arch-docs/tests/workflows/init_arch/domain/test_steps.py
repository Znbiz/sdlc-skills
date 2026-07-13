from app.workflows.init_arch.domain import STEP_DEFINITION_BY_ID, STEP_DEFINITIONS, StepId


def test_generate_release_notes_is_between_validate_final_and_confirm_window() -> None:
    step_ids = [definition.step_id for definition in STEP_DEFINITIONS]

    validate_final_index = step_ids.index(StepId.VALIDATE_FINAL)
    generate_notes_index = step_ids.index(StepId.GENERATE_RELEASE_NOTES)
    confirm_window_index = step_ids.index(StepId.CONFIRM_NEXT_TEMPORAL_WINDOW)

    assert validate_final_index < generate_notes_index < confirm_window_index


def test_generate_release_notes_requires_validate_final_and_uses_llm() -> None:
    definition = STEP_DEFINITION_BY_ID[StepId.GENERATE_RELEASE_NOTES]

    assert definition.required_previous_steps == [StepId.VALIDATE_FINAL]
    assert definition.uses_llm_worker is True
    assert definition.requires_historical_prep is False


def test_confirm_next_temporal_window_now_requires_generate_release_notes() -> None:
    definition = STEP_DEFINITION_BY_ID[StepId.CONFIRM_NEXT_TEMPORAL_WINDOW]

    assert definition.required_previous_steps == [StepId.GENERATE_RELEASE_NOTES]
