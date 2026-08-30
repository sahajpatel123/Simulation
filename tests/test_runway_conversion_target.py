"""Tests for the simulation-backed runway conversion target."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from fastapi import HTTPException

from app.simulation.cash_runway import build_cash_runway
from app.simulation.runway_conversion_target import (
    CONVERSION_PRECISION,
    VERDICT_CONVERSION_GAP,
    VERDICT_INFEASIBLE,
    VERDICT_PREDICTION_SUFFICIENT,
    build_runway_conversion_target,
)

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def _results(conversion: Any = 0.05) -> dict[str, Any]:
    return {"population_weighted_conversion": conversion}


def _target(conversion: Any = 0.05, **overrides: Any) -> Any:
    inputs: dict[str, Any] = {
        "starting_cash": 0,
        "horizon_months": 1,
        "initial_monthly_visitors": 1_000,
        "monthly_visitor_growth_rate": 0.0,
        "monthly_fixed_costs": 3_000,
        "average_order_value": 100,
        "gross_margin": 0.50,
        "cost_per_visitor": 0.50,
    }
    inputs.update(overrides)
    return build_runway_conversion_target(_results(conversion), **inputs)


def test_conversion_gap_quantifies_threshold_and_relative_lift() -> None:
    out = _target()

    assert out.verdict == VERDICT_CONVERSION_GAP
    assert out.constraint == "SIMULATED_CONVERSION"
    assert out.required_conversion_rate == pytest.approx(0.07, abs=1e-7)
    assert out.conversion_gap_percentage_points == pytest.approx(2.0, abs=1e-5)
    assert out.conversion_headroom_percentage_points == 0.0
    assert out.relative_conversion_lift_percent == pytest.approx(40.0, abs=0.01)
    assert out.predicted.succeeds is False
    assert out.target is not None
    assert out.target.succeeds is True
    assert out.target.break_even_month == 1
    assert "relative lift" in out.recommendations[0]


def test_target_is_smallest_success_at_advertised_precision() -> None:
    out = _target()
    required = out.required_conversion_rate
    assert required is not None

    inputs = {
        "starting_cash": 0,
        "horizon_months": 1,
        "initial_monthly_visitors": 1_000,
        "monthly_visitor_growth_rate": 0.0,
        "monthly_fixed_costs": 3_000,
        "average_order_value": 100,
        "gross_margin": 0.50,
        "cost_per_visitor": 0.50,
    }
    at_target = build_cash_runway(
        _results(required),
        **inputs,
    )
    before_target = build_cash_runway(
        _results(required - 10**-CONVERSION_PRECISION),
        **inputs,
    )

    assert at_target.break_even_month == 1
    assert at_target.cash_out_month is None
    assert before_target.break_even_month is None
    assert before_target.cash_out_month == 1


def test_sufficient_prediction_reports_conversion_headroom() -> None:
    out = _target(0.08)

    assert out.verdict == VERDICT_PREDICTION_SUFFICIENT
    assert out.constraint == "NONE"
    assert out.conversion_gap_percentage_points == 0.0
    assert out.conversion_headroom_percentage_points == pytest.approx(
        1.0,
        abs=1e-5,
    )
    assert out.relative_conversion_lift_percent == 0.0
    assert out.predicted.succeeds is True


def test_zero_simulated_conversion_reports_gap_without_infinite_lift() -> None:
    out = _target(0.0)

    assert out.verdict == VERDICT_CONVERSION_GAP
    assert out.simulated_conversion_rate == 0.0
    assert out.required_conversion_rate is not None
    assert out.relative_conversion_lift_percent is None
    assert out.target is not None and out.target.succeeds is True
    assert "undefined from a zero-conversion baseline" in out.recommendations[0]


def test_non_positive_value_is_unit_economics_constraint() -> None:
    out = _target(average_order_value=0.0)

    assert out.verdict == VERDICT_INFEASIBLE
    assert out.constraint == "UNIT_ECONOMICS"
    assert out.required_conversion_rate is None
    assert out.target is None
    assert out.maximum_tested.succeeds is False
    assert "100%" in out.recommendations[0]


def test_first_month_cash_gap_can_be_infeasible_even_at_full_conversion() -> None:
    out = _target(
        starting_cash=0,
        horizon_months=2,
        initial_monthly_visitors=1,
        monthly_visitor_growth_rate=1.0,
        monthly_fixed_costs=1_000,
        average_order_value=100,
        gross_margin=1.0,
        cost_per_visitor=0.0,
    )

    assert out.verdict == VERDICT_INFEASIBLE
    assert out.constraint == "FIRST_MONTH_CASH"
    assert out.maximum_tested.cash_out_month == 1
    assert "month 1" in out.recommendations[0]


def test_horizon_constraint_is_distinct_from_immediate_cash_gap() -> None:
    out = _target(
        starting_cash=1_000,
        horizon_months=1,
        initial_monthly_visitors=1,
        monthly_fixed_costs=1_000,
        average_order_value=100,
        gross_margin=1.0,
        cost_per_visitor=0.0,
    )

    assert out.verdict == VERDICT_INFEASIBLE
    assert out.constraint == "HORIZON_OR_CASH"
    assert out.maximum_tested.cash_out_month is None
    assert out.maximum_tested.break_even_month is None


def test_metadata_and_low_signal_warning() -> None:
    out = build_runway_conversion_target(
        _results(),
        simulation_id=7,
        project_id=3,
        signal_quality=0.42,
    )

    assert out.simulation_id == 7
    assert out.project_id == 3
    assert out.meta["model"] == "runway_conversion_target_v1"
    assert out.meta["search_increment"] == pytest.approx(1e-8)
    assert out.meta["search_method"] == (
        "integer_binary_search_with_boundary_verification"
    )
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
        self.results_json = results if results is not None else _results()


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

    return sim_mod.get_runway_conversion_target(
        simulation_id=1,
        starting_cash=0,
        horizon_months=1,
        initial_monthly_visitors=1_000,
        monthly_visitor_growth_rate=0.0,
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
    path = "/simulations/{simulation_id}/runway-conversion-target"
    assert path in paths
    assert "GET" in (paths[path] or set())

    out = _call_route()
    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.verdict == VERDICT_CONVERSION_GAP
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


def test_route_does_not_expose_persisted_failure_details() -> None:
    private_error = "provider failed at postgres://founder:secret@internal-db/thecee"

    with pytest.raises(HTTPException) as exc:
        _call_route(
            session=_FakeSession(
                _FakeSimulation(status="FAILED", error_message=private_error)
            )
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == (
        "Simulation failed; runway conversion analysis is unavailable."
    )
    assert private_error not in exc.value.detail
