"""Route-level tests for the /simulations/{id}/investor-readiness endpoint."""
from __future__ import annotations

import sys
import types

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


_MISSING = object()


def _results(**overrides) -> dict:
    payload = {
        "population_weighted_conversion": 0.04,
        "product_type_detected": "saas",
        "total_agents": 10000,
        "raw_funnel": {
            "ARRIVE": 1000,
            "BROWSE": 600,
            "CONSIDER": 300,
            "DECIDE": 120,
            "PURCHASE": 40,
        },
        "cluster_breakdown": {
            "metro_power_professional": 0.06,
            "tier3_first_time_app_user": 0.03,
            "anxiety_driven_researcher": 0.04,
        },
        "domain_findings": [
            {"id": "f1", "title": "Support burden", "severity": "CRITICAL"},
            {"id": "f2", "title": "Pricing confusion", "severity": "MAJOR"},
        ],
    }
    payload.update(overrides)
    return payload


class _FakeEnvironment:
    def __init__(self) -> None:
        self.average_order_value = 999.0
        self.price_sensitivity = 0.5
        self.market_maturity = 0.3


class _FakeSimulation:
    def __init__(
        self,
        sim_id: int = 1,
        *,
        status: str = "COMPLETED",
        results: object = _MISSING,
        error_message: str | None = None,
    ) -> None:
        self.id = sim_id
        self.project_id = 10
        self.environment_id = 5
        self.status = status
        self.error_message = error_message
        self.signal_quality = 0.62
        self.results_json = results if results is not _MISSING else _results()


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


class _FakeSession:
    def __init__(self, sim: _FakeSimulation | None = None) -> None:
        self.sim = sim or _FakeSimulation()

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Simulation":
            return _FakeQuery([self.sim])
        if name == "Environment":
            return _FakeQuery([_FakeEnvironment()])
        return _FakeQuery([])


def _call_route(
    *,
    simulation_id: int = 1,
    current_user_id: int = 42,
    session: _FakeSession | None = None,
    **kwargs,
):
    from app.api.v1 import simulations as sim_mod

    db = session or _FakeSession()
    return sim_mod.get_investor_readiness(
        simulation_id=simulation_id,
        db=db,
        current_user=type("U", (), {"id": current_user_id})(),
        **kwargs,
    )


def test_completed_simulation_returns_investor_readiness_payload() -> None:
    out = _call_route()

    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.signal_quality == 0.62
    assert out.product_type == "saas"
    assert len(out.pillars) == 6
    assert {p.key for p in out.pillars} == {
        "market",
        "economics",
        "retention",
        "moat",
        "readiness",
        "trust",
    }
    assert out.investor_score is None or 0 <= out.investor_score <= 100
    assert out.verdict in {
        "INVESTMENT_GRADE",
        "RAISABLE",
        "PRE_SEED",
        "NOT_INVESTABLE",
        "INSUFFICIENT_DATA",
    }
    assert out.verdict_label
    assert out.narrative
    assert out.meta["total_pillars"] == 6
    assert any("Finding: Support burden" in risk for risk in out.risks)


def test_query_params_flow_through() -> None:
    out = _call_route(market_size=2_000_000, average_order_value=250.0)

    market_pillar = next(p for p in out.pillars if p.key == "market")
    assert market_pillar.evidence
    assert any("TAM 2,000,000" in line for line in market_pillar.evidence)


def test_failed_simulation_raises_422() -> None:
    session = _FakeSession(_FakeSimulation(status="FAILED", error_message="boom"))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422


def test_pending_simulation_raises_409() -> None:
    session = _FakeSession(_FakeSimulation(status="PENDING"))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 409


def test_empty_results_raises_422() -> None:
    session = _FakeSession(_FakeSimulation(results=None))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422
