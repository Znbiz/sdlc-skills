from __future__ import annotations

import re

_TRUNCATION_MARKER = "...[truncated]"
_SENSITIVE_INLINE_PATTERNS = (
    re.compile(r"(?i)\b(authorization:\s*bearer\s+)(\S+)"),
    re.compile(r"(?i)\b([A-Z0-9_]*(?:token|secret|password|api[_-]?key)[A-Z0-9_]*=)(\S+)"),
)


def mask_sensitive_text(value: str) -> str:
    masked = value
    for pattern in _SENSITIVE_INLINE_PATTERNS:
        masked = pattern.sub(r"\1[REDACTED]", masked)
    return masked


def truncate_text(value: str, *, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    cutoff = max(0, max_chars - len(_TRUNCATION_MARKER))
    redacted_start = value.find("[REDACTED]")
    redacted_end = redacted_start + len("[REDACTED]") if redacted_start >= 0 else -1
    if redacted_start >= 0 and redacted_start < cutoff < redacted_end:
        cutoff = redacted_end
    return value[:cutoff] + _TRUNCATION_MARKER


def sanitize_text(value: str | None, *, max_chars: int) -> str | None:
    if value is None:
        return None
    return truncate_text(mask_sensitive_text(value), max_chars=max_chars)
