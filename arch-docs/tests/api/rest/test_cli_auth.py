import datetime
import json
import unittest.mock
import uuid

import httpx
from fastapi import status

from app.services.cli_auth_checker import CliAuthStatus
from app.services.cli_auth_session import AuthFlowStatus, CliAuthSession, get_auth_session_registry


def _parse_sse(raw: str) -> list[dict]:
    return [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]


class TestGetCliAuthStatus:
    async def test_returns_status_for_both_engines(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        ok_info = {"authenticated": True, "auth_status": CliAuthStatus.OK, "auth_file_exists": True}

        with (
            unittest.mock.patch("app.api.rest.cli_auth.check_codex_auth", return_value=ok_info),
            unittest.mock.patch("app.api.rest.cli_auth.check_claude_auth", return_value=ok_info),
        ):
            response = await async_client.get("/api/rest/cli-auth/", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "codex" in data
        assert "claude" in data
        assert data["codex"]["auth_status"] == "ok"
        assert data["claude"]["authenticated"] is True

    async def test_returns_not_initialized_when_no_auth(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        not_init = {"authenticated": False, "auth_status": CliAuthStatus.NOT_INITIALIZED, "auth_file_exists": False}

        with (
            unittest.mock.patch("app.api.rest.cli_auth.check_codex_auth", return_value=not_init),
            unittest.mock.patch("app.api.rest.cli_auth.check_claude_auth", return_value=not_init),
        ):
            response = await async_client.get("/api/rest/cli-auth/", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["codex"]["auth_status"] == "not_initialized"

    async def test_requires_auth(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.get("/api/rest/cli-auth/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestGetAuthSession:
    def _add_session(
        self,
        cli_engine: str = "codex",
        auth_flow_status: AuthFlowStatus = AuthFlowStatus.PENDING,
        instructions: str | None = None,
    ) -> CliAuthSession:
        session = CliAuthSession(
            auth_session_id=str(uuid.uuid4()),
            cli_engine=cli_engine,
            auth_flow_status=auth_flow_status,
            instructions=instructions,
        )
        get_auth_session_registry()[session.auth_session_id] = session
        return session

    async def test_returns_session_by_id(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        session = self._add_session(cli_engine="codex", auth_flow_status=AuthFlowStatus.PENDING)

        response = await async_client.get(
            f"/api/rest/cli-auth/auth-sessions/{session.auth_session_id}/",
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["auth_session_id"] == session.auth_session_id
        assert data["cli_engine"] == "codex"
        assert data["auth_flow_status"] == "pending"

    async def test_returns_404_for_unknown_session(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        response = await async_client.get(
            f"/api/rest/cli-auth/auth-sessions/{uuid.uuid4()}/",
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_marks_expired_when_ttl_exceeded(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        session = self._add_session(auth_flow_status=AuthFlowStatus.PENDING)
        session.expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)

        response = await async_client.get(
            f"/api/rest/cli-auth/auth-sessions/{session.auth_session_id}/",
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["auth_flow_status"] == "expired"

    async def test_returns_instructions_when_set(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        session = self._add_session(instructions="Open https://chatgpt.com/device and enter: XXXX-XXXX")

        response = await async_client.get(
            f"/api/rest/cli-auth/auth-sessions/{session.auth_session_id}/",
            headers=auth_headers,
        )

        assert response.json()["instructions"] == "Open https://chatgpt.com/device and enter: XXXX-XXXX"

    async def test_requires_auth(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.get(f"/api/rest/cli-auth/auth-sessions/{uuid.uuid4()}/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestStreamAuthSession:
    def _add_session(
        self,
        cli_engine: str = "codex",
        auth_flow_status: AuthFlowStatus = AuthFlowStatus.SUCCESS,
        output_lines: list[str] | None = None,
    ) -> CliAuthSession:
        session = CliAuthSession(
            auth_session_id=str(uuid.uuid4()),
            cli_engine=cli_engine,
            auth_flow_status=auth_flow_status,
        )
        if output_lines:
            session.output_lines.extend(output_lines)
        get_auth_session_registry()[session.auth_session_id] = session
        return session

    async def test_streams_error_for_unknown_session(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        fake_id = str(uuid.uuid4())
        response = await async_client.get(
            f"/api/rest/cli-auth/auth-sessions/{fake_id}/stream/",
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        events = _parse_sse(response.text)
        assert events[0]["event_type"] == "error"

    async def test_streams_auth_success(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        session = self._add_session(
            cli_engine="codex",
            auth_flow_status=AuthFlowStatus.SUCCESS,
            output_lines=["Open https://device.example.com enter: ABCD-1234"],
        )

        response = await async_client.get(
            f"/api/rest/cli-auth/auth-sessions/{session.auth_session_id}/stream/",
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        events = _parse_sse(response.text)
        instructions = [e for e in events if e["event_type"] == "instructions"]
        assert len(instructions) == 1
        assert instructions[0]["event_data"] == "Open https://device.example.com enter: ABCD-1234"
        done_event = events[-1]
        assert done_event["event_type"] == "auth_success"
        assert done_event["cli_engine"] == "codex"

    async def test_streams_auth_failed(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        session = self._add_session(auth_flow_status=AuthFlowStatus.FAILED)

        response = await async_client.get(
            f"/api/rest/cli-auth/auth-sessions/{session.auth_session_id}/stream/",
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        assert events[-1]["event_type"] == "auth_failed"

    async def test_streams_expired_session(
        self,
        async_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        session = self._add_session(auth_flow_status=AuthFlowStatus.PENDING)
        session.expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)

        response = await async_client.get(
            f"/api/rest/cli-auth/auth-sessions/{session.auth_session_id}/stream/",
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        assert events[-1]["event_type"] == "auth_failed"

    async def test_requires_auth(self, async_client: httpx.AsyncClient) -> None:
        session = self._add_session()
        response = await async_client.get(f"/api/rest/cli-auth/auth-sessions/{session.auth_session_id}/stream/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
