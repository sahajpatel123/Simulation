"""Tests for the per-project stale-check helper.

The helper is pure-Python so it can be exercised without
a DB.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import stale_check

    assert set(stale_check.__all__) == {
        "ASSUMPTIONS_STALE_DAYS",
        "SIM_STALE_DAYS",
        "OUTCOMES_STALE_DAYS",
        "DECISIONS_STALE_DAYS",
        "PREMORTEM_STALE_DAYS",
        "INTERVENTIONS_STALE_DAYS",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_stale_check",
    }


def test_digest_all_none_is_critical() -> None:
    """All 6 sources missing -> 6 stale (critical each)."""
    from app.simulation.stale_check import (
        SIGNAL_CRITICAL,
        build_stale_check,
    )

    out = build_stale_check(None, None, None, None, None, None)
    assert out["stale_count"] == 6
    for s in out["sources"]:
        assert s["severity"] == SIGNAL_CRITICAL


def test_digest_fresh_everything_is_zero_stale() -> None:
    from app.simulation.stale_check import (
        SIGNAL_OK,
        build_stale_check,
    )

    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    fresh = now - timedelta(days=1)
    out = build_stale_check(
        fresh, fresh, fresh, fresh, fresh, fresh, now=now,
    )
    assert out["stale_count"] == 0
    assert all(s["severity"] == SIGNAL_OK for s in out["sources"])


def test_digest_sim_at_threshold_is_watch() -> None:
    """Sim source 14d old (threshold) -> watch, not critical."""
    from app.simulation.stale_check import (
        SIM_STALE_DAYS,
        SIGNAL_WATCH,
        build_stale_check,
    )

    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    sim_at = now - timedelta(days=SIM_STALE_DAYS)
    out = build_stale_check(
        None, sim_at, None, None, None, None, now=now,
    )
    sim_src = next(
        s for s in out["sources"] if s["name"] == "sims"
    )
    assert sim_src["severity"] == SIGNAL_WATCH


def test_digest_sim_at_double_threshold_is_critical() -> None:
    """Sim source 28d old (>2x threshold) -> critical."""
    from app.simulation.stale_check import (
        SIM_STALE_DAYS,
        SIGNAL_CRITICAL,
        build_stale_check,
    )

    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    sim_at = now - timedelta(days=SIM_STALE_DAYS * 2)
    out = build_stale_check(
        None, sim_at, None, None, None, None, now=now,
    )
    sim_src = next(
        s for s in out["sources"] if s["name"] == "sims"
    )
    assert sim_src["severity"] == SIGNAL_CRITICAL
    assert "strongly consider" in sim_src["recommendation"]


def test_digest_naive_datetime_coerced_to_utc() -> None:
    from app.simulation.stale_check import build_stale_check

    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    naive = datetime(2026, 5, 20)  # 12 days ago
    out = build_stale_check(None, naive, None, None, None, None,
                            now=now)
    sim_src = next(
        s for s in out["sources"] if s["name"] == "sims"
    )
    assert sim_src["days_since"] == 12


def test_digest_key_signal_critical_at_3_stale() -> None:
    from app.simulation.stale_check import (
        SIGNAL_CRITICAL,
        build_stale_check,
    )

    # 3 sources missing -> 3 stale -> critical signal.
    out = build_stale_check(None, None, None, None, None, None)
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "stale_source_count"
    )
    assert sig["severity"] == SIGNAL_CRITICAL


def test_digest_key_signal_watch_at_1_stale() -> None:
    from app.simulation.stale_check import (
        SIGNAL_WATCH,
        build_stale_check,
    )

    # 5 sources fresh + 1 missing = 1 stale = watch.
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    fresh = now - timedelta(days=1)
    out = build_stale_check(
        fresh, fresh, fresh, fresh, fresh, None, now=now,
    )
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "stale_source_count"
    )
    assert sig["severity"] == SIGNAL_WATCH


def test_digest_narrative_critical_sources_mention() -> None:
    from app.simulation.stale_check import build_stale_check

    out = build_stale_check(None, None, None, None, None, None)
    n = out["narrative"].lower()
    assert "critical" in n
    # At least one critical source named.
    sources_in_narrative = [
        name
        for name in (
            "assumptions", "sims", "outcomes",
            "decisions", "premortem", "interventions",
        )
        if name in n
    ]
    assert len(sources_in_narrative) >= 1


def test_digest_narrative_fresh_message() -> None:
    from app.simulation.stale_check import build_stale_check

    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    fresh = now - timedelta(days=1)
    out = build_stale_check(
        fresh, fresh, fresh, fresh, fresh, fresh, now=now,
    )
    assert "fresh" in out["narrative"].lower()


def test_digest_recommendation_text_for_watch() -> None:
    from app.simulation.stale_check import (
        DECISIONS_STALE_DAYS,
        build_stale_check,
    )

    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    dec_at = now - timedelta(days=DECISIONS_STALE_DAYS + 1)
    out = build_stale_check(
        None, None, None, dec_at, None, None, now=now,
    )
    dec_src = next(
        s for s in out["sources"] if s["name"] == "decisions"
    )
    assert "consider refreshing" in dec_src["recommendation"]


def test_digest_recommendation_text_for_missing() -> None:
    from app.simulation.stale_check import build_stale_check

    out = build_stale_check(
        None, None, None, None, None, None,
    )
    # Pick any source; they all say 'no X on record yet'.
    src = out["sources"][0]
    assert "no" in src["recommendation"].lower()
    assert "re-run" in src["recommendation"].lower()


def test_digest_sources_checked_count() -> None:
    from app.simulation.stale_check import build_stale_check

    out = build_stale_check(
        None, None, None, None, None, None,
    )
    assert out["sources_checked"] == 6
    assert len(out["sources"]) == 6


def test_digest_schema_round_trip() -> None:
    from app.schemas.project import StaleCheckOut
    from app.simulation.stale_check import build_stale_check

    payload = build_stale_check(
        None, None, None, None, None, None,
    )
    out = StaleCheckOut(**payload)
    assert out.stale_count == 6
    assert out.sources_checked == 6


def test_digest_schema_default_shape() -> None:
    from app.schemas.project import StaleCheckOut

    out = StaleCheckOut()
    assert out.stale_count == 0
    assert out.sources_checked == 0
    assert out.sources == []


def test_digest_each_source_has_recommendation() -> None:
    from app.simulation.stale_check import build_stale_check

    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    fresh = now - timedelta(days=1)
    very_old = now - timedelta(days=100)
    out = build_stale_check(
        very_old, fresh, very_old, fresh, very_old, fresh,
        now=now,
    )
    for s in out["sources"]:
        assert "recommendation" in s
        assert s["recommendation"].strip() != ""