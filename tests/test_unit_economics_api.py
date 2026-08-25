"""Route-level tests for the /simulations/{id}/unit-economics endpoint.
"""
from __future__ import annotations

import sys
import types

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


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
        results: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        self.id = sim_id
        self.project_id = 10
        self.environment_id = 5
        self.status = status
        self.error_message = error_message
        self.signal_quality = 0.62
        self.results_json = (
            results
            if results is not None
            else {
                "population_weighted_conversion": 0.04,
                "product_type_detected": "saas",
                "cluster_breakdown": {
                    "metro_power_professional": 0.06,
                    "tier3_first_time_app_user": 0.03,
                    "anxiety_driven_researcher": 0.04,
                },
            }
        )


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else [_FakeSimulation()]

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None


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
    return sim_mod.get_unit_economics(
        simulation_id=simulation_id,
        db=db,
        current_user=type("U", (), {"id": current_user_id})(),
        **kwargs,
    )


def test_completed_simulation_returns_unit_economics_payload() -> None:
    out = _call_route()
    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.signal_quality == 0.62
    assert out.product_type == "saas"
    assert out.aov == 999.0
    assert out.verdict in {
        "STRONG",
        "VIABLE",
        "MARGINAL",
        "UNPROFITABLE",
        "INSUFFICIENT_DATA",
    }
    assert out.total_clusters >= 50
    assert out.clusters_with_data == out.total_clusters
    assert out.blended_ltv > 0.0
    assert out.blended_cac > 0.0
    assert out.blended_ltv_cac_ratio > 0.0
    assert out.recommendations
    assert len(out.cac_scenarios) == 4
    assert len(out.price_scenarios) == 3


def test_query_params_flow_through() -> None:
    out = _call_route(gross_margin=0.4, purchase_frequency_per_year=4.0, assumed_cac=750.0)
    assert out.gross_margin == 0.4
    assert out.purchase_frequency_per_year == 4.0
    assert out.base_cac == 750.0
    assert out.effective_base_cac == 750.0
    assert out.meta["cac_source"] == "founder_input"


def test_failed_simulation_raises_422() -> None:
    session = _FakeSession(
        sim=_FakeSimulation(status="FAILED", error_message="boom")
    )
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422
    assert "boom" in exc.value.detail


def test_pending_simulation_raises_409() -> None:
    session = _FakeSession(sim=_FakeSimulation(status="PENDING"))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 409


def test_empty_results_raises_422() -> None:
    session = _FakeSession(sim=_FakeSimulation(results={}))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422
