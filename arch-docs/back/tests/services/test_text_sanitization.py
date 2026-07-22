from app.services.text_sanitization import sanitize_text, truncate_text


def test_truncate_text_keeps_short_text_unchanged():
    assert truncate_text("short", max_chars=100) == "short"


def test_truncate_text_appends_marker_when_over_limit():
    result = truncate_text("a" * 30, max_chars=20)
    assert result.endswith("...[truncated]")
    assert len(result) == 20


def test_sanitize_text_returns_none_for_none():
    assert sanitize_text(None, max_chars=100) is None


def test_sanitize_text_does_not_mask_secrets():
    result = sanitize_text("Authorization: Bearer abc123", max_chars=100)
    assert result == "Authorization: Bearer abc123"


def test_sanitize_text_truncates_long_values():
    result = sanitize_text("z" * 30, max_chars=20)
    assert result is not None
    assert result.endswith("...[truncated]")
