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


def _patch_redis(monkeypatch: pytest.MonkeyPatch, value):
    from app.api.v1 import simulations as sim_mod

    monkeypatch.setattr(sim_mod, "get_redis_client", lambda: value)
    return sim_mod


def test_redis_health_returns_unconfigured_when_no_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sim_mod = _patch_redis(monkeypatch, None)

    result = sim_mod.redis_health()

    assert result["redis"] == "unconfigured"


def test_redis_health_returns_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    sim_mod = _patch_redis(monkeypatch, _OkRedis())

    result = sim_mod.redis_health()

    assert result["redis"] == "reachable"
    assert isinstance(result["latency_ms"], float)
    assert result["latency_ms"] >= 0.0
    assert isinstance(result["checked_at"], str)
    assert result["checked_at"]


def test_redis_health_raises_503_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    sim_mod = _patch_redis(monkeypatch, _BadRedis())

    with pytest.raises(HTTPException) as exc:
        sim_mod.redis_health()
    assert exc.value.status_code == 503
    assert exc.value.detail == "Redis unreachable"
