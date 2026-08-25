"""Tests for the per-user recent-outcomes helper."""
from __future__ import annotations

from datetime import UTC, datetime


def test_public_allowlist_matches_callers():
    from app.simulation import recent_outcomes
    assert set(recent_outcomes.__all__) == {
        "MAX_RECENT", "SIGNAL_OK", "SIGNAL_WATCH",
        "SIGNAL_CRITICAL", "build_recent_outcomes",
    }


def test_default_empty_state():
    from app.simulation.recent_outcomes import (
        build_recent_outcomes,
    )
    out = build_recent_outcomes()
    assert out["outcomes"] == []
    assert out["outcome_count"] == 0
    assert out["key_signals"] == []


def test_caps_at_max_recent():
    from app.simulation.recent_outcomes import build_recent_outcomes
    out = build_recent_outcomes([
        {"outcome_id": i, "project_id": 1,
         "actual_conversion_rate": 0.01 * i,
         "created_at": None}
        for i in range(1, 10)
    ])
    assert len(out["outcomes"]) == 5  # MAX_RECENT = 5


def test_normalizes_alternate_field_names():
    from app.simulation.recent_outcomes import build_recent_outcomes
    out = build_recent_outcomes([
        {
            "id": 1, "project_id": 2,
            "actual_cr": 0.05,
            "recorded_at": datetime(2026, 1, 1, tzinfo=UTC),
        },
    ])
    assert out["outcomes"][0]["outcome_id"] == 1
    assert out["outcomes"][0]["project_id"] == 2
    assert out["outcomes"][0]["actual_conversion_rate"] == 0.05
    assert "2026-01-01" in out["outcomes"][0]["created_at"]


def test_handles_naive_datetime():
    from app.simulation.recent_outcomes import build_recent_outcomes
    out = build_recent_outcomes([
        {
            "outcome_id": 1, "project_id": 1,
            "actual_conversion_rate": 0.05,
            "created_at": datetime(2026, 1, 1),
        },
    ])
    assert "2026-01-01" in out["outcomes"][0]["created_at"]


def test_handles_datetime_object():
    from app.simulation.recent_outcomes import build_recent_outcomes
    out = build_recent_outcomes([
        {
            "outcome_id": 1, "project_id": 1,
            "actual_conversion_rate": 0.05,
            "created_at": datetime(2026, 1, 5, tzinfo=UTC),
        },
    ])
    assert "2026-01-05" in out["outcomes"][0]["created_at"]


def test_skips_non_dict_entries():
    from app.simulation.recent_outcomes import build_recent_outcomes
    out = build_recent_outcomes([
        "not-a-dict",
        None,
        {
            "outcome_id": 1, "project_id": 1,
            "actual_conversion_rate": 0.05,
            "created_at": None,
        },
    ])
    assert out["outcome_count"] == 1


def test_severity_ok_at_3_outcomes():
    from app.simulation.recent_outcomes import (
        SIGNAL_OK,
        build_recent_outcomes,
    )
    out = build_recent_outcomes([
        {"outcome_id": i, "project_id": 1,
         "actual_conversion_rate": 0.01, "created_at": None}
        for i in range(3)
    ])
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_OK


def test_severity_watch_at_1_outcome():
    from app.simulation.recent_outcomes import (
        SIGNAL_WATCH,
        build_recent_outcomes,
    )
    out = build_recent_outcomes([
        {"outcome_id": 1, "project_id": 1,
         "actual_conversion_rate": 0.05, "created_at": None},
    ])
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_WATCH


def test_no_key_signal_when_empty():
    from app.simulation.recent_outcomes import build_recent_outcomes
    out = build_recent_outcomes()
    assert out["key_signals"] == []


def test_narrative_quiet_when_empty():
    from app.simulation.recent_outcomes import build_recent_outcomes
    out = build_recent_outcomes()
    assert "record a few" in out["narrative"].lower()


def test_narrative_best_and_worst_diff():
    from app.simulation.recent_outcomes import build_recent_outcomes
    out = build_recent_outcomes([
        {"outcome_id": 1, "project_id": 7,
         "actual_conversion_rate": 0.10, "created_at": None},
        {"outcome_id": 2, "project_id": 3,
         "actual_conversion_rate": 0.02, "created_at": None},
    ])
    assert "0.1" in out["narrative"]
    assert "0.02" in out["narrative"]
    assert "best" in out["narrative"].lower()
    assert "worst" in out["narrative"].lower()


def test_narrative_when_all_same():
    from app.simulation.recent_outcomes import build_recent_outcomes
    out = build_recent_outcomes([
        {"outcome_id": i, "project_id": 1,
         "actual_conversion_rate": 0.05, "created_at": None}
        for i in range(3)
    ])
    assert "best / worst same" in out["narrative"].lower()


def test_schema_default_shape():
    from app.schemas.project import RecentOutcomesOut
    out = RecentOutcomesOut()
    assert out.outcomes == []
    assert out.outcome_count == 0
    assert out.key_signals == []


def test_schema_round_trip():
    from app.schemas.project import RecentOutcomesOut
    from app.simulation.recent_outcomes import build_recent_outcomes
    payload = build_recent_outcomes([
        {
            "outcome_id": 1, "project_id": 1,
            "actual_conversion_rate": 0.05,
            "created_at": None,
        },
    ])
    out = RecentOutcomesOut(**payload)
    assert out.outcome_count == 1
    assert out.outcomes[0]["outcome_id"] == 1
