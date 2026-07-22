from __future__ import annotations

_TRUNCATION_MARKER = "...[truncated]"


def truncate_text(value: str, *, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    cutoff = max(0, max_chars - len(_TRUNCATION_MARKER))
    return value[:cutoff] + _TRUNCATION_MARKER


def sanitize_text(value: str | None, *, max_chars: int) -> str | None:
    if value is None:
        return None
    return truncate_text(value, max_chars=max_chars)
