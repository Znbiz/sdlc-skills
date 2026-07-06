from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workflows.init_arch.guard import run_guard


async def test_run_guard_success():
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"guard output", b""))

    with patch("app.workflows.init_arch.guard.asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc), \
         patch("app.workflows.init_arch.guard.GatewaySettings") as mock_settings:
        mock_settings.return_value.skill_root_dir = "/app/skills"
        result = await run_guard("init", "--product", "test")

    assert result == "guard output"


async def test_run_guard_failure():
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"error message"))

    with patch("app.workflows.init_arch.guard.asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc), \
         patch("app.workflows.init_arch.guard.GatewaySettings") as mock_settings:
        mock_settings.return_value.skill_root_dir = "/app/skills"
        with pytest.raises(RuntimeError, match="analysis_guard failed"):
            await run_guard("advance", "--step", "define_scope")
