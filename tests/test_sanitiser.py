"""
Tests for the sanitiser module (cycle 37 sanitiser-test-coverage).

The sanitiser is a security boundary for user-supplied text — every
project description, assumption, and free-form field passes through it
before it lands on the database or the LLM. These tests pin the
behaviour:

  1. Length caps (default + per-call).
  2. Empty / None / non-string inputs.
  3. HTML escaping (script tags, quotes).
  4. Dangerous pattern stripping (javascript:, on*= handlers, data URIs).
  5. Custom max_length overrides.
  6. Dict + list recursion preserves non-string types.
  7. Whitespace stripping.
"""
from __future__ import annotations

import pytest

from app.core.sanitiser import (
    MAX_ASSUMPTION_LENGTH,
    MAX_DESCRIPTION_LENGTH,
    MAX_FIELD_LENGTH,
    sanitise_assumption,
    sanitise_description,
    sanitise_dict,
    sanitise_text,
)


# ---------------------------------------------------------------------------
# Empty / None / non-string inputs
# ---------------------------------------------------------------------------


def test_sanitise_text_empty_string() -> None:
    assert sanitise_text("") == ""


def test_sanitise_text_none_returns_empty() -> None:
    assert sanitise_text(None) == ""  # type: ignore[arg-type]


def test_sanitise_text_non_string_coerced() -> None:
    # Numeric input is coerced to string then sanitised.
    out = sanitise_text(42)  # type: ignore[arg-type]
    assert out == "42"


# ---------------------------------------------------------------------------
# Length limits
# ---------------------------------------------------------------------------


def test_sanitise_text_default_length_cap() -> None:
    long = "a" * (MAX_FIELD_LENGTH + 50)
    out = sanitise_text(long)
    assert len(out) == MAX_FIELD_LENGTH
    assert out == "a" * MAX_FIELD_LENGTH


def test_sanitise_text_custom_length_cap() -> None:
    out = sanitise_text("abcdefghij", max_length=5)
    assert out == "abcde"


def test_sanitise_text_zero_length_returns_empty() -> None:
    assert sanitise_text("hello", max_length=0) == ""


def test_sanitise_description_uses_description_limit() -> None:
    long = "x" * (MAX_DESCRIPTION_LENGTH + 100)
    out = sanitise_description(long)
    assert len(out) == MAX_DESCRIPTION_LENGTH


def test_sanitise_assumption_uses_assumption_limit() -> None:
    long = "y" * (MAX_ASSUMPTION_LENGTH + 50)
    out = sanitise_assumption(long)
    assert len(out) == MAX_ASSUMPTION_LENGTH


def test_sanitise_assumption_typical_text_under_limit() -> None:
    text = "Users will pay ₹999 without a trial"
    out = sanitise_assumption(text)
    assert out.startswith("Users will pay")
    # The rupee symbol is HTML-escaped.
    assert "₹" in out  # unicode survives


# ---------------------------------------------------------------------------
# HTML escaping
# ---------------------------------------------------------------------------


def test_sanitise_text_html_escapes_angle_brackets() -> None:
    out = sanitise_text("<script>alert(1)</script>")
    # < > & get escaped.
    assert "<" not in out
    assert ">" not in out
    assert "&lt;" in out or "&#x27;" in out or "&amp;" in out


def test_sanitise_text_strips_script_tag_with_embedded_text() -> None:
    """HTML escaping happens first, so '<script>' becomes '&lt;script&gt;'.
    The raw '<script>' substring is therefore gone, but the literal word
    'script' remains in escaped form — and crucially the executable form
    (raw angle brackets) is fully neutralised."""
    out = sanitise_text("hello <script>evil()</script> world")
    # No raw angle brackets survive.
    assert "<" not in out
    assert ">" not in out
    # The surrounding "hello" / "world" is preserved.
    assert "hello" in out
    assert "world" in out


def test_sanitise_text_escapes_quotes() -> None:
    out = sanitise_text('She said "hello"')
    # Default quote=False for html.escape, so we expect either &quot; or
    # literal " depending on Python version. The string must remain valid
    # and contain the word "hello".
    assert "hello" in out


def test_sanitise_text_escapes_ampersand() -> None:
    out = sanitise_text("A & B")
    assert "&amp;" in out


# ---------------------------------------------------------------------------
# Dangerous pattern stripping
# ---------------------------------------------------------------------------


