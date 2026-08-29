"""Tests for the simulation-backed runway growth target."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from fastapi import HTTPException

from app.simulation.runway_growth_target import (
    VERDICT_GROWTH_GAP,
    VERDICT_INFEASIBLE,
    VERDICT_NO_GROWTH_REQUIRED,
    VERDICT_PLAN_SUFFICIENT,
    build_runway_growth_target,
)

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def _results(conversion: Any = 0.05) -> dict[str, Any]:
    return {"population_weighted_conversion": conversion}


def _target(**overrides: Any) -> Any:
    inputs: dict[str, Any] = {
        "starting_cash": 5_000,
        "horizon_months": 3,
        "initial_monthly_visitors": 1_000,
        "planned_monthly_visitor_growth_rate": 0.20,
        "monthly_fixed_costs": 3_000,
        "average_order_value": 100,
        "gross_margin": 0.50,
        "cost_per_visitor": 0.50,
    }
    inputs.update(overrides)
    return build_runway_growth_target(_results(), **inputs)


def test_growth_gap_finds_smallest_cash_safe_rate() -> None:
    out = _target(horizon_months=2)

    assert out.verdict == VERDICT_GROWTH_GAP
    assert out.constraint == "GROWTH_PLAN"
    assert out.required_monthly_visitor_growth_rate == pytest.approx(0.4995, abs=0.000001)
    assert out.growth_gap_percentage_points == pytest.approx(
        (out.required_monthly_visitor_growth_rate - 0.20) * 100.0,
        abs=0.0001,
    )
    assert out.planned.succeeds is False
    assert out.target is not None
    assert out.target.succeeds is True
    assert out.target.break_even_month == 2
    assert out.target.cash_out_month is None
    assert "29.95-point gap" in out.recommendations[0]


def test_plan_sufficient_reports_lower_required_rate() -> None:
    out = _target(planned_monthly_visitor_growth_rate=0.30)

    assert out.verdict == VERDICT_PLAN_SUFFICIENT
    assert out.constraint == "NONE"
    assert out.required_monthly_visitor_growth_rate is not None
    assert out.required_monthly_visitor_growth_rate < 0.30
    assert out.growth_gap_percentage_points == 0.0
    assert out.planned.succeeds is True
    assert out.target is not None and out.target.succeeds is True


def test_no_growth_required_when_initial_traffic_breaks_even() -> None:
    out = _target(
        initial_monthly_visitors=1_500,
        planned_monthly_visitor_growth_rate=0.0,
    )

    assert out.verdict == VERDICT_NO_GROWTH_REQUIRED
    assert out.required_monthly_visitor_growth_rate == 0.0
    assert out.target is not None
    assert out.target.break_even_month == 1
    assert out.target.succeeds is True


def test_first_month_cash_gap_cannot_be_rescued_by_growth() -> None:
    out = _target(starting_cash=500)

    assert out.verdict == VERDICT_INFEASIBLE
    assert out.constraint == "FIRST_MONTH_CASH"
    assert out.required_monthly_visitor_growth_rate is None
    assert out.target is None
    assert out.maximum_tested.cash_out_month == 1
    assert "month 1" in out.recommendations[0]


def test_non_positive_contribution_is_unit_economics_constraint() -> None:
    out = _target(cost_per_visitor=3.0)

    assert out.verdict == VERDICT_INFEASIBLE
    assert out.constraint == "UNIT_ECONOMICS"
    assert out.maximum_tested.succeeds is False
    assert "no positive contribution" in out.recommendations[0]


def test_horizon_can_make_growth_target_infeasible() -> None:
    out = _target(
        starting_cash=10_000,
        horizon_months=2,
        monthly_fixed_costs=5_000,
    )

    assert out.verdict == VERDICT_INFEASIBLE
    assert out.constraint == "HORIZON_OR_CASH"
    assert out.maximum_tested.cash_out_month is None
    assert out.maximum_tested.break_even_month is None
    assert "100%" in out.recommendations[0]


def test_schema_metadata_and_low_signal_warning() -> None:
    out = build_runway_growth_target(
        _results(0.05),
        simulation_id=7,
        project_id=3,
        signal_quality=0.42,
    )

    assert out.simulation_id == 7
    assert out.project_id == 3
    assert out.weighted_conversion_rate == pytest.approx(0.05)
    assert out.meta["model"] == "runway_growth_target_v1"
    assert out.meta["search_precision"] == 6
    assert out.meta["conversion_source"] == "population_weighted_conversion"
    assert "low signal quality" in out.recommendations[-1]


class _FakeSimulation:
    def __init__(
        self,
        *,
        status: str = "COMPLETED",
        results: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        self.id = 1
        self.project_id = 10
        self.status = status
        self.error_message = error_message
        self.signal_quality = 0.62
        self.results_json = (
            results if results is not None else {"population_weighted_conversion": 0.05}
        )


class _FakeQuery:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def join(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def filter(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def first(self) -> Any | None:
        return self.items[0] if self.items else None


class _FakeSession:
    def __init__(self, sim: object | None) -> None:
        self.sim = sim

    def query(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return _FakeQuery([self.sim] if self.sim is not None else [])


def _call_route(*, session: _FakeSession | None = None) -> Any:
    from app.api.v1 import simulations as sim_mod

    return sim_mod.get_runway_growth_target(
        simulation_id=1,
        starting_cash=5_000,
        horizon_months=2,
        initial_monthly_visitors=1_000,
        planned_monthly_visitor_growth_rate=0.20,
        monthly_fixed_costs=3_000,
        average_order_value=100,
        gross_margin=0.50,
        purchases_per_customer_per_month=1.0,
        cost_per_visitor=0.50,
        db=session or _FakeSession(_FakeSimulation()),
        current_user=type("User", (), {"id": 42})(),
    )


def test_route_is_registered_and_returns_target() -> None:
    from app.api.v1 import simulations as sim_mod

    paths = {route.path: route.methods for route in sim_mod.router.routes}
    path = "/simulations/{simulation_id}/runway-growth-target"
    assert path in paths
    assert "GET" in (paths[path] or set())

    out = _call_route()
    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.verdict == VERDICT_GROWTH_GAP
    assert out.meta["signal_quality"] == pytest.approx(0.62)


@pytest.mark.parametrize(
    ("sim", "status_code"),
    [
        (_FakeSimulation(status="PENDING"), 409),
        (_FakeSimulation(status="FAILED", error_message="boom"), 422),
        (_FakeSimulation(results={}), 422),
        (None, 404),
    ],
)
def test_route_rejects_unusable_simulations(
    sim: _FakeSimulation | None,
    status_code: int,
) -> None:
    with pytest.raises(HTTPException) as exc:
        _call_route(session=_FakeSession(sim))
    assert exc.value.status_code == status_code
