# Frontend Backend Capabilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the minimal backend surface needed by the new `arch-docs-front` React SPA: a shared status/reason-code taxonomy, a PAT-based Git credentials flow (replacing the in-progress ad-hoc `git-credentials` endpoints with the spec's exact contract), workflow path metadata (`workspace_dir`/`arch_repo_dir`) on responses, and a response-scoped read-only docs browser API.

**Architecture:** Extend existing routers/services in place (`app/api/rest/conversations.py`, `app/services/init_arch_workflow.py`, `app/db/workflow_repo.py`) rather than introducing a parallel platform. Two new small modules are added: `app/services/status_taxonomy.py` (shared enums) and `app/services/docs_browser.py` + `app/api/rest/docs.py` (response-scoped docs viewer). The existing `git_credentials` service/API (added in an earlier, incomplete pass) is reshaped to match the spec's exact endpoint contract and moved fully under `app/api/rest/` (the spec lists no RPC endpoints for git credentials), and the existing `app/api/rpc/git_credentials.py` is deleted.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2.x (async) + Alembic, existing `GatewaySettings`, `git` subprocess checks, pytest + real Postgres test container (`just test-db-up`).

## Global Constraints

- Backend остаётся source of truth for readiness and generated docs access.
- Never return token contents, auth files, or unfiltered shell output to the frontend.
- All filesystem operations are confined to the allowed workspace and the generated arch-repo directory for a given response.
- New capabilities are read-only except explicit actions (`start auth`, `submit action`, `rerun readiness checks`, PAT set/delete, access-check).
- Do not break existing consumers (`open-webui`, existing workflow transports, existing `cli-auth`/`git-ssh` endpoints).
- Git access readiness must be operationally meaningful (a real `git ls-remote`, not just "git is installed").
- Plaintext PAT must never appear in logs, exception text, SSE events, or the DB read-model.
- Typed reason codes over free-text messages; frontend depends on reason codes.
- Error mapping: `404` missing file/response resource, `403` path traversal/forbidden path, `422` invalid probe payload, `503` optional for transient dependency unavailability.

---

## File Structure

- `app/services/status_taxonomy.py` — **create**. Shared `CheckStatus` enum (`ok`, `warning`, `failed`, `running`, `unknown`) and `ReasonCode` enum with every code from the spec's taxonomy.
- `app/services/git_credentials.py` — **modify**. Keep the git-credential-store mechanics (already correct), add git-binary-missing detection and reason-code classification, add a masked-status accessor and a `delete_git_token` function.
- `app/api/rest/git_credentials.py` — **modify**. Becomes the single home for all git-credentials endpoints: `GET /git-credentials/`, `PUT /git-credentials/personal-access-token/`, `DELETE /git-credentials/personal-access-token/`, `POST /git-credentials/check-access/`.
- `app/api/rpc/git_credentials.py` — **delete** (spec defines no RPC endpoints for this capability; its logic moves into `app/api/rest/git_credentials.py`).
- `app/api/__init__.py` — **modify**. Drop the RPC git-credentials router registration; register the new docs router.
- `app/services/workflow_registry.py` — **modify**. Add `workspace_dir: str = ""` and `arch_repo_dir: str = ""` to `WorkflowRecord`.
- `app/db/models.py` — **modify**. Add `workspace_dir`/`arch_repo_dir` text columns to `WorkflowRunModel`.
- `migrations/versions/0006_add_workflow_path_metadata.py` — **create**. Alembic migration adding the two columns.
- `app/db/workflow_repo.py` — **modify**. Persist and hydrate the two new fields in `upsert_workflow_run` / `_workflow_record_from_model`.
- `app/services/init_arch_workflow.py` — **modify**. Set `record.workspace_dir` / `record.arch_repo_dir` in `start_init_arch_workflow`; include both fields in `_workflow_response_payload` and `_task_response_payload`; add `get_response_arch_repo_dir_async(response_id)` helper used by the docs API.
- `app/api/rest/conversations.py` — **modify**. Add `workspace_dir`/`arch_repo_dir` to `ResponseStatusResponse` and `_response_model`.
- `app/services/docs_browser.py` — **create**. Path normalization (traversal-safe), tree walking, media-kind detection, text file reading with size/encoding metadata.
- `app/api/rest/docs.py` — **create**. `GET /responses/{response_id}/docs/tree/` and `GET /responses/{response_id}/docs/file/`.
- Tests mirror each module under `tests/services/` and `tests/api/rest/` (existing `tests/services/test_git_credentials.py` and `tests/api/rest/test_git_credentials.py` are updated in place; `tests/api/rpc/test_git_credentials.py` is deleted).

---

### Task 1: Shared status/reason-code taxonomy

**Files:**
- Create: `app/services/status_taxonomy.py`
- Test: `tests/services/test_status_taxonomy.py`

**Interfaces:**
- Produces: `CheckStatus` (StrEnum: `OK`, `WARNING`, `FAILED`, `RUNNING`, `UNKNOWN`, values via `enum.auto()`), `AggregateStatus` (StrEnum: `READY`, `DEGRADED`, `BLOCKED`), `ReasonCode` (StrEnum with members `CODEX_NOT_AUTHENTICATED`, `CLAUDE_NOT_AUTHENTICATED`, `GIT_BINARY_MISSING`, `GIT_PAT_MISSING`, `GIT_PAT_INVALID`, `GIT_ACCESS_AUTH_FAILED`, `GIT_ACCESS_TIMEOUT`, `GIT_ACCESS_ERROR`, `ARCH_REPO_MISSING_FOR_RESPONSE`, `PATH_FORBIDDEN`, `FILE_UNSUPPORTED`, values via `enum.auto()`).

- [ ] **Step 1: Write the failing test**

