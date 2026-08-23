"""Tests for the per-user projects-by-status helper."""
from __future__ import annotations



def test_public_allowlist_matches_callers() -> None:
    from app.simulation import projects_by_status

    assert set(projects_by_status.__all__) == {
        "ACTIONABLE_STATUSES",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_projects_by_status",
    }


def test_empty_returns_zero_state() -> None:
    from app.simulation.projects_by_status import build_projects_by_status

    out = build_projects_by_status([])
    assert out["project_count"] == 0
    assert out["status_breakdown"] == {}
    assert out["most_common_status"] is None


def test_aggregates_per_status() -> None:
    from app.simulation.projects_by_status import build_projects_by_status

    out = build_projects_by_status([
        ("COMPLETE", 3),
        ("BRIEF", 1),
        ("RUNNING", 2),
    ])
    assert out["project_count"] == 6
    assert out["status_breakdown"]["COMPLETE"] == 3
    assert out["status_breakdown"]["BRIEF"] == 1
    assert out["status_breakdown"]["RUNNING"] == 2


def test_most_common_picks_highest_count() -> None:
    from app.simulation.projects_by_status import build_projects_by_status

    out = build_projects_by_status([
        ("COMPLETE", 5),
        ("RUNNING", 2),
    ])
    assert out["most_common_status"] == "COMPLETE"


def test_actionable_count_when_PRESENT() -> None:
    """PENDING + RUNNING count as actionable."""
    from app.simulation.projects_by_status import build_projects_by_status

    out = build_projects_by_status([
        ("COMPLETE", 5),
        ("RUNNING", 2),
        ("PENDING", 1),
    ])
    assert out["actionable_count"] == 3


def test_no_actionable_signal_when_zero() -> None:
    from app.simulation.projects_by_status import build_projects_by_status

    out = build_projects_by_status([
        ("COMPLETE", 5),
    ])
    assert out["actionable_count"] == 0
    labels = {s["label"] for s in out["key_signals"]}
    assert "actionable_count" not in labels


def test_handles_list_and_tuple_entries() -> None:
    from app.simulation.projects_by_status import build_projects_by_status

    out = build_projects_by_status([
        ("A", 2),
        ["B", 3],
    ])
    assert out["status_breakdown"]["A"] == 2
    assert out["status_breakdown"]["B"] == 3


def test_skips_non_tuple_entries() -> None:
    from app.simulation.projects_by_status import build_projects_by_status

    out = build_projects_by_status([
        "not-a-tuple",
        None,
        ("COMPLETE", 1),
    ])
    assert out["project_count"] == 1


def test_skips_empty_status() -> None:
    from app.simulation.projects_by_status import build_projects_by_status

    out = build_projects_by_status([
        ("", 5),
        ("COMPLETE", 1),
    ])
    assert out["project_count"] == 1


def test_narrative_mentions_most_common() -> None:
    from app.simulation.projects_by_status import build_projects_by_status

    out = build_projects_by_status([
        ("COMPLETE", 5),
        ("RUNNING", 2),
    ])
    assert "COMPLETE" in out["narrative"]


def test_schema_default_shape() -> None:
    from app.schemas.user import ProjectsByStatusOut

    out = ProjectsByStatusOut()
    assert out.project_count == 0
    assert out.status_breakdown == {}
    assert out.most_common_status is None
    assert out.actionable_count == 0


def test_schema_round_trip() -> None:
    from app.schemas.user import ProjectsByStatusOut
    from app.simulation.projects_by_status import (
        build_projects_by_status,
    )

    payload = build_projects_by_status([
        ("RUNNING", 3), ("COMPLETE", 1),
    ])
    out = ProjectsByStatusOut(**payload)
    assert out.project_count == 4
    assert out.status_breakdown["RUNNING"] == 3
    assert out.most_common_status == "RUNNING"
    assert out.actionable_count == 3