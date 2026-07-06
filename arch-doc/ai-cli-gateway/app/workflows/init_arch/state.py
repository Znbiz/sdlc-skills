from __future__ import annotations

import typing


class InitArchState(typing.TypedDict):
    # параметры запуска
    product_name: str
    analysis_scope: str
    workspace_dir: str
    arch_repo_dir: str
    engine_name: str
    timeout_seconds: int

    # прогресс
    progress_file_path: str
    current_step_id: str
    current_repo_name: str
    completed_steps: list[str]

    # данные шагов
    repo_list: list[str]
    domain_strategy: str
    open_questions: list[str]
    answered_questions: list[str]
    pending_user_question: str

    # вывод CLI и guard
    last_cli_output: str
    last_guard_output: str

    # ошибки и retry
    step_error: str | None
    retry_count: int