```python
import pytest

from app.services.status_taxonomy import AggregateStatus, CheckStatus, ReasonCode


def test_check_status_values():
    assert CheckStatus.OK == "ok"
    assert CheckStatus.WARNING == "warning"
    assert CheckStatus.FAILED == "failed"
    assert CheckStatus.RUNNING == "running"
    assert CheckStatus.UNKNOWN == "unknown"


def test_aggregate_status_values():
    assert AggregateStatus.READY == "ready"
    assert AggregateStatus.DEGRADED == "degraded"
    assert AggregateStatus.BLOCKED == "blocked"


@pytest.mark.parametrize(
    "member,expected",
    [
        (ReasonCode.CODEX_NOT_AUTHENTICATED, "codex_not_authenticated"),
        (ReasonCode.CLAUDE_NOT_AUTHENTICATED, "claude_not_authenticated"),
        (ReasonCode.GIT_BINARY_MISSING, "git_binary_missing"),
        (ReasonCode.GIT_PAT_MISSING, "git_pat_missing"),
        (ReasonCode.GIT_PAT_INVALID, "git_pat_invalid"),
        (ReasonCode.GIT_ACCESS_AUTH_FAILED, "git_access_auth_failed"),
        (ReasonCode.GIT_ACCESS_TIMEOUT, "git_access_timeout"),
        (ReasonCode.GIT_ACCESS_ERROR, "git_access_error"),
        (ReasonCode.ARCH_REPO_MISSING_FOR_RESPONSE, "arch_repo_missing_for_response"),
        (ReasonCode.PATH_FORBIDDEN, "path_forbidden"),
        (ReasonCode.FILE_UNSUPPORTED, "file_unsupported"),
    ],
)
def test_reason_code_values(member, expected):
    assert member == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test tests/services/test_status_taxonomy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.status_taxonomy'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

import enum


class CheckStatus(enum.StrEnum):
    OK = enum.auto()
    WARNING = enum.auto()
    FAILED = enum.auto()
    RUNNING = enum.auto()
    UNKNOWN = enum.auto()


class AggregateStatus(enum.StrEnum):
    READY = enum.auto()
    DEGRADED = enum.auto()
    BLOCKED = enum.auto()


class ReasonCode(enum.StrEnum):
    CODEX_NOT_AUTHENTICATED = enum.auto()
    CLAUDE_NOT_AUTHENTICATED = enum.auto()
    GIT_BINARY_MISSING = enum.auto()
    GIT_PAT_MISSING = enum.auto()
    GIT_PAT_INVALID = enum.auto()
    GIT_ACCESS_AUTH_FAILED = enum.auto()
    GIT_ACCESS_TIMEOUT = enum.auto()
    GIT_ACCESS_ERROR = enum.auto()
    ARCH_REPO_MISSING_FOR_RESPONSE = enum.auto()
    PATH_FORBIDDEN = enum.auto()
    FILE_UNSUPPORTED = enum.auto()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `just test tests/services/test_status_taxonomy.py -v`
Expected: PASS (3 tests, 11 parametrized cases)

- [ ] **Step 5: Commit**

```bash
git add app/services/status_taxonomy.py tests/services/test_status_taxonomy.py
git commit -m "feat(arch-docs): добавить общий словарь статусов и reason codes"
```

---

### Task 2: Git credentials service — binary check + reason codes + delete

**Files:**
- Modify: `app/services/git_credentials.py`
- Test: `tests/services/test_git_credentials.py`

**Interfaces:**
- Consumes: `ReasonCode` from Task 1 (`app.services.status_taxonomy`).
- Produces: `GitAccessResult` gains a `reason_code: str | None` key. New `delete_git_token(host: str) -> bool` (returns whether an entry was removed). New `is_git_pat_configured() -> bool` via `list_configured_hosts()` non-empty (no new function needed, callers just check `bool(hosts)`). `check_git_access` now short-circuits to `GIT_PAT_MISSING` when no hosts are configured, and to `GIT_BINARY_MISSING` when the `git` binary is absent (`FileNotFoundError` from subprocess exec).

- [ ] **Step 1: Write the failing tests**

Add to `tests/services/test_git_credentials.py`:

```python
class TestDeleteGitToken:
    async def test_removes_existing_host(self):
        await set_git_token(host="github.com", token="tok-a")
        await set_git_token(host="gitlab.com", token="tok-b")

        removed = await delete_git_token("github.com")

        assert removed is True
        assert await list_configured_hosts() == ["gitlab.com"]

    async def test_returns_false_when_host_not_configured(self):
        assert await delete_git_token("github.com") is False


class TestCheckGitAccessReasonCodes:
    async def test_missing_pat_short_circuits_before_subprocess(self, isolated_git_credentials_store):
        with unittest.mock.patch("asyncio.create_subprocess_exec") as mock_exec:
            result = await check_git_access("https://github.com/org/repo.git")

        mock_exec.assert_not_called()
        assert result["accessible"] is False
        assert result["reason_code"] == "git_pat_missing"

    async def test_git_binary_missing_maps_to_reason_code(self):
        await set_git_token(host="github.com", token="tok-a")

        with unittest.mock.patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            result = await check_git_access("https://github.com/org/repo.git")

        assert result["accessible"] is False
        assert result["reason_code"] == "git_binary_missing"

    async def test_auth_failed_maps_to_reason_code(self):
        await set_git_token(host="github.com", token="tok-a")
        mock_proc = unittest.mock.AsyncMock()
        mock_proc.communicate = unittest.mock.AsyncMock(
            return_value=(b"", b"fatal: Authentication failed")
        )
        mock_proc.returncode = 128

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await check_git_access("https://github.com/org/repo.git")

        assert result["reason_code"] == "git_access_auth_failed"

    async def test_ok_result_has_no_reason_code(self):
        await set_git_token(host="github.com", token="tok-a")
        mock_proc = unittest.mock.AsyncMock()
        mock_proc.communicate = unittest.mock.AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await check_git_access("https://github.com/org/repo.git")

        assert result["reason_code"] is None
```

Update the existing imports at the top of the test file:

```python
from app.services.git_credentials import (
    GitAccessStatus,
    check_git_access,
    delete_git_token,
    ensure_git_credentials_store,
    list_configured_hosts,
    set_git_token,
)
```

Existing tests in `TestCheckGitAccess` configure no host before calling `check_git_access` (only the `_store_already_configured` autouse fixture runs `ensure_git_credentials_store`, no token). Update that class's autouse fixture to also register a token, since access checks now require a configured PAT to reach the subprocess at all:

```python
class TestCheckGitAccess:
    @pytest.fixture(autouse=True)
    async def _store_already_configured(self):
        await ensure_git_credentials_store()
        await set_git_token(host="github.com", token="tok-a")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test tests/services/test_git_credentials.py -v`
Expected: FAIL — `delete_git_token` not defined, `reason_code` key missing/KeyError, `test_missing_pat_short_circuits_before_subprocess` asserts a subprocess call that currently happens.

- [ ] **Step 3: Write implementation**

Edit `app/services/git_credentials.py`:

```python
import enum
...
from app.services.status_taxonomy import ReasonCode
```

Extend `GitAccessResult`:

```python
class GitAccessResult(typing.TypedDict):
    accessible: bool
    access_status: str
    reason_code: str | None
    message: str
