"""Tests for the simulation-backed cash-runway forecast."""
from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest
from fastapi import HTTPException

from app.simulation.cash_runway import (
    MAX_HORIZON_MONTHS,
    VERDICT_BEYOND_HORIZON,
    VERDICT_CASH_GAP,
    VERDICT_FUNDED_TO_BREAK_EVEN,
    VERDICT_INVIABLE,
    VERDICT_SELF_SUSTAINING,
    build_cash_runway,
)

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def _results(conversion: Any = 0.05) -> dict[str, Any]:
    return {"population_weighted_conversion": conversion}


def _growth_case(*, starting_cash: float) -> Any:
    return build_cash_runway(
        _results(0.05),
        starting_cash=starting_cash,
        horizon_months=3,
        initial_monthly_visitors=1_000,
        monthly_visitor_growth_rate=0.50,
        monthly_fixed_costs=3_000,
        average_order_value=100,
        gross_margin=0.50,
        cost_per_visitor=0.50,
    )


def test_self_sustaining_forecast_tracks_cash_and_totals() -> None:
    out = build_cash_runway(
        _results(0.10),
        starting_cash=10_000,
        horizon_months=3,
        initial_monthly_visitors=2_000,
        monthly_visitor_growth_rate=0.0,
        monthly_fixed_costs=5_000,
        average_order_value=100,
        gross_margin=0.70,
        cost_per_visitor=1.0,
    )

    assert out.verdict == VERDICT_SELF_SUSTAINING
    assert out.break_even_month == 1
    assert out.cash_out_month is None
    assert out.initial_monthly_burn == 0.0
    assert out.static_runway_months is None
    assert out.lowest_cash_balance == pytest.approx(10_000)
    assert out.ending_cash_balance == pytest.approx(31_000)
    assert out.total_revenue == pytest.approx(60_000)
    assert out.total_operating_result == pytest.approx(21_000)
    assert len(out.trajectory) == 3
    assert all(point.is_break_even for point in out.trajectory)


def test_cash_survives_until_growth_reaches_break_even() -> None:
    out = _growth_case(starting_cash=5_000)

    assert out.verdict == VERDICT_FUNDED_TO_BREAK_EVEN
    assert out.break_even_month == 2
    assert out.cash_out_month is None
    assert out.cash_at_break_even == pytest.approx(4_000)
    assert out.lowest_cash_balance == pytest.approx(4_000)
    assert out.minimum_additional_cash == 0.0
    assert out.initial_monthly_burn == pytest.approx(1_000)
    assert out.static_runway_months == pytest.approx(5.0)
    assert [point.monthly_visitors for point in out.trajectory] == [
        1_000,
        1_500,
        2_250,
    ]
    assert [point.monthly_operating_result for point in out.trajectory] == [
        -1_000,
        0,
        1_500,
    ]


def test_cash_gap_quantifies_minimum_bridge_before_break_even() -> None:
    out = _growth_case(starting_cash=500)

    assert out.verdict == VERDICT_CASH_GAP
    assert out.cash_out_month == 1
    assert out.break_even_month == 2
    assert out.cash_at_break_even == pytest.approx(-500)
    assert out.lowest_cash_balance == pytest.approx(-500)
    assert out.minimum_additional_cash == pytest.approx(500)
    assert out.trajectory[0].requires_additional_cash is True
    assert "500.00" in out.recommendations[0]


def test_temporary_negative_balance_remains_a_cash_gap() -> None:
    out = build_cash_runway(
        _results(0.05),
        starting_cash=500,
        horizon_months=2,
        initial_monthly_visitors=1_000,
        monthly_visitor_growth_rate=1.0,
        monthly_fixed_costs=3_000,
        average_order_value=100,
        gross_margin=0.50,
        cost_per_visitor=0.50,
    )

    assert out.cash_out_month == 1
    assert out.break_even_month == 2
    assert out.cash_at_break_even == pytest.approx(500)
    assert out.minimum_additional_cash == pytest.approx(500)
    assert out.verdict == VERDICT_CASH_GAP


