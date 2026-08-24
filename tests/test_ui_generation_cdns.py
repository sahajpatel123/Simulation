"""Tests for the Tailwind CDN detection in ui_generation._ensure_cdns."""

from __future__ import annotations

import re

from app.api.v1.ui_generation import (
    TAILWIND_CDN,
    _ensure_cdns,
    _strip_unsafe_scripts,
)


def _has_cdn(html: str) -> bool:
    return TAILWIND_CDN in html


def test_page_with_real_cdn_script_is_left_alone() -> None:
    html = (
        "<html><head>"
        '<script src="https://cdn.tailwindcss.com"></script>'
        "</head><body></body></html>"
    )

    assert _ensure_cdns(html) == html


def test_page_with_uppercase_cdn_tag_is_detected() -> None:
    html = '<html><head><SCRIPT SRC="HTTPS://CDN.TAILWINDCSS.COM"></SCRIPT></head></html>'

    assert _ensure_cdns(html) == html


def test_page_mentioning_tailwind_in_text_gets_injection() -> None:
    # A bare substring check ("tailwindcss" in html) would treat this page as
    # already styled and skip injection; host-based detection must not.
    html = "<html><head></head><body><p>Built with tailwindcss utilities.</p></body></html>"

    result = _ensure_cdns(html)

    assert _has_cdn(result)
    assert "tailwindcss utilities" in result  # page content untouched


def test_lookalike_host_does_not_count_as_present() -> None:
    # evil.com serving a path that contains the CDN name is not the CDN;
    # only an exact host match may suppress injection.
    html = '<html><head><script src="https://evil.com/cdn.tailwindcss.com/x.js"></script></head></html>'

    assert _has_cdn(_ensure_cdns(html))


def test_injection_goes_into_head_before_body() -> None:
    html = "<html><head><title>t</title></head><body></body></html>"

    result = _ensure_cdns(html)

    head = result.split("</head>")[0]
    body = result.split("<body>")[1]
    assert _has_cdn(head) and not _has_cdn(body)


def test_injection_into_body_when_head_missing() -> None:
    html = '<html><body class="x"><p>hi</p></body></html>'

    result = _ensure_cdns(html)

    assert re.search(r'<body[^>]*><script src="https://cdn\.tailwindcss\.com"', result)


def test_prepended_verbatim_when_no_head_or_body() -> None:
    html = "<div>fragment</div>"

    assert _ensure_cdns(html).startswith(TAILWIND_CDN + "<div>")


# ---------------------------------------------------------------------------
# _strip_unsafe_scripts: host-exact allowlisting
# ---------------------------------------------------------------------------


def test_allowlisted_cdn_script_is_kept() -> None:
    html = '<script src="https://cdn.tailwindcss.com/3.4.1"></script>'

    assert _strip_unsafe_scripts(html) == html


def test_unknown_host_script_is_stripped() -> None:
    html = '<p>a</p><script src="https://evil.example/payload.js"></script>'

    assert _strip_unsafe_scripts(html) == "<p>a</p>"


def test_lookalike_path_cannot_impersonate_allowlisted_cdn() -> None:
    # A substring filter ("tailwindcss" in tag) would keep this tag; only an
    # exact host match may survive.
    html = '<script src="https://evil.example/cdn.tailwindcss.com/x.js"></script>'

    assert _strip_unsafe_scripts(html) == ""


def test_inline_script_without_src_is_out_of_scope() -> None:
    # This filter only targets remote ``<script src=...>`` tags; inline
    # script bodies are neutralized by _build_safe_html.
    html = "<script>alert(1)</script>"

    assert _strip_unsafe_scripts(html) == html
