"""Tests for the per-user decision-velocity helper."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta


def test_public_allowlist_matches_callers():
    from app.simulation import decision_velocity
    assert set(decision_velocity.__all__) == {
        "FAST_MAX_HOURS", "NORMAL_MAX_HOURS",
        "SIGNAL_OK", "SIGNAL_WATCH", "SIGNAL_CRITICAL",
        "build_decision_velocity",
    }


def test_default_empty_state():
    from app.simulation.decision_velocity import (
        build_decision_velocity,
    )
    out = build_decision_velocity()
    assert out["sample_count"] == 0
    assert out["average_gap_hours"] is None
    assert out["verdict"] == "INSUFFICIENT_DATA"


def test_fast_verdict_when_under_4_hours():
    from app.simulation.decision_velocity import (
        build_decision_velocity,
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    out = build_decision_velocity([
        (now, now + timedelta(hours=2)),
        (now, now + timedelta(hours=3)),
    ])
    assert out["sample_count"] == 2
    assert out["verdict"] == "FAST"
    assert out["average_gap_hours"] == 2.5


def test_normal_verdict_when_under_24_hours():
    from app.simulation.decision_velocity import (
        build_decision_velocity,
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    out = build_decision_velocity([
        (now, now + timedelta(hours=10)),
    ])
    assert out["verdict"] == "NORMAL"


def test_slow_verdict_when_over_24_hours():
    from app.simulation.decision_velocity import (
        build_decision_velocity,
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    out = build_decision_velocity([
        (now, now + timedelta(hours=48)),
    ])
    assert out["verdict"] == "SLOW"


def test_skips_pairs_with_none_values():
    from app.simulation.decision_velocity import (
        build_decision_velocity,
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    out = build_decision_velocity([
        (None, now + timedelta(hours=2)),
        (now, None),
        (now, now + timedelta(hours=3)),
    ])
    assert out["sample_count"] == 1


def test_skips_negative_gaps():
    """Decision before sim completion is nonsense - skip."""
    from app.simulation.decision_velocity import (
        build_decision_velocity,
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    out = build_decision_velocity([
        (now, now - timedelta(hours=5)),  # negative
        (now, now + timedelta(hours=2)),  # valid
    ])
    assert out["sample_count"] == 1
    assert out["average_gap_hours"] == 2.0


def test_skips_non_list_entries():
    from app.simulation.decision_velocity import (
        build_decision_velocity,
    )
    out = build_decision_velocity([
        "not-a-list",
        None,
        (datetime(2026, 1, 1, tzinfo=UTC),
         datetime(2026, 1, 1, 1, tzinfo=UTC)),
    ])
    assert out["sample_count"] == 1


def test_median_calculation_even_count():
    from app.simulation.decision_velocity import (
        build_decision_velocity,
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    out = build_decision_velocity([
        (now, now + timedelta(hours=1)),
        (now, now + timedelta(hours=3)),
    ])
    # Median of [1, 3] = 2.
    assert out["median_gap_hours"] == 2.0


def test_median_calculation_odd_count():
    from app.simulation.decision_velocity import (
        build_decision_velocity,
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    out = build_decision_velocity([
        (now, now + timedelta(hours=1)),
        (now, now + timedelta(hours=2)),
        (now, now + timedelta(hours=5)),
    ])
    # Median of [1, 2, 5] = 2.
    assert out["median_gap_hours"] == 2.0


def test_fastest_and_slowest():
    from app.simulation.decision_velocity import (
        build_decision_velocity,
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    out = build_decision_velocity([
        (now, now + timedelta(hours=1)),
        (now, now + timedelta(hours=10)),
        (now, now + timedelta(hours=5)),
    ])
    assert out["fastest_gap_hours"] == 1.0
    assert out["slowest_gap_hours"] == 10.0


def test_handles_iso_string_pairs():
    from app.simulation.decision_velocity import (
        build_decision_velocity,
    )
    out = build_decision_velocity([
        ("2026-01-01T00:00:00+00:00",
         "2026-01-01T02:00:00+00:00"),
    ])
    assert out["sample_count"] == 1
    assert out["average_gap_hours"] == 2.0


def test_skips_invalid_iso_strings():
    from app.simulation.decision_velocity import (
        build_decision_velocity,
    )
    out = build_decision_velocity([
        ("not-a-date", "also-not-a-date"),
    ])
    assert out["sample_count"] == 0


def test_key_signal_present_when_data_exists():
    from app.simulation.decision_velocity import (
        build_decision_velocity,
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    out = build_decision_velocity([
        (now, now + timedelta(hours=1)),
    ])
    assert out["key_signals"][0]["label"] == "average_gap_hours"


def test_no_key_signal_when_no_data():
    from app.simulation.decision_velocity import (
        build_decision_velocity,
    )
    out = build_decision_velocity()
    assert out["key_signals"] == []


def test_narrative_mentions_verdict():
    from app.simulation.decision_velocity import (
        build_decision_velocity,
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    out = build_decision_velocity([
        (now, now + timedelta(hours=2)),
    ])
    assert "fast" in out["narrative"].lower()


def test_narrative_no_data_message():
    from app.simulation.decision_velocity import (
        build_decision_velocity,
    )
    out = build_decision_velocity()
    assert "not enough" in out["narrative"].lower()


def test_schema_default_shape():
    from app.schemas.user import DecisionVelocityOut
    out = DecisionVelocityOut()
    assert out.sample_count == 0
    assert out.average_gap_hours is None
    assert out.verdict == "INSUFFICIENT_DATA"
    assert out.key_signals == []


def test_schema_round_trip():
    from app.schemas.user import DecisionVelocityOut
    from app.simulation.decision_velocity import (
        build_decision_velocity,
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    payload = build_decision_velocity([
        (now, now + timedelta(hours=3)),
    ])
    out = DecisionVelocityOut(**payload)
    assert out.sample_count == 1
    assert out.average_gap_hours == 3.0
    assert out.verdict == "FAST"
