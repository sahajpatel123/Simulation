"""Unit tests for ``app.core.audit_middleware``.

The middleware is the load-bearing piece of the audit-log feature: it
filters out GETs, normalises the route, resolves the user, and
guarantees the audit write never breaks the response. Covering it
without a DB means exercising the pure-path branches: the
method/path filter and the route template extraction.
"""
from __future__ import annotations

from starlette.requests import Request

from app.core.audit_middleware import (
    _AUDIT_EXEMPT_PATHS,
    _MUTATING_METHODS,
    _normalise_route,
)


def _fake_request(method: str, path: str, matched_template: str | None = None) -> Request:
    """Build a minimal ``Request`` stub for the helpers.

    Real ``Request`` instances need the full ASGI scope; here we only
    need ``scope['route']`` (for ``_normalise_route``) and ``method``
    so a small dict-shaped scope is enough.
    """
    scope: dict[str, object] = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": b"",
    }
    if matched_template is not None:
        scope["route"] = _RouteStub(matched_template)
    return Request(scope)


class _RouteStub:
    """Stand-in for ``starlette.routing.Route`` carrying only ``path``."""

    def __init__(self, path: str) -> None:
        self.path = path


def test_mutating_methods_only_include_writes():
    assert "POST" in _MUTATING_METHODS
    assert "PUT" in _MUTATING_METHODS
    assert "PATCH" in _MUTATING_METHODS
    assert "DELETE" in _MUTATING_METHODS
    # Reads and preflight must never be persisted.
    assert "GET" not in _MUTATING_METHODS
    assert "HEAD" not in _MUTATING_METHODS
    assert "OPTIONS" not in _MUTATING_METHODS


def test_exempt_paths_include_probes_and_public_share():
    # Health probes are GETs and would already be filtered, but listing
    # them here means the intent is documented and future changes can't
    # accidentally start logging them.
    assert "/metrics" in _AUDIT_EXEMPT_PATHS
    assert "/health" in _AUDIT_EXEMPT_PATHS
    assert "/readyz" in _AUDIT_EXEMPT_PATHS
    # ``/api/v1/share`` is the public unauthenticated read endpoint;
    # logging it would leak token access patterns.
    assert "/api/v1/share" in _AUDIT_EXEMPT_PATHS


def test_normalise_route_returns_template_when_matched():
    request = _fake_request(
        "POST",
        "/projects/42/simulate",
        matched_template="/projects/{project_id}/simulate",
    )
    assert _normalise_route(request) == "/projects/{project_id}/simulate"


def test_normalise_route_falls_back_to_unmatched():
    """Unmatched routes (404s, scanner traffic) collapse to one bucket."""
    request = _fake_request("POST", "/wp-login.php")
    assert _normalise_route(request) == "unmatched"


def test_normalise_route_handles_missing_route_key():
    """Defensive: ``scope['route']`` can be absent in some edge paths."""
    request = _fake_request("POST", "/x")
    # The stub above doesn't add a ``route`` key, so the helper should
    # hit the falsy fallback.
    assert "route" not in request.scope
    assert _normalise_route(request) == "unmatched"