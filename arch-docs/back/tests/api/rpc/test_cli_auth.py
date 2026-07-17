import asyncio
import unittest.mock

import httpx
from fastapi import status

from app.services.cli_auth_session import AuthFlowStatus, get_auth_session_registry


def _make_stream_reader(data: bytes) -> unittest.mock.MagicMock:
    lines = [*data.splitlines(keepends=True), b""]
    state = {"idx": 0}

    async def readline() -> bytes:
        idx = state["idx"]
        state["idx"] += 1
        return lines[idx] if idx < len(lines) else b""

    mock_reader = unittest.mock.MagicMock()
    mock_reader.readline = readline
    return mock_reader


def _make_mock_process(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> unittest.mock.MagicMock:
    mock_proc = unittest.mock.MagicMock()
    mock_proc.returncode = returncode
    mock_proc.stdout = _make_stream_reader(stdout)
    mock_proc.stderr = _make_stream_reader(stderr)
    mock_proc.terminate = unittest.mock.MagicMock()
    mock_proc.wait = unittest.mock.AsyncMock(return_value=returncode)
    return mock_proc


class TestInitCliAuth:
    async def test_returns_202_with_session_id(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        mock_proc = _make_mock_process(returncode=0, stdout=b"Logged in successfully", stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await async_client.post(
                "/api/rpc/cli-auth/init/",
                json={"cli_engine": "codex"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert "auth_session_id" in data
        assert data["cli_engine"] == "codex"
        assert data["auth_flow_status"] == "pending"
        assert "expires_at" in data

    async def test_session_added_to_registry(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        mock_proc = _make_mock_process(returncode=0, stdout=b"ok", stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await async_client.post(
                "/api/rpc/cli-auth/init/",
                json={"cli_engine": "claude"},
                headers=auth_headers,
            )

        session_id = response.json()["auth_session_id"]
        registry = get_auth_session_registry()
        assert session_id in registry
        assert registry[session_id].cli_engine == "claude"

    async def test_invalid_engine_returns_422(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        response = await async_client.post(
            "/api/rpc/cli-auth/init/",
            json={"cli_engine": "openai"},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_requires_auth(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.post("/api/rpc/cli-auth/init/", json={"cli_engine": "codex"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_background_task_marks_success_on_exit_0(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        mock_proc = _make_mock_process(returncode=0, stdout=b"Authorization complete", stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await async_client.post(
                "/api/rpc/cli-auth/init/",
                json={"cli_engine": "codex"},
                headers=auth_headers,
            )

        session_id = response.json()["auth_session_id"]

        for _ in range(20):
            await asyncio.sleep(0)

        registry = get_auth_session_registry()
        session = registry[session_id]
        assert session.auth_flow_status == AuthFlowStatus.SUCCESS

    async def test_background_task_marks_failed_on_nonzero_exit(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        mock_proc = _make_mock_process(returncode=1, stdout=b"", stderr=b"login failed")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await async_client.post(
                "/api/rpc/cli-auth/init/",
                json={"cli_engine": "claude"},
                headers=auth_headers,
            )

        session_id = response.json()["auth_session_id"]

        for _ in range(20):
            await asyncio.sleep(0)

        registry = get_auth_session_registry()
        session = registry[session_id]
        assert session.auth_flow_status == AuthFlowStatus.FAILED

    async def test_instructions_extracted_from_output(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        output = b"Open https://chatgpt.com/device and enter code: ABCD-1234"
        mock_proc = _make_mock_process(returncode=0, stdout=output, stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await async_client.post(
                "/api/rpc/cli-auth/init/",
                json={"cli_engine": "codex"},
                headers=auth_headers,
            )

        session_id = response.json()["auth_session_id"]

        for _ in range(20):
            await asyncio.sleep(0)

        registry = get_auth_session_registry()
        session = registry[session_id]
        assert session.instructions is not None
        assert "http" in session.instructions.lower()

    async def test_verification_uri_and_user_code_extracted_and_ansi_stripped(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Mirrors real `codex login --device-auth` output: ANSI color codes wrapping the URL
        # and the one-time code on their own lines.
        output = (
            b"Welcome to Codex \x1b[90m0.144.5\x1b[0m\n"
            b"Follow these steps to sign in with ChatGPT using device code authorization:\n"
            b"\n"
            b"1. Open this link in your browser and sign in to your account\n"
            b"   \x1b[94mhttps://auth.openai.com/codex/device\x1b[0m\n"
            b"\n"
            b"2. Enter this one-time code \x1b[90m(expires in 15 minutes)\x1b[0m\n"
            b"   \x1b[94m9WFG-D3I62\x1b[0m\n"
        )
        mock_proc = _make_mock_process(returncode=0, stdout=output, stderr=b"")

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await async_client.post(
                "/api/rpc/cli-auth/init/",
                json={"cli_engine": "codex"},
                headers=auth_headers,
            )

        session_id = response.json()["auth_session_id"]

        for _ in range(20):
            await asyncio.sleep(0)

        registry = get_auth_session_registry()
        session = registry[session_id]
        assert session.verification_uri == "https://auth.openai.com/codex/device"
        assert session.user_code == "9WFG-D3I62"
        assert all("\x1b[" not in line for line in session.output_lines)
