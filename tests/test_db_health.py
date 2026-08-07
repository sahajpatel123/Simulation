"""Tests for the /simulations/db-health probe."""
from __future__ import annotations

import sys
import types

import pytest
from fastapi import HTTPException

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

    assert sim_mod.db_health(db=_OkDB()) == {"database": "reachable"}


def test_db_health_raises_503_on_failure() -> None:
    from app.api.v1 import simulations as sim_mod

    with pytest.raises(HTTPException) as exc:
        sim_mod.db_health(db=_BadDB())
    assert exc.value.status_code == 503
    assert "connection refused" in exc.value.detail
