"""Tests for the simulation-backed runway acquisition-cost ceiling."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from fastapi import HTTPException

from app.simulation.cash_runway import build_cash_runway
from app.simulation.runway_acquisition_ceiling import (
    VERDICT_INFEASIBLE,
    VERDICT_PLAN_EXCEEDS_CEILING,
    VERDICT_PLAN_WITHIN_CEILING,
    build_runway_acquisition_ceiling,
)

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def _results(conversion: Any = 0.05) -> dict[str, Any]:
    return {"population_weighted_conversion": conversion}


def _ceiling(**overrides: Any) -> Any:
    inputs: dict[str, Any] = {
        "starting_cash": 1_000,
        "horizon_months": 3,
        "initial_monthly_visitors": 1_000,
        "monthly_visitor_growth_rate": 0.50,
        "monthly_fixed_costs": 3_000,
        "average_order_value": 100,
        "gross_margin": 0.50,
        "planned_cost_per_visitor": 0.25,
    }
    inputs.update(overrides)
    return build_runway_acquisition_ceiling(_results(), **inputs)


def test_plan_within_ceiling_reports_per_visitor_headroom() -> None:
    out = _ceiling()

    assert out.verdict == VERDICT_PLAN_WITHIN_CEILING
    assert out.constraint == "NONE"
    assert out.cash_safe_cost_per_visitor_ceiling == pytest.approx(0.50)
    assert out.cost_per_visitor_headroom == pytest.approx(0.25)
    assert out.required_cost_per_visitor_reduction == 0.0
    assert out.planned.succeeds is True
    assert out.ceiling is not None
    assert out.ceiling.succeeds is True
    assert out.ceiling.break_even_month == 2
    assert out.ceiling.lowest_cash_balance == 0.0
    assert "0.2500" in out.recommendations[0]


def test_plan_over_ceiling_quantifies_required_cost_reduction() -> None:
    out = _ceiling(planned_cost_per_visitor=0.75)

    assert out.verdict == VERDICT_PLAN_EXCEEDS_CEILING
    assert out.constraint == "ACQUISITION_COST_PLAN"
    assert out.cash_safe_cost_per_visitor_ceiling == pytest.approx(0.50)
    assert out.cost_per_visitor_headroom == 0.0
    assert out.required_cost_per_visitor_reduction == pytest.approx(0.25)
    assert out.planned.succeeds is False
    assert out.planned.cash_out_month == 1
    assert "0.2500" in out.recommendations[0]


def test_ceiling_is_exact_to_the_advertised_increment() -> None:
    out = _ceiling(starting_cash=5_000)
    ceiling = out.cash_safe_cost_per_visitor_ceiling
    assert ceiling is not None

    common = {
        "starting_cash": 5_000,
        "horizon_months": 3,
        "initial_monthly_visitors": 1_000,
        "monthly_visitor_growth_rate": 0.50,
        "monthly_fixed_costs": 3_000,
        "average_order_value": 100,
        "gross_margin": 0.50,
    }
    at_ceiling = build_cash_runway(
        _results(),
        cost_per_visitor=ceiling,
        **common,
    )
    above_ceiling = build_cash_runway(
        _results(),
        cost_per_visitor=ceiling + 0.0001,
        **common,
    )

    assert ceiling == pytest.approx(1.1666)
    assert at_ceiling.break_even_month == 3
    assert at_ceiling.cash_out_month is None
    assert above_ceiling.break_even_month is None
    assert out.meta["search_increment"] == pytest.approx(0.0001)
    assert out.meta["search_method"] == (
        "integer_binary_search_with_boundary_verification"
    )


def test_no_conversion_value_is_infeasible_unit_economics() -> None:
    out = build_runway_acquisition_ceiling(
        _results(0.0),
        starting_cash=1_000,
        horizon_months=3,
        initial_monthly_visitors=1_000,
        monthly_visitor_growth_rate=0.50,
        monthly_fixed_costs=3_000,
        average_order_value=100,
        gross_margin=0.50,
    )

    assert out.verdict == VERDICT_INFEASIBLE
    assert out.constraint == "UNIT_ECONOMICS"
    assert out.cash_safe_cost_per_visitor_ceiling is None
    assert out.cost_per_visitor_headroom is None
    assert out.required_cost_per_visitor_reduction is None
    assert out.ceiling is None
    assert "no positive conversion value" in out.recommendations[0]


def test_zero_cost_acquisition_cannot_rescue_unsafe_operating_plan() -> None:
    out = _ceiling(starting_cash=0.0, planned_cost_per_visitor=0.0)

    assert out.verdict == VERDICT_INFEASIBLE
    assert out.constraint == "OPERATING_PLAN"
    assert out.cash_safe_cost_per_visitor_ceiling is None
    assert out.planned.cash_out_month == 1
    assert out.ceiling is None
    assert "zero-cost acquisition" in out.recommendations[0]


def test_search_limit_is_reported_as_a_lower_bound() -> None:
    out = _ceiling(
        starting_cash=0,
        horizon_months=1,
        initial_monthly_visitors=1,
        monthly_visitor_growth_rate=0.0,
        monthly_fixed_costs=0.0,
        average_order_value=10_000_000,
        gross_margin=1.0,
        purchases_per_customer_per_month=1_000,
        planned_cost_per_visitor=1_000_000,
    )

    assert out.verdict == VERDICT_PLAN_WITHIN_CEILING
    assert out.constraint == "SEARCH_LIMIT"
    assert out.search_limit_reached is True
    assert out.cash_safe_cost_per_visitor_ceiling == pytest.approx(1_000_000)
    assert "true acquisition ceiling is above" in out.recommendations[0]


def test_metadata_and_low_signal_warning() -> None:
    out = build_runway_acquisition_ceiling(
        _results(),
        simulation_id=7,
        project_id=3,
        signal_quality=0.42,
    )

    assert out.simulation_id == 7
    assert out.project_id == 3
    assert out.weighted_conversion_rate == pytest.approx(0.05)
    assert out.meta["model"] == "runway_acquisition_ceiling_v1"
    assert out.meta["conversion_source"] == "population_weighted_conversion"
    assert out.meta["signal_quality"] == pytest.approx(0.42)
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

    return sim_mod.get_runway_acquisition_ceiling(
        simulation_id=1,
        starting_cash=1_000,
        horizon_months=3,
        initial_monthly_visitors=1_000,
        monthly_visitor_growth_rate=0.50,
        monthly_fixed_costs=3_000,
        average_order_value=100,
        gross_margin=0.50,
        purchases_per_customer_per_month=1.0,
        planned_cost_per_visitor=0.75,
        db=session or _FakeSession(_FakeSimulation()),
        current_user=type("User", (), {"id": 42})(),
    )


def test_route_is_registered_and_returns_ceiling() -> None:
    from app.api.v1 import simulations as sim_mod

    paths = {route.path: route.methods for route in sim_mod.router.routes}
    path = "/simulations/{simulation_id}/runway-acquisition-ceiling"
    assert path in paths
    assert "GET" in (paths[path] or set())

    out = _call_route()
    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.verdict == VERDICT_PLAN_EXCEEDS_CEILING
    assert out.cash_safe_cost_per_visitor_ceiling == pytest.approx(0.50)
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
    private_error = (
        "Provider request failed at postgres://founder:secret@internal-db/thecee"
    )

    with pytest.raises(HTTPException) as exc:
        _call_route(
            session=_FakeSession(
                _FakeSimulation(status="FAILED", error_message=private_error)
            )
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == (
        "Simulation failed; runway acquisition analysis is unavailable."
    )
    assert private_error not in exc.value.detail
