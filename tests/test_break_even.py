"""Tests for the simulation-backed monthly break-even insight."""
from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest
from fastapi import HTTPException

from app.simulation.break_even import (
    MAX_MONTHLY_VISITORS,
    MIN_MONTHLY_VISITORS,
    VERDICT_NEAR_BREAK_EVEN,
    VERDICT_PROFITABLE,
    VERDICT_SHORTFALL,
    VERDICT_UNREACHABLE,
    build_break_even,
)

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def _results(conversion: Any = 0.05) -> dict[str, Any]:
    return {"population_weighted_conversion": conversion}


def test_profitable_projection_reports_margin_of_safety() -> None:
    out = build_break_even(
        _results(0.10),
        monthly_visitors=2_000,
        monthly_fixed_costs=5_000,
        average_order_value=100,
        gross_margin=0.70,
        cost_per_visitor=1.0,
    )

    assert out.verdict == VERDICT_PROFITABLE
    assert out.monthly_customers == pytest.approx(200.0)
    assert out.monthly_revenue == pytest.approx(20_000.0)
    assert out.monthly_gross_profit == pytest.approx(14_000.0)
    assert out.monthly_acquisition_cost == pytest.approx(2_000.0)
    assert out.monthly_contribution == pytest.approx(12_000.0)
    assert out.monthly_operating_result == pytest.approx(7_000.0)
    assert out.contribution_per_visitor == pytest.approx(6.0)
    assert out.break_even_visitors == 834
    assert out.break_even_customers == 84
    assert out.additional_visitors_needed == 0
    assert out.additional_customers_needed == 0
    assert out.safety_margin_ratio == pytest.approx(0.583)
    assert out.maximum_affordable_cost_per_visitor == pytest.approx(4.5)
    assert out.recommendations


def test_shortfall_reports_incremental_volume_needed() -> None:
    out = build_break_even(
        _results(0.05),
        monthly_visitors=1_000,
        monthly_fixed_costs=10_000,
        average_order_value=100,
        gross_margin=0.50,
        cost_per_visitor=0.50,
    )

    assert out.verdict == VERDICT_SHORTFALL
    assert out.contribution_per_visitor == pytest.approx(2.0)
    assert out.monthly_operating_result == pytest.approx(-8_000.0)
    assert out.break_even_visitors == 5_000
    assert out.break_even_customers == 250
    assert out.additional_visitors_needed == 4_000
    assert out.additional_customers_needed == 200
    assert out.safety_margin_ratio == pytest.approx(-4.0)
    assert "4,000 visits" in out.recommendations[0]


def test_near_break_even_verdict_uses_fixed_cost_coverage() -> None:
    out = build_break_even(
        _results(0.10),
        monthly_visitors=1_000,
        monthly_fixed_costs=10_000,
        average_order_value=100,
        gross_margin=0.80,
    )

    assert out.monthly_contribution == pytest.approx(8_000.0)
    assert out.verdict == VERDICT_NEAR_BREAK_EVEN


@pytest.mark.parametrize(
    ("conversion", "cost_per_visitor"),
    [(0.0, 0.0), (0.05, 4.0)],
)
def test_unreachable_when_conversion_or_incremental_contribution_is_zero(
    conversion: float,
    cost_per_visitor: float,
) -> None:
    out = build_break_even(
        _results(conversion),
        average_order_value=100,
        gross_margin=0.80,
        cost_per_visitor=cost_per_visitor,
    )

    assert out.verdict == VERDICT_UNREACHABLE
    assert out.break_even_visitors is None
    assert out.break_even_customers is None
    assert out.additional_visitors_needed is None
    assert out.safety_margin_ratio is None
    assert out.recommendations


def test_zero_fixed_costs_break_even_immediately() -> None:
    out = build_break_even(
        _results(0.02),
        monthly_fixed_costs=0,
        average_order_value=50,
        gross_margin=0.5,
    )
    assert out.verdict == VERDICT_PROFITABLE
    assert out.break_even_visitors == 0
    assert out.break_even_customers == 0
    assert out.safety_margin_ratio == pytest.approx(1.0)


