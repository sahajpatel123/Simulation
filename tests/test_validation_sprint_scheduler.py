"""Tests for the budget-constrained validation sprint scheduler.

The experiment planner assumes an unconstrained founder; the scheduler
re-fits the plan to an explicit calendar (``max_days`` of sequential run
time) and wallet (``budget_tier`` ceiling). These tests pin the greedy
first-fit selection, deferral reasons, day sequencing, and coverage math.
"""
from __future__ import annotations

import sys
import types

import pytest

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.schemas.validation_roi import (
    AssumptionValidationRoi,
    ValidationRoiOut,
    ValidationRoiSummary,
)
from app.simulation.validation_experiment_planner import (
    build_validation_experiment_plan,
)
from app.simulation.validation_sprint_scheduler import (
    COST_RANK,
    schedule_validation_sprint,
)


def _row(
    text: str,
    *,
    category: str,
    roi: float = 0.40,
) -> AssumptionValidationRoi:
    return AssumptionValidationRoi(
        assumption_text=text,
        category=category,
        roi_tier="VALIDATE_FIRST",
        validation_roi=roi,
        confidence_tier="ASPIRATIONAL",
        expected_conversion_swing=0.25,
    )


def _plan(rows: list[AssumptionValidationRoi]):
    return build_validation_experiment_plan(
        ValidationRoiOut(
            simulation_id=1,
            project_id=2,
            status="COMPLETED",
            baseline_conversion=0.05,
            signal_quality=0.62,
            summary=ValidationRoiSummary(total_assumptions=len(rows)),
            assumptions=rows,
        )
    )


# Pricing -> WTP survey (FREE, 7d); Demand -> landing page (LOW, 14d);
# Acquisition -> paid test (MEDIUM, 14d); Competition -> desk research
# (FREE, 5d).
def _four_row_plan():
    return _plan(
        [
            _row("Users will pay ₹999 monthly", category="Pricing", roi=0.50),
            _row("Ads are a cheap acquisition channel", category="Acquisition", roi=0.42),
            _row("Demand exists in tier-2 cities", category="Demand", roi=0.35),
            _row("Competitors price higher", category="Competition", roi=0.30),
        ]
    )


def test_unknown_budget_tier_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unknown cost tier"):
        schedule_validation_sprint(_plan([]), budget_tier="LUXURY")  # type: ignore[arg-type]


def test_cost_rank_ordering() -> None:
    assert COST_RANK == {"FREE": 0, "LOW": 1, "MEDIUM": 2}


def test_generous_envelope_schedules_everything() -> None:
    plan = _four_row_plan()

    out = schedule_validation_sprint(plan, max_days=90, budget_tier="MEDIUM")

    assert out.summary.planned_count == 4
    assert out.summary.scheduled_count == 4
    assert out.summary.deferred_count == 0
    assert out.deferred == []
    # Sequential days: 7 + 14 + 14 + 5 = 40.
    assert out.summary.days_used == 40
    assert out.summary.days_remaining == 50
    assert out.summary.coverage_retained == pytest.approx(1.0)
    assert out.narrative.endswith("Everything planned made the cut.")


def test_experiments_sequence_back_to_back() -> None:
    out = schedule_validation_sprint(_four_row_plan(), max_days=90, budget_tier="MEDIUM")

    days = [(e.scheduled_day, e.finishes_by_day) for e in out.experiments]
    assert days[0][0] == 1
    for (_, prev_end), (next_start, _) in zip(days, days[1:]):
        assert next_start == prev_end + 1


def test_low_budget_defers_medium_cost_with_reason() -> None:
    out = schedule_validation_sprint(_four_row_plan(), max_days=90, budget_tier="LOW")

    deferred_methods = [d.method_label for d in out.deferred]
    # Only the paid-acquisition test is MEDIUM cost.
    assert deferred_methods == ["Paid acquisition test"]
    reason = out.deferred[0].reason
    assert "cost tier medium exceeds the low budget ceiling" in reason
    assert out.summary.medium_cost_count == 0
    assert out.summary.scheduled_count == 3


def test_day_budget_defers_non_fitting_experiment_with_reason() -> None:
    # 20 sequential days: WTP survey (7d) fits, paid test is above the LOW
    # ceiling anyway, landing-page test (14d) does not fit in the remaining
    # 13, desk research (5d) still fits.
    out = schedule_validation_sprint(_four_row_plan(), max_days=20, budget_tier="LOW")

    scheduled_texts = [e.assumption_text for e in out.experiments]
    assert scheduled_texts == [
        "Users will pay ₹999 monthly",
        "Competitors price higher",
    ]
    assert out.summary.days_used == 12
    assert out.summary.days_remaining == 8

    reasons = {d.method_label: d.reason for d in out.deferred}
    assert "needs 14 days but only 13 remain in the 20-day sprint" in (
        reasons["Landing-page smoke test"]
    )
    assert "cost tier medium exceeds the low budget ceiling" in (
        reasons["Paid acquisition test"]
    )
    # Deferred rows keep their ROI so founders can see what was lost.
    by_label = {d.method_label: d.validation_roi for d in out.deferred}
    assert by_label["Landing-page smoke test"] == pytest.approx(0.35)


def test_coverage_retained_math() -> None:
    out = schedule_validation_sprint(_four_row_plan(), max_days=20, budget_tier="LOW")

    kept = 0.50 + 0.30
    total = 0.50 + 0.42 + 0.35 + 0.30
    assert out.summary.coverage_retained == pytest.approx(kept / total)


