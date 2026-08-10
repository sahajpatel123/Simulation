"""
Tests for the first-customer trajectory digest (helper + route).

The helper is pure-Python, mirroring ``market_sizing``, so it can be
exercised without a database. The route is smoke-tested via the
route-registration / direct-call pattern used across this suite.
"""
from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest
from fastapi import HTTPException

from app.simulation.first_customers import (
    CONVERSION_BENCHMARK,
    DEFAULT_MONTHLY_VISITORS,
    MAX_MONTHLY_VISITORS,
    MIN_MONTHLY_VISITORS,
    SIGNAL_CRITICAL,
    SIGNAL_OK,
    SIGNAL_WATCH,
    build_first_customers,
)

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def _results(
    *,
    cr: float = 0.05,
    breakdown: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "population_weighted_conversion": cr,
        "conversion_rate": cr,
        "cluster_breakdown": breakdown or {
            "a": 0.05,
            "b": 0.05,
        },
    }


def _signals_by_key(out: dict) -> dict[str, dict]:
    return {s["key"]: s for s in out["signals"]}


def _milestones_by_count(out: dict) -> dict[int, dict]:
    return {m["milestone"]: m for m in out["milestones"]}


# ---------------------------------------------------------------------------
# Public surface + purity
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import first_customers

    assert set(first_customers.__all__) == {
        "CONVERSION_BENCHMARK",
        "CONVERSION_WATCH_THRESHOLD",
        "DEFAULT_MONTHLY_VISITORS",
        "MAX_MONTHLY_VISITORS",
        "MILESTONES",
        "MIN_MONTHLY_VISITORS",
        "SIGNAL_CRITICAL",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "TOP_SEGMENTS_LIMIT",
        "WEEKS_PER_MONTH",
        "build_first_customers",
    }


def test_helper_is_pure() -> None:
    import inspect

    from app.simulation import first_customers

    source = inspect.getsource(first_customers)
    forbidden = ("sqlalchemy", "SessionLocal", "get_db")
    for token in forbidden:
        assert token.lower() not in source.lower(), (
            f"first_customers.py must not depend on {token}"
        )


# ---------------------------------------------------------------------------
# Empty / malformed input
# ---------------------------------------------------------------------------


def test_empty_results_yield_zero_state() -> None:
    out = build_first_customers(None, simulation_id=1, project_id=2)
    assert out["simulation_id"] == 1
    assert out["project_id"] == 2
    assert out["weighted_conversion_rate"] == 0.0
    assert out["monthly_customers"] == 0.0
    assert all(
        m["months"] is None and m["visitors_needed"] is None
        for m in out["milestones"]
    )
    assert all(p["customers"] == 0 for p in out["adoption_curve"])
    assert out["top_segments"] == []
    assert out["signals"]
    assert out["narrative"]


def test_json_string_and_garbage_inputs() -> None:
    ok = build_first_customers(json.dumps(_results(cr=0.05)))
    assert ok["monthly_customers"] == pytest.approx(50.0)
    bad = build_first_customers("{nope")
    assert bad["weighted_conversion_rate"] == 0.0
    assert bad["signals"]
    list_bad = build_first_customers([1, 2, 3])
    assert list_bad["weighted_conversion_rate"] == 0.0


def test_non_finite_conversion_degrades_to_zero() -> None:
    out = build_first_customers(_results(cr=float("nan")))
    assert out["weighted_conversion_rate"] == 0.0
    assert out["monthly_customers"] == 0.0


# ---------------------------------------------------------------------------
# Milestone math
# ---------------------------------------------------------------------------


def test_milestone_timing_and_visitor_requirements() -> None:
    out = build_first_customers(
        _results(cr=0.05),
        monthly_visitors=1000,
    )
    assert out["weighted_conversion_rate"] == pytest.approx(0.05)
    assert out["monthly_customers"] == pytest.approx(50.0)

    milestones = _milestones_by_count(out)
    assert milestones[10]["months"] == pytest.approx(0.2)
    assert milestones[10]["weeks"] == pytest.approx(0.9)
    assert milestones[10]["visitors_needed"] == 200
    assert milestones[100]["months"] == pytest.approx(2.0)
    assert milestones[100]["visitors_needed"] == 2000
    assert milestones[1000]["months"] == pytest.approx(20.0)
    assert milestones[1000]["visitors_needed"] == 20_000
    assert milestones[10]["display"]