```

Add reason-code mapping and rewrite `check_git_access`:

```python
_ACCESS_STATUS_REASON_CODES: typing.Final[dict[GitAccessStatus, ReasonCode]] = {
    GitAccessStatus.AUTH_FAILED: ReasonCode.GIT_ACCESS_AUTH_FAILED,
    GitAccessStatus.TIMEOUT: ReasonCode.GIT_ACCESS_TIMEOUT,
    GitAccessStatus.ERROR: ReasonCode.GIT_ACCESS_ERROR,
}


async def delete_git_token(host: str) -> bool:
    if not _CREDENTIALS_FILE.exists():
        return False
    existing_lines = _CREDENTIALS_FILE.read_text().splitlines()
    kept_lines = [line for line in existing_lines if line and _host_of_credentials_line(line) != host]
    if len(kept_lines) == len(existing_lines):
        return False
    content = "\n".join(kept_lines)
    _CREDENTIALS_FILE.write_text(f"{content}\n" if content else "")
    _CREDENTIALS_FILE.chmod(0o600)
    return True


async def check_git_access(repository_url: str) -> GitAccessResult:
    await ensure_git_credentials_store()

    if not await list_configured_hosts():
        return GitAccessResult(
            accessible=False,
            access_status=GitAccessStatus.AUTH_FAILED,
            reason_code=ReasonCode.GIT_PAT_MISSING,
            message="No Git personal access token is configured",
        )

    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        exit_code, stderr_text = await _run_git_access_check(
            ["git", "ls-remote", "--exit-code", repository_url, "HEAD"],
            env=env,
        )
    except FileNotFoundError:
        return GitAccessResult(
            accessible=False,
            access_status=GitAccessStatus.ERROR,
            reason_code=ReasonCode.GIT_BINARY_MISSING,
            message="git binary is not available in this container",
        )

    if exit_code == 0:
        return GitAccessResult(accessible=True, access_status=GitAccessStatus.OK, reason_code=None, message="ok")

    access_status = _classify_git_access_failure(stderr_text)
    return GitAccessResult(
        accessible=False,
        access_status=access_status,
        reason_code=_ACCESS_STATUS_REASON_CODES[access_status],
        message=stderr_text.strip() or f"git ls-remote exited with code {exit_code}",
    )
```

`_run_git_access_check` currently calls `asyncio.create_subprocess_exec` directly and lets `FileNotFoundError` propagate — no change needed there, the `try/except` in `check_git_access` now catches it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test tests/services/test_git_credentials.py -v`
Expected: PASS, all tests including the pre-existing ones (now updated to configure a token first).

- [ ] **Step 5: Commit**

```bash
git add app/services/git_credentials.py tests/services/test_git_credentials.py
git commit -m "feat(arch-docs): добавить reason codes и удаление PAT в git_credentials"
```

---

### Task 3: Git credentials REST API — full spec contract, remove RPC duplicate

**Files:**
- Modify: `app/api/rest/git_credentials.py`
- Delete: `app/api/rpc/git_credentials.py`
- Delete: `tests/api/rpc/test_git_credentials.py`
- Modify: `tests/api/rest/test_git_credentials.py`
- Modify: `app/api/__init__.py`

**Interfaces:**
- Consumes: `check_git_access`, `delete_git_token`, `list_configured_hosts`, `set_git_token` from `app.services.git_credentials` (Task 2).
- Produces: REST endpoints `GET /api/rest/git-credentials/`, `PUT /api/rest/git-credentials/personal-access-token/`, `DELETE /api/rest/git-credentials/personal-access-token/`, `POST /api/rest/git-credentials/check-access/`.

- [ ] **Step 1: Write the failing tests**

Replace `tests/api/rest/test_git_credentials.py` entirely:

```python
import unittest.mock

import httpx
from fastapi import status


class TestGetGitCredentialsStatus:
    async def test_returns_configured_true_with_hosts(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with unittest.mock.patch(
            "app.api.rest.git_credentials.list_configured_hosts",
            new=unittest.mock.AsyncMock(return_value=["github.com"]),
        ):
            response = await async_client.get("/api/rest/git-credentials/", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"configured": True, "configured_hosts": ["github.com"]}

    async def test_returns_configured_false_when_empty(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with unittest.mock.patch(
            "app.api.rest.git_credentials.list_configured_hosts",
            new=unittest.mock.AsyncMock(return_value=[]),
        ):
            response = await async_client.get("/api/rest/git-credentials/", headers=auth_headers)

        assert response.json() == {"configured": False, "configured_hosts": []}

    async def test_requires_auth(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.get("/api/rest/git-credentials/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestPutPersonalAccessToken:
    async def test_stores_token_and_returns_masked_status(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with (
            unittest.mock.patch(
                "app.api.rest.git_credentials.set_git_token", new=unittest.mock.AsyncMock()
            ) as mock_set,
            unittest.mock.patch(
                "app.api.rest.git_credentials.list_configured_hosts",
                new=unittest.mock.AsyncMock(return_value=["github.com"]),
            ),
        ):
            response = await async_client.put(
                "/api/rest/git-credentials/personal-access-token/",
                json={"host": "github.com", "token": "ghp_abc123"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"configured": True, "configured_hosts": ["github.com"]}
        mock_set.assert_awaited_once_with(host="github.com", token="ghp_abc123", username=None)

    async def test_rejects_empty_token(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await async_client.put(
            "/api/rest/git-credentials/personal-access-token/",
            json={"host": "github.com", "token": "   "},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_never_echoes_token_back(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with (
            unittest.mock.patch("app.api.rest.git_credentials.set_git_token", new=unittest.mock.AsyncMock()),
            unittest.mock.patch(
                "app.api.rest.git_credentials.list_configured_hosts",
                new=unittest.mock.AsyncMock(return_value=["github.com"]),
            ),
        ):
            response = await async_client.put(
                "/api/rest/git-credentials/personal-access-token/",
                json={"host": "github.com", "token": "super-secret-token"},
                headers=auth_headers,
            )

        assert "super-secret-token" not in response.text


class TestDeletePersonalAccessToken:
    async def test_removes_token_for_host(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with (
            unittest.mock.patch(
                "app.api.rest.git_credentials.delete_git_token", new=unittest.mock.AsyncMock(return_value=True)
            ) as mock_delete,
            unittest.mock.patch(
                "app.api.rest.git_credentials.list_configured_hosts", new=unittest.mock.AsyncMock(return_value=[])
            ),
        ):
            response = await async_client.request(
                "DELETE",
                "/api/rest/git-credentials/personal-access-token/",
                params={"host": "github.com"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"configured": False, "configured_hosts": []}
        mock_delete.assert_awaited_once_with("github.com")


class TestCheckGitCredentialsAccess:
    async def test_returns_access_result_with_reason_code(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with unittest.mock.patch(
            "app.api.rest.git_credentials.check_git_access",
            new=unittest.mock.AsyncMock(
                return_value={
                    "accessible": False,
                    "access_status": "auth_failed",
                    "reason_code": "git_pat_missing",
                    "message": "No Git personal access token is configured",
                }
            ),
        ):
            response = await async_client.post(
                "/api/rest/git-credentials/check-access/",
                json={"repository_url": "https://github.com/org/repo.git"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["accessible"] is False
        assert body["reason_code"] == "git_pat_missing"

    async def test_rejects_empty_repository_url(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await async_client.post(
            "/api/rest/git-credentials/check-access/",
            json={"repository_url": "  "},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
```

