"""Tests for the per-user recent-decisions helper."""
from __future__ import annotations

from datetime import UTC, datetime


def test_public_allowlist_matches_callers():
    from app.simulation import recent_decisions
    assert set(recent_decisions.__all__) == {
        "MAX_RECENT", "SIGNAL_OK", "SIGNAL_WATCH",
        "SIGNAL_CRITICAL", "build_recent_decisions",
    }


def test_default_empty_state():
    from app.simulation.recent_decisions import (
        build_recent_decisions,
    )
    out = build_recent_decisions()
    assert out["decisions"] == []
    assert out["decision_count"] == 0
    assert out["key_signals"] == []


def test_caps_at_max_recent():
    from app.simulation.recent_decisions import (
        build_recent_decisions,
    )
    out = build_recent_decisions([
        {"decision_id": i, "project_id": 1,
         "title": f"D{i}", "status": "PENDING",
         "created_at": None}
        for i in range(1, 10)
    ])
    assert len(out["decisions"]) == 5  # MAX_RECENT = 5


def test_normalizes_alternate_field_names():
    from app.simulation.recent_decisions import (
        build_recent_decisions,
    )
    out = build_recent_decisions([
        {
            "id": 1, "project_id": 2,
            "title": "Pivot?",
            "status": "PENDING",
            "created_at": datetime(
                2026, 1, 1, tzinfo=UTC
            ),
        },
    ])
    assert out["decisions"][0]["decision_id"] == 1
    assert out["decisions"][0]["title"] == "Pivot?"
    assert "2026-01-01" in out["decisions"][0]["created_at"]


def test_handles_naive_datetime():
    from app.simulation.recent_decisions import (
        build_recent_decisions,
    )
    out = build_recent_decisions([
        {"decision_id": 1, "project_id": 1,
         "title": "T", "status": "PENDING",
         "created_at": datetime(2026, 1, 1)},
    ])
    assert "2026-01-01" in out["decisions"][0]["created_at"]


def test_handles_unknown_status():
    from app.simulation.recent_decisions import (
        build_recent_decisions,
    )
    out = build_recent_decisions([
        {"decision_id": 1, "project_id": 1,
         "title": "T", "status": "MAYBE",
         "created_at": None},
    ])
    assert out["decisions"][0]["status"] == "MAYBE"


def test_skips_non_dict_entries():
    from app.simulation.recent_decisions import (
        build_recent_decisions,
    )
    out = build_recent_decisions([
        "not-a-dict",
        None,
        {"decision_id": 1, "project_id": 1,
         "title": "T", "status": "PENDING",
         "created_at": None},
    ])
    assert out["decision_count"] == 1


def test_skips_missing_status():
    from app.simulation.recent_decisions import (
        build_recent_decisions,
    )
    out = build_recent_decisions([
        {"decision_id": 1, "project_id": 1,
         "title": "T", "created_at": None},
    ])
    assert out["decisions"][0]["status"] == "UNKNOWN"


def test_severity_ok_when_no_pending():
    from app.simulation.recent_decisions import (
        SIGNAL_OK,
        build_recent_decisions,
    )
    out = build_recent_decisions([
        {"decision_id": 1, "project_id": 1,
         "title": "T", "status": "COMPLETED",
         "created_at": None},
    ])
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_OK


def test_severity_watch_when_1_pending():
    from app.simulation.recent_decisions import (
        SIGNAL_WATCH,
        build_recent_decisions,
    )
    out = build_recent_decisions([
        {"decision_id": 1, "project_id": 1,
         "title": "T", "status": "PENDING",
         "created_at": None},
    ])
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_WATCH


def test_severity_critical_when_2_plus_pending():
    from app.simulation.recent_decisions import (
        SIGNAL_CRITICAL,
        build_recent_decisions,
    )
    out = build_recent_decisions([
        {"decision_id": 1, "project_id": 1,
         "title": "T1", "status": "PENDING",
         "created_at": None},
        {"decision_id": 2, "project_id": 1,
         "title": "T2", "status": "PENDING",
         "created_at": None},
    ])
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_CRITICAL


def test_no_key_signal_when_empty():
    from app.simulation.recent_decisions import (
        build_recent_decisions,
    )
    out = build_recent_decisions()
    assert out["key_signals"] == []


def test_narrative_all_resolved():
    from app.simulation.recent_decisions import (
        build_recent_decisions,
    )
    out = build_recent_decisions([
        {"decision_id": 1, "project_id": 1,
         "title": "T1", "status": "COMPLETED",
         "created_at": None},
        {"decision_id": 2, "project_id": 1,
         "title": "T2", "status": "COMPLETED",
         "created_at": None},
    ])
    assert "all resolved" in out["narrative"].lower()


def test_narrative_with_pending():
    from app.simulation.recent_decisions import (
        build_recent_decisions,
    )
    out = build_recent_decisions([
        {"decision_id": 1, "project_id": 1,
         "title": "T1", "status": "PENDING",
         "created_at": None},
        {"decision_id": 2, "project_id": 1,
         "title": "T2", "status": "COMPLETED",
         "created_at": None},
    ])
    assert "1 pending" in out["narrative"].lower()


def test_narrative_quiet_when_empty():
    from app.simulation.recent_decisions import (
        build_recent_decisions,
    )
    out = build_recent_decisions()
    assert "decisions" in out["narrative"].lower()


def test_schema_default_shape():
    from app.schemas.project import RecentDecisionsOut
    out = RecentDecisionsOut()
    assert out.decisions == []
    assert out.decision_count == 0
    assert out.key_signals == []


def test_schema_round_trip():
    from app.schemas.project import RecentDecisionsOut
    from app.simulation.recent_decisions import (
        build_recent_decisions,
    )
    payload = build_recent_decisions([
        {"decision_id": 1, "project_id": 1,
         "title": "T1", "status": "PENDING",
         "created_at": None},
    ])
    out = RecentDecisionsOut(**payload)
    assert out.decision_count == 1
    assert out.decisions[0]["decision_id"] == 1
