import asyncio
import os
import typing

import fastmcp
import structlog

logger = structlog.get_logger()

mcp_server = fastmcp.FastMCP("ai-gateway")

INIT_ARCH_PROMPT: typing.Final = "/init-repo-arch-skill"
UPDATE_ARCH_PROMPT_BASE: typing.Final = "/update-repo-arch-skill"


async def run_cli_subprocess(
    engine_name: str,
    prompt_text: str,
    workspace_dir: str,
    timeout_seconds: int,
) -> str:
    if engine_name == "claude":
        cmd = ["claude", "-p", prompt_text, "--output-format", "stream-json"]
    else:
        cmd = [
            "codex",
            "exec",
            "--sandbox",
            "workspace-write",
            "--skip-git-repo-check",
            "--json",
            prompt_text,
        ]

    logger.info("mcp.cli_subprocess.started", engine=engine_name, workspace_dir=workspace_dir)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=workspace_dir,
        env={**os.environ},
    )
    stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=float(timeout_seconds))
    exit_code = proc.returncode or 0

    logger.info("mcp.cli_subprocess.finished", engine=engine_name, exit_code=exit_code)

    if exit_code != 0:
        raise RuntimeError(stderr_bytes.decode())

    return stdout_bytes.decode()


@mcp_server.tool()
async def init_arch(
    repo_path: str,
    engine_name: str = "claude",
    timeout_seconds: int = 600,
) -> dict:
    """Инициализирует архитектурную документацию для репозитория через init-repo-arch-skill."""
    logger.info("mcp.init_arch.called", repo_path=repo_path, engine=engine_name)
    cli_output = await run_cli_subprocess(engine_name, INIT_ARCH_PROMPT, repo_path, timeout_seconds)
    return {"operation_status": "success", "cli_output": cli_output}


@mcp_server.tool()
async def update_arch(
    repo_path: str,
    diff_context: str = "",
    engine_name: str = "claude",
    timeout_seconds: int = 600,
) -> dict:
    """Обновляет архитектурную документацию на основе изменений в репозитории."""
    logger.info("mcp.update_arch.called", repo_path=repo_path, engine=engine_name)
    prompt_text = f"{UPDATE_ARCH_PROMPT_BASE}\n{diff_context}" if diff_context else UPDATE_ARCH_PROMPT_BASE
    cli_output = await run_cli_subprocess(engine_name, prompt_text, repo_path, timeout_seconds)
    return {"operation_status": "success", "cli_output": cli_output}


@mcp_server.tool()
async def query(
    question: str,
    repo_path: str,
    engine_name: str = "claude",
    timeout_seconds: int = 120,
) -> dict:
    """Отвечает на вопрос по архитектуре репозитория, читая артефакты из arch-doc/."""
    logger.info("mcp.query.called", repo_path=repo_path, engine=engine_name)
    prompt_text = f"Прочитай arch-doc/ и ответь на вопрос: {question}"
    answer_text = await run_cli_subprocess(engine_name, prompt_text, repo_path, timeout_seconds)
    return {"answer_text": answer_text}
