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
    ("member", "expected"),
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
