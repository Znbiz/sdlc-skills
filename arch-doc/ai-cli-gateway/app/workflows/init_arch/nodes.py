from __future__ import annotations

import asyncio
import os
import typing

import structlog
from langgraph.types import interrupt

from app.workflows.init_arch.guard import run_guard
from app.workflows.init_arch.prompts import CHECKLIST_ITEM_TO_REFERENCE, build_step_prompt
from app.workflows.init_arch.state import InitArchState

logger = structlog.get_logger()

_MAX_RETRY: typing.Final[int] = 3


async def _run_cli(state: InitArchState, prompt_text: str) -> str:
    engine = state["engine_name"]
    cwd = state["workspace_dir"]
    timeout = float(state["timeout_seconds"])

    if engine == "claude":
        cmd = ["claude", "-p", prompt_text, "--output-format", "stream-json"]
    else:
        cmd = ["codex", "exec", "--sandbox", "workspace-write", "--skip-git-repo-check", "--json", prompt_text]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env={**os.environ},
    )
    stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(_stderr.decode())
    return stdout.decode()


async def node_define_scope(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.define_scope")
    try:
        guard_out = await run_guard(
            "init",
            "--output", state["progress_file_path"],
            "--product", state["product_name"],
            "--scope", state["analysis_scope"],
        )
        prompt_text = build_step_prompt("define_scope", state)
        cli_output = await _run_cli(state, prompt_text)
        await run_guard(
            "advance",
            "--progress", state["progress_file_path"],
            "--step", "define_scope",
            "--note", "Scope определён через LangGraph",
        )
        completed = [*state.get("completed_steps", []), "define_scope"]
    except Exception as exc:  # noqa: BLE001
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    else:
        return {
            "current_step_id": "request_repository_list",
            "completed_steps": completed,
            "last_cli_output": cli_output,
            "last_guard_output": guard_out,
            "step_error": None,
            "retry_count": 0,
        }


async def node_request_repository_list(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.request_repository_list")
    if state.get("repo_list"):
        await run_guard(
            "advance",
            "--progress", state["progress_file_path"],
            "--step", "request_repository_list",
            "--note", f"Репозитории: {', '.join(state['repo_list'])}",
        )
        completed = [*state.get("completed_steps", []), "request_repository_list"]
        return {
            "current_step_id": "prepare_temp_workspace",
            "completed_steps": completed,
            "step_error": None,
            "retry_count": 0,
        }

    interrupt({
        "interrupt_type": "user_input",
        "field": "repo_list",
        "question": "Укажите список репозиториев для анализа (имена через запятую или JSON-массив)",
    })
    return {}


async def node_prepare_temp_workspace(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.prepare_temp_workspace")
    try:
        prompt_text = build_step_prompt("prepare_temp_workspace", state)
        cli_output = await _run_cli(state, prompt_text)
        await run_guard(
            "advance",
            "--progress", state["progress_file_path"],
            "--step", "prepare_temp_workspace",
        )
        completed = [*state.get("completed_steps", []), "prepare_temp_workspace"]
    except Exception as exc:  # noqa: BLE001
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    else:
        return {
            "current_step_id": "clone_repositories",
            "completed_steps": completed,
            "last_cli_output": cli_output,
            "step_error": None,
            "retry_count": 0,
        }


async def node_clone_repositories(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.clone_repositories")
    try:
        prompt_text = build_step_prompt("clone_repositories", state)
        cli_output = await _run_cli(state, prompt_text)
        await run_guard("advance", "--progress", state["progress_file_path"], "--step", "clone_repositories")
        completed = [*state.get("completed_steps", []), "clone_repositories"]
    except Exception as exc:  # noqa: BLE001
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    else:
        return {
            "current_step_id": "refresh_main_branches",
            "completed_steps": completed,
            "last_cli_output": cli_output,
            "step_error": None,
            "retry_count": 0,
        }


async def node_refresh_main_branches(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.refresh_main_branches")
    try:
        prompt_text = build_step_prompt("refresh_main_branches", state)
        cli_output = await _run_cli(state, prompt_text)
        await run_guard("advance", "--progress", state["progress_file_path"], "--step", "refresh_main_branches")
        completed = [*state.get("completed_steps", []), "refresh_main_branches"]
    except Exception as exc:  # noqa: BLE001
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    else:
        return {
            "current_step_id": "plan_repository_order",
            "completed_steps": completed,
            "last_cli_output": cli_output,
            "step_error": None,
            "retry_count": 0,
        }


async def node_plan_repository_order(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.plan_repository_order")
    try:
        prompt_text = build_step_prompt("plan_repository_order", state)
        cli_output = await _run_cli(state, prompt_text)
        await run_guard("advance", "--progress", state["progress_file_path"], "--step", "plan_repository_order")
        completed = [*state.get("completed_steps", []), "plan_repository_order"]
    except Exception as exc:  # noqa: BLE001
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    else:
        return {
            "current_step_id": "assess_scope_and_domains",
            "completed_steps": completed,
            "last_cli_output": cli_output,
            "step_error": None,
            "retry_count": 0,
        }


async def node_assess_scope_and_domains(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.assess_scope_and_domains")
    try:
        prompt_text = build_step_prompt("assess_scope_and_domains", state)
        cli_output = await _run_cli(state, prompt_text)
        await run_guard("advance", "--progress", state["progress_file_path"], "--step", "assess_scope_and_domains")
        completed = [*state.get("completed_steps", []), "assess_scope_and_domains"]
        domain_strategy = "per_module" if len(state.get("repo_list", [])) == 1 else "per_domain"
    except Exception as exc:  # noqa: BLE001
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    else:
        return {
            "current_step_id": "analyze_repositories",
            "completed_steps": completed,
            "domain_strategy": domain_strategy,
            "last_cli_output": cli_output,
            "step_error": None,
            "retry_count": 0,
        }


async def node_analyze_repositories(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.analyze_repositories")
    try:
        checklist_items = list(CHECKLIST_ITEM_TO_REFERENCE.keys())
        all_cli_outputs: list[str] = []

        for repo_name in state.get("repo_list", []):
            await run_guard("repo", "--start", "--progress", state["progress_file_path"], "--repo", repo_name)

            for item_id in checklist_items:
                prompt_text = build_step_prompt("analyze_repositories", state, checklist_item_id=item_id)
                cli_out = await _run_cli({**state, "current_repo_name": repo_name}, prompt_text)
                all_cli_outputs.append(cli_out)
                await run_guard(
                    "repo", "--checklist-item",
                    "--progress", state["progress_file_path"],
                    "--repo", repo_name,
                    "--item", item_id,
                )

            await run_guard("repo", "--complete", "--progress", state["progress_file_path"], "--repo", repo_name)

        await run_guard("advance", "--progress", state["progress_file_path"], "--step", "analyze_repositories")
        completed = [*state.get("completed_steps", []), "analyze_repositories"]
    except Exception as exc:  # noqa: BLE001
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    else:
        return {
            "current_step_id": "interview_user",
            "completed_steps": completed,
            "last_cli_output": "\n---\n".join(all_cli_outputs),
            "step_error": None,
            "retry_count": 0,
        }


async def node_interview_user(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.interview_user")
    answered = state.get("answered_questions", [])
    remaining = [q for q in state.get("open_questions", []) if q not in answered]

    if not remaining:
        await run_guard(
            "advance",
            "--progress", state["progress_file_path"],
            "--step", "interview_user",
            "--note", "Все вопросы закрыты",
        )
        completed = [*state.get("completed_steps", []), "interview_user"]
        return {
            "current_step_id": "refine_features",
            "completed_steps": completed,
            "step_error": None,
            "retry_count": 0,
        }

    current_question = remaining[0]
    interrupt({
        "interrupt_type": "user_question",
        "question": current_question,
        "remaining_count": len(remaining) - 1,
    })
    return {}


async def node_refine_features(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.refine_features")
    try:
        prompt_text = build_step_prompt("refine_features", state)
        cli_output = await _run_cli(state, prompt_text)
        await run_guard("advance", "--progress", state["progress_file_path"], "--step", "refine_features")
        completed = [*state.get("completed_steps", []), "refine_features"]
    except Exception as exc:  # noqa: BLE001
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    else:
        return {
            "current_step_id": "build_navigation_index",
            "completed_steps": completed,
            "last_cli_output": cli_output,
            "step_error": None,
            "retry_count": 0,
        }


async def node_build_navigation_index(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.build_navigation_index")
    try:
        prompt_text = build_step_prompt("build_navigation_index", state)
        cli_output = await _run_cli(state, prompt_text)
        await run_guard("advance", "--progress", state["progress_file_path"], "--step", "build_navigation_index")
        completed = [*state.get("completed_steps", []), "build_navigation_index"]
    except Exception as exc:  # noqa: BLE001
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    else:
        return {
            "current_step_id": "run_knowledge_lint",
            "completed_steps": completed,
            "last_cli_output": cli_output,
            "step_error": None,
            "retry_count": 0,
        }


async def node_run_knowledge_lint(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.run_knowledge_lint")
    try:
        prompt_text = build_step_prompt("run_knowledge_lint", state)
        cli_output = await _run_cli(state, prompt_text)
        await run_guard("advance", "--progress", state["progress_file_path"], "--step", "run_knowledge_lint")
        completed = [*state.get("completed_steps", []), "run_knowledge_lint"]
    except Exception as exc:  # noqa: BLE001
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    else:
        return {
            "current_step_id": "validate_final",
            "completed_steps": completed,
            "last_cli_output": cli_output,
            "step_error": None,
            "retry_count": 0,
        }


async def node_validate_final(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.validate_final")
    try:
        prompt_text = build_step_prompt("validate_final", state)
        cli_output = await _run_cli(state, prompt_text)
        await run_guard("advance", "--progress", state["progress_file_path"], "--step", "validate_final")
        completed = [*state.get("completed_steps", []), "validate_final"]
    except Exception as exc:  # noqa: BLE001
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    else:
        return {
            "current_step_id": "finalize_progress",
            "completed_steps": completed,
            "last_cli_output": cli_output,
            "step_error": None,
            "retry_count": 0,
        }


async def node_finalize_progress(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.finalize_progress")
    try:
        await run_guard("finalize", "--progress", state["progress_file_path"])
        completed = [*state.get("completed_steps", []), "finalize_progress"]
    except Exception as exc:  # noqa: BLE001
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    else:
        return {"current_step_id": "done", "completed_steps": completed, "step_error": None, "retry_count": 0}


async def node_handle_error(state: InitArchState) -> dict[str, typing.Any]:
    logger.error(
        "workflow.node.error",
        step=state.get("current_step_id"),
        error=state.get("step_error"),
        retry_count=state.get("retry_count"),
    )
    return {}
