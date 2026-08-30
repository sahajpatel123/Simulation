"""Tests for the simulation-backed runway funding target."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from fastapi import HTTPException

from app.schemas.cash_runway import CashRunwayOut
from app.simulation import runway_funding_target as funding_target_module
from app.simulation.cash_runway import build_cash_runway
from app.simulation.runway_funding_target import (
    VERDICT_FUNDING_GAP,
    VERDICT_INFEASIBLE,
    VERDICT_PLAN_FUNDED,
    build_runway_funding_target,
)

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def _results(conversion: Any = 0.05) -> dict[str, Any]:
    return {"population_weighted_conversion": conversion}


def _target(**overrides: Any) -> Any:
    inputs: dict[str, Any] = {
        "planned_starting_cash": 500,
        "horizon_months": 3,
        "initial_monthly_visitors": 1_000,
        "monthly_visitor_growth_rate": 0.50,
        "monthly_fixed_costs": 3_000,
        "average_order_value": 100,
        "gross_margin": 0.50,
        "cost_per_visitor": 0.50,
    }
    inputs.update(overrides)
    return build_runway_funding_target(_results(), **inputs)


def test_funding_gap_reports_exact_opening_cash_requirement() -> None:
    out = _target()

    assert out.verdict == VERDICT_FUNDING_GAP
    assert out.constraint == "STARTING_CASH"
    assert out.minimum_starting_cash == pytest.approx(1_000)
    assert out.additional_cash_required == pytest.approx(500)
    assert out.funding_surplus == 0.0
    assert out.planned.succeeds is False
    assert out.planned.cash_out_month == 1
    assert out.target is not None
    assert out.target.succeeds is True
    assert out.target.lowest_cash_balance == 0.0
    assert out.target.break_even_month == 2
    assert "500.00" in out.recommendations[0]


def test_funded_plan_reports_cash_buffer() -> None:
    out = _target(planned_starting_cash=2_500)

    assert out.verdict == VERDICT_PLAN_FUNDED
    assert out.constraint == "NONE"
    assert out.minimum_starting_cash == pytest.approx(1_000)
    assert out.additional_cash_required == 0.0
    assert out.funding_surplus == pytest.approx(1_500)
    assert out.planned.succeeds is True
    assert "1,500.00 buffer" in out.recommendations[0]


def test_zero_cash_is_enough_for_a_self_funding_plan() -> None:
    out = _target(
        planned_starting_cash=0,
        monthly_fixed_costs=1_000,
    )

    assert out.verdict == VERDICT_PLAN_FUNDED
    assert out.minimum_starting_cash == 0.0
    assert out.additional_cash_required == 0.0
    assert out.funding_surplus == 0.0
    assert out.target is not None
    assert out.target.starting_cash == 0.0
    assert out.target.break_even_month == 1
    assert out.target.succeeds is True


def test_target_is_exact_to_one_cent() -> None:
    out = _target(planned_starting_cash=0)
    requirement = out.minimum_starting_cash
    assert requirement is not None

    common = {
        "horizon_months": 3,
        "initial_monthly_visitors": 1_000,
        "monthly_visitor_growth_rate": 0.50,
        "monthly_fixed_costs": 3_000,
        "average_order_value": 100,
        "gross_margin": 0.50,
        "cost_per_visitor": 0.50,
    }
    at_target = build_cash_runway(
        _results(),
        starting_cash=requirement,
        **common,
    )
    below_target = build_cash_runway(
        _results(),
        starting_cash=requirement - 0.01,
        **common,
    )

    assert at_target.cash_out_month is None
    assert at_target.lowest_cash_balance == 0.0
    assert below_target.cash_out_month == 1
    assert below_target.lowest_cash_balance == pytest.approx(-0.01)
    assert out.target is not None
    assert out.target.starting_cash == at_target.starting_cash
    assert out.target.break_even_month == at_target.break_even_month
    assert out.target.cash_out_month == at_target.cash_out_month
    assert out.target.lowest_cash_balance == at_target.lowest_cash_balance
    assert out.target.ending_cash_balance == at_target.ending_cash_balance
    assert out.target.succeeds is True
    assert out.meta["currency_precision"] == pytest.approx(0.01)
    assert out.meta["calculation_method"] == (
        "zero_cash_ledger_trough_verified_forecast"
    )


def test_invalid_derived_target_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    real_build_cash_runway = funding_target_module.build_cash_runway

    def inconsistent_forecast(*args: Any, **kwargs: Any) -> CashRunwayOut:
        forecast = real_build_cash_runway(*args, **kwargs)
        if forecast.starting_cash == 1_000.0:
            return forecast.model_copy(
                update={"cash_out_month": 1, "verdict": "CASH_GAP"}
            )
        return forecast

    monkeypatch.setattr(
        funding_target_module,
        "build_cash_runway",
        inconsistent_forecast,
    )

    with pytest.raises(
        RuntimeError,
        match="Derived runway funding target failed forecast verification",
    ):
        _target()


def test_non_positive_contribution_is_infeasible() -> None:
    out = _target(cost_per_visitor=3.0)

    assert out.verdict == VERDICT_INFEASIBLE
    assert out.constraint == "UNIT_ECONOMICS"
    assert out.minimum_starting_cash is None
    assert out.additional_cash_required is None
    assert out.funding_surplus is None
    assert out.target is None
    assert "cannot create a sustainable runway" in out.recommendations[0]


def test_break_even_beyond_horizon_is_infeasible() -> None:
    out = _target(horizon_months=1)

    assert out.verdict == VERDICT_INFEASIBLE
    assert out.constraint == "BREAK_EVEN_HORIZON"
    assert out.minimum_starting_cash is None
    assert out.target is None
    assert "does not reach monthly break-even" in out.recommendations[0]


def test_metadata_and_low_signal_warning() -> None:
    out = build_runway_funding_target(
        _results(),
        simulation_id=7,
        project_id=3,
        signal_quality=0.42,
    )

    assert out.simulation_id == 7
    assert out.project_id == 3
    assert out.weighted_conversion_rate == pytest.approx(0.05)
    assert out.meta["model"] == "runway_funding_target_v2"
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

    return sim_mod.get_runway_funding_target(
        simulation_id=1,
        planned_starting_cash=500,
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


def test_route_is_registered_and_returns_funding_target() -> None:
    from app.api.v1 import simulations as sim_mod

    paths = {route.path: route.methods for route in sim_mod.router.routes}
    path = "/simulations/{simulation_id}/runway-funding-target"
    assert path in paths
    assert "GET" in (paths[path] or set())

    out = _call_route()
    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.verdict == VERDICT_FUNDING_GAP
    assert out.minimum_starting_cash == pytest.approx(1_000)
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
    private_error = "Provider request failed at postgres://founder:secret@internal-db/thecee"

    with pytest.raises(HTTPException) as exc:
        _call_route(
            session=_FakeSession(_FakeSimulation(status="FAILED", error_message=private_error))
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == ("Simulation failed; runway funding analysis is unavailable.")
    assert private_error not in exc.value.detail
