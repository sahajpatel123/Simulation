"""Tests for the per-user decision-to-outcome-delay helper."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone



def test_public_allowlist_matches_callers():
    from app.simulation import decision_to_outcome_delay
    assert set(decision_to_outcome_delay.__all__) == {
        "FAST_MAX_HOURS", "NORMAL_MAX_HOURS",
        "SIGNAL_OK", "SIGNAL_WATCH", "SIGNAL_CRITICAL",
        "build_decision_to_outcome_delay",
    }


def test_default_empty_state():
    from app.simulation.decision_to_outcome_delay import (
        build_decision_to_outcome_delay,
    )
    out = build_decision_to_outcome_delay()
    assert out["sample_count"] == 0
    assert out["average_gap_hours"] is None
    assert out["verdict"] == "INSUFFICIENT_DATA"


def test_fast_verdict_when_under_24_hours():
    from app.simulation.decision_to_outcome_delay import (
        build_decision_to_outcome_delay,
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = build_decision_to_outcome_delay([
        (now, now + timedelta(hours=2)),
        (now, now + timedelta(hours=8)),
    ])
    assert out["sample_count"] == 2
    assert out["verdict"] == "FAST"
    assert out["average_gap_hours"] == 5.0


def test_normal_verdict_when_under_7_days():
    from app.simulation.decision_to_outcome_delay import (
        build_decision_to_outcome_delay,
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = build_decision_to_outcome_delay([
        (now, now + timedelta(hours=72)),
    ])
    assert out["verdict"] == "NORMAL"


def test_slow_verdict_when_over_7_days():
    from app.simulation.decision_to_outcome_delay import (
        build_decision_to_outcome_delay,
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = build_decision_to_outcome_delay([
        (now, now + timedelta(hours=240)),
    ])
    assert out["verdict"] == "SLOW"


def test_skips_pairs_with_none_values():
    from app.simulation.decision_to_outcome_delay import (
        build_decision_to_outcome_delay,
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = build_decision_to_outcome_delay([
        (None, now + timedelta(hours=2)),
        (now, None),
        (now, now + timedelta(hours=6)),
    ])
    assert out["sample_count"] == 1


def test_skips_negative_gaps():
    from app.simulation.decision_to_outcome_delay import (
        build_decision_to_outcome_delay,
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = build_decision_to_outcome_delay([
        (now, now - timedelta(hours=2)),
        (now, now + timedelta(hours=4)),
    ])
    assert out["sample_count"] == 1
    assert out["average_gap_hours"] == 4.0


def test_skips_non_list_entries():
    from app.simulation.decision_to_outcome_delay import (
        build_decision_to_outcome_delay,
    )
    out = build_decision_to_outcome_delay([
        "not-a-list",
        None,
        (datetime(2026, 1, 1, tzinfo=timezone.utc),
         datetime(2026, 1, 1, 1, tzinfo=timezone.utc)),
    ])
    assert out["sample_count"] == 1


def test_handles_iso_string_pairs():
    from app.simulation.decision_to_outcome_delay import (
        build_decision_to_outcome_delay,
    )
    out = build_decision_to_outcome_delay([
        ("2026-01-01T00:00:00+00:00",
         "2026-01-01T12:00:00+00:00"),
    ])
    assert out["sample_count"] == 1
    assert out["average_gap_hours"] == 12.0


def test_skips_invalid_iso_strings():
    from app.simulation.decision_to_outcome_delay import (
        build_decision_to_outcome_delay,
    )
    out = build_decision_to_outcome_delay([
        ("not-a-date", "also-not-a-date"),
    ])
    assert out["sample_count"] == 0


def test_median_even_count():
    from app.simulation.decision_to_outcome_delay import (
        build_decision_to_outcome_delay,
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = build_decision_to_outcome_delay([
        (now, now + timedelta(hours=1)),
        (now, now + timedelta(hours=5)),
    ])
    # Median of [1, 5] = 3.
    assert out["median_gap_hours"] == 3.0


def test_fastest_and_slowest():
    from app.simulation.decision_to_outcome_delay import (
        build_decision_to_outcome_delay,
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = build_decision_to_outcome_delay([
        (now, now + timedelta(hours=2)),
        (now, now + timedelta(hours=20)),
        (now, now + timedelta(hours=10)),
    ])
    assert out["fastest_gap_hours"] == 2.0
    assert out["slowest_gap_hours"] == 20.0


def test_narrative_mentions_verdict():
    from app.simulation.decision_to_outcome_delay import (
        build_decision_to_outcome_delay,
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = build_decision_to_outcome_delay([
        (now, now + timedelta(hours=6)),
    ])
    assert "fast" in out["narrative"].lower()


def test_narrative_no_data_message():
    from app.simulation.decision_to_outcome_delay import (
        build_decision_to_outcome_delay,
    )
    out = build_decision_to_outcome_delay()
    assert "not enough" in out["narrative"].lower()


def test_key_signal_present_when_data_exists():
    from app.simulation.decision_to_outcome_delay import (
        build_decision_to_outcome_delay,
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = build_decision_to_outcome_delay([
        (now, now + timedelta(hours=12)),
    ])
    assert out["key_signals"][0]["label"] == "average_gap_hours"


def test_no_key_signal_when_no_data():
    from app.simulation.decision_to_outcome_delay import (
        build_decision_to_outcome_delay,
    )
    out = build_decision_to_outcome_delay()
    assert out["key_signals"] == []


def test_schema_default_shape():
    from app.schemas.user import DecisionToOutcomeDelayOut
    out = DecisionToOutcomeDelayOut()
    assert out.sample_count == 0
    assert out.average_gap_hours is None
    assert out.verdict == "INSUFFICIENT_DATA"
    assert out.key_signals == []


def test_schema_round_trip():
    from app.schemas.user import DecisionToOutcomeDelayOut
    from app.simulation.decision_to_outcome_delay import (
        build_decision_to_outcome_delay,
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    payload = build_decision_to_outcome_delay([
        (now, now + timedelta(hours=12)),
    ])
    out = DecisionToOutcomeDelayOut(**payload)
    assert out.sample_count == 1
    assert out.average_gap_hours == 12.0
    assert out.verdict == "FAST"
