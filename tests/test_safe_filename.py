"""Regression tests for the _safe_filename helper used in Content-Disposition.

``_safe_filename`` produces the filename embedded in the
``Content-Disposition`` header for PDF report downloads. The function
is the last line of defence against header-smuggling characters
(CR / LF / quote / semicolon) and against path-traversal-like
strings leaking into the user's download folder.

These tests pin:
- Allowed character set (alnum + space + dash + underscore)
- Disallowed characters become ``_`` (not stripped — keeps length)
- Empty / whitespace-only input falls back to ``"project"``
- Length is capped at 40 chars
- No control characters, quotes, or semicolons can reach the header
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Bypass the package __init__ chain (razorpay etc.) by loading the
# reports module directly via spec.
_REPORTS_PATH = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "app"
    / "api"
    / "v1"
    / "reports.py"
)


def _load_reports_module():
    # Stub razorpay so the package __init__ chain doesn't fail locally.
    if "razorpay" not in sys.modules:
        stub = type(sys)("razorpay")
        stub.Client = type("Client", (), {})
        sys.modules["razorpay"] = stub

    spec = importlib.util.spec_from_file_location(
        "reports_under_test", _REPORTS_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_reports = _load_reports_module()


class TestAllowedChars:
    def test_passthrough_ascii_alnum(self) -> None:
        assert _reports._safe_filename("MyProject123") == "MyProject123"

    def test_passthrough_dash_underscore(self) -> None:
        assert _reports._safe_filename("My-Project_v2") == "My-Project_v2"

    def test_passthrough_spaces(self) -> None:
        assert _reports._safe_filename("My Project Name") == "My Project Name"

    def test_max_length_40(self) -> None:
        out = _reports._safe_filename("x" * 100)
        assert len(out) == 40


class TestDisallowedCharsReplaced:
    def test_slash_replaced(self) -> None:
        """Path-traversal-ish ``/`` must not reach the header."""
        assert "/" not in _reports._safe_filename("../etc/passwd")

    def test_backslash_replaced(self) -> None:
        assert "\\" not in _reports._safe_filename("a\\b")

    def test_dotdot_replaced(self) -> None:
        out = _reports._safe_filename("..")
        assert out == "__"  # two dots → two underscores

    def test_quote_replaced(self) -> None:
        out = _reports._safe_filename('a"b')
        assert '"' not in out

    def test_semicolon_replaced(self) -> None:
        out = _reports._safe_filename("a;b")
        assert ";" not in out

    def test_angle_bracket_replaced(self) -> None:
        """< and > must never reach Content-Disposition — they would
        confuse parsers and could enable header injection."""
        out = _reports._safe_filename("<script>")
        assert "<" not in out
        assert ">" not in out


class TestControlChars:
    def test_crlf_replaced(self) -> None:
        """CR / LF would split the HTTP header — must be filtered."""
        out = _reports._safe_filename("a\r\nb")
        assert "\r" not in out
        assert "\n" not in out

    def test_null_byte_replaced(self) -> None:
        out = _reports._safe_filename("a\x00b")
        assert "\x00" not in out

    def test_tab_replaced(self) -> None:
        out = _reports._safe_filename("a\tb")
        assert "\t" not in out

    def test_crlf_alone_replaced(self) -> None:
        """A title that's just CRLF collapses to ``__`` (two
        underscores), not the ``"project"`` fallback — the stripped
        result is non-empty."""
        assert _reports._safe_filename("\r\n") == "__"

    def test_vertical_tab_replaced(self) -> None:
        """VT (U+000B) is a control char — replaced with ``_``."""
        out = _reports._safe_filename("\v")
        assert "\v" not in out

    def test_form_feed_replaced(self) -> None:
        """FF (U+000C) is a control char — replaced with ``_``."""
        out = _reports._safe_filename("\f")
        assert "\f" not in out


class TestFallback:
    def test_empty_falls_back_to_project(self) -> None:
        assert _reports._safe_filename("") == "project"

    def test_whitespace_only_falls_back(self) -> None:
        assert _reports._safe_filename("    ") == "project"

    def test_punctuation_only_does_not_fall_back(self) -> None:
        """``...`` becomes ``___`` (3 underscores), which is a valid
        filename — the fallback only triggers when the stripped result
        is fully empty. Punctuation-only inputs become underscored
        names that are still safe to drop into Content-Disposition."""
        assert _reports._safe_filename("...") == "___"


class TestUnicode:
    def test_emoji_replaced(self) -> None:
        """Emoji are not alnum, so each becomes ``_``."""
        out = _reports._safe_filename("Hello 🚀 World")
        assert "🚀" not in out
        assert "🚀" not in out
        assert "_" in out

    def test_accented_latin_preserved(self) -> None:
        """``isalnum()`` accepts unicode letters — accented Latin is fine."""
        assert _reports._safe_filename("café") == "café"

    def test_greek_preserved(self) -> None:
        assert _reports._safe_filename("α-beta-γ") == "α-beta-γ"

    def test_cjk_preserved(self) -> None:
        assert _reports._safe_filename("日本語") == "日本語"

    def test_strips_surrounding_whitespace(self) -> None:
        assert _reports._safe_filename("   hello   ") == "hello"


class TestShellSafety:
    def test_leading_dash_passes_through(self) -> None:
        """``-`` is in the allowed char set, so the function passes
        it through. This is fine because ``Content-Disposition``
        ``filename=...`` is parsed by the browser, not a shell —
        a leading ``-`` doesn't trigger flag interpretation."""
        assert _reports._safe_filename("-rf") == "-rf"

    def test_leading_dot_replaced(self) -> None:
        """``.`` is not in the allowed char set, so leading dots are
        replaced with ``_``. This means ``.env`` becomes ``_env`` —
        the download won't be a hidden file on POSIX. Acceptable
        trade-off: a leading-dot title is unusual for a project."""
        assert _reports._safe_filename(".env") == "_env"

    def test_length_boundary_40_passes(self) -> None:
        """Exactly 40 chars is allowed; 41 is truncated."""
        assert len(_reports._safe_filename("a" * 40)) == 40
        assert len(_reports._safe_filename("a" * 41)) == 40

    def test_null_bytes_replaced(self) -> None:
        """Null bytes would terminate the path in C-level handlers."""
        out = _reports._safe_filename("a\x00b\x00c")
        assert "\x00" not in out

    def test_non_breaking_space_replaced(self) -> None:
        """NBSP (U+00A0) is whitespace-like but NOT in the allowed
        set, so it's replaced with ``_``. This matters because the
        "strip" check wouldn't catch NBSP — ``str.strip()`` only
        strips standard ASCII whitespace."""
        assert _reports._safe_filename("\xa0") == "_"
        assert _reports._safe_filename("\xa0test\xa0") == "_test_"

    def test_tab_replaced(self) -> None:
        """Tab is a control character — replaced with ``_``."""
        assert _reports._safe_filename("\t") == "_"
        assert _reports._safe_filename("\ttest\t") == "_test_"

    def test_only_underscore_passes_through(self) -> None:
        """A single ``_`` is allowed (in the allowed set) so it
        passes through unchanged. Not empty after strip, so no
        ``"project"`` fallback."""
        assert _reports._safe_filename("_") == "_"
        assert _reports._safe_filename("___") == "___"