def test_zero_conversion_leaves_timing_blank() -> None:
    out = build_first_customers(_results(cr=0.0), monthly_visitors=5000)
    for m in out["milestones"]:
        assert m["months"] is None
        assert m["weeks"] is None
        assert m["visitors_needed"] is None
        assert m["display"] == ""


def test_adoption_curve_is_linear_cumulative() -> None:
    out = build_first_customers(
        _results(cr=0.03),
        monthly_visitors=2000,
    )
    # 2000 x 3% = 60 customers/month.
    by_month = {p["month"]: p["customers"] for p in out["adoption_curve"]}
    assert by_month == {1: 60, 3: 180, 6: 360, 12: 720}


def test_milestone_visitors_needed_rounds_up() -> None:
    out = build_first_customers(_results(cr=0.03))
    milestones = _milestones_by_count(out)
    # 10 / 0.03 = 333.33 -> 334.
    assert milestones[10]["visitors_needed"] == 334
    assert milestones[100]["visitors_needed"] == 3334


# ---------------------------------------------------------------------------
# First-wave segments
# ---------------------------------------------------------------------------


def test_segments_ranked_by_weighted_conversion() -> None:
    registry = {
        "big": {"name": "Big Cluster", "population_weight": 0.9},
        "small": {"name": "Small Cluster", "population_weight": 0.1},
    }
    out = build_first_customers(
        _results(
            cr=0.05,
            breakdown={"big": 0.04, "small": 0.10},
        ),
        cluster_registry=registry,
    )
    top = out["top_segments"]
    assert [s["cluster_id"] for s in top] == ["big", "small"]
    assert top[0]["cluster_name"] == "Big Cluster"
    assert top[0]["population_weight"] == 0.9
    assert top[0]["conversion_rate"] == 0.04
    assert top[0]["first_adopter_share"] == pytest.approx(0.782608, abs=1e-5)


def test_segments_skip_zero_conversion_clusters() -> None:
    out = build_first_customers(
        _results(
            cr=0.05,
            breakdown={"alive": 0.05, "dead": 0.0},
        ),
    )
    assert [s["cluster_id"] for s in out["top_segments"]] == ["alive"]


def test_uniform_weight_fallback_without_registry() -> None:
    out = build_first_customers(
        _results(cr=0.05, breakdown={"a": 0.05, "b": 0.05}),
    )
    assert len(out["top_segments"]) == 2
    shares = sum(s["first_adopter_share"] for s in out["top_segments"])
    assert shares == pytest.approx(1.0)


def test_no_breakdown_warns_but_timeline_survives() -> None:
    out = build_first_customers(
        {"population_weighted_conversion": 0.04},
    )
    assert out["monthly_customers"] == pytest.approx(40.0)
    assert out["top_segments"] == []
    assert (
        _signals_by_key(out)["cluster_breakdown"]["level"]
        == SIGNAL_WATCH
    )


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


def test_conversion_signal_levels() -> None:
    critical = build_first_customers(_results(cr=0.01))
    assert (
        _signals_by_key(critical)["conversion"]["level"]
        == SIGNAL_CRITICAL
    )

    watch = build_first_customers(_results(cr=0.03))
    assert (
        _signals_by_key(watch)["conversion"]["level"]
        == SIGNAL_WATCH
    )

    ok = build_first_customers(_results(cr=0.06))
    assert _signals_by_key(ok)["conversion"]["level"] == SIGNAL_OK


def test_trajectory_signal_levels() -> None:
    fast = build_first_customers(
        _results(cr=0.05),
        monthly_visitors=1000,  # 50/month -> first 10 within a month
    )
    assert (
        _signals_by_key(fast)["trajectory"]["level"]
        == SIGNAL_OK
    )

    slow = build_first_customers(
        _results(cr=0.003),
        monthly_visitors=1000,  # 3/month -> first 10 in ~3.3 months
    )
    assert (
        _signals_by_key(slow)["trajectory"]["level"]
        == SIGNAL_WATCH
    )

    stalled = build_first_customers(
        _results(cr=0.0005),
        monthly_visitors=1000,  # 0.5/month -> 20 months to first 10
    )
    assert (
        _signals_by_key(stalled)["trajectory"]["level"]
        == SIGNAL_CRITICAL
    )

    no_data = build_first_customers(_results(cr=0.0))
    assert (
        _signals_by_key(no_data)["trajectory"]["level"]
        == SIGNAL_CRITICAL
    )


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------