def test_purchase_frequency_flows_through_revenue_and_contribution() -> None:
    out = build_break_even(
        _results(0.10),
        monthly_visitors=100,
        monthly_fixed_costs=0,
        average_order_value=20,
        purchases_per_customer_per_month=3,
        gross_margin=0.50,
    )
    assert out.monthly_customers == pytest.approx(10)
    assert out.monthly_revenue == pytest.approx(600)
    assert out.monthly_gross_profit == pytest.approx(300)
    assert out.contribution_per_customer == pytest.approx(30)


def test_conversion_precedence_and_legacy_fallbacks() -> None:
    preferred = build_break_even(
        {
            "population_weighted_conversion": 0.04,
            "conversion_rate": 0.90,
        }
    )
    assert preferred.weighted_conversion_rate == pytest.approx(0.04)
    assert preferred.meta["conversion_source"] == "population_weighted_conversion"

    legacy = build_break_even({"raw_funnel": {"conversion_rate": 0.03}})
    assert legacy.weighted_conversion_rate == pytest.approx(0.03)
    assert legacy.meta["conversion_source"] == "raw_funnel"


def test_json_string_and_malformed_inputs_are_safe() -> None:
    parsed = build_break_even(json.dumps(_results(0.06)))
    assert parsed.weighted_conversion_rate == pytest.approx(0.06)

    for bad in (None, "{broken", [1], {"conversion_rate": float("nan")}):
        out = build_break_even(bad)
        assert out.verdict == VERDICT_UNREACHABLE
        assert out.weighted_conversion_rate == 0.0


def test_builder_clamps_out_of_range_inputs() -> None:
    low = build_break_even(
        _results(),
        monthly_visitors=0,
        monthly_fixed_costs=-1,
        average_order_value=-1,
        gross_margin=-1,
        purchases_per_customer_per_month=-1,
        cost_per_visitor=-1,
    )
    assert low.monthly_visitors == MIN_MONTHLY_VISITORS
    assert low.monthly_fixed_costs == 0.0
    assert low.average_order_value == 0.0
    assert low.gross_margin == 0.0
    assert low.purchases_per_customer_per_month == 0.0
    assert low.cost_per_visitor == 0.0

    high = build_break_even(_results(), monthly_visitors=10**12)
    assert high.monthly_visitors == MAX_MONTHLY_VISITORS


def test_signal_quality_and_schema_contract() -> None:
    out = build_break_even(
        _results(),
        simulation_id=7,
        project_id=3,
        signal_quality=0.81234567,
    )
    assert out.simulation_id == 7
    assert out.project_id == 3
    assert out.meta["signal_quality"] == pytest.approx(0.812346)
    assert out.meta["model"] == "linear_monthly_break_even_v1"


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
            else {"population_weighted_conversion": 0.10}
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


def _call_route(
    *,
    session: _FakeSession | None = None,
    monthly_visitors: int = 2_000,
) -> Any:
    from app.api.v1 import simulations as sim_mod

    return sim_mod.get_break_even(
        simulation_id=1,
        monthly_visitors=monthly_visitors,
        monthly_fixed_costs=5_000,
        average_order_value=100,
        gross_margin=0.70,
        purchases_per_customer_per_month=1.0,
        cost_per_visitor=1.0,
        db=session or _FakeSession(_FakeSimulation()),
        current_user=type("User", (), {"id": 42})(),
    )


def test_route_is_registered_and_returns_projection() -> None:
    from app.api.v1 import simulations as sim_mod

    paths = {route.path: route.methods for route in sim_mod.router.routes}
    path = "/simulations/{simulation_id}/break-even"
    assert path in paths
    assert "GET" in (paths[path] or set())

    out = _call_route()
    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.verdict == VERDICT_PROFITABLE
    assert out.monthly_operating_result == pytest.approx(7_000)
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
