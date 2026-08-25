"""Tests for the per-project adoption milestones helper.

The helper is pure-Python so it can be exercised without
a DB.
"""
from __future__ import annotations


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import adoption_milestones

    assert set(adoption_milestones.__all__) == {
        "STANDARD_MILESTONES",
        "MIN_ASSUMPTIONS_FOR_EXTRACTED",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "build_adoption_milestones",
    }


def test_default_empty_zero_progress() -> None:
    from app.simulation.adoption_milestones import (
        build_adoption_milestones,
    )

    out = build_adoption_milestones()
    assert out["milestone_count"] == 7
    assert out["completed_count"] == 0
    assert out["progress_pct"] == 0


def test_full_progress_when_all_completed() -> None:
    from app.simulation.adoption_milestones import (
        build_adoption_milestones,
    )

    out = build_adoption_milestones(
        brief_completed=True,
        assumption_count=5,
        simulation_count=2,
        decision_count=3,
        outcome_count=1,
        premortem_present=True,
        interventions_present=True,
    )
    assert out["completed_count"] == 7
    assert out["progress_pct"] == 100
    assert all(out["milestones"].values())


def test_partial_progress_calculation() -> None:
    from app.simulation.adoption_milestones import (
        build_adoption_milestones,
    )

    out = build_adoption_milestones(
        brief_completed=True,
        assumption_count=5,
    )
    # 2 of 7 milestones complete.
    assert out["completed_count"] == 2
    assert out["progress_pct"] == round(200 / 7)


def test_assumptions_threshold_exactly_at_minimum() -> None:
    """assumption_count == MIN must count as extracted."""
    from app.simulation.adoption_milestones import (
        MIN_ASSUMPTIONS_FOR_EXTRACTED,
        build_adoption_milestones,
    )

    out = build_adoption_milestones(
        assumption_count=MIN_ASSUMPTIONS_FOR_EXTRACTED,
    )
    assert out["milestones"]["assumptions_extracted"] is True


def test_assumptions_below_threshold_not_extracted() -> None:
    from app.simulation.adoption_milestones import (
        MIN_ASSUMPTIONS_FOR_EXTRACTED,
        build_adoption_milestones,
    )

    out = build_adoption_milestones(
        assumption_count=MIN_ASSUMPTIONS_FOR_EXTRACTED - 1,
    )
    assert out["milestones"]["assumptions_extracted"] is False


def test_milestone_order_preserved() -> None:
    from app.simulation.adoption_milestones import (
        STANDARD_MILESTONES,
        build_adoption_milestones,
    )

    out = build_adoption_milestones()
    assert out["milestone_order"] == list(STANDARD_MILESTONES)


def test_next_milestone_signal() -> None:
    from app.simulation.adoption_milestones import (
        build_adoption_milestones,
    )

    out = build_adoption_milestones(brief_completed=True)
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "next_milestone"
    )
    # brief_completed is the first milestone; after
    # completing it, the next is assumptions_extracted.
    assert sig["value"] == "assumptions_extracted"


def test_no_next_milestone_when_all_complete() -> None:
    from app.simulation.adoption_milestones import (
        build_adoption_milestones,
    )

    out = build_adoption_milestones(
        brief_completed=True,
        assumption_count=5,
        simulation_count=2,
        decision_count=1,
        outcome_count=1,
        premortem_present=True,
        interventions_present=True,
    )
    labels = {s["label"] for s in out["key_signals"]}
    assert "next_milestone" not in labels


def test_narrative_early_stage_message() -> None:
    from app.simulation.adoption_milestones import (
        build_adoption_milestones,
    )

    # 1 of 7 milestones - early stage.
    out = build_adoption_milestones(brief_completed=True)
    assert "early" in out["narrative"].lower()


def test_narrative_complete_message() -> None:
    from app.simulation.adoption_milestones import (
        build_adoption_milestones,
    )

    out = build_adoption_milestones(
        brief_completed=True,
        assumption_count=5,
        simulation_count=2,
        decision_count=1,
        outcome_count=1,
        premortem_present=True,
        interventions_present=True,
    )
    assert "fully-instrumented" in out["narrative"].lower()


def test_schema_round_trip() -> None:
    from app.schemas.project import AdoptionMilestonesOut
    from app.simulation.adoption_milestones import (
        build_adoption_milestones,
    )

    payload = build_adoption_milestones(
        brief_completed=True, assumption_count=5,
    )
    out = AdoptionMilestonesOut(**payload)
    assert out.completed_count == 2
    assert out.milestones["brief_completed"] is True
    assert out.milestones["first_sim_run"] is False
