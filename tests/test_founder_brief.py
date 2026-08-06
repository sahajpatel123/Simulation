"""Tests for the founder-brief digest and its route."""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from fastapi import HTTPException

from app.simulation.founder_brief import build_founder_brief


if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def _results(**overrides: Any) -> dict[str, Any]:
    payload = {
        "population_weighted_conversion": 0.04,
        "product_type_detected": "saas",
        "cluster_breakdown": {
            "metro_power_professional": 0.06,
            "tier3_first_time_app_user": 0.03,
        },
        "total_agents": 10000,
        "raw_funnel": {
            "ARRIVE": 1000,
            "BROWSE": 600,
            "CONSIDER": 300,
            "DECIDE": 120,
            "PURCHASE": 40,
        },
        "domain_findings": [
            {"id": "f1", "title": "Support burden", "severity": "MAJOR"}
        ],
    }
    payload.update(overrides)
    return payload


def _build(
    *,
    results: dict[str, Any] | None = None,
    signal_quality: float | None = 0.85,
    visible_assumptions: int | None = 4,
) -> Any:
    return build_founder_brief(
        results if results is not None else _results(),
        simulation_id=1,
        project_id=10,
        status="COMPLETED",
        signal_quality=signal_quality,
        visible_assumption_count=visible_assumptions,
        product_type="saas",
        average_order_value=100.0,
        purchase_frequency_per_year=2.0,
        market_size=1_000_000,
    )


def test_brief_bundles_quality_readiness_and_market() -> None:
    out = _build()

    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.product_type == "saas"
    assert out.trust_score is not None
    assert 0.0 <= out.trust_score <= 1.0
    assert 0.0 <= out.readiness_score <= 1.0
    assert out.verdict in {"READY", "NEEDS_WORK", "NOT_READY", "INSUFFICIENT_DATA"}
    assert out.annual_revenue > 0
    assert out.som_customers >= 0
    assert out.tam_customers == 1_000_000
    assert out.top_recommendations
    assert out.meta["readiness_items"] >= 6


def test_brief_reflects_low_signal_and_missing_assumptions() -> None:
    out = _build(signal_quality=0.25, visible_assumptions=0)

    assert out.signal_quality == 0.25
    assert out.visible_assumptions == 0
    assert any("Signal quality is low" in rec for rec in out.top_recommendations)
    assert any("Add assumptions" in rec for rec in out.top_recommendations)


class _FakeSimulation:
    def __init__(
        self,
        *,
        status: str = "COMPLETED",
        results: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        self.id = 1
        self.project_id = 10
        self.environment_id = 5
        self.status = status
        self.error_message = error_message
        self.signal_quality = 0.85
        self.results_json = results if results is not None else _results()


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else [_FakeSimulation()]

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return list(self.items)


class _FakeAssumption:
    def __init__(self, text: str) -> None:
        self.text = text
        self.sensitivity = "MEDIUM"
        self.impact_score = 5.0


class _FakeSession:
    def __init__(
        self,
        sim: object | None = None,
        assumptions: list | None = None,
    ) -> None:
        self.sim = sim
        self.assumptions = assumptions

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Simulation":
            return _FakeQuery([self.sim] if self.sim is not None else [])
        if name == "Assumption":
            return _FakeQuery(self.assumptions or [])
        return _FakeQuery([])


def _call_route(session: _FakeSession | None = None):
    from app.api.v1 import simulations as sim_mod

    db = session if session is not None else _FakeSession(_FakeSimulation())
    return sim_mod.get_founder_brief(
        simulation_id=1,
        market_size=1_000_000,
        target_market_fraction=0.25,
        average_order_value=100.0,
        purchase_frequency_per_year=2.0,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


def test_route_returns_founder_brief() -> None:
    out = _call_route(
        _FakeSession(_FakeSimulation(), assumptions=[_FakeAssumption("viral loop")])
    )

    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.visible_assumptions == 1
    assert out.annual_revenue > 0
    assert out.top_recommendations


def test_route_rejects_pending_simulation() -> None:
    session = _FakeSession(_FakeSimulation(status="PENDING"))
    with pytest.raises(HTTPException) as exc:
        _call_route(session)
    assert exc.value.status_code == 409
