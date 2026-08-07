"""Tests for the /simulations/db-health probe."""
from __future__ import annotations

import sys
import types

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _OkDB:
    def execute(self, stmt):
        return object()


class _BadDB:
    def execute(self, stmt):
        raise RuntimeError("connection refused")


def test_db_health_returns_reachable() -> None:
    from app.api.v1 import simulations as sim_mod
    from app.schemas.simulation import DatabaseHealthOut

    result = sim_mod.db_health(db=_OkDB())

    assert isinstance(result, DatabaseHealthOut)
    assert result.database == "reachable"
    assert isinstance(result.latency_ms, float)
    assert result.latency_ms >= 0.0
    assert isinstance(result.checked_at, str)
    assert result.checked_at


def test_db_health_raises_503_on_failure() -> None:
    from app.api.v1 import simulations as sim_mod

    with pytest.raises(HTTPException) as exc:
        sim_mod.db_health(db=_BadDB())
    assert exc.value.status_code == 503
    assert exc.value.detail == "Database unreachable"
    assert "connection refused" not in exc.value.detail


def test_db_health_route_uses_typed_response() -> None:
    from app.api.v1 import simulations as sim_mod
    from app.schemas.simulation import DatabaseHealthOut

    matching = [
        r for r in sim_mod.router.routes
        if isinstance(r, APIRoute) and r.path.endswith("/db-health")
    ]

    assert matching
    assert matching[0].response_model is DatabaseHealthOut
