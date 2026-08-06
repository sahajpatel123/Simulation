"""Tests for the launch-checklist read and route."""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from fastapi import HTTPException

from app.simulation.launch_checklist import build_launch_checklist


if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def _registry(count: int = 52) -> list[dict[str, Any]]:
    return [
        {
            "cluster_id": f"cluster_{i}",
            "name": f"Cluster {i}",
            "population_weight": 1.0 / count,
        }
        for i in range(count)
    ]


def _results(**overrides: Any) -> dict[str, Any]:
    payload = {
        "population_weighted_conversion": 0.04,
        "product_type_detected": "saas",
        "cluster_breakdown": {
            "metro_power_professional": 0.06,
            "tier3_first_time_app_user": 0.03,
        },
        "raw_funnel": {
            "ARRIVE": 1000,
            "BROWSE": 600,
            "CONSIDER": 300,
            "DECIDE": 120,
            "PURCHASE": 40,
        },
        "domain_findings": [
            {"id": "f1", "title": "Support burden", "severity": "MAJOR"}
        ],
    }
    payload.update(overrides)
    return payload


def _build(
    *,
    results: dict[str, Any] | None = None,
    signal_quality: float | None = 0.85,
    visible_assumptions: int | None = 4,
    cluster_registry: list[dict[str, Any]] | None = None,
) -> Any:
    return build_launch_checklist(
        results if results is not None else _results(),
        simulation_id=1,
        project_id=10,
        status="COMPLETED",
        signal_quality=signal_quality,
        visible_assumption_count=visible_assumptions,
        product_type="saas",
        cluster_registry=cluster_registry,
    )


def test_strong_run_is_ready() -> None:
    registry = _registry()
    out = _build(
        results=_results(
            cluster_breakdown={item["cluster_id"]: 1.0 / 52 for item in registry}
        ),
        cluster_registry=registry,
    )

    assert out.verdict == "READY"
    assert out.readiness_score >= 0.80
    assert out.summary.total_items >= 6
    assert out.summary.failed_items == 0
    assert out.meta["coverage"] == 1.0
    assert out.recommendations


def test_missing_assumptions_and_low_signal_need_work() -> None:
    out = _build(signal_quality=0.35, visible_assumptions=0)

    assert out.verdict == "NEEDS_WORK"
    assert out.readiness_score < 0.8
    assert any("Signal quality is low" in rec for rec in out.recommendations)
    assert any("Add assumptions" in rec for rec in out.recommendations)


def test_empty_results_fails() -> None:
    out = _build(results={})

    assert out.verdict == "NOT_READY"
    assert out.readiness_score == 0.0
    assert out.items[0].id == "results_present"
    assert out.items[0].status == "FAIL"


def test_missing_funnel_is_skipped_not_failed() -> None:
    out = _build(results=_results(raw_funnel=None))

    funnel = next(item for item in out.items if item.id == "funnel_sanity")
    assert funnel.status == "SKIP"
    assert funnel.weight == 0.0


def test_nan_or_inf_results_fail_hard() -> None:
    out = _build(results=_results(population_weighted_conversion=float("nan")))

    non_finite = next(item for item in out.items if item.id == "non_finite_free")
    assert non_finite.status == "FAIL"
    assert out.meta["non_finite_free"] is False
    assert any("NaN/Inf" in rec for rec in out.recommendations)


class _FakeSimulation:
    def __init__(
        self,
        *,
        status: str = "COMPLETED",
        results: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        self.id = 1
        self.project_id = 10
        self.environment_id = 5
        self.status = status
        self.error_message = error_message
        self.signal_quality = 0.85
        self.results_json = results if results is not None else _results()


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


class _FakeAssumption:
    def __init__(self, text: str) -> None:
        self.text = text
        self.sensitivity = "MEDIUM"
        self.impact_score = 5.0


class _FakeSession:
    def __init__(
        self,
        sim: object | None = None,
        assumptions: list | None = None,
    ) -> None:
        self.sim = sim
        self.assumptions = assumptions

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Simulation":
            return _FakeQuery([self.sim] if self.sim is not None else [])
        if name == "Assumption":
            return _FakeQuery(self.assumptions or [])
        return _FakeQuery([])


def _call_route(session: _FakeSession | None = None):
    from app.api.v1 import simulations as sim_mod

    db = session if session is not None else _FakeSession(_FakeSimulation())
    return sim_mod.get_launch_checklist(
        simulation_id=1,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


def test_route_returns_launch_checklist() -> None:
    out = _call_route(
        _FakeSession(_FakeSimulation(), assumptions=[_FakeAssumption("viral loop")])
    )

    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.verdict in {"READY", "NEEDS_WORK", "NOT_READY", "INSUFFICIENT_DATA"}
    assert out.visible_assumptions == 1


def test_route_rejects_non_completed_simulation() -> None:
    session = _FakeSession(_FakeSimulation(status="PENDING"))
    with pytest.raises(HTTPException) as exc:
        _call_route(session)
    assert exc.value.status_code == 409
