"""Tests for the per-user quick-stats helper."""
from __future__ import annotations



def test_public_allowlist_matches_callers():
    from app.simulation import quick_stats
    assert set(quick_stats.__all__) == {
        "SIGNAL_OK", "SIGNAL_WATCH", "build_quick_stats",
    }


def test_default_zero_state():
    from app.simulation.quick_stats import build_quick_stats
    out = build_quick_stats()
    assert out["total_projects"] == 0
    assert out["total_simulations"] == 0
    assert out["total_decisions"] == 0
    assert out["total_outcomes"] == 0
    assert out["account_age_days"] == 0


def test_passes_through_counts():
    from app.simulation.quick_stats import build_quick_stats
    out = build_quick_stats(
        total_projects=3,
        total_simulations=10,
        total_decisions=4,
        total_outcomes=2,
        account_age_days=120,
    )
    assert out["total_projects"] == 3
    assert out["total_simulations"] == 10
    assert out["account_age_days"] == 120


def test_narrative_mentions_totals():
    from app.simulation.quick_stats import build_quick_stats
    out = build_quick_stats(
        total_projects=2,
        total_simulations=5,
        total_decisions=1,
        total_outcomes=1,
    )
    n = out["narrative"]
    assert "2 project" in n
    assert "7 action" in n  # 5 + 1 + 1


def test_account_age_label_buckets():
    """Each age bucket has the right label."""
    from app.simulation.quick_stats import build_quick_stats
    cases = [
        (0, None),  # no label
        (3, "less than a week"),
        (20, "less than a month"),
        (60, "less than a quarter"),
        (200, "less than a year"),
        (500, "well established"),
    ]
    for days, expected_label in cases:
        out = build_quick_stats(account_age_days=days)
        if expected_label is None:
            assert "Account is" not in out["narrative"]
        else:
            assert expected_label in out["narrative"]


def test_key_signals_present():
    from app.simulation.quick_stats import build_quick_stats
    out = build_quick_stats(
        total_projects=2,
        account_age_days=60,
    )
    labels = {s["label"] for s in out["key_signals"]}
    assert "total_projects" in labels
    assert "account_age_days" in labels


def test_no_account_age_signal_when_zero():
    from app.simulation.quick_stats import build_quick_stats
    out = build_quick_stats(total_projects=3)
    labels = {s["label"] for s in out["key_signals"]}
    assert "account_age_days" not in labels


def test_watch_severity_when_no_projects():
    from app.simulation.quick_stats import (
        SIGNAL_WATCH,
        build_quick_stats,
    )
    out = build_quick_stats()
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "total_projects"
    )
    assert sig["severity"] == SIGNAL_WATCH


def test_ok_severity_for_mature_account():
    from app.simulation.quick_stats import (
        SIGNAL_OK,
        build_quick_stats,
    )
    out = build_quick_stats(account_age_days=120)
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "account_age_days"
    )
    assert sig["severity"] == SIGNAL_OK


def test_schema_default_shape():
    from app.schemas.user import QuickStatsOut
    out = QuickStatsOut()
    assert out.total_projects == 0
    assert out.total_simulations == 0
    assert out.account_age_days == 0


def test_schema_round_trip():
    from app.schemas.user import QuickStatsOut
    from app.simulation.quick_stats import build_quick_stats
    payload = build_quick_stats(
        total_projects=5,
        total_simulations=10,
        account_age_days=100,
    )
    out = QuickStatsOut(**payload)
    assert out.total_projects == 5
    assert out.total_simulations == 10
    assert out.account_age_days == 100
