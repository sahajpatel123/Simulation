"""Tests for the per-user runs-this-month helper."""
from __future__ import annotations


def test_public_allowlist_matches_callers():
    from app.simulation import runs_this_month
    assert set(runs_this_month.__all__) == {
        "SIGNAL_OK", "SIGNAL_WATCH", "SIGNAL_CRITICAL",
        "build_runs_this_month",
    }


def test_default_zero_state():
    from app.simulation.runs_this_month import (
        build_runs_this_month,
    )
    out = build_runs_this_month()
    assert out["runs_this_month"] == 0
    assert out["monthly_cap"] == 0
    assert out["remaining"] == 0
    assert out["tier"] == "FREE"


def test_remaining_clamps_at_zero():
    from app.simulation.runs_this_month import (
        build_runs_this_month,
    )
    out = build_runs_this_month(
        runs_this_month=10,
        monthly_cap=2,
    )
    # Used exceeds cap → remaining clamps at 0 (never
    # negative).
    assert out["remaining"] == 0


def test_severity_ok_below_80_percent():
    from app.simulation.runs_this_month import (
        SIGNAL_OK,
        build_runs_this_month,
    )
    out = build_runs_this_month(runs_this_month=3, monthly_cap=10)
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_OK


def test_severity_watch_at_80_percent():
    from app.simulation.runs_this_month import (
        SIGNAL_WATCH,
        build_runs_this_month,
    )
    out = build_runs_this_month(runs_this_month=8, monthly_cap=10)
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_WATCH


def test_severity_critical_at_or_above_cap():
    from app.simulation.runs_this_month import (
        SIGNAL_CRITICAL,
        build_runs_this_month,
    )
    out = build_runs_this_month(
        runs_this_month=10,
        monthly_cap=10,
    )
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_CRITICAL


def test_severity_watch_when_cap_zero():
    from app.simulation.runs_this_month import (
        SIGNAL_WATCH,
        build_runs_this_month,
    )
    out = build_runs_this_month(runs_this_month=5, monthly_cap=0)
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_WATCH


def test_narrative_mentions_counts():
    from app.simulation.runs_this_month import (
        build_runs_this_month,
    )
    out = build_runs_this_month(runs_this_month=3, monthly_cap=10)
    n = out["narrative"]
    assert "3" in n
    assert "10" in n
    assert "7" in n  # remaining


def test_narrative_at_cap_message():
    from app.simulation.runs_this_month import (
        build_runs_this_month,
    )
    out = build_runs_this_month(
        runs_this_month=10,
        monthly_cap=10,
    )
    assert "exhausted" in out["narrative"].lower()


def test_narrative_approaching_cap_message():
    from app.simulation.runs_this_month import (
        build_runs_this_month,
    )
    out = build_runs_this_month(runs_this_month=9, monthly_cap=10)
    assert "approaching" in out["narrative"].lower()


def test_narrative_no_cap_message():
    from app.simulation.runs_this_month import (
        build_runs_this_month,
    )
    out = build_runs_this_month(runs_this_month=5, monthly_cap=0)
    assert "no monthly cap" in out["narrative"].lower()


def test_tier_passthrough():
    from app.simulation.runs_this_month import (
        build_runs_this_month,
    )
    out = build_runs_this_month(tier="ENTERPRISE")
    assert out["tier"] == "ENTERPRISE"


def test_schema_default_shape():
    from app.schemas.user import RunsThisMonthOut
    out = RunsThisMonthOut()
    assert out.runs_this_month == 0
    assert out.monthly_cap == 0
    assert out.remaining == 0
    assert out.tier == "FREE"
    assert out.key_signals == []


def test_schema_round_trip():
    from app.schemas.user import RunsThisMonthOut
    from app.simulation.runs_this_month import (
        build_runs_this_month,
    )
    payload = build_runs_this_month(
        runs_this_month=5,
        monthly_cap=50,
        tier="PRO",
    )
    out = RunsThisMonthOut(**payload)
    assert out.runs_this_month == 5
    assert out.monthly_cap == 50
    assert out.remaining == 45
    assert out.tier == "PRO"
