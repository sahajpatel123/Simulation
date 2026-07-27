"""Tests for the per-user last-touched-project helper."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


def test_public_allowlist_matches_callers():
    from app.simulation import last_touched_project
    assert set(last_touched_project.__all__) == {
        "SIGNAL_OK", "SIGNAL_WATCH",
        "build_last_touched_project",
    }


def test_default_empty_state():
    from app.simulation.last_touched_project import (
        build_last_touched_project,
    )
    out = build_last_touched_project()
    assert out["has_activity"] is False
    assert out["project_id"] is None
    assert out["last_activity_at"] is None
    assert out["last_activity_type"] is None


def test_picks_most_recent_across_types():
    from app.simulation.last_touched_project import (
        build_last_touched_project,
    )
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    out = build_last_touched_project([
        {
            "project_id": 1, "project_title": "A",
            "activity_type": "sim",
            "activity_at": now - timedelta(days=5),
        },
        {
            "project_id": 2, "project_title": "B",
            "activity_type": "decision",
            "activity_at": now - timedelta(days=1),  # newest
        },
        {
            "project_id": 3, "project_title": "C",
            "activity_type": "outcome",
            "activity_at": now - timedelta(days=3),
        },
    ])
    assert out["has_activity"] is True
    assert out["project_id"] == 2
    assert out["project_title"] == "B"
    assert out["last_activity_type"] == "decision"


def test_handles_iso_string_activity_at():
    from app.simulation.last_touched_project import (
        build_last_touched_project,
    )
    out = build_last_touched_project([
        {
            "project_id": 1, "project_title": "A",
            "activity_type": "sim",
            "activity_at": "2026-06-01T00:00:00+00:00",
        },
        {
            "project_id": 2, "project_title": "B",
            "activity_type": "outcome",
            "activity_at": "2026-06-05T00:00:00+00:00",
        },
    ])
    assert out["project_id"] == 2


def test_handles_naive_datetime():
    from app.simulation.last_touched_project import (
        build_last_touched_project,
    )
    out = build_last_touched_project([
        {
            "project_id": 1, "project_title": "A",
            "activity_type": "sim",
            "activity_at": datetime(2026, 6, 1),  # naive
        },
    ])
    assert out["has_activity"] is True


def test_skips_entries_with_invalid_datetime():
    from app.simulation.last_touched_project import (
        build_last_touched_project,
    )
    out = build_last_touched_project([
        {
            "project_id": 1, "project_title": "A",
            "activity_type": "sim",
            "activity_at": "not-a-date",
        },
        {
            "project_id": 2, "project_title": "B",
            "activity_type": "decision",
            "activity_at": "2026-06-05T00:00:00+00:00",
        },
    ])
    assert out["project_id"] == 2


def test_skips_non_dict_entries():
    from app.simulation.last_touched_project import (
        build_last_touched_project,
    )
    out = build_last_touched_project([
        "not-a-dict",
        None,
        {
            "project_id": 1, "project_title": "A",
            "activity_type": "sim",
            "activity_at": "2026-06-01T00:00:00+00:00",
        },
    ])
    assert out["project_id"] == 1


def test_picks_sim_over_decision_when_same_time():
    """Stable iteration order: ties resolve to first
    seen (no sort on activity_type)."""
    from app.simulation.last_touched_project import (
        build_last_touched_project,
    )
    out = build_last_touched_project([
        {
            "project_id": 1, "project_title": "Sim Project",
            "activity_type": "sim",
            "activity_at": "2026-06-05T00:00:00+00:00",
        },
        {
            "project_id": 2, "project_title": "Decision Project",
            "activity_type": "decision",
            "activity_at": "2026-06-05T00:00:00+00:00",
        },
    ])
    # First activity_at wins on tie (helper is "if dt > best_dt").
    # For equal timestamps, the FIRST entry is kept.
    assert out["project_id"] == 1


def test_narrative_mentions_winning_project():
    from app.simulation.last_touched_project import (
        build_last_touched_project,
    )
    out = build_last_touched_project([
        {
            "project_id": 7, "project_title": "DevTwin",
            "activity_type": "sim",
            "activity_at": "2026-06-01T00:00:00+00:00",
        },
    ])
    assert "DevTwin" in out["narrative"]


def test_narrative_quiet_message():
    from app.simulation.last_touched_project import (
        build_last_touched_project,
    )
    out = build_last_touched_project([])
    assert "No project activity" in out["narrative"]


def test_key_signal_present():
    from app.simulation.last_touched_project import (
        build_last_touched_project,
    )
    out = build_last_touched_project([
        {
            "project_id": 1, "project_title": "A",
            "activity_type": "sim",
            "activity_at": "2026-06-01T00:00:00+00:00",
        },
    ])
    assert out["key_signals"][0]["label"] == "has_activity"


def test_schema_default_shape():
    from app.schemas.user import LastTouchedProjectOut
    out = LastTouchedProjectOut()
    assert out.has_activity is False
    assert out.project_id is None
    assert out.key_signals == []


def test_schema_round_trip():
    from app.schemas.user import LastTouchedProjectOut
    from app.simulation.last_touched_project import (
        build_last_touched_project,
    )
    payload = build_last_touched_project([
        {
            "project_id": 1, "project_title": "X",
            "activity_type": "sim",
            "activity_at": "2026-06-01T00:00:00+00:00",
        },
    ])
    out = LastTouchedProjectOut(**payload)
    assert out.project_id == 1
    assert out.project_title == "X"
    assert out.has_activity is True
