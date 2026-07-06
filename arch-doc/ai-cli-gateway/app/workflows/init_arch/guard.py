from __future__ import annotations

import asyncio
import pathlib

from app.settings import GatewaySettings


async def run_guard(*args: str) -> str:
    settings = GatewaySettings()
    guard_script = pathlib.Path(settings.skill_root_dir) / "init-repo-arch-skill/scripts/analysis_guard.py"
    cmd = ["python", str(guard_script), *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"analysis_guard failed: {stderr.decode()}")
    return stdout.decode()
