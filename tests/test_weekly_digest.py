"""Tests for the per-user weekly-digest helper.

The helper is pure-Python so it can be exercised without
a DB.
"""
from __future__ import annotations



def test_public_allowlist_matches_callers() -> None:
    from app.simulation import weekly_digest

    assert set(weekly_digest.__all__) == {
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_weekly_digest",
    }


def test_digest_quiet_week() -> None:
    from app.simulation.weekly_digest import build_weekly_digest

    out = build_weekly_digest()
    assert out["sim_count_week"] == 0
    assert "quiet" in out["narrative"].lower()


def test_digest_mentions_counts_when_active() -> None:
    from app.simulation.weekly_digest import build_weekly_digest

    out = build_weekly_digest(
        sim_count_week=3,
        decision_count_week=2,
        outcome_count_week=1,
    )
    assert "3 sim" in out["narrative"]
    assert "2 decision" in out["narrative"]
    assert "1 outcome" in out["narrative"]


def test_digest_completion_rate_when_high() -> None:
    from app.simulation.weekly_digest import build_weekly_digest

    out = build_weekly_digest(
        sim_count_week=10,
        completed_sim_count_week=9,
    )
    assert "90%" in out["narrative"]


def test_digest_no_completion_line_when_data_missing() -> None:
    """No completion-rate line if completed_sim_count
    isn't supplied."""
    from app.simulation.weekly_digest import build_weekly_digest

    out = build_weekly_digest(sim_count_week=2)
    assert "%" not in out["narrative"]


def test_digest_critical_escalates_severity() -> None:
    from app.simulation.weekly_digest import (
        SIGNAL_CRITICAL,
        build_weekly_digest,
    )

    out = build_weekly_digest(
        critical_failure_modes_total=5,
    )
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "critical_failure_modes_total"
    )
    assert sig["severity"] == SIGNAL_CRITICAL


def test_digest_quick_win_severity_scaling() -> None:
    from app.simulation.weekly_digest import (
        SIGNAL_OK,
        SIGNAL_WATCH,
        build_weekly_digest,
    )

    out1 = build_weekly_digest(quick_wins_total=1)
    sig = next(
        s for s in out1["key_signals"]
        if s["label"] == "quick_wins_total"
    )
    assert sig["severity"] == SIGNAL_WATCH

    out2 = build_weekly_digest(quick_wins_total=3)
    sig = next(
        s for s in out2["key_signals"]
        if s["label"] == "quick_wins_total"
    )
    assert sig["severity"] == SIGNAL_OK


def test_digest_mentions_critical_and_quick_win_when_both() -> None:
    from app.simulation.weekly_digest import build_weekly_digest

    out = build_weekly_digest(
        critical_failure_modes_total=2,
        quick_wins_total=3,
    )
    n = out["narrative"].lower()
    assert "critical" in n
    assert "quick" in n


def test_digest_calibration_passthrough() -> None:
    from app.simulation.weekly_digest import build_weekly_digest

    cal = {"overall_health": "WELL_CALIBRATED"}
    out = build_weekly_digest(calibration_health=cal)
    assert out["calibration_health"] == cal


def test_digest_calibration_none_when_omitted() -> None:
    from app.simulation.weekly_digest import build_weekly_digest

    out = build_weekly_digest()
    assert out["calibration_health"] == {}


def test_digest_schema_round_trip() -> None:
    from app.schemas.user import WeeklyDigestOut
    from app.simulation.weekly_digest import build_weekly_digest

    payload = build_weekly_digest(
        sim_count_week=2,
        decision_count_week=1,
        outcome_count_week=1,
    )
    out = WeeklyDigestOut(**payload)
    assert out.sim_count_week == 2
    assert out.decision_count_week == 1
    assert out.outcome_count_week == 1


def test_digest_schema_default_shape() -> None:
    from app.schemas.user import WeeklyDigestOut

    out = WeeklyDigestOut()
    assert out.sim_count_week == 0
    assert out.decision_count_week == 0
    assert out.outcome_count_week == 0
    assert out.calibration_health is None
    assert out.quick_wins_total == 0
    assert out.top_dropoff_stage is None


def test_digest_top_dropoff_stage_included_in_narrative_and_signals() -> None:
    from app.schemas.user import WeeklyDigestOut
    from app.simulation.weekly_digest import build_weekly_digest

    payload = build_weekly_digest(
        sim_count_week=5,
        top_dropoff_stage="CONSIDER_TO_DECIDE_DROPOFF",
    )
    assert payload["top_dropoff_stage"] == "CONSIDER_TO_DECIDE_DROPOFF"
    assert "CONSIDER_TO_DECIDE_DROPOFF" in payload["narrative"]
    assert any(s["label"] == "top_dropoff_stage" for s in payload["key_signals"])

    out = WeeklyDigestOut(**payload)
    assert out.top_dropoff_stage == "CONSIDER_TO_DECIDE_DROPOFF"


def test_digest_funnel_dropoff_rates_passed_through() -> None:
    from app.schemas.user import WeeklyDigestOut
    from app.simulation.weekly_digest import build_weekly_digest

    dropoff_rates = {
        "CONSIDER_TO_DECIDE_DROPOFF": 0.55,
        "BROWSE_TO_CONSIDER_DROPOFF": 0.42,
    }
    payload = build_weekly_digest(
        sim_count_week=5,
        top_dropoff_stage="CONSIDER_TO_DECIDE_DROPOFF",
        funnel_dropoff_rates=dropoff_rates,
    )
    assert payload["funnel_dropoff_rates"] == dropoff_rates
    assert payload["top_dropoff_stage"] == "CONSIDER_TO_DECIDE_DROPOFF"

    out = WeeklyDigestOut(**payload)
    assert out.funnel_dropoff_rates == dropoff_rates


def test_digest_funnel_dropoff_rates_default_empty() -> None:
    from app.schemas.user import WeeklyDigestOut
    from app.simulation.weekly_digest import build_weekly_digest

    payload = build_weekly_digest(sim_count_week=1)
    assert payload["funnel_dropoff_rates"] == {}

    out = WeeklyDigestOut(**payload)
    assert out.funnel_dropoff_rates == {}