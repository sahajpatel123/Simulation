"""Tests for the per-user runs-per-week helper."""
from __future__ import annotations

from datetime import datetime, timezone



def test_public_allowlist_matches_callers():
    from app.simulation import runs_per_week
    assert set(runs_per_week.__all__) == {
        "SIGNAL_OK", "SIGNAL_WATCH", "SIGNAL_CRITICAL",
        "build_runs_per_week",
    }


def test_default_empty_state():
    from app.simulation.runs_per_week import build_runs_per_week
    out = build_runs_per_week()
    assert out["weeks"] == []
    assert out["total_simulations"] == 0
    assert out["average_per_week"] == 0.0
    assert out["trend"] == "INSUFFICIENT_DATA"


def test_handles_iso_string_week_start():
    from app.simulation.runs_per_week import build_runs_per_week
    out = build_runs_per_week([
        ("2026-01-01", 5),
        ("2026-01-08", 7),
    ])
    assert out["weeks"][0]["week_start"] == "2026-01-01"
    assert out["weeks"][0]["sim_count"] == 5
    assert out["weeks"][1]["sim_count"] == 7


def test_handles_datetime_week_start():
    from app.simulation.runs_per_week import build_runs_per_week
    out = build_runs_per_week([
        (datetime(2026, 1, 1, tzinfo=timezone.utc), 3),
    ])
    assert out["weeks"][0]["week_start"] == "2026-01-01"
    assert out["weeks"][0]["sim_count"] == 3


def test_total_simulations_is_sum():
    from app.simulation.runs_per_week import build_runs_per_week
    out = build_runs_per_week([
        ("2026-01-01", 5),
        ("2026-01-08", 7),
        ("2026-01-15", 3),
    ])
    assert out["total_simulations"] == 15


def test_average_per_week():
    from app.simulation.runs_per_week import build_runs_per_week
    out = build_runs_per_week([
        ("2026-01-01", 5),
        ("2026-01-08", 7),
    ])
    assert out["average_per_week"] == 6.0


def test_trend_up_when_latest_greater():
    from app.simulation.runs_per_week import build_runs_per_week
    out = build_runs_per_week([
        ("2026-01-01", 2),
        ("2026-01-15", 10),
    ])
    assert out["trend"] == "UP"


def test_trend_down_when_latest_smaller():
    from app.simulation.runs_per_week import build_runs_per_week
    out = build_runs_per_week([
        ("2026-01-01", 10),
        ("2026-01-15", 2),
    ])
    assert out["trend"] == "DOWN"


def test_trend_steady_when_latest_equals():
    from app.simulation.runs_per_week import build_runs_per_week
    out = build_runs_per_week([
        ("2026-01-01", 5),
        ("2026-01-15", 5),
    ])
    assert out["trend"] == "STEADY"


def test_trend_insufficient_when_less_than_2():
    from app.simulation.runs_per_week import build_runs_per_week
    out = build_runs_per_week([
        ("2026-01-01", 5),
    ])
    assert out["trend"] == "INSUFFICIENT_DATA"


def test_trend_insufficient_when_empty():
    from app.simulation.runs_per_week import build_runs_per_week
    out = build_runs_per_week()
    assert out["trend"] == "INSUFFICIENT_DATA"


def test_severity_ok_when_up():
    from app.simulation.runs_per_week import (
        SIGNAL_OK,
        build_runs_per_week,
    )
    out = build_runs_per_week([
        ("2026-01-01", 2),
        ("2026-01-15", 10),
    ])
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_OK


def test_severity_critical_when_down():
    from app.simulation.runs_per_week import (
        SIGNAL_CRITICAL,
        build_runs_per_week,
    )
    out = build_runs_per_week([
        ("2026-01-01", 10),
        ("2026-01-15", 2),
    ])
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_CRITICAL


def test_skips_non_tuple_entries():
    from app.simulation.runs_per_week import build_runs_per_week
    out = build_runs_per_week([
        "not-a-tuple",
        None,
        ("2026-01-01", 5),
    ])
    assert out["total_simulations"] == 5


def test_narrative_quiet_when_empty():
    from app.simulation.runs_per_week import build_runs_per_week
    out = build_runs_per_week()
    assert "run a few sims" in out["narrative"].lower()


def test_narrative_includes_counts_when_data():
    from app.simulation.runs_per_week import build_runs_per_week
    out = build_runs_per_week([
        ("2026-01-01", 5),
        ("2026-01-08", 7),
    ])
    assert "5 sim" in out["narrative"]
    assert "7 sim" in out["narrative"]
    assert "12 total" in out["narrative"]


def test_schema_default_shape():
    from app.schemas.project import RunsPerWeekOut
    out = RunsPerWeekOut()
    assert out.weeks == []
    assert out.total_simulations == 0
    assert out.average_per_week == 0.0
    assert out.trend == "INSUFFICIENT_DATA"
    assert out.key_signals == []


def test_schema_round_trip():
    from app.schemas.project import RunsPerWeekOut
    from app.simulation.runs_per_week import build_runs_per_week
    payload = build_runs_per_week([
        ("2026-01-01", 5),
    ])
    out = RunsPerWeekOut(**payload)
    assert out.weeks[0]["week_start"] == "2026-01-01"
    assert out.weeks[0]["sim_count"] == 5