def test_free_only_ceiling_keeps_only_free_tiers() -> None:
    out = schedule_validation_sprint(_four_row_plan(), max_days=90, budget_tier="FREE")

    assert all(e.cost_tier == "FREE" for e in out.experiments)
    assert out.summary.free_count == 2
    assert out.summary.low_cost_count == 0
    deferred_labels = sorted(d.cost_tier for d in out.deferred)
    assert deferred_labels == ["LOW", "MEDIUM"]


def test_empty_plan_yields_empty_schedule() -> None:
    out = schedule_validation_sprint(_plan([]), max_days=14, budget_tier="LOW")

    assert out.experiments == []
    assert out.deferred == []
    assert out.summary.coverage_retained is None
    assert "nothing to fit into a sprint window" in out.narrative


# ---------------------------------------------------------------------------
# Parallel tracks
# ---------------------------------------------------------------------------


def test_parallel_tracks_overlap_experiments() -> None:
    # Sequential: WTP (7d) then desk research (5d) = 12 days used.
    # Two tracks: they overlap, so the sprint ends when WTP does — day 7.
    two_free_plan = _plan(
        [
            _row("Users will pay ₹999 monthly", category="Pricing", roi=0.50),
            _row("Competitors price higher", category="Competition", roi=0.30),
        ]
    )
    out = schedule_validation_sprint(
        two_free_plan, max_days=90, budget_tier="MEDIUM", max_parallel=2
    )

    wtp = next(e for e in out.experiments if e.method_label == "Willingness-to-pay survey")
    desk = next(e for e in out.experiments if e.method_label == "Competitive desk research")
    assert (wtp.scheduled_day, wtp.finishes_by_day) == (1, 7)
    assert desk.scheduled_day == 1  # starts on the second track immediately
    assert out.summary.days_used == 7
    assert out.summary.days_remaining == 83
    assert out.summary.max_parallel == 2


def test_parallel_tracks_fill_earliest_finishing_lane() -> None:
    # Two tracks, all four experiments fit. ROI order drives placement and
    # each experiment takes the track that finishes it earliest:
    # WTP (7d) -> track 1; paid (14d) -> track 2; landing (14d) -> track 1
    # (free day 7 beats track 2's day 14); desk (5d) -> track 2.
    out = schedule_validation_sprint(
        _four_row_plan(), max_days=90, budget_tier="MEDIUM", max_parallel=2
    )

    spans = {
        e.method_label: (e.scheduled_day, e.finishes_by_day)
        for e in out.experiments
    }
    assert spans["Willingness-to-pay survey"] == (1, 7)
    assert spans["Paid acquisition test"] == (1, 14)
    assert spans["Landing-page smoke test"] == (8, 21)
    assert spans["Competitive desk research"] == (15, 19)
    # The sprint ends when the last track does — day 21, not 40.
    assert out.summary.days_used == 21
    assert out.summary.days_remaining == 69


def test_parallel_tracks_do_not_resurrect_blocked_experiments() -> None:
    # A MEDIUM-cost experiment stays deferred under a LOW ceiling even with
    # two tracks available.
    out = schedule_validation_sprint(
        _four_row_plan(), max_days=90, budget_tier="LOW", max_parallel=3
    )

    assert [d.method_label for d in out.deferred] == ["Paid acquisition test"]
    assert out.summary.scheduled_count == 3


def test_single_track_matches_sequential_behavior() -> None:
    # max_parallel=1 must reproduce the original sequential schedule exactly.
    sequential = schedule_validation_sprint(_four_row_plan(), max_days=20)
    explicit = schedule_validation_sprint(_four_row_plan(), max_days=20, max_parallel=1)

    assert [(e.scheduled_day, e.finishes_by_day) for e in explicit.experiments] == [
        (e.scheduled_day, e.finishes_by_day) for e in sequential.experiments
    ]
    assert explicit.summary.days_used == 12


def test_narrative_names_parallel_tracks() -> None:
    out = schedule_validation_sprint(
        _four_row_plan(), max_days=30, budget_tier="MEDIUM", max_parallel=2
    )

    assert "on 2 parallel tracks" in out.narrative


def test_all_cut_narrative_names_both_knobs() -> None:
    out = schedule_validation_sprint(_four_row_plan(), max_days=3, budget_tier="FREE")

    assert out.experiments == []
    assert out.summary.deferred_count == 4
    assert "Raise the day budget or the cost ceiling" in out.narrative


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


def test_schedule_route_registered() -> None:
    from app.api.v1 import simulations as sim_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in sim_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    path = "/simulations/{simulation_id}/validation-experiment-plan/schedule"
    assert "GET" in methods_by_path.get(path, set())


def test_schedule_endpoint_round_trip(monkeypatch) -> None:
    from app.api.v1 import simulations as sim_mod

    captured: dict = {}

    def _fake_roi(**kwargs):
        captured.update(kwargs)
        return ValidationRoiOut(
            simulation_id=7,
            project_id=8,
            summary=ValidationRoiSummary(total_assumptions=1),
            assumptions=[
                _row("Users will pay ₹999 monthly", category="Pricing", roi=0.5)
            ],
        )

    monkeypatch.setattr(sim_mod, "get_validation_roi", _fake_roi)

    out = sim_mod.get_validation_experiment_schedule(
        simulation_id=7,
        max_days=10,
        budget_tier="FREE",
        max_parallel=1,
        db=None,  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )

    assert captured["simulation_id"] == 7
    assert out.simulation_id == 7
    assert out.project_id == 8
    assert out.summary.max_days == 10
    assert out.summary.budget_tier == "FREE"
    assert out.summary.scheduled_count == 1  # WTP survey is FREE, 7d ≤ 10
