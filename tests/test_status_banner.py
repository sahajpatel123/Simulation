"""Tests for the per-project status-banner helper."""
from __future__ import annotations



def test_public_allowlist_matches_callers():
    from app.simulation import status_banner
    assert set(status_banner.__all__) == {
        "SIM_RECENT_DAYS",
        "SIM_STALE_DAYS",
        "ASSUMPTION_STALE_DAYS",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_status_banner",
    }


def test_empty_state_when_nothing_set():
    from app.simulation.status_banner import (
        SIGNAL_WATCH,
        build_status_banner,
    )
    out = build_status_banner(
        brief_completed=False,
        assumption_count=0,
        has_completed_sim=False,
        days_since_latest_sim=None,
        pending_decision_count=0,
        days_since_latest_assumption_extraction=None,
    )
    assert out["status"] == "Empty"
    assert out["severity"] == SIGNAL_WATCH


def test_healthy_when_recent_sim_and_no_pending():
    from app.simulation.status_banner import (
        SIGNAL_OK,
        build_status_banner,
    )
    out = build_status_banner(
        brief_completed=True,
        assumption_count=5,
        has_completed_sim=True,
        days_since_latest_sim=2,
        pending_decision_count=0,
        days_since_latest_assumption_extraction=10,
    )
    assert out["status"] == "Healthy"
    assert out["severity"] == SIGNAL_OK


def test_healthy_with_zero_days_since_sim():
    from app.simulation.status_banner import build_status_banner
    out = build_status_banner(
        brief_completed=True,
        assumption_count=5,
        has_completed_sim=True,
        days_since_latest_sim=0,
        pending_decision_count=0,
        days_since_latest_assumption_extraction=1,
    )
    assert out["status"] == "Healthy"


def test_stale_when_no_sim_at_all():
    from app.simulation.status_banner import (
        SIGNAL_CRITICAL,
        build_status_banner,
    )
    out = build_status_banner(
        brief_completed=True,
        assumption_count=5,
        has_completed_sim=False,
        days_since_latest_sim=None,
        pending_decision_count=0,
        days_since_latest_assumption_extraction=5,
    )
    assert out["status"] == "Stale"
    assert out["severity"] == SIGNAL_CRITICAL


def test_stale_when_sim_older_than_threshold():
    from app.simulation.status_banner import (
        SIGNAL_CRITICAL,
        build_status_banner,
    )
    out = build_status_banner(
        brief_completed=True,
        assumption_count=5,
        has_completed_sim=True,
        days_since_latest_sim=30,  # > SIM_STALE_DAYS (14)
        pending_decision_count=0,
        days_since_latest_assumption_extraction=5,
    )
    assert out["status"] == "Stale"
    assert out["severity"] == SIGNAL_CRITICAL


def test_action_needed_when_pending_decisions():
    from app.simulation.status_banner import (
        SIGNAL_WATCH,
        build_status_banner,
    )
    out = build_status_banner(
        brief_completed=True,
        assumption_count=5,
        has_completed_sim=True,
        days_since_latest_sim=3,
        pending_decision_count=2,
        days_since_latest_assumption_extraction=10,
    )
    assert out["status"] == "Action needed"
    assert out["severity"] == SIGNAL_WATCH


def test_action_needed_when_assumption_extraction_stale():
    from app.simulation.status_banner import (
        SIGNAL_WATCH,
        build_status_banner,
    )
    out = build_status_banner(
        brief_completed=True,
        assumption_count=5,
        has_completed_sim=True,
        days_since_latest_sim=3,
        pending_decision_count=0,
        days_since_latest_assumption_extraction=60,  # > 30d
    )
    assert out["status"] == "Action needed"
    assert out["severity"] == SIGNAL_WATCH


def test_narrative_empty_state():
    from app.simulation.status_banner import build_status_banner
    out = build_status_banner(
        brief_completed=False,
        assumption_count=0,
        has_completed_sim=False,
        days_since_latest_sim=None,
        pending_decision_count=0,
        days_since_latest_assumption_extraction=None,
    )
    assert "empty" in out["narrative"].lower()


def test_narrative_stale_mentions_days():
    from app.simulation.status_banner import build_status_banner
    out = build_status_banner(
        brief_completed=True,
        assumption_count=5,
        has_completed_sim=True,
        days_since_latest_sim=20,
        pending_decision_count=0,
        days_since_latest_assumption_extraction=5,
    )
    assert "20 day" in out["narrative"]


def test_narrative_action_needed_mentions_pending():
    from app.simulation.status_banner import build_status_banner
    out = build_status_banner(
        brief_completed=True,
        assumption_count=5,
        has_completed_sim=True,
        days_since_latest_sim=3,
        pending_decision_count=2,
        days_since_latest_assumption_extraction=10,
    )
    assert "2 decision" in out["narrative"]


def test_key_signals_always_present():
    from app.simulation.status_banner import build_status_banner
    out = build_status_banner(
        brief_completed=False,
        assumption_count=0,
        has_completed_sim=False,
        days_since_latest_sim=None,
        pending_decision_count=0,
        days_since_latest_assumption_extraction=None,
    )
    assert len(out["key_signals"]) >= 1
    assert out["key_signals"][0]["label"] == "status"


def test_schema_default_shape():
    from app.schemas.project import StatusBannerOut
    out = StatusBannerOut()
    assert out.status == "Empty"
    assert out.severity == "watch"
    assert out.key_signals == []


def test_schema_round_trip():
    from app.schemas.project import StatusBannerOut
    from app.simulation.status_banner import build_status_banner
    payload = build_status_banner(
        brief_completed=True,
        assumption_count=5,
        has_completed_sim=True,
        days_since_latest_sim=2,
        pending_decision_count=0,
        days_since_latest_assumption_extraction=10,
    )
    out = StatusBannerOut(**payload)
    assert out.status == "Healthy"
    assert out.severity == "ok"
