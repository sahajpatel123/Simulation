"""Tests for the per-user sim-failure-rate helper."""
from __future__ import annotations

import pytest


def test_public_allowlist_matches_callers():
    from app.simulation import sim_failure_rate
    assert set(sim_failure_rate.__all__) == {
        "RELIABLE_MAX", "ACCEPTABLE_MAX",
        "SIGNAL_OK", "SIGNAL_WATCH", "SIGNAL_CRITICAL",
        "build_sim_failure_rate",
    }


def test_default_zero_state():
    from app.simulation.sim_failure_rate import (
        build_sim_failure_rate,
    )
    out = build_sim_failure_rate()
    assert out["total_simulations"] == 0
    assert out["failed_simulations"] == 0
    assert out["failure_rate_pct"] == 0.0
    assert out["verdict"] == "INSUFFICIENT_DATA"


def test_reliable_when_below_5_percent():
    from app.simulation.sim_failure_rate import (
        build_sim_failure_rate,
    )
    out = build_sim_failure_rate(
        total_simulations=100, failed_simulations=3,
    )
    assert out["verdict"] == "RELIABLE"
    assert out["failure_rate_pct"] == 3.0


def test_acceptable_when_below_15_percent():
    from app.simulation.sim_failure_rate import (
        build_sim_failure_rate,
    )
    out = build_sim_failure_rate(
        total_simulations=100, failed_simulations=10,
    )
    assert out["verdict"] == "ACCEPTABLE"
    assert out["failure_rate_pct"] == 10.0


def test_unreliable_when_above_15_percent():
    from app.simulation.sim_failure_rate import (
        build_sim_failure_rate,
    )
    out = build_sim_failure_rate(
        total_simulations=100, failed_simulations=30,
    )
    assert out["verdict"] == "UNRELIABLE"
    assert out["failure_rate_pct"] == 30.0


def test_clamps_failed_at_total():
    """Failed > total clamped to total (no negative pct)."""
    from app.simulation.sim_failure_rate import (
        build_sim_failure_rate,
    )
    out = build_sim_failure_rate(
        total_simulations=5, failed_simulations=10,
    )
    # 5/5 = 100%.
    assert out["failure_rate_pct"] == 100.0
    assert out["failed_simulations"] == 5  # clamped


def test_rounds_to_1_decimal():
    from app.simulation.sim_failure_rate import (
        build_sim_failure_rate,
    )
    out = build_sim_failure_rate(
        total_simulations=3, failed_simulations=1,
    )
    # 1/3 = 33.33... -> 33.3
    assert out["failure_rate_pct"] == 33.3


def test_zero_total_returns_zero_pct():
    from app.simulation.sim_failure_rate import (
        build_sim_failure_rate,
    )
    out = build_sim_failure_rate(
        total_simulations=0, failed_simulations=0,
    )
    assert out["failure_rate_pct"] == 0.0
    assert out["verdict"] == "INSUFFICIENT_DATA"


def test_severity_ok_when_reliable():
    from app.simulation.sim_failure_rate import (
        SIGNAL_OK,
        build_sim_failure_rate,
    )
    out = build_sim_failure_rate(
        total_simulations=100, failed_simulations=1,
    )
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_OK


def test_severity_watch_when_acceptable():
    from app.simulation.sim_failure_rate import (
        SIGNAL_WATCH,
        build_sim_failure_rate,
    )
    out = build_sim_failure_rate(
        total_simulations=100, failed_simulations=10,
    )
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_WATCH


def test_severity_critical_when_unreliable():
    from app.simulation.sim_failure_rate import (
        SIGNAL_CRITICAL,
        build_sim_failure_rate,
    )
    out = build_sim_failure_rate(
        total_simulations=100, failed_simulations=30,
    )
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_CRITICAL


def test_no_key_signal_when_no_data():
    from app.simulation.sim_failure_rate import (
        build_sim_failure_rate,
    )
    out = build_sim_failure_rate()
    assert out["key_signals"] == []


def test_narrative_quiet_when_no_data():
    from app.simulation.sim_failure_rate import (
        build_sim_failure_rate,
    )
    out = build_sim_failure_rate()
    assert "no simulations" in out["narrative"].lower()


def test_narrative_mentions_pct_when_data():
    from app.simulation.sim_failure_rate import (
        build_sim_failure_rate,
    )
    out = build_sim_failure_rate(
        total_simulations=100, failed_simulations=5,
    )
    assert "5.0%" in out["narrative"]
    assert "reliable" in out["narrative"].lower()


def test_schema_default_shape():
    from app.schemas.project import SimFailureRateOut
    out = SimFailureRateOut()
    assert out.total_simulations == 0
    assert out.failed_simulations == 0
    assert out.failure_rate_pct == 0.0
    assert out.verdict == "INSUFFICIENT_DATA"
    assert out.key_signals == []


def test_schema_round_trip():
    from app.schemas.project import SimFailureRateOut
    from app.simulation.sim_failure_rate import (
        build_sim_failure_rate,
    )
    payload = build_sim_failure_rate(
        total_simulations=10, failed_simulations=1,
    )
    out = SimFailureRateOut(**payload)
    assert out.total_simulations == 10
    assert out.failed_simulations == 1
    assert out.verdict == "RELIABLE"
