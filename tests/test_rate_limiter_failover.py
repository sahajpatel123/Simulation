"""Regression tests for app.core.rate_limiter fail-closed semantics."""

from __future__ import annotations

import asyncio

from fastapi import HTTPException

from app.core import rate_limiter
from app.core.config import settings


class _StubRequest:
    class _StubClient:
        host = "127.0.0.1"

    client = _StubClient()
    url = type("U", (), {"path": "/protected"})()
    headers: dict = {}


async def _invoke(window_s: int = 30) -> HTTPException | None:
    dep = rate_limiter.rate_limit(limit=10, window_s=window_s)
    try:
        await dep(_StubRequest())
    except HTTPException as e:
        return e
    return None


def test_production_redis_outage_returns_503_with_retry_after(monkeypatch):
    """Pre-fix code raised a bare RuntimeError in production when Redis was
    unreachable, surfacing as a generic 500 via the global error handler.
    The new path returns 503 with a Retry-After header."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(rate_limiter._redis_limiter, "is_allowed", lambda *a, **kw: None)

    raised = asyncio.run(_invoke(window_s=30))

    assert isinstance(raised, HTTPException)
    assert raised.status_code == 503
    assert raised.headers and "Retry-After" in raised.headers
    assert raised.headers["Retry-After"] == "30"


def test_development_redis_outage_falls_back_to_in_memory(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(rate_limiter._redis_limiter, "is_allowed", lambda *a, **kw: None)

    raised = asyncio.run(_invoke(window_s=30))

    # In development we silently fall through to the in-memory limiter, which
    # always allows the request. No 503/429 should be raised on the first call.
    assert raised is None


def test_production_fail_open_allows_observability_probes(monkeypatch):
    """Observability endpoints that diagnose Redis itself must stay
    reachable during a Redis outage; fail_open skips the limit instead of
    raising the production 503."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(rate_limiter._redis_limiter, "is_allowed", lambda *a, **kw: None)

    async def _invoke_fail_open() -> HTTPException | None:
        dep = rate_limiter.rate_limit(limit=10, window_s=30, fail_open=True)
        try:
            await dep(_StubRequest())
        except HTTPException as exc:
            return exc
        return None

    raised = asyncio.run(_invoke_fail_open())

    assert raised is None


# ---------------------------------------------------------------------------
# Bucket identity — X-Forwarded-For must not be client-spoofable
# ---------------------------------------------------------------------------


def _request_with_headers(headers: dict) -> object:
    """A request stub whose headers drive ``_client_ip`` selection."""

    class _Client:
        host = "127.0.0.1"

    return type(
        "R",
        (),
        {"client": _Client(), "url": type("U", (), {"path": "/protected"})(), "headers": headers},
    )()


def _captured_bucket_key(monkeypatch, request) -> str:
    seen: dict[str, str] = {}

    def fake_is_allowed(key: str, limit: int, window_s: int) -> bool | None:
        seen["key"] = key
        return True

    monkeypatch.setattr(rate_limiter._redis_limiter, "is_allowed", fake_is_allowed)
    asyncio.run(rate_limiter.rate_limit(limit=10, window_s=30)(request))
    return seen["key"]


def test_rightmost_xff_entry_wins_over_spoofed_leftmost(monkeypatch):
    """Proxies append hops, so the leftmost XFF value is attacker-supplied.
    Rotating it used to mint unlimited buckets and bypass every limit —
    the rightmost entry (written by the trusted platform edge) is the only
    client-controlled-proof identifier."""
    request = _request_with_headers({"x-forwarded-for": "1.2.3.4, 10.0.0.9"})

    key = _captured_bucket_key(monkeypatch, request)

    assert key == "rate-limit:/protected:10.0.0.9"


def test_single_xff_entry_is_used_directly(monkeypatch):
    request = _request_with_headers({"x-forwarded-for": "203.0.113.7"})

    key = _captured_bucket_key(monkeypatch, request)

    assert key == "rate-limit:/protected:203.0.113.7"


def test_xff_entries_are_whitespace_stripped(monkeypatch):
    request = _request_with_headers({"x-forwarded-for": " 198.51.100.2 , 192.0.2.5 "})

    key = _captured_bucket_key(monkeypatch, request)

    assert key == "rate-limit:/protected:192.0.2.5"


def test_blank_xff_falls_back_to_peer_address(monkeypatch):
    request = _request_with_headers({"x-forwarded-for": "  ,  "})

    key = _captured_bucket_key(monkeypatch, request)

    assert key == "rate-limit:/protected:127.0.0.1"


def test_missing_xff_and_peer_yields_anon_bucket(monkeypatch):
    """No headers and no peer address must not collapse all anonymous
    traffic into one global bucket a single actor can saturate."""

    class _NoPeer:
        client = None
        url = type("U", (), {"path": "/protected"})()
        headers: dict = {}

    key = _captured_bucket_key(monkeypatch, _NoPeer())

    assert key.startswith("rate-limit:/protected:anon-")
