"""Tests for the per-user last-week-stats helper."""
from __future__ import annotations


def test_public_allowlist_matches_callers():
    from app.simulation import last_week_stats
    assert set(last_week_stats.__all__) == {
        "ACCELERATION_THRESHOLD",
        "SIGNAL_OK", "SIGNAL_WATCH", "SIGNAL_CRITICAL",
        "build_last_week_stats",
    }


def test_default_empty_state():
    from app.simulation.last_week_stats import (
        build_last_week_stats,
    )
    out = build_last_week_stats()
    assert out["this_week"] == {
        "sim_count": 0, "decision_count": 0, "outcome_count": 0,
    }
    assert out["last_week"] == {
        "sim_count": 0, "decision_count": 0, "outcome_count": 0,
    }
    assert out["verdict"] == "INSUFFICIENT_DATA"


def test_accelerating_when_50_percent_up():
    from app.simulation.last_week_stats import (
        build_last_week_stats,
    )
    out = build_last_week_stats(
        this_week_counts={"sim_count": 0, "decision_count": 0,
                         "outcome_count": 15},
        last_week_counts={"sim_count": 0, "decision_count": 0,
                          "outcome_count": 5},
    )
    # 15 vs 5 = 200% up, beyond 50% threshold.
    assert out["verdict"] == "ACCELERATING"


def test_slowing_when_50_percent_down():
    from app.simulation.last_week_stats import (
        build_last_week_stats,
    )
    out = build_last_week_stats(
        this_week_counts={"sim_count": 0, "decision_count": 0,
                         "outcome_count": 5},
        last_week_counts={"sim_count": 0, "decision_count": 0,
                          "outcome_count": 15},
    )
    # 5 vs 15 = 67% down, beyond 50% threshold.
    assert out["verdict"] == "SLOWING"


def test_steady_when_change_under_50_percent():
    from app.simulation.last_week_stats import (
        build_last_week_stats,
    )
    out = build_last_week_stats(
        this_week_counts={"sim_count": 0, "decision_count": 0,
                         "outcome_count": 10},
        last_week_counts={"sim_count": 0, "decision_count": 0,
                          "outcome_count": 12},
    )
    # 10 vs 12 = 17% down, below 50% threshold.
    assert out["verdict"] == "STEADY"


def test_accelerating_when_last_week_zero_and_this_week_positive():
    from app.simulation.last_week_stats import (
        build_last_week_stats,
    )
    out = build_last_week_stats(
        this_week_counts={"sim_count": 0, "decision_count": 0,
                         "outcome_count": 3},
        last_week_counts={"sim_count": 0, "decision_count": 0,
                          "outcome_count": 0},
    )
    assert out["verdict"] == "ACCELERATING"


def test_deltas_computed_correctly():
    from app.simulation.last_week_stats import (
        build_last_week_stats,
    )
    out = build_last_week_stats(
        this_week_counts={"sim_count": 5, "decision_count": 7,
                         "outcome_count": 9},
        last_week_counts={"sim_count": 2, "decision_count": 3,
                          "outcome_count": 4},
    )
    assert out["deltas"]["sim_count"] == 3
    assert out["deltas"]["decision_count"] == 4
    assert out["deltas"]["outcome_count"] == 5


def test_narrative_quiet_when_no_data():
    from app.simulation.last_week_stats import (
        build_last_week_stats,
    )
    out = build_last_week_stats()
    assert "not enough" in out["narrative"].lower()


def test_narrative_includes_deltas():
    from app.simulation.last_week_stats import (
        build_last_week_stats,
    )
    out = build_last_week_stats(
        this_week_counts={"sim_count": 0, "decision_count": 0,
                         "outcome_count": 10},
        last_week_counts={"sim_count": 0, "decision_count": 0,
                          "outcome_count": 5},
    )
    n = out["narrative"].lower()
    assert "up" in n
    assert "10" in n
    assert "5" in n


def test_severity_ok_when_accelerating():
    from app.simulation.last_week_stats import (
        SIGNAL_OK,
        build_last_week_stats,
    )
    out = build_last_week_stats(
        this_week_counts={"sim_count": 0, "decision_count": 0,
                         "outcome_count": 10},
        last_week_counts={"sim_count": 0, "decision_count": 0,
                          "outcome_count": 5},
    )
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_OK


def test_severity_critical_when_slowing():
    from app.simulation.last_week_stats import (
        SIGNAL_CRITICAL,
        build_last_week_stats,
    )
    out = build_last_week_stats(
        this_week_counts={"sim_count": 0, "decision_count": 0,
                         "outcome_count": 5},
        last_week_counts={"sim_count": 0, "decision_count": 0,
                          "outcome_count": 15},
    )
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_CRITICAL


def test_severity_watch_when_steady():
    from app.simulation.last_week_stats import (
        SIGNAL_WATCH,
        build_last_week_stats,
    )
    out = build_last_week_stats(
        this_week_counts={"sim_count": 0, "decision_count": 0,
                         "outcome_count": 10},
        last_week_counts={"sim_count": 0, "decision_count": 0,
                          "outcome_count": 12},
    )
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_WATCH


def test_schema_default_shape():
    from app.schemas.user import LastWeekStatsOut
    out = LastWeekStatsOut()
    assert out.this_week == {}
    assert out.last_week == {}
    assert out.deltas == {}
    assert out.verdict == "INSUFFICIENT_DATA"
    assert out.key_signals == []


def test_schema_round_trip():
    from app.schemas.user import LastWeekStatsOut
    from app.simulation.last_week_stats import (
        build_last_week_stats,
    )
    payload = build_last_week_stats(
        this_week_counts={"sim_count": 0, "decision_count": 0,
                         "outcome_count": 10},
        last_week_counts={"sim_count": 0, "decision_count": 0,
                          "outcome_count": 5},
    )
    out = LastWeekStatsOut(**payload)
    assert out.verdict == "ACCELERATING"
    assert out.deltas["outcome_count"] == 5
