"""Tests for the run-vs-run simulation comparison.

``build_simulation_comparison`` diffs two completed runs' ``results_json``
payloads: headline conversion in percentage points, per-stage drop-off
changes matched on funnel-state name, and per-cluster conversion movers
sorted by absolute impact. Route-level tests pin ownership checks and the
status guards.
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

from app.simulation.simulation_compare import build_simulation_comparison


def _results(
    *,
    conv: float,
    revenue: float = 1200.0,
    confidence: float | None = 0.7,
    worst_stage: str = "DECIDE",
    stages: dict[str, float] | None = None,
    clusters: dict[str, float] | None = None,
) -> dict:
    return {
        "mean_conversion_rate": conv,
        "mean_revenue": revenue,
        "confidence_score": confidence,
        "worst_drop_off_stage": worst_stage,
        "stage_aggregations": [
            {"state": state, "mean_drop_off_rate": drop}
            for state, drop in (stages or {}).items()
        ],
        "cluster_breakdown": clusters or {},
    }


def _compare(current: dict, baseline: dict, **kwargs):
    return build_simulation_comparison(
        simulation_id=20,
        baseline_id=10,
        current_results=current,
        baseline_results=baseline,
        **kwargs,
    )


def test_headline_improvement_math() -> None:
    out = _compare(
        _results(conv=0.075),
        _results(conv=0.050),
        current_signal=0.81,
        baseline_signal=0.77,
    )

    h = out.headline
    assert h.conversion_before == pytest.approx(0.05)
    assert h.conversion_after == pytest.approx(0.075)
    assert h.conversion_delta_pp == pytest.approx(2.5)
    assert h.conversion_delta_pct == pytest.approx(0.5)
    assert h.verdict == "IMPROVED"
    assert h.signal_quality_after == pytest.approx(0.81)
    assert h.signal_quality_before == pytest.approx(0.77)


def test_flat_and_regression_verdicts() -> None:
    flat = _compare(_results(conv=0.0500), _results(conv=0.0500))
    assert flat.headline.verdict == "FLAT"
    assert flat.headline.conversion_delta_pct == pytest.approx(0.0)

    regressed = _compare(_results(conv=0.041), _results(conv=0.050))
    assert regressed.headline.verdict == "REGRESSED"

    noise = _compare(
        _results(conv=0.05005), _results(conv=0.05000)
    )
    assert noise.headline.verdict == "FLAT"


def test_zero_baseline_leaves_relative_delta_null() -> None:
    out = _compare(_results(conv=0.02), _results(conv=0.0))
    assert out.headline.conversion_delta_pct is None
    assert out.headline.verdict == "IMPROVED"


def test_worst_stage_change_flag() -> None:
    same = _compare(_results(conv=0.05, worst_stage="DECIDE"),
                    _results(conv=0.06, worst_stage="DECIDE"))
    assert same.headline.worst_stage_changed is False

    moved = _compare(_results(conv=0.05, worst_stage="BROWSE"),
                     _results(conv=0.06, worst_stage="DECIDE"))
    assert moved.headline.worst_stage_changed is True


def test_stage_deltas_union_states_and_match_by_name() -> None:
    out = _compare(
        _results(conv=0.06, stages={"ARRIVE": 0.13, "BROWSE": 0.38}),
        _results(conv=0.05, stages={"ARRIVE": 0.20, "CONSIDER": 0.44}),
    )

    by_state = {s.state: s for s in out.stage_deltas}
    assert set(by_state) == {"ARRIVE", "BROWSE", "CONSIDER"}
    # ARRIVE present in both: 13% - 20% = -7pp.
    assert by_state["ARRIVE"].drop_off_delta_pp == pytest.approx(-7.0)
    # New stage has no baseline value.
    assert by_state["BROWSE"].drop_off_before is None
    assert by_state["BROWSE"].drop_off_after == pytest.approx(0.38)
    # Vanished stage keeps its history.
    assert by_state["CONSIDER"].drop_off_before == pytest.approx(0.44)
    assert by_state["CONSIDER"].drop_off_after is None


def test_cluster_movers_sorted_by_impact_with_counts() -> None:
    out = _compare(
        _results(conv=0.06, clusters={
            "metro_power_professional": 0.10,
            "tier3_first_time_app_user": 0.02,
            "impulsive_trend_follower": 0.05,
        }),
        _results(conv=0.05, clusters={
            "metro_power_professional": 0.04,
            "tier3_first_time_app_user": 0.05,
            "low_literacy_student_passive": 0.01,
        }),
    )

    ids = [c.cluster_id for c in out.cluster_deltas]
    # Sorted by |delta| desc: metro +6pp, tier3 -3pp, impulsive +4pp, low -1pp.
    assert ids[0] == "metro_power_professional"
    assert ids[1] == "impulsive_trend_follower"
    assert ids[2] == "tier3_first_time_app_user"
    assert out.clusters_improved == 2
    assert out.clusters_worsened == 2
    mover = out.biggest_mover
    assert mover is not None and mover.cluster_id == "metro_power_professional"
    assert "+6" in out.narrative and "Biggest mover" in out.narrative


def test_missing_keys_degrade_gracefully() -> None:
    out = _compare({}, {})

    assert out.headline.conversion_before == 0.0
    assert out.stage_deltas == []
    assert out.cluster_deltas == []
    assert out.biggest_mover is None
    assert "predicted conversion moved 0.00% → 0.00%" in out.narrative


def test_narrative_mentions_weakest_stage_shift() -> None:
    out = _compare(
        _results(conv=0.06, worst_stage="BROWSE"),
        _results(conv=0.05, worst_stage="DECIDE"),
    )
    assert "Weakest stage shifted from 'DECIDE' to 'BROWSE'" in out.narrative


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


class _FakeQuery:
    def __init__(self, items: list) -> None:
        self.items = items
        self.filtered: list | None = None

    def join(self, *args, **kwargs):
        return self

    def filter(self, *criteria):
        # Resolve ``Simulation.id == <int>`` so the ownership helper can
        # fetch each run by its ID; other criteria are ignored.
        for c in criteria:
            left_name = getattr(getattr(c, "left", None), "name", "")
            right_value = getattr(getattr(c, "right", None), "value", None)
            if left_name == "id" and isinstance(right_value, int):
                self.filtered = [s for s in self.items if s.id == right_value]
        return self

    def first(self):
        pool = self.items if self.filtered is None else self.filtered
        return pool[0] if pool else None


class _FakeSession:
    def __init__(self, sims: list) -> None:
        self.sims = sims

    def query(self, model, *args, **kwargs):
        return _FakeQuery(list(self.sims))


class _FakeSim:
    def __init__(
        self,
        sim_id: int,
        *,
        status: str = "COMPLETED",
        results_json: dict | None = None,
        signal_quality: float | None = 0.8,
    ) -> None:
        self.id = sim_id
        self.project_id = 5
        self.status = status
        self.results_json = results_json if results_json is not None else {}
        self.signal_quality = signal_quality
        self.error_message = None


def _route(sims: list, *, simulation_id: int = 20, baseline_id: int = 10):
    from app.api.v1 import simulations as sim_mod

    return sim_mod.get_simulation_comparison(
        simulation_id=simulation_id,
        baseline_id=baseline_id,
        db=_FakeSession(sims),  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )


def _two_completed_sims() -> list:
    return [
        _FakeSim(10, results_json=_results(conv=0.050)),
        _FakeSim(20, results_json=_results(conv=0.075)),
    ]


def test_compare_route_registered() -> None:
    from app.api.v1 import simulations as sim_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in sim_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    path = "/simulations/{simulation_id}/compare/{baseline_id}"
    assert "GET" in methods_by_path.get(path, set())


def test_compare_route_happy_path() -> None:
    out = _route(_two_completed_sims())

    assert out.simulation_id == 20
    assert out.baseline_id == 10
    assert out.project_id == 5
    assert out.headline.verdict == "IMPROVED"


def test_compare_route_rejects_self_comparison() -> None:
    with pytest.raises(HTTPException) as exc:
        _route([_FakeSim(10)], simulation_id=10, baseline_id=10)
    assert exc.value.status_code == 400


def test_compare_route_requires_both_runs_completed() -> None:
    running = [
        _FakeSim(10),
        _FakeSim(20, status="RUNNING"),
    ]
    with pytest.raises(HTTPException) as exc:
        _route(running)
    assert exc.value.status_code == 409
    assert "compared simulation is RUNNING" in exc.value.detail


def test_compare_route_requires_nonempty_results() -> None:
    empty = [_FakeSim(10, results_json=None), _FakeSim(20, results_json=_results(conv=0.06))]
    with pytest.raises(HTTPException) as exc:
        _route(empty)
    assert exc.value.status_code == 422
    assert "baseline" in exc.value.detail


def test_compare_route_ownership_is_enforced() -> None:
    """The fake session returns no rows → helper raises 404."""
    with pytest.raises(HTTPException) as exc:
        _route([])
    assert exc.value.status_code == 404
