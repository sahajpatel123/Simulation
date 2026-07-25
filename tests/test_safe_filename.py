"""Regression tests for the _safe_filename helper used in Content-Disposition.

``_safe_filename`` produces the filename embedded in the
``Content-Disposition`` header for PDF report downloads. The function
is the last line of defence against header-smuggling characters
(CR / LF / quote / semicolon) and against path-traversal-like
strings leaking into the user's download folder.

Re-pinned to confirm CI green after transient Docker registry timeout.

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

    def test_exact_fallback_string_passes_through(self) -> None:
        """A title that IS exactly ``"project"`` after sanitization
        is left alone — it doesn't trigger the fallback (the
        fallback only fires when the stripped result is empty)."""
        assert _reports._safe_filename("project") == "project"
        assert _reports._safe_filename("  project  ") == "project"

    def test_dashed_project_name_passes_through(self) -> None:
        """``p-r-o-j-e-c-t`` (allowed chars) stays as-is, not the
        fallback."""
        assert _reports._safe_filename("p-r-o-j-e-c-t") == "p-r-o-j-e-c-t"

    def test_length_boundary_39_passes_unchanged(self) -> None:
        assert _reports._safe_filename("a" * 39) == "a" * 39

    def test_length_boundary_40_preserved(self) -> None:
        """Exactly 40 chars preserved (boundary)."""
        assert _reports._safe_filename("a" * 40) == "a" * 40

    def test_length_40_underscores_preserved(self) -> None:
        """40 underscores are all allowed, so the result is 40
        underscores — not the ``"project"`` fallback."""
        assert _reports._safe_filename("_" * 40) == "_" * 40

    def test_length_40_spaces_triggers_fallback(self) -> None:
        """40 spaces all strip away, so the fallback fires."""
        assert _reports._safe_filename(" " * 40) == "project"

    def test_mixed_allowed_and_disallowed_chars(self) -> None:
        """A title with both alnum and special chars: alnum survives,
        disallowed chars become ``_``. The replacement happens per-char
        and length is preserved (modulo strip)."""
        out = _reports._safe_filename("My Project! 2024?")
        # Letters, digits, space preserved; ! and ? → _
        assert out == "My Project_ 2024_"

    def test_replacement_preserves_length(self) -> None:
        """Each disallowed char becomes exactly one ``_`` — no
        shortening (modulo the trailing strip)."""
        assert len(_reports._safe_filename("a" * 10 + "!" * 10)) == 20

    def test_underscore_passes_through_with_alnum(self) -> None:
        """``_a_`` round-trips — underscores are allowed and the
        trailing ``_`` doesn't trigger strip()."""
        assert _reports._safe_filename("_a_") == "_a_"

    def test_double_underscore_passes_through(self) -> None:
        """Multiple underscores in a row are all preserved."""
        assert _reports._safe_filename("__test__") == "__test__"

    def test_underscore_between_alnum_passes_through(self) -> None:
        """Snake-case title ``a_b_c`` round-trips unchanged."""
        assert _reports._safe_filename("a_b_c") == "a_b_c"

    def test_underscore_only_becomes_solid_underscore(self) -> None:
        """``_!_`` (underscores with a non-allowed char between)
        becomes ``___`` — every char is allowed (3 underscores)."""
        assert _reports._safe_filename("_!_") == "___"

    def test_mixed_case_preserved(self) -> None:
        """Mixed case is preserved — the function doesn't lowercase."""
        assert _reports._safe_filename("Hello World") == "Hello World"
        assert _reports._safe_filename("hELLO wORLD") == "hELLO wORLD"

    def test_snake_case_passes_through(self) -> None:
        """Common snake_case title like ``MyProject_V2`` passes through."""
        assert _reports._safe_filename("MyProject_V2") == "MyProject_V2"

    def test_trailing_whitespace_and_alnum_preserves_alnum(self) -> None:
        """``"  hello  "`` strips to ``"hello"`` — the surrounding
        whitespace is consumed but the alnum core survives."""
        assert _reports._safe_filename("  hello  ") == "hello"

    def test_trailing_whitespace_only_after_alnum_preserves(self) -> None:
        """``"hello   "`` strips trailing whitespace but the leading
        alnum is unchanged."""
        assert _reports._safe_filename("hello   ") == "hello"

    def test_leading_alnum_only_after_whitespace_preserves(self) -> None:
        """``"   hello"`` strips leading whitespace but the trailing
        alnum is unchanged."""
        assert _reports._safe_filename("   hello") == "hello"

    def test_trailing_punctuation_replaced(self) -> None:
        """Common trailing punctuation marks (. ! ? , ; :) are all
        replaced with ``_``. The alnum core survives."""
        for t in ("hello.", "hello!", "hello?", "hello,", "hello;", "hello:"):
            assert _reports._safe_filename(t) == "hello_", f"failed for {t!r}"

    def test_alnum_alnum_preserved(self) -> None:
        """Two alnum tokens back-to-back preserve."""
        assert _reports._safe_filename("AB") == "AB"
        assert _reports._safe_filename("123") == "123"
        assert _reports._safe_filename("A1B2") == "A1B2"

    def test_single_char_whitespace_falls_back(self) -> None:
        """A single space strips to empty → fallback ``"project"``."""
        assert _reports._safe_filename(" ") == "project"

    def test_single_underscore_preserved(self) -> None:
        """A single ``_`` is allowed and not empty after strip —
        passes through unchanged."""
        assert _reports._safe_filename("_") == "_"

    def test_single_dash_preserved(self) -> None:
        """A single ``-`` is allowed and not empty after strip —
        passes through unchanged."""
        assert _reports._safe_filename("-") == "-"

    def test_single_disallowed_char_replaced(self) -> None:
        """A single disallowed char (e.g. ``!``) becomes ``_`` —
        passes through (not the ``"project"`` fallback)."""
        assert _reports._safe_filename("!") == "_"

    def test_alnum_underscore_disallowed_per_char(self) -> None:
        """Each disallowed char in a mixed string is replaced
        individually with ``_``. The replacement preserves the
        surrounding allowed chars."""
        assert _reports._safe_filename("a_!") == "a__"
        assert _reports._safe_filename("a!_") == "a__"
        assert _reports._safe_filename("_a!") == "_a_"
        assert _reports._safe_filename("!a_") == "_a_"

    def test_underscore_space_combos_preserved(self) -> None:
        """Combinations of underscores and spaces (both allowed
        chars) round-trip unchanged."""
        assert _reports._safe_filename("_ _") == "_ _"
        assert _reports._safe_filename("_ _ _") == "_ _ _"
        assert _reports._safe_filename("_   _") == "_   _"
        assert _reports._safe_filename("__ __") == "__ __"

    def test_whitespace_and_disallowed_chars_mixed(self) -> None:
        """Whitespace is allowed (preserved); disallowed chars are
        replaced. The per-char replacement is independent of the
        surrounding char class. (Trailing ``strip()`` only fires
        when the entire result is empty — see ``test_*_only``.)"""
        assert _reports._safe_filename("a ! b") == "a _ b"
        # ``" ! "`` strips the surrounding whitespace, leaving ``"!"``
        # → ``"_"``.
        assert _reports._safe_filename(" ! ") == "_"
        assert _reports._safe_filename("a!b c") == "a_b c"
        assert _reports._safe_filename("a b c") == "a b c"

    def test_single_char_type_strings_round_trip(self) -> None:
        """Strings of a single allowed char type (all-uppercase,
        all-lowercase, all-digits, all-underscores, or a mixed
        combination) round-trip unchanged. This pins that the
        function does not collapse or transform runs of the same
        character class."""
        assert _reports._safe_filename("A" * 20) == "A" * 20
        assert _reports._safe_filename("a" * 20) == "a" * 20
        assert _reports._safe_filename("1" * 20) == "1" * 20
        assert _reports._safe_filename("_" * 20) == "_" * 20
        assert (
            _reports._safe_filename("AAAAA_____11111")
            == "AAAAA_____11111"
        )

    def test_nul_byte_replaced(self) -> None:
        """A NUL byte (``\\x00``) is replaced with ``_`` so the
        filename string never contains a NUL — C-level path handlers
        terminate on NUL."""
        out = _reports._safe_filename("hello\x00world")
        assert "\x00" not in out
        assert out == "hello_world"

    def test_multiple_consecutive_newlines(self) -> None:
        """Multiple consecutive CRLF or LF separators each become
        a single ``_``. The function preserves the 1-char-in → 1-char-
        out replacement contract."""
        assert _reports._safe_filename("\r\n\r\n") == "____"
        assert _reports._safe_filename("\r\r\r") == "___"
        assert _reports._safe_filename("a\r\nb\rc") == "a__b_c"
        assert _reports._safe_filename("\n\n\n") == "___"

    def test_length_and_strip_boundary(self) -> None:
        """Pins the interaction between the length cap and
        ``strip()``: stripping happens BEFORE the slice, so a
        39-char string with trailing whitespace becomes the
        39-char string (not 40-char). A trailing newline becomes
        a ``_`` so the result is 40 chars."""
        assert _reports._safe_filename("a" * 39 + "  ") == "a" * 39
        assert _reports._safe_filename("a" * 39 + "\n") == "a" * 39 + "_"
        assert _reports._safe_filename("a" * 39 + "\t") == "a" * 39 + "_"

    def test_unicode_whitespace_variants_replaced(self) -> None:
        """Pins the contract that non-ASCII whitespace-like chars
        (NBSP ``\\xa0``, zero-width space ``\\u200b``) are replaced
        with ``_`` — they look like whitespace visually but
        ``str.strip()`` doesn't catch them."""
        assert _reports._safe_filename("hello\xa0world") == "hello_world"
        assert _reports._safe_filename("test​case") == "test_case"
        # Latin-1 accented chars (alnum) round-trip.
        assert _reports._safe_filename("café") == "café"
        assert _reports._safe_filename("naïve") == "naïve"

    def test_mixed_whitespace_padding_round_trip(self) -> None:
        """ASCII-space padding around an alnum core strips away
        cleanly. ``\"  hello  \"`` → ``\"hello\"``.

        Note: ``\\t`` and ``\\n`` are NOT considered whitespace by
        ``str.strip()`` — they are replaced with ``_`` (per the
        disallowed-char rule). This test pins that subtle
        distinction."""
        assert _reports._safe_filename("  hello  ") == "hello"
        assert _reports._safe_filename("\thello\t") == "_hello_"
        assert _reports._safe_filename("\nhello\n") == "_hello_"

    def test_case_sensitive_round_trip(self) -> None:
        """``isalnum()`` is case-sensitive: uppercase and lowercase
        letters both pass through unchanged. Pins that the function
        doesn't lowercase or uppercase the result."""
        assert _reports._safe_filename("a") == "a"
        assert _reports._safe_filename("A") == "A"
        assert _reports._safe_filename("A_a") == "A_a"
        assert _reports._safe_filename("a!A") == "a_A"
        assert _reports._safe_filename("aA1") == "aA1"

    def test_dash_preserved_in_combinations(self) -> None:
        """``-`` is in the allowed char set, so it round-trips in
        every position: leading, trailing, consecutive, and
        surrounded by spaces. Spaces are preserved too.

        Pin these so a future \"simplification\" that filtered out
        leading or trailing dashes (mistaking them for command-line
        flags) wouldn't silently break the user's intent."""
        assert _reports._safe_filename("a-b") == "a-b"
        assert _reports._safe_filename("a-") == "a-"
        assert _reports._safe_filename("-a") == "-a"
        assert _reports._safe_filename("a--b") == "a--b"
        assert _reports._safe_filename("a -b") == "a -b"
        assert _reports._safe_filename("a- b") == "a- b"
        assert _reports._safe_filename("a  -  b") == "a  -  b"

    def test_version_string_round_trip(self) -> None:
        """Version-like strings (digits + alnum + dashes) round-trip.
        The dot is the only char that gets replaced with ``_``.

        ``\"1.0\"`` → ``\"1_0\"``
        ``\"v1.0\"`` → ``\"v1_0\"``
        ``\"v2\"`` → ``\"v2\"``
        ``\"2024Q3\"`` → ``\"2024Q3\"``
        ``\"2024-12-25\"`` → ``\"2024-12-25\"``

        Pins that the dot is replaced (it's not alnum, not space,
        not dash/underscore) — a common version separator that
        would otherwise break OS-level path handling on some shells.
        ``\":\"`` and ``\"/\"`` are already covered by the
        disallowed-chars tests above."""
        assert _reports._safe_filename("123") == "123"
        assert _reports._safe_filename("1.0") == "1_0"
        assert _reports._safe_filename("v1.0") == "v1_0"
        assert _reports._safe_filename("v2") == "v2"
        assert _reports._safe_filename("2024Q3") == "2024Q3"
        assert _reports._safe_filename("2024-12-25") == "2024-12-25"

    def test_special_token_round_trip(self) -> None:
        """Common title tokens — TODO markers, semver-ish, draft
        flags — round-trip with the predictable replacement rules:

        - ``\"TODO:\"`` → ``\"TODO_\"`` (colon replaced)
        - ``\"FIXME[bug]\"`` → ``\"FIXME_bug_\"`` (brackets replaced)
        - ``\"v0.0.1-alpha\"`` → ``\"v0_0_1-alpha\"`` (dots replaced,
          dash preserved)
        - ``\"draft (WIP)\"`` → ``\"draft _WIP_\"`` (parens replaced)
        - ``\"Q4 2024\"`` → ``\"Q4 2024\"`` (alnum + space round-trip)

        Pins the contract for these realistic founder-title shapes
        so a future simplification that drops a replacement rule
        silently changes the downloaded filename."""
        assert _reports._safe_filename("TODO:") == "TODO_"
        assert _reports._safe_filename("FIXME[bug]") == "FIXME_bug_"
        assert _reports._safe_filename("v0.0.1-alpha") == "v0_0_1-alpha"
        assert _reports._safe_filename("draft (WIP)") == "draft _WIP_"
        assert _reports._safe_filename("Q4 2024") == "Q4 2024"

    def test_parens_and_brackets_replaced(self) -> None:
        """Pins that ``(``, ``)``, ``[``, ``]`` are replaced with
        ``_``. These appear in common founder titles (``\"draft (1)\"``,
        ``\"final [v2]\"``, ``\"My Project (2024)\"``).

        Without this test, a future \"simplification\" that
        accidentally let ``[``/``]`` through to the filesystem
        could trigger shell globbing or cause issues with certain
        download tools."""
        assert _reports._safe_filename("draft (1)") == "draft _1_"
        assert _reports._safe_filename("final [v2]") == "final _v2_"
        assert _reports._safe_filename("My Project (2024)") == "My Project _2024_"
        # Default-name shapes round-trip without truncation.
        assert _reports._safe_filename("untitled") == "untitled"
        assert _reports._safe_filename("Untitled Project") == "Untitled Project"

    def test_shell_special_chars_replaced(self) -> None:
        """Pins that shell-special chars (``\\\\``, ``*``, ``?``,
        ``|``, ``&``, ``<``, ``>``) are replaced with ``_``. These
        are the chars that trigger globbing, redirection, or
        expansion in most shells — letting them through to a
        downloaded filename could let a malicious title trigger
        unexpected shell behavior in any downstream tool that
        passes the filename through a shell."""
        assert _reports._safe_filename("test\\path") == "test_path"
        assert _reports._safe_filename("a*b") == "a_b"
        assert _reports._safe_filename("a?b") == "a_b"
        assert _reports._safe_filename("a|b") == "a_b"
        assert _reports._safe_filename("a&b") == "a_b"
        assert _reports._safe_filename("a<b>c") == "a_b_c"

    def test_emoji_replaced(self) -> None:
        """Pins the contract that emoji are replaced with ``_``.

        Modern browsers and OS filesystems handle Unicode filenames
        natively, but emoji are visually large and may render
        poorly in downloaded-file pickers. The function deliberately
        keeps the surrounding alnum core and replaces the emoji
        with ``_`` for consistency."""
        assert _reports._safe_filename("🎉") == "_"
        assert _reports._safe_filename("🚀 launch") == "_ launch"
        assert _reports._safe_filename("launch 🚀") == "launch _"
        assert _reports._safe_filename("a🎉b") == "a_b"
        # Plain alnum round-trips.
        assert _reports._safe_filename("ab") == "ab"

    def test_slice_boundary_at_40(self) -> None:
        """Pins the exact slice boundary: input of exactly 40
        alnum chars round-trips; input of 41 alnum chars is
        truncated to 40. When a 41-char input has a disallowed
        char, the replacement happens BEFORE the slice, so the
        truncated result keeps the 40-char length but the
        disallowed-char position determines what gets dropped.

        Without this test, a future \"simplification\" that changed
        the slice index (e.g. ``[:41]`` or ``[:39]``) would
        silently change the filename length semantics."""
        assert len(_reports._safe_filename("a" * 41)) == 40
        assert len(_reports._safe_filename("a" * 40)) == 40
        # Replace happens before slice: the 41st char (disallowed)
        # gets dropped after being replaced.
        out = _reports._safe_filename("a" * 40 + "!")
        assert len(out) == 40
        assert out.endswith("a")
        # Disallowed at position 0: replace first, then slice 40.
        out = _reports._safe_filename("!" + "a" * 40)
        assert len(out) == 40
        assert out.startswith("_")

    def test_url_and_html_entities_replaced(self) -> None:
        """Pins that URL-encoded (``%20``) and HTML-entity (``&amp;``,
        ``&lt;``, ``&gt;``, ``&quot;``, ``&#x27;``) strings are
        character-by-character replaced (not decoded).

        ``&`` and ``;`` are both disallowed — so ``&amp;`` becomes
        ``_amp_`` (4-char → 5-char), and ``&#x27;`` becomes
        ``__x27_``. The function never decodes these strings.

        Without this test, a future \"simplification\" that called
        ``html.unescape()`` or ``urllib.parse.unquote()`` would
        silently change the sanitization contract and let HTML /
        URL payloads through that the caller already escaped for
        safety reasons (e.g. an XSS-resistant frontend)."""
        assert _reports._safe_filename("a%20b") == "a_20b"
        assert _reports._safe_filename("a&amp;b") == "a_amp_b"
        assert _reports._safe_filename("a&lt;b") == "a_lt_b"
        assert _reports._safe_filename("a&gt;b") == "a_gt_b"
        assert _reports._safe_filename("a&quot;b") == "a_quot_b"
        assert _reports._safe_filename("a&#x27;b") == "a__x27_b"

    def test_trailing_newlines_preserved(self) -> None:
        """Trailing newlines are not stripped (they're not in
        ``str.strip()``'s default whitespace set in Python — only
        space, tab, newline, CR, FF, VT). Each becomes ``_``.

        ``\"a\\n\"`` → ``\"a_\"``
        ``\"a\\nb\\n\"`` → ``\"a_b_\"``
        ``\"\\n\"`` → ``\"_\"``
        ``\"\\n\\n\\n\"`` → ``\"___\"``
        ``\"a\\n\\nb\"`` → ``\"a__b\"``

        Pins the distinction between Python's ``str.strip()``
        semantics (which DO strip LF) and the function's
        per-character ``isalnum()`` replacement (which doesn't).

        Wait — actually Python's ``str.strip()`` DOES strip ``\\n``.
        Re-check.

        Actually after testing: ``str.strip()`` with default args
        strips ``\\n``. So ``\"\\n\"``.strip() == ``\"\"`` → fallback
        fires → ``\"project\"``. But the actual output was ``\"_\"``
        (one underscore). That means ``str.strip()`` didn't strip
        the lone ``\\n``.

        This contradicts the documented ``str.strip()`` behaviour.
        Looking at the function: the strip happens AFTER replace, so
        the ``\\n`` is replaced with ``_`` BEFORE strip runs.
        That's why a lone ``\\n`` becomes ``_`` instead of
        ``\"project\"`` — replace runs first, then strip, then
        fallback check.

        Pin this surprising-but-correct behaviour."""
        assert _reports._safe_filename("a\n") == "a_"
        assert _reports._safe_filename("a\nb\n") == "a_b_"
        assert _reports._safe_filename("\n") == "_"
        assert _reports._safe_filename("\n\n\n") == "___"
        assert _reports._safe_filename("a\n\nb") == "a__b"

    def test_empty_and_single_allowed_chars(self) -> None:
        """Pins the degenerate cases: empty string and single
        allowed chars.

        Empty / whitespace-only inputs trigger the fallback
        ``\"project\"``. Single allowed chars (``_``, ``-``, alnum)
        round-trip unchanged."""
        assert _reports._safe_filename("") == "project"
        assert _reports._safe_filename(" ") == "project"
        assert _reports._safe_filename("  ") == "project"
        assert _reports._safe_filename("_") == "_"
        assert _reports._safe_filename("__") == "__"
        assert _reports._safe_filename("-") == "-"
        assert _reports._safe_filename("a") == "a"
        assert _reports._safe_filename("A") == "A"
        assert _reports._safe_filename("1") == "1"

    def test_replace_then_slice_preserves_length(self) -> None:
        """Pins that replace happens BEFORE slice, so a 40-char
        input with a trailing disallowed char is replaced first
        (becoming 40 chars with a trailing ``_``), then the slice
        keeps it at 40. The 41st char is only created when the
        input itself is ≥41 chars (and then it gets dropped by
        the slice)."""
        out = _reports._safe_filename("a" * 39 + "!")
        assert len(out) == 40
        assert out.endswith("_")
        out = _reports._safe_filename("a" * 38 + "!!")
        assert len(out) == 40
        assert out.endswith("__")

    def test_all_disallowed_input_truncates_to_underscores(self) -> None:
        """Pins that an input of entirely disallowed chars (e.g.
        100 ``!`` chars) replaces every char with ``_`` and then
        truncates to 40 chars.

        These inputs all become 40 underscores — same length as
        the cap. This pins the per-char 1-to-1 replacement
        followed by slice-to-40 contract for the all-disallowed
        edge case."""
        assert _reports._safe_filename("!" * 100) == "_" * 40
        assert _reports._safe_filename("@#$%^&*()" * 5) == "_" * 40
        assert _reports._safe_filename("~" * 200) == "_" * 40

    def test_all_control_chars_consistent(self) -> None:
        """Pins that every ASCII control char (``\\x00``–``\\x1f``
        except space) behaves consistently: each is replaced with
        ``_`` (per-char isalnum check fails for control chars).

        The function never falls through to the ``\"project\"``
        fallback for any single control char because the replace
        runs first and produces a single ``_`` which is non-empty
        after strip.

        Pins the contract that no control char accidentally slips
        through to the filesystem — a malicious NUL byte in
        particular would terminate the filename at the OS layer.
        """
        control_chars = [chr(i) for i in range(32) if i != ord(" ")]
        for c in control_chars:
            out = _reports._safe_filename(c)
            assert out == "_", (
                f"control char chr({ord(c)}) did not become '_'; "
                f"got {out!r}"
            )

    def test_high_bit_bytes_pin_isalnum(self) -> None:
        """Pins that ``isalnum()`` correctly distinguishes Latin-1
        alnum (e.g. ``ÿ`` = chr(255), ``chr(0x80)``) from
        non-alnum high-bit bytes:

        - ``chr(0x80)`` is not alnum → ``\"_\"``
        - ``chr(0x90)`` is not alnum → ``\"_\"``
        - ``chr(0xa0)`` is not alnum → ``\"_\"``
        - ``chr(0xff)`` (``\"ÿ\"``) IS alnum → round-trips

        Pin so a future \"simplification\" that changes the alnum
        threshold (e.g. dropping the ``\".isalnum()\"`` for a regex
        like ``r\"^[A-Za-z0-9]+$\"`` which excludes non-ASCII alnum)
        would silently change the contract for non-English founders.
        """
        assert _reports._safe_filename(chr(0x80)) == "_"
        assert _reports._safe_filename(chr(0x90)) == "_"
        assert _reports._safe_filename(chr(0xa0)) == "_"
        # ``\\xFF`` is ``\"ÿ\"`` which IS alnum.
        assert _reports._safe_filename(chr(0xff)) == chr(0xff)

    def test_idempotency(self) -> None:
        """Pins the contract that ``_safe_filename`` is idempotent —
        applying it twice yields the same result as applying it once.

        This is useful for callers that may invoke the function
        defensively (e.g. pre-process user-provided filenames twice)
        and rely on the second call being a no-op."""
        for t in ("hello world!", "normal title", "   spaced   title   ",
                  "!@#$%^&*()"):
            once = _reports._safe_filename(t)
            twice = _reports._safe_filename(once)
            assert once == twice, (
                f"idempotency violated for {t!r}: {once!r} != {twice!r}"
            )

    def test_homograph_unicode_round_trips(self) -> None:
        """Pins that Cyrillic / accented Latin chars (which look
        visually similar to ASCII letters in homograph attacks)
        round-trip unchanged.

        ``\"рауl\"`` (Cyrillic а + Latin p + y + Latin l) →
        ``\"рауl\"``
        ``\"аlice\"`` (Cyrillic а + Latin l i c e) → ``\"аlice\"``
        ``\"аdmin\"`` (Cyrillic а + Latin d m i n) → ``\"аdmin\"``
        ``\"google\"`` → ``\"google\"``
        ``\"paypal\"`` → ``\"paypal\"``

        This pins the contract that the function preserves Unicode
        alnum (it doesn't normalize to ASCII). A future
        \"simplification\" that called ``unicodedata.normalize(\"NFKD\", ...)``
        would silently break the homograph defense (and also
        legitimately non-English founders' titles). The function
        correctly leaves Unicode alone and relies on downstream
        rendering to handle visual safety.
        """
        assert _reports._safe_filename("рауl") == "рауl"
        assert _reports._safe_filename("аlice") == "аlice"
        assert _reports._safe_filename("аdmin") == "аdmin"
        assert _reports._safe_filename("google") == "google"
        assert _reports._safe_filename("paypal") == "paypal"

    def test_leading_dot_replaced_in_filename(self) -> None:
        """Pins that a leading ``.`` is replaced with ``_`` so the
        downloaded filename doesn't appear as a hidden file on
        POSIX systems.

        ``\".env\"`` → ``\"_env\"``
        ``\"..\"`` → ``\"__\"``
        ``\".hidden\"`` → ``\"_hidden\"``
        ``\".gitignore\"`` → ``\"_gitignore\"``

        Note: ``..`` (two dots) is NOT a path-traversal vector in a
        filename string itself — it's only dangerous when used as a
        filesystem path component. But replacing it anyway is
        defense-in-depth and avoids visual confusion in the
        download picker."""
        assert _reports._safe_filename(".env") == "_env"
        assert _reports._safe_filename("..") == "__"
        assert _reports._safe_filename(".hidden") == "_hidden"
        assert _reports._safe_filename(".gitignore") == "_gitignore"

    def test_bidi_control_chars_replaced(self) -> None:
        """Pins that bidi control chars (RLO ``\\u202e``, RLM
        ``\\u200f``, etc.) are replaced with ``_``.

        These are invisible formatting chars that can be used in
        filename-spoofing attacks (a file named
        ``\"virus\\u202eexe.txt\"`` displays as ``virus_txt.exe`` in
        some file managers but is actually ``virus…exe.txt`` on
        disk). Replacing them at the API boundary is
        defense-in-depth — the frontend should also strip bidi
        controls before display, but the API doesn't trust the
        renderer."""
        # RLO (right-to-left override) at position 4.
        assert _reports._safe_filename("test‮exe") == "test_exe"
        # RLM (right-to-left mark).
        assert _reports._safe_filename("test‏exe") == "test_exe"
        # Plain text round-trips.
        assert _reports._safe_filename("normal") == "normal"
        assert _reports._safe_filename("normal text") == "normal text"

    def test_windows_reserved_names_preserved_as_is(self) -> None:
        """Pins that Windows-reserved device names (``CON``, ``PRN``,
        ``AUX``, ``NUL``, ``COM1``–``COM9``, ``LPT1``–``LPT9``)
        round-trip unchanged by ``_safe_filename``.

        These names are blocked at the OS level on Windows, but
        ``_safe_filename`` is a content sanitiser, not an OS path
        validator — the filename is passed to a ``StreamingResponse``
        which the browser's download manager handles. If a user
        names their project ``CON``, the downloaded file may collide
        with the Windows CON device on save, but the API itself
        doesn't refuse to serve it (the path doesn't have to be
        unique on the user's filesystem).

        Pin this so a future \"simplification\" that added an
        explicit ``CON``/``PRN`` blocklist wouldn't silently change
        the contract — that blocklist belongs in a separate
        filesystem-path validator, not in this filename sanitiser.
        """
        for t in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT1"):
            assert _reports._safe_filename(t) == t
        # Case-insensitive — the OS-level check is, but the function
        # round-trips whatever case is provided.
        assert _reports._safe_filename("con") == "con"
        assert _reports._safe_filename("prn") == "prn"

    def test_single_disallowed_glob_chars(self) -> None:
        """Pins that single glob / pipe / redirect chars become a
        single ``_``. These are the chars that the shell would
        treat as control syntax — a malicious title could otherwise
        trigger expansion / redirection downstream."""
        for t in ("?", "/", "|", "<", ">", "*"):
            assert _reports._safe_filename(t) == "_", (
                f"single {t!r} did not become '_'; "
                f"got {_reports._safe_filename(t)!r}"
            )

    def test_double_quote_replaced(self) -> None:
        """Pins that the double quote (``\"``) is replaced with
        ``_``. A ``\"`` in the filename would break the
        ``Content-Disposition: attachment; filename=\"...\"``
        header parser — the closing quote terminates the filename
        early and the trailing content becomes a new header.

        ``\"\"`` → ``\"_\"``
        ``\"a\\\"b\"`` → ``\"a_b\"``
        ``\"\\\"a\"`` → ``\"_a\"``"""
        assert _reports._safe_filename(chr(34)) == "_"
        assert _reports._safe_filename("a" + chr(34) + "b") == "a_b"
        assert _reports._safe_filename(chr(34) + "a") == "_a"
