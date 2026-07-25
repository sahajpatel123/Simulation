"""Regression tests for the X-Robots-Tag header on the generated-UI serve endpoint.

Generated UIs are project-specific prototypes behind a preview_token.
Search engines don't authenticate, so token-gating alone is not enough
to prevent index leakage if the token URL ever leaks (pastebin,
support tickets, screenshots taken from public previews).

The /serve endpoint now sets ``X-Robots-Tag: noindex, nofollow`` so
search crawlers refuse to index the page even if they reach it.
"""

from __future__ import annotations

from pathlib import Path

_UI_GEN_PATH = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "app"
    / "api"
    / "v1"
    / "ui_generation.py"
)


def test_serve_endpoint_sets_x_robots_tag_noindex() -> None:
    """The serve_generated_ui handler must emit X-Robots-Tag: noindex."""
    import re

    source = _UI_GEN_PATH.read_text()
    block = re.search(
        r"async def serve_generated_ui[\s\S]*?_inject_tracking",
        source,
    )
    assert block, "serve_generated_ui handler not found"

    body = block.group(0)
    assert "X-Robots-Tag" in body, (
        "serve_generated_ui must declare X-Robots-Tag header so search "
        "engines don't index project-specific prototypes."
    )
    assert "noindex" in body, "X-Robots-Tag value must include 'noindex'"
    # nofollow is the second directive — keep crawlers from walking any
    # links the prototype may contain.
    assert "nofollow" in body, "X-Robots-Tag value must include 'nofollow'"


def test_x_robots_tag_value_is_well_formed() -> None:
    """The header value should be the literal 'noindex, nofollow' — a
    single string, not concatenated fragments."""
    import re

    source = _UI_GEN_PATH.read_text()
    block = re.search(
        r"async def serve_generated_ui[\s\S]*?_inject_tracking",
        source,
    )
    body = block.group(0)
    match = re.search(r'"X-Robots-Tag":\s*"([^"]*)"', body)
    assert match, "X-Robots-Tag header line not found in headers dict"
    value = match.group(1)
    parts = {p.strip() for p in value.split(",")}
    assert "noindex" in parts
    assert "nofollow" in parts


def test_serve_endpoint_still_sets_other_security_headers() -> None:
    """Defense in depth: don't accidentally drop CSP / nosniff /
    Referrer-Policy while adding noindex."""
    import re

    source = _UI_GEN_PATH.read_text()
    block = re.search(
        r"async def serve_generated_ui[\s\S]*?_inject_tracking",
        source,
    )
    body = block.group(0)
    assert "Content-Security-Policy" in body
    assert "X-Content-Type-Options" in body
    assert "nosniff" in body
    assert "Referrer-Policy" in body
