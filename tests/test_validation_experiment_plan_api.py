"""Route-level tests for the /simulations/{id}/validation-experiment-plan endpoint.
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


class _FakeSimulation:
    def __init__(
        self,
        sim_id: int = 1,
        *,
        status: str = "COMPLETED",
        results: dict | None = None,
        error_message: str | None = None,
        signal_quality: float | None = 0.62,
        environment_id: int | None = 7,
    ) -> None:
        self.id = sim_id
        self.project_id = 10
        self.status = status
        self.error_message = error_message
        self.signal_quality = signal_quality
        self.environment_id = environment_id
        self.results_json = (
            results
            if results is not None
            else {
                "population_weighted_conversion": 0.05,
                "mean_conversion_rate": 0.05,
                "mean_revenue": 999.0,
                "total_agents": 10000,
                "converted": 500,
                "product_type_detected": "saas",
            }
        )


class _FakeEnvironment:
    def __init__(self) -> None:
        self.average_order_value = 999.0
        self.price_sensitivity = 0.5
        self.market_maturity = 0.3
        self.consumer_volume = 10000
        self.growth_rate_per_month = 5.0


class _FakeAssumption:
    def __init__(self, text: str, category: str) -> None:
        self.text = text
        self.category = category
        self.sensitivity = "CRITICAL"
        self.impact_score = 9.0
        self.is_hidden = False


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return self.items


class _FakeSession:
    def __init__(
        self,
        sim: _FakeSimulation | None = None,
        env: _FakeEnvironment | None = None,
        assumptions: list | None = None,
    ) -> None:
        self.sim = sim or _FakeSimulation()
        self.env = env
        self.assumptions = assumptions if assumptions is not None else []

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Simulation":
            return _FakeQuery([self.sim])
        if name == "Environment":
            return _FakeQuery([self.env] if self.env is not None else [])
        if name == "Assumption":
            return _FakeQuery(self.assumptions)
        return _FakeQuery()


def _call_route(
    *,
    simulation_id: int = 1,
    current_user_id: int = 42,
    session: _FakeSession | None = None,
):
    from app.api.v1 import simulations as sim_mod

    db = session or _FakeSession(
        assumptions=[
            _FakeAssumption(
                "We believe pricing will be 999 rupees per month",
                "PricingArchitect",
            ),
            _FakeAssumption(
                "Market research shows strong market demand",
                "MarketSizeArchitect",
            ),
        ]
    )
    return sim_mod.get_validation_experiment_plan(
        simulation_id=simulation_id,
        db=db,
        current_user=type("U", (), {"id": current_user_id})(),
    )


def test_completed_simulation_returns_plan_payload() -> None:
    out = _call_route()
    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.status == "COMPLETED"
    assert out.signal_quality == 0.62
    assert out.summary.experiment_count == len(out.experiments)
    assert out.summary.experiment_count >= 1
    methods = {e.method for e in out.experiments}
    assert "WILLINGNESS_TO_PAY_SURVEY" in methods
    for exp in out.experiments:
        assert exp.success_threshold
        assert exp.go_no_go_rule
        assert exp.rationale
    assert out.summary.top_experiment == out.experiments[0].method_label
    assert out.meta["model"] == "validation_experiment_planner_v1"


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


def test_no_environment_falls_back_to_defaults() -> None:
    session = _FakeSession(
        env=None,
        assumptions=[
            _FakeAssumption(
                "We believe pricing will be 999 rupees per month",
                "PricingArchitect",
            ),
        ],
    )
    out = _call_route(session=session)
    assert out.summary.experiment_count == 1


def test_no_assumptions_returns_zero_state() -> None:
    session = _FakeSession(assumptions=[])
    out = _call_route(session=session)
    assert out.summary.experiment_count == 0
    assert out.experiments == []
    assert "No assumptions" in out.narrative
