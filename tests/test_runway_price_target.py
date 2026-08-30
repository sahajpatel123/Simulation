"""Tests for the simulation-backed runway average-order-value target."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from fastapi import HTTPException

from app.simulation.cash_runway import build_cash_runway
from app.simulation.runway_price_target import (
    VERDICT_INFEASIBLE,
    VERDICT_PLAN_PRICE_SUFFICIENT,
    VERDICT_PRICE_GAP,
    build_runway_price_target,
)

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def _results(conversion: Any = 0.05) -> dict[str, Any]:
    return {"population_weighted_conversion": conversion}


def _target(**overrides: Any) -> Any:
    inputs: dict[str, Any] = {
        "starting_cash": 500,
        "horizon_months": 3,
        "initial_monthly_visitors": 1_000,
        "monthly_visitor_growth_rate": 0.50,
        "monthly_fixed_costs": 3_000,
        "planned_average_order_value": 100,
        "gross_margin": 0.50,
        "cost_per_visitor": 0.50,
    }
    inputs.update(overrides)
    return build_runway_price_target(_results(), **inputs)


def test_price_gap_quantifies_required_average_order_value_increase() -> None:
    out = _target()

    assert out.verdict == VERDICT_PRICE_GAP
    assert out.constraint == "PRICE_PLAN"
    assert out.required_average_order_value == pytest.approx(120.0)
    assert out.required_price_increase == pytest.approx(20.0)
    assert out.price_headroom == 0.0
    assert out.relative_price_increase_percent == pytest.approx(20.0)
    assert out.planned.succeeds is False
    assert out.planned.cash_out_month == 1
    assert out.target is not None
    assert out.target.succeeds is True
    assert out.target.lowest_cash_balance == 0.0
    assert "20.00" in out.recommendations[0]


def test_sufficient_plan_reports_price_headroom() -> None:
    out = _target(planned_average_order_value=140)

    assert out.verdict == VERDICT_PLAN_PRICE_SUFFICIENT
    assert out.constraint == "NONE"
    assert out.required_average_order_value == pytest.approx(120.0)
    assert out.price_headroom == pytest.approx(20.0)
    assert out.required_price_increase == 0.0
    assert out.relative_price_increase_percent == 0.0
    assert out.planned.succeeds is True
    assert "20.00" in out.recommendations[0]


def test_target_is_exact_to_the_advertised_cent_increment() -> None:
    out = _target()
    target = out.required_average_order_value
    assert target is not None

    common = {
        "starting_cash": 500,
        "horizon_months": 3,
        "initial_monthly_visitors": 1_000,
        "monthly_visitor_growth_rate": 0.50,
        "monthly_fixed_costs": 3_000,
        "gross_margin": 0.50,
        "cost_per_visitor": 0.50,
    }
    at_target = build_cash_runway(
        _results(),
        average_order_value=target,
        **common,
    )
    below_target = build_cash_runway(
        _results(),
        average_order_value=target - 0.01,
        **common,
    )

    assert target == pytest.approx(120.0)
    assert at_target.cash_out_month is None
    assert at_target.break_even_month == 2
    assert below_target.cash_out_month == 1
    assert out.meta["search_increment"] == pytest.approx(0.01)
    assert out.meta["search_method"] == (
        "integer_binary_search_with_boundary_verification"
    )


def test_zero_price_plan_reports_undefined_relative_increase() -> None:
    out = _target(planned_average_order_value=0.0)

    assert out.verdict == VERDICT_PRICE_GAP
    assert out.required_average_order_value == pytest.approx(120.0)
    assert out.required_price_increase == pytest.approx(120.0)
    assert out.relative_price_increase_percent is None
    assert "undefined from a zero-price baseline" in out.recommendations[0]


def test_missing_conversion_signal_is_infeasible() -> None:
    out = build_runway_price_target(_results(0.0))

    assert out.verdict == VERDICT_INFEASIBLE
    assert out.constraint == "DEMAND_SIGNAL"
    assert out.required_average_order_value is None
    assert out.required_price_increase is None
    assert out.price_headroom is None
    assert out.target is None
    assert out.maximum_tested.succeeds is False
    assert "No positive conversion signal" in out.recommendations[0]


@pytest.mark.parametrize(
    ("overrides", "label"),
    [
        ({"gross_margin": 0.0}, "gross margin"),
        ({"purchases_per_customer_per_month": 0.0}, "purchase frequency"),
    ],
)
def test_zero_margin_or_frequency_is_infeasible(
    overrides: dict[str, float],
    label: str,
) -> None:
    out = _target(**overrides)

    assert out.verdict == VERDICT_INFEASIBLE
    assert out.constraint == "MARGIN_OR_FREQUENCY"
    assert out.required_average_order_value is None
    assert label in out.recommendations[0]


def test_supported_price_limit_is_explicit_when_maximum_cannot_rescue_plan() -> None:
    out = build_runway_price_target(
        _results(0.00000001),
        starting_cash=0.0,
        horizon_months=1,
        initial_monthly_visitors=1,
        monthly_visitor_growth_rate=0.0,
        monthly_fixed_costs=1_000_000_000,
        planned_average_order_value=100.0,
        gross_margin=0.01,
        purchases_per_customer_per_month=1.0,
        cost_per_visitor=0.0,
    )

    assert out.verdict == VERDICT_INFEASIBLE
    assert out.constraint == "SUPPORTED_PRICE_LIMIT"
    assert out.required_average_order_value is None
    assert out.maximum_tested.average_order_value == pytest.approx(10_000_000)
    assert out.maximum_tested.succeeds is False
    assert "maximum tested average order value" in out.recommendations[0]


def test_metadata_and_low_signal_warning() -> None:
    out = build_runway_price_target(
        _results(),
        simulation_id=7,
        project_id=3,
        signal_quality=0.42,
    )

    assert out.simulation_id == 7
    assert out.project_id == 3
    assert out.weighted_conversion_rate == pytest.approx(0.05)
    assert out.meta["model"] == "runway_price_target_v1"
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

    return sim_mod.get_runway_price_target(
        simulation_id=1,
        starting_cash=500,
        horizon_months=3,
        initial_monthly_visitors=1_000,
        monthly_visitor_growth_rate=0.50,
        monthly_fixed_costs=3_000,
        planned_average_order_value=100,
        gross_margin=0.50,
        purchases_per_customer_per_month=1.0,
        cost_per_visitor=0.50,
        db=session or _FakeSession(_FakeSimulation()),
        current_user=type("User", (), {"id": 42})(),
    )


def test_route_is_registered_and_returns_price_target() -> None:
    from app.api.v1 import simulations as sim_mod

    paths = {route.path: route.methods for route in sim_mod.router.routes}
    path = "/simulations/{simulation_id}/runway-price-target"
    assert path in paths
    assert "GET" in (paths[path] or set())

    out = _call_route()
    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.verdict == VERDICT_PRICE_GAP
    assert out.required_average_order_value == pytest.approx(120.0)
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
        "Simulation failed; runway price analysis is unavailable."
    )
    assert private_error not in exc.value.detail
