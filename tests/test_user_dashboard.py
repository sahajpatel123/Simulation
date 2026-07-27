"""Tests for the user-dashboard helper + schema + route
registration.

The helper is pure-Python so it can be exercised without
a DB. The route-registration check is gated by scipy + a
razorpay stub (same pattern as the other route tests).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import user_dashboard

    assert set(user_dashboard.__all__) == {
        "FREE_TIER_MONTHLY_CAP",
        "ACCOUNT_AGE_BANDS",
        "QUOTA_WARN_RATIO",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_user_dashboard",
    }


# ---------------------------------------------------------------------------
# Default-empty input
# ---------------------------------------------------------------------------


def test_dashboard_empty_input_zero_state() -> None:
    from app.simulation.user_dashboard import build_user_dashboard

    out = build_user_dashboard(
        account_created_at=None,
        tier="",
        monthly_sim_used=0,
    )
    assert out["account_age_days"] == 0
    assert out["account_age_label"] == "fresh"
    assert out["tier"] == "FREE"
    assert out["monthly_usage"]["used"] == 0
    assert out["key_signals"][0]["label"] == "tier"


# ---------------------------------------------------------------------------
# Monthly quota severity
# ---------------------------------------------------------------------------


def test_dashboard_quota_ok_below_warn() -> None:
    from app.simulation.user_dashboard import (
        SIGNAL_OK,
        build_user_dashboard,
    )

    out = build_user_dashboard(
        account_created_at=None, tier="FREE",
        monthly_sim_used=1, monthly_sim_cap=10,
    )
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "monthly_sims"
    )
    assert sig["severity"] == SIGNAL_OK


def test_dashboard_quota_watch_at_80_percent() -> None:
    from app.simulation.user_dashboard import (
        SIGNAL_WATCH,
        build_user_dashboard,
    )

    out = build_user_dashboard(
        account_created_at=None, tier="FREE",
        monthly_sim_used=8, monthly_sim_cap=10,
    )
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "monthly_sims"
    )
    assert sig["severity"] == SIGNAL_WATCH


def test_dashboard_quota_critical_at_cap() -> None:
    from app.simulation.user_dashboard import (
        SIGNAL_CRITICAL,
        build_user_dashboard,
    )

    out = build_user_dashboard(
        account_created_at=None, tier="FREE",
        monthly_sim_used=10, monthly_sim_cap=10,
    )
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "monthly_sims"
    )
    assert sig["severity"] == SIGNAL_CRITICAL
    # remaining clamped at 0, never negative.
    assert out["monthly_usage"]["remaining"] == 0


# ---------------------------------------------------------------------------
# Account age
# ---------------------------------------------------------------------------


def test_dashboard_account_age_label_week() -> None:
    from app.simulation.user_dashboard import build_user_dashboard

    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    created = datetime(2026, 1, 5, tzinfo=timezone.utc)
    out = build_user_dashboard(
        account_created_at=created,
        tier="FREE",
        monthly_sim_used=0,
        now=now,
    )
    assert out["account_age_days"] == 5
    assert out["account_age_label"] == "less than a week old"


def test_dashboard_account_age_label_quarter() -> None:
    from app.simulation.user_dashboard import build_user_dashboard

    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = build_user_dashboard(
        account_created_at=created,
        tier="FREE",
        monthly_sim_used=0,
        now=now,
    )
    assert out["account_age_days"] >= 90
    assert "quarter" in out["account_age_label"]


def test_dashboard_account_age_handles_naive_datetime() -> None:
    """Naive datetimes are coerced to UTC."""
    from app.simulation.user_dashboard import build_user_dashboard

    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    created = datetime(2026, 5, 15)
    out = build_user_dashboard(
        account_created_at=created,
        tier="FREE", monthly_sim_used=0, now=now,
    )
    assert out["account_age_days"] == 17


def test_dashboard_account_age_handles_iso_string() -> None:
    """Account_created_at can also be passed as an ISO string."""
    from app.simulation.user_dashboard import build_user_dashboard

    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    out = build_user_dashboard(
        account_created_at="2026-01-05T00:00:00+00:00",
        tier="FREE",
        monthly_sim_used=0,
        now=now,
    )
    assert out["account_age_days"] == 5


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------


def test_dashboard_counts_pass_through() -> None:
    from app.simulation.user_dashboard import build_user_dashboard

    out = build_user_dashboard(
        account_created_at=None,
        tier="PRO",
        monthly_sim_used=12, monthly_sim_cap=50,
        project_count=4,
        simulation_count=12,
        decision_count=8,
        outcome_count=5,
    )
    assert out["project_count"] == 4
    assert out["simulation_count"] == 12
    assert out["decision_count"] == 8
    assert out["outcome_count"] == 5


# ---------------------------------------------------------------------------
# Blindspot escalation
# ---------------------------------------------------------------------------


def test_dashboard_blindspot_watch_when_under_3() -> None:
    from app.simulation.user_dashboard import (
        SIGNAL_WATCH,
        build_user_dashboard,
    )

    out = build_user_dashboard(
        account_created_at=None, tier="FREE",
        monthly_sim_used=0, blindspot_count=2,
    )
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "blindspot_count"
    )
    assert sig["severity"] == SIGNAL_WATCH


def test_dashboard_blindspot_critical_when_3_or_more() -> None:
    from app.simulation.user_dashboard import (
        SIGNAL_CRITICAL,
        build_user_dashboard,
    )

    out = build_user_dashboard(
        account_created_at=None, tier="FREE",
        monthly_sim_used=0, blindspot_count=3,
    )
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "blindspot_count"
    )
    assert sig["severity"] == SIGNAL_CRITICAL


def test_dashboard_blindspot_signal_absent_when_zero() -> None:
    """Signal is only emitted when count > 0."""
    from app.simulation.user_dashboard import build_user_dashboard

    out = build_user_dashboard(
        account_created_at=None, tier="FREE",
        monthly_sim_used=0, blindspot_count=0,
    )
    labels = {s["label"] for s in out["key_signals"]}
    assert "blindspot_count" not in labels


# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------


def test_dashboard_narrative_mentions_tier() -> None:
    from app.simulation.user_dashboard import build_user_dashboard

    out = build_user_dashboard(
        account_created_at=None, tier="PRO",
        monthly_sim_used=0,
    )
    assert "PRO" in out["narrative"]


def test_dashboard_narrative_warns_at_cap() -> None:
    from app.simulation.user_dashboard import build_user_dashboard

    out = build_user_dashboard(
        account_created_at=None, tier="FREE",
        monthly_sim_used=2, monthly_sim_cap=2,
    )
    assert "exhausted" in out["narrative"].lower()


def test_dashboard_narrative_warns_near_cap() -> None:
    from app.simulation.user_dashboard import build_user_dashboard

    out = build_user_dashboard(
        account_created_at=None, tier="FREE",
        monthly_sim_used=2, monthly_sim_cap=2,
    )
    # Already-exhausted case takes priority; check at >80%
    # under cap boundary separately.
    out2 = build_user_dashboard(
        account_created_at=None, tier="FREE",
        monthly_sim_used=9, monthly_sim_cap=10,
    )
    assert "approaching" in out2["narrative"].lower()


def test_dashboard_narrative_mentions_last_activity() -> None:
    from app.simulation.user_dashboard import build_user_dashboard

    out = build_user_dashboard(
        account_created_at=None, tier="FREE",
        monthly_sim_used=0,
        last_activity_at="2026-06-01T12:00:00Z",
    )
    assert "2026-06-01" in out["narrative"]


# ---------------------------------------------------------------------------
# Defensive
# ---------------------------------------------------------------------------


def test_dashboard_used_negative_clamped_to_zero_remaining() -> None:
    """``used`` shouldn't exceed ``cap``, but if a
    misconfigured call passes a higher value the ``remaining``
    must clamp at zero (never negative)."""
    from app.simulation.user_dashboard import build_user_dashboard

    out = build_user_dashboard(
        account_created_at=None, tier="FREE",
        monthly_sim_used=99, monthly_sim_cap=10,
    )
    assert out["monthly_usage"]["remaining"] == 0


def test_dashboard_handles_zero_cap() -> None:
    from app.simulation.user_dashboard import (
        SIGNAL_WATCH,
        build_user_dashboard,
    )

    # 0 cap falls back to "watch" severity (not division by zero).
    out = build_user_dashboard(
        account_created_at=None, tier="FREE",
        monthly_sim_used=0, monthly_sim_cap=0,
    )
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "monthly_sims"
    )
    assert sig["severity"] == SIGNAL_WATCH


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_user_dashboard_out_default_shape() -> None:
    from app.schemas.user import UserDashboardOut

    out = UserDashboardOut()
    assert out.account_age_days == 0
    assert out.tier == "FREE"
    assert out.project_count == 0
    assert out.key_signals == []


def test_user_dashboard_out_round_trips_helper_payload() -> None:
    from app.schemas.user import UserDashboardOut
    from app.simulation.user_dashboard import build_user_dashboard

    payload = build_user_dashboard(
        account_created_at=datetime(
            2026, 1, 1, tzinfo=timezone.utc,
        ),
        tier="PRO",
        monthly_sim_used=5, monthly_sim_cap=50,
        project_count=3,
    )
    out = UserDashboardOut(**payload)
    assert out.tier == "PRO"
    assert out.project_count == 3
    assert out.monthly_usage["used"] == 5


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_dashboard_route_registered() -> None:
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import users as users_mod

    paths = {r.path for r in users_mod.router.routes}
    assert "/users/me/dashboard" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in users_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET" in methods_by_path["/users/me/dashboard"]
    )