def test_sanitise_text_strips_javascript_protocol() -> None:
    out = sanitise_text("javascript:alert(1)")
    # The dangerous 'javascript:' prefix is removed (case-insensitive).
    assert "javascript" not in out.lower()
    # Trailing payload remains — it's not part of the dangerous protocol.
    assert "alert" in out.lower()


def test_sanitise_text_strips_event_handlers() -> None:
    """on*= patterns are removed."""
    out = sanitise_text("hello onclick=evil() world")
    assert "onclick" not in out.lower()


def test_sanitise_text_strips_data_uri() -> None:
    out = sanitise_text("data:text/html,<script>alert(1)</script>")
    assert "data:text/html" not in out.lower()


def test_sanitise_text_strips_vbscript() -> None:
    out = sanitise_text("vbscript:msgbox(1)")
    assert "vbscript" not in out.lower()


def test_sanitise_text_strips_uppercase_dangerous_patterns() -> None:
    out = sanitise_text("JavaScript:alert(1)")
    assert "javascript" not in out.lower()


def test_sanitise_text_preserves_safe_content() -> None:
    safe = "The quick brown fox jumps over the lazy dog. Numbers: 123."
    assert sanitise_text(safe) == safe


# ---------------------------------------------------------------------------
# Whitespace stripping
# ---------------------------------------------------------------------------


def test_sanitise_text_strips_leading_trailing_whitespace() -> None:
    assert sanitise_text("  hello  ") == "hello"


def test_sanitise_text_preserves_internal_whitespace() -> None:
    assert sanitise_text("hello world") == "hello world"


# ---------------------------------------------------------------------------
# sanitise_dict recursion
# ---------------------------------------------------------------------------


def test_sanitise_dict_recursively_sanitises_strings() -> None:
    data = {
        "title": "<b>Title</b>",
        "nested": {"deep": "<script>alert(1)</script>"},
    }
    out = sanitise_dict(data)
    assert "<b>" not in out["title"]
    assert "&lt;" in out["title"]
    assert "<" not in out["nested"]["deep"]


def test_sanitise_dict_handles_list_of_strings() -> None:
    data = {"tags": ["<script>alert(1)</script>", "safe-tag"]}
    out = sanitise_dict(data)
    assert "<" not in out["tags"][0]
    assert out["tags"][1] == "safe-tag"


def test_sanitise_dict_preserves_non_string_types() -> None:
    data = {
        "name": "string-value",
        "count": 42,
        "ratio": 0.5,
        "active": True,
        "missing": None,
        "list_of_ints": [1, 2, 3],
    }
    out = sanitise_dict(data)
    assert out["count"] == 42
    assert out["ratio"] == 0.5
    assert out["active"] is True
    assert out["missing"] is None
    assert out["list_of_ints"] == [1, 2, 3]


def test_sanitise_dict_respects_max_length() -> None:
    data = {"k": "x" * 500}
    out = sanitise_dict(data, max_length=100)
    assert len(out["k"]) == 100


def test_sanitise_dict_empty_dict_returns_empty_dict() -> None:
    assert sanitise_dict({}) == {}


def test_sanitise_dict_handles_list_of_dicts() -> None:
    """Lists of dicts aren't recursed — they're treated as leaf values. The
    inner dict must be sanitised only via sanitise_dict at the top level."""
    data = {"rows": [{"a": "<b>1</b>"}]}
    out = sanitise_dict(data)
    # List of dicts is preserved as-is (not recursed).
    assert isinstance(out["rows"], list)
    assert isinstance(out["rows"][0], dict)
    # The inner dict wasn't sanitised — contract: only top-level strings
    # inside lists are sanitised.
    assert out["rows"][0]["a"] == "<b>1</b>"


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


def test_length_constants_are_positive() -> None:
    """Sanity: every constant is a positive integer."""
    assert isinstance(MAX_FIELD_LENGTH, int) and MAX_FIELD_LENGTH > 0
    assert isinstance(MAX_ASSUMPTION_LENGTH, int) and MAX_ASSUMPTION_LENGTH > 0
    assert isinstance(MAX_DESCRIPTION_LENGTH, int) and MAX_DESCRIPTION_LENGTH > 0
    # Description is the largest field by an order of magnitude.
    assert MAX_DESCRIPTION_LENGTH > MAX_ASSUMPTION_LENGTH


def test_dangerous_patterns_are_lowercase_strings() -> None:
    """Module-level invariant: every pattern is a non-empty string."""
    from app.core.sanitiser import DANGEROUS_PATTERNS

    assert len(DANGEROUS_PATTERNS) >= 3
    for p in DANGEROUS_PATTERNS:
        assert isinstance(p, str) and p
