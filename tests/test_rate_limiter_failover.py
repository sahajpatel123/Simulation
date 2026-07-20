"""Regression tests for app.core.rate_limiter fail-closed semantics."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.core import rate_limiter
from app.core.config import settings


class _StubRequest:
    class _StubClient:
        host = "127.0.0.1"

    client = _StubClient()
    url = type("U", (), {"path": "/protected"})()


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
    monkeypatch.setattr(
        rate_limiter._redis_limiter, "is_allowed", lambda *a, **kw: None
    )

    raised = asyncio.run(_invoke(window_s=30))

    assert isinstance(raised, HTTPException)
    assert raised.status_code == 503
    assert raised.headers and "Retry-After" in raised.headers
    assert raised.headers["Retry-After"] == "30"


def test_development_redis_outage_falls_back_to_in_memory(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(
        rate_limiter._redis_limiter, "is_allowed", lambda *a, **kw: None
    )

    raised = asyncio.run(_invoke(window_s=30))

    # In development we silently fall through to the in-memory limiter, which
    # always allows the request. No 503/429 should be raised on the first call.
    assert raised is None
