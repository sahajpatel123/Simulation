"""Tests for the /simulations/redis-health probe."""
from __future__ import annotations

import sys
import types

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _OkRedis:
    def ping(self):
        return True


class _BadRedis:
    def ping(self):
        raise RuntimeError("connection refused")


class _FalseRedis:
    def ping(self):
        return False


def _patch_redis(monkeypatch: pytest.MonkeyPatch, value):
    from app.api.v1 import simulations as sim_mod

    monkeypatch.setattr(sim_mod, "get_redis_client", lambda: value)
    return sim_mod


def test_redis_health_returns_unconfigured_when_no_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.schemas.simulation import RedisHealthOut

    sim_mod = _patch_redis(monkeypatch, None)

    result = sim_mod.redis_health()

    assert isinstance(result, RedisHealthOut)
    assert result.redis == "unconfigured"


def test_redis_health_returns_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    import datetime as _dt

    from app.schemas.simulation import RedisHealthOut

    sim_mod = _patch_redis(monkeypatch, _OkRedis())

    result = sim_mod.redis_health()

    assert isinstance(result, RedisHealthOut)
    assert result.redis == "reachable"
    assert isinstance(result.latency_ms, float)
    assert result.latency_ms >= 0.0
    assert isinstance(result.checked_at, str)
    parsed = _dt.datetime.fromisoformat(result.checked_at)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None


def test_redis_health_treats_falsy_ping_as_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sim_mod = _patch_redis(monkeypatch, _FalseRedis())

    with pytest.raises(HTTPException) as exc:
        sim_mod.redis_health()
    assert exc.value.status_code == 503
    assert exc.value.detail == "Redis unreachable"


def test_redis_health_raises_503_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    sim_mod = _patch_redis(monkeypatch, _BadRedis())

    with pytest.raises(HTTPException) as exc:
        sim_mod.redis_health()
    assert exc.value.status_code == 503
    assert exc.value.detail == "Redis unreachable"


def test_redis_health_route_uses_typed_response() -> None:
    from fastapi.routing import APIRoute

    from app.api.v1 import simulations as sim_mod
    from app.schemas.simulation import RedisHealthOut

    matching = [
        r
        for r in sim_mod.router.routes
        if isinstance(r, APIRoute) and r.path.endswith("/redis-health")
    ]

    assert matching
    assert matching[0].response_model is RedisHealthOut
