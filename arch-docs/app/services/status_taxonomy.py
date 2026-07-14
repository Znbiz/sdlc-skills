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
