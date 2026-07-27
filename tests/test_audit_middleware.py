"""Regression tests for ``app.core.audit_middleware``.

The middleware is a security-critical component: it persists
one row per mutating request to ``api_audit_log`` so the
founder can see what actions they (or anyone with their
token) actually took. A bug here would either:

* log too little (compliance gap — missing rows for security
  forensics)
* log too much (write amplification — every GET bloats the
  table ten-thousandfold)
* leak sensitive data into the row (path with concrete IDs,
  request body, etc.)

These tests pin the middleware's filter behaviour and the
helper functions so a future refactor can't silently change
the contract.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.core.audit_middleware import (
    _AUDIT_EXEMPT_PATHS,
    _MUTATING_METHODS,
    _normalise_route,
    _resolve_user_id,
)


# ---------------------------------------------------------------------------
# Filter constants
# ---------------------------------------------------------------------------


def test_mutating_methods_includes_post_put_patch_delete() -> None:
    """Only mutating HTTP methods are audited.

    GET, HEAD, OPTIONS are reads / CORS handshakes — logging
    them would inflate the table 10,000× without giving the
    user anything useful for forensics.
    """
    assert _MUTATING_METHODS == frozenset({"POST", "PUT", "PATCH", "DELETE"})


def test_audit_exempt_paths_includes_probes_and_share() -> None:
    """/metrics, /health, /readyz, /api/v1/share are
    exempt — probes fire on a fixed cadence (don't
    represent real load) and /api/v1/share is the public
    unauthenticated read endpoint (logging it would let
    anyone enumerate every shared link by hitting the
    path with a leaked token)."""
    assert "/metrics" in _AUDIT_EXEMPT_PATHS
    assert "/health" in _AUDIT_EXEMPT_PATHS
    assert "/readyz" in _AUDIT_EXEMPT_PATHS
    # /api/v1/share is the prefix — the actual share
    # token path is /api/v1/share/{token}.
    assert "/api/v1/share" in _AUDIT_EXEMPT_PATHS


# ---------------------------------------------------------------------------
# _normalise_route helper
# ---------------------------------------------------------------------------


def test_normalise_route_returns_template_when_route_matches() -> None:
    """When Starlette has matched a route, return its
    template (e.g. ``/projects/{id}/health``) so the audit
    row buckets by template, not by concrete URL."""
    request = MagicMock()
    request.scope = {
        "route": MagicMock(path="/projects/{project_id}/health")
    }
    assert _normalise_route(request) == "/projects/{project_id}/health"


def test_normalise_route_returns_unmatched_when_no_route() -> None:
    """When Starlette has NOT matched a route (404 path,
    middleware runs before routing), return ``"unmatched"``
    so the audit row is bucketed under a single label
    instead of millions of unique URLs."""
    request = MagicMock()
    request.scope = {"route": None}
    assert _normalise_route(request) == "unmatched"

    request.scope = {}
    assert _normalise_route(request) == "unmatched"


# ---------------------------------------------------------------------------
# _resolve_user_id helper
# ---------------------------------------------------------------------------


def test_resolve_user_id_returns_none_for_anonymous_request() -> None:
    """Requests without an Authorization header get
    ``user_id = None`` (anonymous row). The middleware
    never raises on auth-decode failure — that would
    break the user's response just to attribute a log row."""
    request = MagicMock()
    request.headers = {}
    assert _resolve_user_id(request) is None


def test_resolve_user_id_returns_none_for_non_bearer_token() -> None:
    """Tokens that aren't Bearer (e.g. Basic auth) are
    also anonymous — the middleware only understands
    JWT Bearer."""
    request = MagicMock()
    request.headers = {"authorization": "Basic dXNlcjpwYXNz"}
    assert _resolve_user_id(request) is None


def test_resolve_user_id_returns_none_on_invalid_jwt() -> None:
    """Malformed / invalid / expired tokens fall back to
    ``user_id = None``. The audit row is still written
    (the request itself is the interesting event), just
    without user attribution."""
    request = MagicMock()
    request.headers = {"authorization": "Bearer not-a-valid-jwt"}
    assert _resolve_user_id(request) is None


def test_resolve_user_id_decodes_valid_jwt() -> None:
    """A valid JWT signed with the configured secret
    decodes to the user id encoded in the ``sub`` claim."""
    import time as _t

    from app.core.config import settings
    from app.core.security import create_access_token

    sub = "42"
    token = create_access_token(sub)
    request = MagicMock()
    request.headers = {"authorization": f"Bearer {token}"}
    assert _resolve_user_id(request) == int(sub)


def test_resolve_user_id_returns_none_on_decode_exception() -> None:
    """A bug in decode_token must not break the user's
    request — return ``None`` and let the request through."""
    request = MagicMock()
    request.headers = {"authorization": "Bearer anything"}
    with patch(
        "app.core.security.decode_token",
        side_effect=RuntimeError("boom"),
    ):
        assert _resolve_user_id(request) is None
