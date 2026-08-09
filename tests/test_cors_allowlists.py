"""Regression tests for the CORS allowlists in app.main.

The Cee API uses GET and POST only — no PUT / PATCH / DELETE. The
CORSMiddleware was previously configured with ``allow_methods=["*"]``
and ``allow_headers=["*"]`` so any page in the allowlist could drive
arbitrary HTTP methods and headers through the CORS preflight,
broadening the attack surface unnecessarily.

These tests pin the explicit allowlist so a future regression that
reverts to ``["*"]`` is caught at the source level.
"""

from __future__ import annotations

from pathlib import Path

_MAIN_PATH = Path(__file__).resolve().parents[1] / "backend" / "app" / "main.py"


def _read_main() -> str:
    return _MAIN_PATH.read_text()


def test_cors_allow_methods_is_not_wildcard() -> None:
    """allow_methods must be an explicit list, not ``['*']``."""
    src = _read_main()
    assert 'allow_methods=["*"]' not in src, (
        "CORSMiddleware allow_methods reverted to wildcard — that "
        "lets an attacker page drive PUT/PATCH/DELETE through preflight."
    )
    assert "allow_methods=" in src, "CORSMiddleware allow_methods missing"


def test_cors_allow_headers_is_not_wildcard() -> None:
    """allow_headers must be an explicit list, not ``['*']``."""
    src = _read_main()
    assert 'allow_headers=["*"]' not in src, (
        "CORSMiddleware allow_headers reverted to wildcard — that "
        "lets an attacker page send arbitrary headers through preflight."
    )
    assert "allow_headers=" in src, "CORSMiddleware allow_headers missing"


def test_cors_allows_only_get_and_post() -> None:
    """The API uses only GET and POST; PUT/PATCH/DELETE/OPTIONS must
    not be in the allowlist. (OPTIONS is handled by the CORS preflight
    handler itself.)"""
    import re

    src = _read_main()
    match = re.search(r'allow_methods=\[([^\]]+)\]', src)
    assert match, "allow_methods list not found"
    methods = {m.strip().strip('"').strip("'") for m in match.group(1).split(",")}
    for verb in ("PUT", "PATCH", "DELETE", "TRACE", "CONNECT"):
        assert verb not in methods, f"{verb} should not be in CORS allow_methods"
    assert "GET" in methods
    assert "POST" in methods


def test_cors_allow_headers_lists_only_what_is_actually_inspected() -> None:
    """Pin the explicit allowlist so a future "let me just wildcard it"
    is caught."""
    import re

    src = _read_main()
    match = re.search(r'allow_headers=\[([^\]]+)\]', src)
    assert match, "allow_headers list not found"
    headers = {h.strip().strip('"').strip("'") for h in match.group(1).split(",")}
    # Required:
    assert "Authorization" in headers  # Bearer token
    assert "Content-Type" in headers    # JSON request bodies
    assert "X-Request-ID" in headers    # correlation IDs (RequestIdMiddleware)
    # Should NOT be wildcarded:
    assert "*" not in headers