def test_solvent_but_no_break_even_inside_horizon() -> None:
    out = build_cash_runway(
        _results(0.05),
        starting_cash=5_000,
        horizon_months=3,
        initial_monthly_visitors=1_000,
        monthly_visitor_growth_rate=0.0,
        monthly_fixed_costs=3_000,
        average_order_value=100,
        gross_margin=0.50,
        cost_per_visitor=0.50,
    )

    assert out.verdict == VERDICT_BEYOND_HORIZON
    assert out.break_even_month is None
    assert out.cash_out_month is None
    assert out.ending_cash_balance == pytest.approx(2_000)


@pytest.mark.parametrize(
    ("conversion", "cost_per_visitor"),
    [(0.0, 0.0), (0.05, 3.0)],
)
def test_inviable_when_traffic_cannot_add_positive_contribution(
    conversion: float,
    cost_per_visitor: float,
) -> None:
    out = build_cash_runway(
        _results(conversion),
        starting_cash=5_000,
        monthly_fixed_costs=100,
        average_order_value=100,
        gross_margin=0.50,
        cost_per_visitor=cost_per_visitor,
    )

    assert out.verdict == VERDICT_INVIABLE
    assert out.break_even_month is None
    assert out.recommendations


def test_json_results_signal_quality_and_schema_contract() -> None:
    out = build_cash_runway(
        json.dumps(_results(0.06)),
        simulation_id=7,
        project_id=3,
        horizon_months=1,
        signal_quality=0.42,
    )

    assert out.simulation_id == 7
    assert out.project_id == 3
    assert out.weighted_conversion_rate == pytest.approx(0.06)
    assert out.meta["conversion_source"] == "population_weighted_conversion"
    assert out.meta["signal_quality"] == pytest.approx(0.42)
    assert out.meta["model"] == "cash_runway_growth_v1"
    assert "low signal quality" in out.recommendations[-1]


def test_builder_safely_clamps_malformed_inputs() -> None:
    out = build_cash_runway(
        "{broken",
        starting_cash=-1,
        horizon_months=10_000,
        initial_monthly_visitors=0,
        monthly_visitor_growth_rate=float("inf"),
        monthly_fixed_costs=-1,
        average_order_value=-1,
        gross_margin=-1,
        purchases_per_customer_per_month=-1,
        cost_per_visitor=-1,
    )

    assert out.starting_cash == 0.0
    assert out.horizon_months == MAX_HORIZON_MONTHS
    assert len(out.trajectory) == MAX_HORIZON_MONTHS
    assert out.initial_monthly_visitors == 1
    assert out.monthly_fixed_costs == 0.0
    assert out.average_order_value == 0.0
    assert out.gross_margin == 0.0
    assert out.purchases_per_customer_per_month == 0.0
    assert out.cost_per_visitor == 0.0
    assert out.verdict == VERDICT_INVIABLE


class _FakeSimulation:
    def __init__(
        self,
        sim_id: int = 1,
        *,
        status: str = "COMPLETED",
        results: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        self.id = sim_id
        self.project_id = 10
        self.status = status
        self.error_message = error_message
        self.signal_quality = 0.62
        self.results_json = (
            results
            if results is not None
            else {"population_weighted_conversion": 0.05}
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

    return sim_mod.get_cash_runway(
        simulation_id=1,
        starting_cash=5_000,
        horizon_months=3,
        initial_monthly_visitors=1_000,
        monthly_visitor_growth_rate=0.50,
        monthly_fixed_costs=3_000,
        average_order_value=100,
        gross_margin=0.50,
        purchases_per_customer_per_month=1.0,
        cost_per_visitor=0.50,
        db=session or _FakeSession(_FakeSimulation()),
        current_user=type("User", (), {"id": 42})(),
    )


def test_route_is_registered_and_returns_forecast() -> None:
    from app.api.v1 import simulations as sim_mod

    paths = {route.path: route.methods for route in sim_mod.router.routes}
    path = "/simulations/{simulation_id}/cash-runway"
    assert path in paths
    assert "GET" in (paths[path] or set())

    out = _call_route()
    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.verdict == VERDICT_FUNDED_TO_BREAK_EVEN
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
