"""Tests for the per-user projects summary helper."""
from __future__ import annotations

import pytest


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import projects_summary

    assert set(projects_summary.__all__) == {
        "MAX_PROJECTS",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_projects_summary",
    }


def test_summary_empty_returns_zero_state() -> None:
    from app.simulation.projects_summary import build_projects_summary

    out = build_projects_summary([])
    assert out["project_count"] == 0
    assert out["projects"] == []
    assert out["sim_count_total"] == 0


def test_summary_passes_through_per_project_fields() -> None:
    from app.simulation.projects_summary import build_projects_summary

    summaries = [
        {
            "id": 1, "title": "Project A", "status": "COMPLETE",
            "brief_completed": True,
            "latest_sim_conversion_rate": 0.042,
            "latest_sim_status": "COMPLETED",
            "latest_sim_created_at": "2026-01-05T00:00:00Z",
            "sim_count": 3, "decision_count": 1, "outcome_count": 0,
        },
    ]
    out = build_projects_summary(summaries)
    assert out["project_count"] == 1
    card = out["projects"][0]
    assert card["id"] == 1
    assert card["title"] == "Project A"
    assert card["brief_completed"] is True
    assert card["latest_sim_conversion_rate"] == 0.042
    assert card["sim_count"] == 3


def test_summary_aggregates_total_counts() -> None:
    from app.simulation.projects_summary import build_projects_summary

    summaries = [
        {"id": i, "title": f"p{i}", "sim_count": 2,
         "decision_count": 1, "outcome_count": 1}
        for i in range(3)
    ]
    out = build_projects_summary(summaries)
    assert out["sim_count_total"] == 6
    assert out["decision_count_total"] == 3
    assert out["outcome_count_total"] == 3


def test_summary_capped_at_max() -> None:
    from app.simulation.projects_summary import (
        MAX_PROJECTS,
        build_projects_summary,
    )

    summaries = [
        {"id": i, "title": f"p{i}"}
        for i in range(MAX_PROJECTS + 10)
    ]
    out = build_projects_summary(summaries)
    assert len(out["projects"]) == MAX_PROJECTS


def test_summary_handles_non_dict_entries() -> None:
    from app.simulation.projects_summary import build_projects_summary

    out = build_projects_summary([
        "not-a-dict",
        None,
        {"id": 1, "title": "ok"},
    ])
    assert out["project_count"] == 1


def test_summary_skips_projects_with_no_sim() -> None:
    from app.simulation.projects_summary import build_projects_summary

    out = build_projects_summary([
        {"id": 1, "title": "New"},  # no sim_count / latest
    ])
    card = out["projects"][0]
    assert card["sim_count"] == 0
    assert card["latest_sim_conversion_rate"] is None


def test_summary_narrative_mentions_counts() -> None:
    from app.simulation.projects_summary import build_projects_summary

    out = build_projects_summary([
        {"id": 1, "brief_completed": True, "sim_count": 5,
         "decision_count": 2, "outcome_count": 1},
    ])
    n = out["narrative"].lower()
    assert "5 sim" in n
    assert "2 decision" in n
    assert "1 outcome" in n


def test_summary_schema_default_shape() -> None:
    from app.schemas.user import ProjectsSummaryOut

    out = ProjectsSummaryOut()
    assert out.project_count == 0
    assert out.projects == []
    assert out.sim_count_total == 0


def test_summary_schema_round_trip() -> None:
    from app.schemas.user import ProjectsSummaryOut
    from app.simulation.projects_summary import build_projects_summary

    payload = build_projects_summary([
        {"id": 1, "title": "X", "sim_count": 5},
    ])
    out = ProjectsSummaryOut(**payload)
    assert out.projects[0]["id"] == 1
    assert out.sim_count_total == 5