Delete `tests/api/rpc/test_git_credentials.py` (its behavior is now covered above under `tests/api/rest/`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test tests/api/rest/test_git_credentials.py -v`
Expected: FAIL — no `PUT`/`DELETE` routes exist yet (404/405), `GET` doesn't return a `configured` key.

- [ ] **Step 3: Write implementation**

Replace `app/api/rest/git_credentials.py`:

```python
import fastapi
import pydantic

from app.services.git_credentials import check_git_access, delete_git_token, list_configured_hosts, set_git_token

router = fastapi.APIRouter()


class GitCredentialsStatusResponse(pydantic.BaseModel, frozen=True):
    configured: bool
    configured_hosts: list[str]


class SetPersonalAccessTokenRequest(pydantic.BaseModel, frozen=True):
    host: str
    token: str
    username: str | None = None

    @pydantic.field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped or "/" in stripped or "://" in stripped:
            msg = "host must be a bare hostname, e.g. 'github.com'"
            raise ValueError(msg)
        return stripped

    @pydantic.field_validator("token")
    @classmethod
    def validate_token(cls, value: str) -> str:
        if not value.strip():
            msg = "token must not be empty"
            raise ValueError(msg)
        return value


class CheckGitAccessRequest(pydantic.BaseModel, frozen=True):
    repository_url: str

    @pydantic.field_validator("repository_url")
    @classmethod
    def validate_repository_url(cls, value: str) -> str:
        if not value.strip():
            msg = "repository_url must not be empty"
            raise ValueError(msg)
        return value


class CheckGitAccessResponse(pydantic.BaseModel, frozen=True):
    repository_url: str
    accessible: bool
    access_status: str
    reason_code: str | None
    message: str


async def _status_response() -> GitCredentialsStatusResponse:
    hosts = await list_configured_hosts()
    return GitCredentialsStatusResponse(configured=bool(hosts), configured_hosts=hosts)


@router.get("/git-credentials/")
async def get_git_credentials_status() -> GitCredentialsStatusResponse:
    return await _status_response()


@router.put("/git-credentials/personal-access-token/")
async def set_personal_access_token(request: SetPersonalAccessTokenRequest) -> GitCredentialsStatusResponse:
    await set_git_token(host=request.host, token=request.token, username=request.username)
    return await _status_response()


@router.delete("/git-credentials/personal-access-token/")
async def delete_personal_access_token(host: str) -> GitCredentialsStatusResponse:
    await delete_git_token(host)
    return await _status_response()


@router.post("/git-credentials/check-access/")
async def check_git_credentials_access(request: CheckGitAccessRequest) -> CheckGitAccessResponse:
    result = await check_git_access(request.repository_url)
    return CheckGitAccessResponse(
        repository_url=request.repository_url,
        accessible=result["accessible"],
        access_status=result["access_status"],
        reason_code=result["reason_code"],
        message=result["message"],
    )
```

Delete `app/api/rpc/git_credentials.py`.

Edit `app/api/__init__.py` to drop the RPC registration:

```python
import fastapi

from app.api.openai import router as openai_router
from app.api.rest.cli_auth import router as rest_cli_auth_router
from app.api.rest.conversations import router as rest_conversations_router
from app.api.rest.git_credentials import router as rest_git_credentials_router
from app.api.rest.tasks import router as rest_tasks_router
from app.api.rpc.cli_auth import router as rpc_cli_auth_router
from app.api.rpc.execute import router as rpc_execute_router


def setup_routers(app: fastapi.FastAPI) -> None:
    app.include_router(openai_router, tags=["openai"])
    app.include_router(rpc_execute_router, prefix="/api/rpc", tags=["rpc"])
    app.include_router(rpc_cli_auth_router, prefix="/api/rpc", tags=["rpc"])
    app.include_router(rest_tasks_router, prefix="/api/rest", tags=["rest"])
    app.include_router(rest_cli_auth_router, prefix="/api/rest", tags=["rest"])
    app.include_router(rest_git_credentials_router, prefix="/api/rest", tags=["rest"])
    app.include_router(rest_conversations_router, prefix="/api/rest", tags=["rest"])
```

(The docs router is added to this file in Task 5.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test tests/api/rest/test_git_credentials.py tests/services/test_git_credentials.py -v`
Expected: PASS. Also run `uv run --extra dev python -m pytest --collect-only` to confirm no lingering references to the deleted `tests/api/rpc/test_git_credentials.py` / `app/api/rpc/git_credentials.py`.

- [ ] **Step 5: Commit**

```bash
git add app/api/rest/git_credentials.py app/api/__init__.py tests/api/rest/test_git_credentials.py
git rm app/api/rpc/git_credentials.py tests/api/rpc/test_git_credentials.py
git commit -m "feat(arch-docs): переписать git-credentials REST API под контракт спеки"
```

---

### Task 4: Workflow path metadata — model, migration, persistence, payload

**Files:**
- Modify: `app/services/workflow_registry.py`
- Modify: `app/db/models.py`
- Create: `migrations/versions/0006_add_workflow_path_metadata.py`
- Modify: `app/db/workflow_repo.py`
- Modify: `app/services/init_arch_workflow.py`
- Modify: `app/api/rest/conversations.py`
- Test: `tests/db/test_workflow_repo.py` (new cases), `tests/services/test_init_arch_workflow.py` (new cases), `tests/api/rest/test_conversations.py` (new cases)

**Interfaces:**
- Consumes: nothing new.
- Produces: `WorkflowRecord.workspace_dir: str`, `WorkflowRecord.arch_repo_dir: str`; `_workflow_response_payload`/`_task_response_payload` dicts gain `workspace_dir`/`arch_repo_dir` keys; `ResponseStatusResponse.workspace_dir: str`, `ResponseStatusResponse.arch_repo_dir: str`; `get_response_arch_repo_dir_async(response_id: str) -> str` (raises `WorkflowNotFoundError` if the response doesn't exist, raises `ArchRepoNotAvailableError` — new exception class in `app.services.init_arch_workflow` — if `arch_repo_dir` is empty) used by Task 6's docs API.

- [ ] **Step 1: Write the failing tests**

Add to `tests/services/test_init_arch_workflow.py` (near the other `start_init_arch_workflow` tests):

```python
async def test_start_init_arch_workflow_persists_resolved_paths(monkeypatch):
    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", AsyncMock())
    monkeypatch.setattr("app.services.init_arch_workflow.asyncio.create_task", asyncio.create_task)
    monkeypatch.setattr("app.services.init_arch_workflow.run_workflow", AsyncMock())

    record = await workflow_module.start_init_arch_workflow(
        product_name="svc",
        analysis_scope="full",
        workspace_dir="/workspace",
        arch_repo_dir="/workspace/arch",
        repo_list=["repo-a"],
        engine_name="claude",
        timeout_seconds=30,
        conversation_id="conv-paths",
    )

    assert record.workspace_dir == "/workspace"
    assert record.arch_repo_dir == "/workspace/arch"
    record.asyncio_task.cancel()


async def test_workflow_response_payload_includes_path_metadata():
    record = workflow_module.WorkflowRecord(
        workflow_id="wf-1",
        conversation_id="conv-1",
        workspace_dir="/workspace",
        arch_repo_dir="/workspace/arch",
    )
    payload = workflow_module._workflow_response_payload(record, [])
    assert payload["workspace_dir"] == "/workspace"
    assert payload["arch_repo_dir"] == "/workspace/arch"


async def test_get_response_arch_repo_dir_async_returns_path(monkeypatch):
    record = workflow_module.WorkflowRecord(workflow_id="wf-2", arch_repo_dir="/workspace/arch")
    monkeypatch.setattr(
        "app.services.init_arch_workflow.get_workflow_record_async", AsyncMock(return_value=record)
    )

    result = await workflow_module.get_response_arch_repo_dir_async("wf-2")

    assert result == "/workspace/arch"


async def test_get_response_arch_repo_dir_async_raises_when_missing(monkeypatch):
    record = workflow_module.WorkflowRecord(workflow_id="wf-3", arch_repo_dir="")
    monkeypatch.setattr(
        "app.services.init_arch_workflow.get_workflow_record_async", AsyncMock(return_value=record)
    )

    with pytest.raises(workflow_module.ArchRepoNotAvailableError):
        await workflow_module.get_response_arch_repo_dir_async("wf-3")
```

Add to `tests/db/test_workflow_repo.py` (a round-trip test alongside existing `upsert_workflow_run`/`get_workflow_run` tests):

```python
async def test_upsert_and_get_workflow_run_round_trips_path_metadata(db_session):
    record = WorkflowRecord(
        workflow_id="wf-paths",
        conversation_id="conv-paths",
        workspace_dir="/workspace",
        arch_repo_dir="/workspace/arch",
    )

    await upsert_workflow_run(db_session, record)
    loaded = await get_workflow_run(db_session, "wf-paths")

    assert loaded.workspace_dir == "/workspace"
    assert loaded.arch_repo_dir == "/workspace/arch"
```

(Import `WorkflowRecord` from `app.services.workflow_registry` and `upsert_workflow_run`/`get_workflow_run` from `app.db.workflow_repo` at the top of that test file if not already imported — check existing imports first and extend rather than duplicate.)

Add to `tests/api/rest/test_conversations.py` (find the existing test that mocks `get_response_async`/`create_response_async` and asserts on the JSON body; extend its payload fixture and assertions):

```python
async def test_get_response_includes_path_metadata(async_client, auth_headers, monkeypatch):
    payload = {
        "response_id": "wf-1",
        "conversation_id": "conv-1",
        "workflow_type": "init_arch",
        "response_status": "running",
        "current_step_id": "define_scope",
        "current_repo_name": "",
        "completed_steps": [],
        "required_actions": [],
        "created_at": "2026-07-14T00:00:00+00:00",
        "updated_at": "2026-07-14T00:00:00+00:00",
        "error_message": None,
        "terminal_result": None,
        "workspace_dir": "/workspace",
        "arch_repo_dir": "/workspace/arch",
    }
    monkeypatch.setattr(
        "app.api.rest.conversations.get_response_async", unittest.mock.AsyncMock(return_value=payload)
    )

    response = await async_client.get("/api/rest/responses/wf-1/", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["workspace_dir"] == "/workspace"
    assert response.json()["arch_repo_dir"] == "/workspace/arch"
```

(Check the existing file's import style — it likely already imports `unittest.mock`; reuse the established `async_client`/`auth_headers` fixtures and existing mock-patching conventions used by neighboring tests in that file rather than introducing a new pattern.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test tests/services/test_init_arch_workflow.py tests/db/test_workflow_repo.py tests/api/rest/test_conversations.py -v`
Expected: FAIL — `WorkflowRecord` has no `workspace_dir`/`arch_repo_dir` kwargs, `ArchRepoNotAvailableError`/`get_response_arch_repo_dir_async` undefined, response payload missing the two keys.

- [ ] **Step 3: Write implementation**

Edit `app/services/workflow_registry.py`, add two fields to `WorkflowRecord` (after `current_repo_name`):

```python
    current_repo_name: str = ""
    workspace_dir: str = ""
    arch_repo_dir: str = ""
```

Edit `app/db/models.py`, add two columns to `WorkflowRunModel` (after `current_repo_name`):

```python
    current_repo_name: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False, default="")
    workspace_dir: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False, default="")
    arch_repo_dir: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False, default="")
```

Create `migrations/versions/0006_add_workflow_path_metadata.py`:

```python
"""add workflow path metadata

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs", sa.Column("workspace_dir", sa.Text(), nullable=False, server_default="")
    )
    op.add_column(
        "workflow_runs", sa.Column("arch_repo_dir", sa.Text(), nullable=False, server_default="")
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "arch_repo_dir")
    op.drop_column("workflow_runs", "workspace_dir")
```

Edit `app/db/workflow_repo.py`:

In `_workflow_record_from_model`, add to the constructed `WorkflowRecord`:

```python
        current_repo_name=model.current_repo_name,
        workspace_dir=model.workspace_dir,
        arch_repo_dir=model.arch_repo_dir,
```

In `upsert_workflow_run`, in the `if existing is None:` branch's `WorkflowRunModel(...)` constructor, add:

```python
            current_repo_name=record.current_repo_name,
            workspace_dir=record.workspace_dir,
            arch_repo_dir=record.arch_repo_dir,
```

In the `else:` branch (update path), add:

```python
        existing.current_repo_name = record.current_repo_name
        existing.workspace_dir = record.workspace_dir
        existing.arch_repo_dir = record.arch_repo_dir
```

Edit `app/services/init_arch_workflow.py`:

Add near the other exception classes:

```python
class ArchRepoNotAvailableError(RuntimeError):
    pass
```

In `start_init_arch_workflow`, after building `record` and before `registry[workflow_id] = record`:

```python
    record = WorkflowRecord(
        workflow_id=workflow_id,
        conversation_id=conversation_id or workflow_id,
        session=session,
        workspace_dir=resolved_workspace_dir,
        arch_repo_dir=resolved_arch_repo_dir,
    )
```

In `_workflow_response_payload`, add two keys to the returned dict:

```python
        "current_repo_name": record.current_repo_name,
        "workspace_dir": record.workspace_dir,
        "arch_repo_dir": record.arch_repo_dir,
```

In `_task_response_payload`, add:

```python
        "current_repo_name": task.repository_name or pathlib.Path(task.workspace_dir).name,
        "workspace_dir": task.workspace_dir,
        "arch_repo_dir": "",
```

Add a new function near `get_response_async`:

```python
async def get_response_arch_repo_dir_async(response_id: str) -> str:
    record = await get_workflow_record_async(response_id)
    if not record.arch_repo_dir:
        raise ArchRepoNotAvailableError(f"No arch_repo_dir recorded for response {response_id!r}")
    return record.arch_repo_dir
```

Edit `app/api/rest/conversations.py`:

Add fields to `ResponseStatusResponse` (after `current_repo_name`):

```python
    current_repo_name: str
    workspace_dir: str
    arch_repo_dir: str
```

Add to `_response_model`:

```python
        current_repo_name=payload["current_repo_name"],
        workspace_dir=payload["workspace_dir"],
        arch_repo_dir=payload["arch_repo_dir"],
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test tests/services/test_init_arch_workflow.py tests/db/test_workflow_repo.py tests/api/rest/test_conversations.py -v`
Expected: PASS. Also run `just test-db-up && uv run --project . alembic upgrade head` (or `just agent-check`, which runs the full suite against the migrated test DB) to confirm migration `0006` applies cleanly on top of `0005`.

- [ ] **Step 5: Commit**

```bash
git add app/services/workflow_registry.py app/db/models.py migrations/versions/0006_add_workflow_path_metadata.py \
        app/db/workflow_repo.py app/services/init_arch_workflow.py app/api/rest/conversations.py \
        tests/services/test_init_arch_workflow.py tests/db/test_workflow_repo.py tests/api/rest/test_conversations.py
git commit -m "feat(arch-docs): сохранять workspace_dir и arch_repo_dir для init_arch run"
```

---

### Task 5: Docs browser service — path normalization, tree, file read

**Files:**
- Create: `app/services/docs_browser.py`
- Test: `tests/services/test_docs_browser.py`

**Interfaces:**
- Consumes: nothing new (pure filesystem + `pathlib`).
- Produces: `MediaKind` enum (`MARKDOWN`, `YAML`, `JSON`, `TEXT`, `UNSUPPORTED`); `DocsPathForbiddenError(ValueError)`; `DocsFileNotFoundError(LookupError)`; `detect_media_kind(path: pathlib.Path) -> MediaKind`; `build_docs_tree(arch_repo_root: str) -> dict` (recursive `{path, name, node_type, children, size, modified_at, media_kind}`); `read_docs_file(arch_repo_root: str, relative_path: str) -> dict` (`{path, name, media_kind, content, encoding, size, modified_at}`, with `content=None`/`encoding=None` when `media_kind == MediaKind.UNSUPPORTED`); `resolve_within_root(arch_repo_root: str, relative_path: str) -> pathlib.Path` (raises `DocsPathForbiddenError` on traversal, `DocsFileNotFoundError` if the resolved path doesn't exist).

- [ ] **Step 1: Write the failing test**

```python
import pathlib

import pytest

from app.services.docs_browser import (
    DocsFileNotFoundError,
    DocsPathForbiddenError,
    MediaKind,
    build_docs_tree,
    detect_media_kind,
    read_docs_file,
    resolve_within_root,
)


@pytest.fixture
def arch_repo(tmp_path):
    root = tmp_path / "arch-doc"
    root.mkdir()
    (root / "README.md").write_text("# Title\n")
    (root / "architecture").mkdir()
    (root / "architecture" / "hld.md").write_text("# HLD\n")
    (root / "architecture" / "tech-stack.yaml").write_text("stack: python\n")
    (root / "config.json").write_text("{}\n")
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    return root


class TestDetectMediaKind:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("README.md", MediaKind.MARKDOWN),
            ("tech-stack.yaml", MediaKind.YAML),
            ("tech-stack.yml", MediaKind.YAML),
            ("config.json", MediaKind.JSON),
            ("notes.txt", MediaKind.TEXT),
            ("logo.png", MediaKind.UNSUPPORTED),
        ],
    )
    def test_maps_extension_to_media_kind(self, filename, expected):
        assert detect_media_kind(pathlib.Path(filename)) == expected


class TestResolveWithinRoot:
    def test_resolves_valid_relative_path(self, arch_repo):
        resolved = resolve_within_root(str(arch_repo), "architecture/hld.md")
        assert resolved == arch_repo / "architecture" / "hld.md"

    def test_rejects_parent_traversal(self, arch_repo):
        with pytest.raises(DocsPathForbiddenError):
            resolve_within_root(str(arch_repo), "../outside.md")

    def test_rejects_absolute_escape_via_symlink_style_path(self, arch_repo):
        with pytest.raises(DocsPathForbiddenError):
            resolve_within_root(str(arch_repo), "architecture/../../outside.md")

    def test_raises_not_found_for_missing_file(self, arch_repo):
        with pytest.raises(DocsFileNotFoundError):
            resolve_within_root(str(arch_repo), "does-not-exist.md")


class TestBuildDocsTree:
    def test_builds_nested_tree_with_media_kinds(self, arch_repo):
        tree = build_docs_tree(str(arch_repo))

        assert tree["node_type"] == "directory"
        assert tree["path"] == ""
        names = {child["name"] for child in tree["children"]}
        assert names == {"README.md", "architecture", "config.json", "logo.png"}

        readme = next(child for child in tree["children"] if child["name"] == "README.md")
        assert readme["node_type"] == "file"
        assert readme["media_kind"] == "markdown"
        assert readme["size"] > 0
        assert readme["modified_at"]

        architecture = next(child for child in tree["children"] if child["name"] == "architecture")
        assert architecture["node_type"] == "directory"
        assert {c["name"] for c in architecture["children"]} == {"hld.md", "tech-stack.yaml"}


class TestReadDocsFile:
    def test_reads_markdown_file_content(self, arch_repo):
        result = read_docs_file(str(arch_repo), "README.md")

        assert result["media_kind"] == "markdown"
        assert result["content"] == "# Title\n"
        assert result["encoding"] == "utf-8"
        assert result["size"] > 0

    def test_returns_metadata_only_for_unsupported_binary(self, arch_repo):
        result = read_docs_file(str(arch_repo), "logo.png")

        assert result["media_kind"] == "unsupported"
        assert result["content"] is None
        assert result["encoding"] is None

    def test_rejects_path_traversal(self, arch_repo):
        with pytest.raises(DocsPathForbiddenError):
            read_docs_file(str(arch_repo), "../outside.md")

    def test_raises_not_found_for_missing_file(self, arch_repo):
        with pytest.raises(DocsFileNotFoundError):
            read_docs_file(str(arch_repo), "missing.md")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test tests/services/test_docs_browser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.docs_browser'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

import datetime
import enum
import pathlib
import typing


class MediaKind(enum.StrEnum):
    MARKDOWN = enum.auto()
    YAML = enum.auto()
    JSON = enum.auto()
    TEXT = enum.auto()
    UNSUPPORTED = enum.auto()


class DocsPathForbiddenError(ValueError):
    pass


class DocsFileNotFoundError(LookupError):
    pass


_MEDIA_KIND_BY_SUFFIX: typing.Final[dict[str, MediaKind]] = {
    ".md": MediaKind.MARKDOWN,
    ".markdown": MediaKind.MARKDOWN,
    ".yaml": MediaKind.YAML,
    ".yml": MediaKind.YAML,
    ".json": MediaKind.JSON,
    ".txt": MediaKind.TEXT,
    ".rst": MediaKind.TEXT,
}


def detect_media_kind(path: pathlib.Path) -> MediaKind:
    return _MEDIA_KIND_BY_SUFFIX.get(path.suffix.lower(), MediaKind.UNSUPPORTED)


def resolve_within_root(arch_repo_root: str, relative_path: str) -> pathlib.Path:
    root = pathlib.Path(arch_repo_root).expanduser().resolve()
    candidate = (root / relative_path).resolve()

    if candidate != root and root not in candidate.parents:
        raise DocsPathForbiddenError(f"Path {relative_path!r} escapes arch_repo_root")
    if not candidate.exists():
        raise DocsFileNotFoundError(f"Path {relative_path!r} does not exist")
    return candidate


def _node_metadata(path: pathlib.Path, *, root: pathlib.Path) -> dict[str, typing.Any]:
    stat = path.stat()
    return {
        "path": str(path.relative_to(root)) if path != root else "",
        "name": path.name if path != root else "",
        "size": stat.st_size,
        "modified_at": datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc).isoformat(),
    }


def _build_node(path: pathlib.Path, *, root: pathlib.Path) -> dict[str, typing.Any]:
    metadata = _node_metadata(path, root=root)
    if path.is_dir():
        children = sorted(path.iterdir(), key=lambda child: (child.is_file(), child.name))
        return {
            **metadata,
            "node_type": "directory",
            "children": [_build_node(child, root=root) for child in children],
            "media_kind": None,
        }
    return {
        **metadata,
        "node_type": "file",
        "children": None,
        "media_kind": detect_media_kind(path).value,
    }


def build_docs_tree(arch_repo_root: str) -> dict[str, typing.Any]:
    root = pathlib.Path(arch_repo_root).expanduser().resolve()
    return _build_node(root, root=root)


def read_docs_file(arch_repo_root: str, relative_path: str) -> dict[str, typing.Any]:
    resolved = resolve_within_root(arch_repo_root, relative_path)
    if resolved.is_dir():
        raise DocsFileNotFoundError(f"Path {relative_path!r} is a directory, not a file")

    media_kind = detect_media_kind(resolved)
    stat = resolved.stat()
    base = {
        "path": relative_path,
        "name": resolved.name,
        "media_kind": media_kind.value,
        "size": stat.st_size,
        "modified_at": datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc).isoformat(),
    }

    if media_kind == MediaKind.UNSUPPORTED:
        return {**base, "content": None, "encoding": None}

    return {**base, "content": resolved.read_text(encoding="utf-8"), "encoding": "utf-8"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `just test tests/services/test_docs_browser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/docs_browser.py tests/services/test_docs_browser.py
git commit -m "feat(arch-docs): добавить docs_browser сервис для tree/file чтения"
```

---

### Task 6: Docs browser REST API

**Files:**
- Create: `app/api/rest/docs.py`
- Modify: `app/api/__init__.py`
- Test: `tests/api/rest/test_docs.py`

**Interfaces:**
- Consumes: `get_response_arch_repo_dir_async` from `app.services.init_arch_workflow` (Task 4), `ArchRepoNotAvailableError` from the same module, `build_docs_tree`/`read_docs_file`/`DocsPathForbiddenError`/`DocsFileNotFoundError` from `app.services.docs_browser` (Task 5), `WorkflowNotFoundError` from `app.services.init_arch_workflow`.
- Produces: `GET /api/rest/responses/{response_id}/docs/tree/`, `GET /api/rest/responses/{response_id}/docs/file/?path=<relative-path>`.

- [ ] **Step 1: Write the failing tests**

```python
import unittest.mock

import httpx
from fastapi import status


class TestGetDocsTree:
    async def test_returns_tree_for_response(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with (
            unittest.mock.patch(
                "app.api.rest.docs.get_response_arch_repo_dir_async",
                new=unittest.mock.AsyncMock(return_value="/workspace/arch"),
            ),
            unittest.mock.patch(
                "app.api.rest.docs.build_docs_tree",
                return_value={
                    "path": "",
                    "name": "",
                    "node_type": "directory",
                    "children": [],
                    "size": 0,
                    "modified_at": "2026-07-14T00:00:00+00:00",
                    "media_kind": None,
                },
            ),
        ):
            response = await async_client.get(
                "/api/rest/responses/wf-1/docs/tree/", headers=auth_headers
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["node_type"] == "directory"

    async def test_returns_404_when_response_missing(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        from app.services.init_arch_workflow import WorkflowNotFoundError

        with unittest.mock.patch(
            "app.api.rest.docs.get_response_arch_repo_dir_async",
            new=unittest.mock.AsyncMock(side_effect=WorkflowNotFoundError("missing")),
        ):
            response = await async_client.get(
                "/api/rest/responses/missing/docs/tree/", headers=auth_headers
            )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_returns_404_when_arch_repo_not_available(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        from app.services.init_arch_workflow import ArchRepoNotAvailableError

        with unittest.mock.patch(
            "app.api.rest.docs.get_response_arch_repo_dir_async",
            new=unittest.mock.AsyncMock(side_effect=ArchRepoNotAvailableError("no arch repo")),
        ):
            response = await async_client.get(
                "/api/rest/responses/wf-1/docs/tree/", headers=auth_headers
            )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"]["reason_code"] == "arch_repo_missing_for_response"


class TestGetDocsFile:
    async def test_returns_file_content(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with (
            unittest.mock.patch(
                "app.api.rest.docs.get_response_arch_repo_dir_async",
                new=unittest.mock.AsyncMock(return_value="/workspace/arch"),
            ),
            unittest.mock.patch(
                "app.api.rest.docs.read_docs_file",
                return_value={
                    "path": "README.md",
                    "name": "README.md",
                    "media_kind": "markdown",
                    "content": "# Title\n",
                    "encoding": "utf-8",
                    "size": 8,
                    "modified_at": "2026-07-14T00:00:00+00:00",
                },
            ),
        ):
            response = await async_client.get(
                "/api/rest/responses/wf-1/docs/file/",
                params={"path": "README.md"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["content"] == "# Title\n"

    async def test_returns_403_for_path_traversal(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        from app.services.docs_browser import DocsPathForbiddenError

        with (
            unittest.mock.patch(
                "app.api.rest.docs.get_response_arch_repo_dir_async",
                new=unittest.mock.AsyncMock(return_value="/workspace/arch"),
            ),
            unittest.mock.patch(
                "app.api.rest.docs.read_docs_file", side_effect=DocsPathForbiddenError("escape")
            ),
        ):
            response = await async_client.get(
                "/api/rest/responses/wf-1/docs/file/",
                params={"path": "../outside.md"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"]["reason_code"] == "path_forbidden"

    async def test_returns_404_for_missing_file(
        self, async_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        from app.services.docs_browser import DocsFileNotFoundError

        with (
            unittest.mock.patch(
                "app.api.rest.docs.get_response_arch_repo_dir_async",
                new=unittest.mock.AsyncMock(return_value="/workspace/arch"),
            ),
            unittest.mock.patch(
                "app.api.rest.docs.read_docs_file", side_effect=DocsFileNotFoundError("missing")
            ),
        ):
            response = await async_client.get(
                "/api/rest/responses/wf-1/docs/file/",
                params={"path": "missing.md"},
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_requires_auth(self, async_client: httpx.AsyncClient) -> None:
        response = await async_client.get(
            "/api/rest/responses/wf-1/docs/file/", params={"path": "README.md"}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test tests/api/rest/test_docs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.api.rest.docs'` (route not registered).

- [ ] **Step 3: Write implementation**

Create `app/api/rest/docs.py`:

```python
from __future__ import annotations

import typing

import fastapi
import pydantic
from fastapi import status

from app.services.docs_browser import (
    DocsFileNotFoundError,
    DocsPathForbiddenError,
    build_docs_tree,
    read_docs_file,
)
from app.services.init_arch_workflow import (
    ArchRepoNotAvailableError,
    WorkflowNotFoundError,
    get_response_arch_repo_dir_async,
)
from app.services.status_taxonomy import ReasonCode

router = fastapi.APIRouter()


class DocsTreeNode(pydantic.BaseModel, frozen=True):
    path: str
    name: str
    node_type: str
    children: list["DocsTreeNode"] | None
    size: int
    modified_at: str
    media_kind: str | None


class DocsFileResponse(pydantic.BaseModel, frozen=True):
    path: str
    name: str
    media_kind: str
    content: str | None
    encoding: str | None
    size: int
    modified_at: str


async def _resolve_arch_repo_dir(response_id: str) -> str:
    try:
        return await get_response_arch_repo_dir_async(response_id)
    except WorkflowNotFoundError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ArchRepoNotAvailableError as exc:
        raise fastapi.HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"reason_code": ReasonCode.ARCH_REPO_MISSING_FOR_RESPONSE.value, "message": str(exc)},
        ) from exc


@router.get("/responses/{response_id}/docs/tree/")
async def get_docs_tree(response_id: str) -> DocsTreeNode:
    arch_repo_dir = await _resolve_arch_repo_dir(response_id)
    tree = build_docs_tree(arch_repo_dir)
    return DocsTreeNode.model_validate(tree)


@router.get("/responses/{response_id}/docs/file/")
async def get_docs_file(response_id: str, path: str) -> DocsFileResponse:
    arch_repo_dir = await _resolve_arch_repo_dir(response_id)
    try:
        file_payload: dict[str, typing.Any] = read_docs_file(arch_repo_dir, path)
    except DocsPathForbiddenError as exc:
        raise fastapi.HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"reason_code": ReasonCode.PATH_FORBIDDEN.value, "message": str(exc)},
        ) from exc
    except DocsFileNotFoundError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return DocsFileResponse.model_validate(file_payload)
```

Edit `app/api/__init__.py` to register the router:

```python
from app.api.rest.docs import router as rest_docs_router
...
    app.include_router(rest_docs_router, prefix="/api/rest", tags=["rest"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test tests/api/rest/test_docs.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/rest/docs.py app/api/__init__.py tests/api/rest/test_docs.py
git commit -m "feat(arch-docs): добавить response-scoped docs browser API"
```

---

### Task 7: Full suite + lint pass

**Files:** none new — verification only.

**Interfaces:** none.

- [ ] **Step 1: Run full lint + type + test suite**

Run: `just agent-check`
Expected: `ruff check .` and `ruff format --check .` clean; `pytest --cov=app --cov-fail-under=74 -x` passes with coverage at or above the existing floor.

- [ ] **Step 2: Grep for accidental secret leakage in new code**

Run: `grep -rn "token" app/api/rest/git_credentials.py app/api/rest/docs.py app/services/docs_browser.py`
Expected: only the `token` field name/parameter appears — no token value is ever placed into a response model, log call, or exception message anywhere in the diff.

- [ ] **Step 3: Confirm no stale RPC git-credentials references remain**

Run: `grep -rn "rpc.git_credentials\|rpc/git_credentials" app tests`
Expected: no matches.

- [ ] **Step 4: Commit (only if Steps 1-3 required fixes)**

```bash
git add -A
git commit -m "fix(arch-docs): доводки после полного прогона suite"
```