def test_visitor_input_clamping() -> None:
    out = build_first_customers(_results(cr=0.05), monthly_visitors=0)
    assert out["monthly_visitors"] == MIN_MONTHLY_VISITORS
    assert out["monthly_customers"] == pytest.approx(0.05)

    big = build_first_customers(_results(cr=0.05), monthly_visitors=10**12)
    assert big["monthly_visitors"] == MAX_MONTHLY_VISITORS
    assert big["monthly_customers"] == pytest.approx(500_000.0)


def test_conversion_source_fallbacks() -> None:
    mean = build_first_customers(
        {"mean_conversion_rate": 0.04},
        monthly_visitors=1000,
    )
    assert mean["weighted_conversion_rate"] == pytest.approx(0.04)
    assert mean["meta"]["conversion_source"] == "mean_conversion_rate"

    legacy = build_first_customers(
        {"conversion_rate": 0.03},
        monthly_visitors=1000,
    )
    assert legacy["weighted_conversion_rate"] == pytest.approx(0.03)
    assert legacy["meta"]["conversion_source"] == "conversion_rate"

    funnel = build_first_customers(
        {"raw_funnel": {"conversion_rate": 0.02}},
        monthly_visitors=1000,
    )
    assert funnel["weighted_conversion_rate"] == pytest.approx(0.02)
    assert funnel["meta"]["conversion_source"] == "raw_funnel"


def test_defaults_are_sane() -> None:
    out = build_first_customers(_results(cr=0.05))
    assert out["monthly_visitors"] == DEFAULT_MONTHLY_VISITORS
    assert out["monthly_customers"] == pytest.approx(50.0)
    assert CONVERSION_BENCHMARK == 0.05


def test_signal_quality_forwarded_into_meta() -> None:
    out = build_first_customers(
        _results(cr=0.05),
        signal_quality=0.8123,
    )
    assert out["meta"]["signal_quality"] == pytest.approx(0.8123)
    none_out = build_first_customers(_results(cr=0.05))
    assert none_out["meta"]["signal_quality"] is None


def test_schema_round_trip() -> None:
    from app.schemas.first_customers import FirstCustomersOut

    payload = build_first_customers(
        _results(cr=0.05),
        simulation_id=7,
        project_id=3,
        monthly_visitors=2000,
    )
    out = FirstCustomersOut(**payload)
    assert out.simulation_id == 7
    assert out.project_id == 3
    assert out.monthly_visitors == 2000
    assert len(out.milestones) == 3
    assert len(out.adoption_curve) == 4


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


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
        self.status = status
        self.error_message = error_message
        self.signal_quality = 0.62
        self.results_json = (
            results
            if results is not None
            else {
                "population_weighted_conversion": 0.04,
                "cluster_breakdown": {
                    "metro_power_professional": 0.06,
                    "tier3_first_time_app_user": 0.03,
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
    def __init__(self, sim: object | None = None) -> None:
        self.sim = sim

    def query(self, *args, **kwargs):
        return _FakeQuery([self.sim] if self.sim is not None else [])


def _call_route(
    simulation_id: int = 1,
    monthly_visitors: int = 1000,
    session: _FakeSession | None = None,
):
    from app.api.v1 import simulations as sim_mod

    db = session or _FakeSession(_FakeSimulation(simulation_id))
    return sim_mod.get_first_customers(
        simulation_id=simulation_id,
        monthly_visitors=monthly_visitors,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


def test_route_registered() -> None:
    from app.api.v1 import simulations as sim_mod

    paths = {r.path for r in sim_mod.router.routes}
    assert "/simulations/{simulation_id}/first-customers" in paths
    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET"
        in methods_by_path["/simulations/{simulation_id}/first-customers"]
    )


def test_route_returns_first_customers() -> None:
    out = _call_route(monthly_visitors=2000)
    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.monthly_visitors == 2000
    assert out.weighted_conversion_rate == pytest.approx(0.04)
    assert out.monthly_customers == pytest.approx(80.0)
    assert len(out.milestones) == 3
    assert out.top_segments


def test_route_rejects_non_completed_simulation() -> None:
    session = _FakeSession(_FakeSimulation(status="PENDING"))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 409


def test_route_rejects_failed_simulation() -> None:
    session = _FakeSession(
        _FakeSimulation(status="FAILED", error_message="boom")
    )
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422
    assert "boom" in str(exc.value.detail)


def test_route_rejects_empty_results() -> None:
    session = _FakeSession(_FakeSimulation(results={}))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422


def test_route_404_when_not_owned() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_route(session=_FakeSession(None))
    assert exc.value.status_code == 404
