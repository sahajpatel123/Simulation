"""Tests for the per-user most-active-project helper."""
from __future__ import annotations


def test_public_allowlist_matches_callers():
    from app.simulation import most_active_project
    assert set(most_active_project.__all__) == {
        "SIGNAL_OK", "SIGNAL_WATCH",
        "build_most_active_project",
    }


def test_empty_returns_zero_state():
    from app.simulation.most_active_project import (
        build_most_active_project,
    )
    out = build_most_active_project([])
    assert out["has_activity"] is False
    assert out["project_id"] is None
    assert out["total_actions_7d"] == 0


def test_picks_highest_total():
    """Test the 3-tuple shape (precomputed total)."""
    from app.simulation.most_active_project import (
        build_most_active_project,
    )
    out = build_most_active_project([
        (1, "A", 3),
        (2, "B", 5),
        (3, "C", 1),
    ])
    assert out["has_activity"] is True
    assert out["project_id"] == 2
    assert out["project_title"] == "B"
    assert out["total_actions_7d"] == 5


def test_sums_sim_decision_outcome():
    """Test the 5-tuple shape (raw counts)."""
    from app.simulation.most_active_project import (
        build_most_active_project,
    )
    out = build_most_active_project([
        (1, "A", 2, 1, 0),  # total = 3
        (2, "B", 1, 2, 1),  # total = 4
    ])
    assert out["project_id"] == 2
    assert out["total_actions_7d"] == 4


def test_zero_total_not_picked():
    """All zeros → no activity (don't surface a
    meaningless winner)."""
    from app.simulation.most_active_project import (
        build_most_active_project,
    )
    out = build_most_active_project([
        (1, "A", 0),
        (2, "B", 0),
    ])
    assert out["has_activity"] is False
    assert out["total_actions_7d"] == 0


def test_skips_non_list_entries():
    from app.simulation.most_active_project import (
        build_most_active_project,
    )
    out = build_most_active_project([
        "not-a-list",
        None,
        (1, "A", 3),
    ])
    assert out["project_id"] == 1


def test_skips_short_entries():
    from app.simulation.most_active_project import (
        build_most_active_project,
    )
    out = build_most_active_project([
        (1,),  # too short
        (1, "A"),  # too short
        (1, "A", 3),  # OK
    ])
    assert out["project_id"] == 1


def test_tiebreak_picks_first():
    from app.simulation.most_active_project import (
        build_most_active_project,
    )
    out = build_most_active_project([
        (1, "A", 3),
        (2, "B", 3),  # tied
    ])
    # First entry with the max wins (stable iteration).
    assert out["project_id"] == 1


def test_narrative_quiet_week():
    from app.simulation.most_active_project import (
        build_most_active_project,
    )
    out = build_most_active_project([])
    assert "No sims" in out["narrative"]


def test_narrative_mentions_winning_project():
    from app.simulation.most_active_project import (
        build_most_active_project,
    )
    out = build_most_active_project([
        (1, "DevTwin", 5),
    ])
    assert "DevTwin" in out["narrative"]
    assert "5 action" in out["narrative"]


def test_key_signals_present():
    from app.simulation.most_active_project import (
        build_most_active_project,
    )
    out = build_most_active_project([
        (1, "A", 5),
    ])
    labels = {s["label"] for s in out["key_signals"]}
    assert "has_activity" in labels
    assert "total_actions_7d" in labels


def test_no_total_signal_when_zero():
    from app.simulation.most_active_project import (
        build_most_active_project,
    )
    out = build_most_active_project([])
    labels = {s["label"] for s in out["key_signals"]}
    assert "total_actions_7d" not in labels


def test_schema_default_shape():
    from app.schemas.user import MostActiveProjectOut
    out = MostActiveProjectOut()
    assert out.has_activity is False
    assert out.project_id is None
    assert out.total_actions_7d == 0


def test_schema_round_trip():
    from app.schemas.user import MostActiveProjectOut
    from app.simulation.most_active_project import (
        build_most_active_project,
    )
    payload = build_most_active_project([
        (1, "X", 5),
    ])
    out = MostActiveProjectOut(**payload)
    assert out.project_id == 1
    assert out.project_title == "X"
    assert out.has_activity is True
