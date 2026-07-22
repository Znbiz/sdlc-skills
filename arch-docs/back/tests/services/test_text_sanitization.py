from app.services.text_sanitization import mask_sensitive_text, sanitize_text, truncate_text


def test_mask_sensitive_text_redacts_bearer_token():
    assert mask_sensitive_text("Authorization: Bearer abc123") == "Authorization: Bearer [REDACTED]"


def test_mask_sensitive_text_redacts_inline_secret_assignment():
    assert mask_sensitive_text("GITHUB_TOKEN=ghp_xxx") == "GITHUB_TOKEN=[REDACTED]"


def test_mask_sensitive_text_leaves_plain_text_untouched():
    assert mask_sensitive_text("hello world") == "hello world"


def test_truncate_text_keeps_short_text_unchanged():
    assert truncate_text("short", max_chars=100) == "short"


def test_truncate_text_appends_marker_when_over_limit():
    result = truncate_text("a" * 30, max_chars=20)
    assert result.endswith("...[truncated]")
    assert len(result) == 20


def test_truncate_text_does_not_cut_inside_redacted_marker():
    value = "x" * 5 + "[REDACTED]" + "y" * 5  # redacted span occupies indices [5, 15)
    result = truncate_text(value, max_chars=25)  # naive cutoff (11) would land inside it
    assert "[REDACTED]" in result


def test_sanitize_text_returns_none_for_none():
    assert sanitize_text(None, max_chars=100) is None


def test_sanitize_text_masks_then_truncates():
    # a space after the secret keeps the padding out of the \S+ match, so truncation still
    # has something left to cut after masking collapses the token value itself.
    result = sanitize_text("TOKEN=secret " + "z" * 50, max_chars=25)
    assert "[REDACTED]" in result
    assert result.endswith("...[truncated]")
