"""Tests for the per-project export helper + schema.

The helper is pure-Python so it can be exercised without
a DB.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import project_export

    assert set(project_export.__all__) == {
        "build_project_export",
    }


def test_export_empty_input() -> None:
    from app.simulation.project_export import build_project_export

    out = build_project_export(
        project_row={},
        brief_dict=None,
        assumption_dicts=None,
        simulation_dicts=None,
        decision_dicts=None,
        outcome_dicts=None,
        premortem_data=None,
        interventions_data=None,
    )
    assert out["exported_at"] != ""
    assert out["schema_version"] == 1
    assert out["project_meta"] == {}
    assert out["brief"] == {}
    assert out["assumptions"] == []
    assert out["simulations"] == []
    assert out["decisions"] == []
    assert out["outcomes"] == []
    assert out["premortem"] == {}
    assert out["interventions"] == {}


def test_export_includes_project_meta() -> None:
    from app.simulation.project_export import build_project_export

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = build_project_export(
        project_row={
            "id": 1,
            "title": "Test project",
            "description": "...",
            "status": "BRIEF_COMPLETE",
            "intake_mode": "IDEA",
            "created_at": now,
            "updated_at": now,
        },
        brief_dict=None,
        assumption_dicts=None,
        simulation_dicts=None,
        decision_dicts=None,
        outcome_dicts=None,
        premortem_data=None,
        interventions_data=None,
    )
    assert out["project_meta"]["id"] == 1
    assert out["project_meta"]["title"] == "Test project"
    assert "2026-01-01" in out["project_meta"]["created_at"]


def test_export_includes_brief() -> None:
    from app.simulation.project_export import build_project_export

    out = build_project_export(
        project_row={},
        brief_dict={
            "positioning": "For devs",
            "features": ["a", "b"],
            "hook": "Save 10 hours/week",
            "completed_at": "2026-01-01T00:00:00Z",
        },
        assumption_dicts=None,
        simulation_dicts=None,
        decision_dicts=None,
        outcome_dicts=None,
        premortem_data=None,
        interventions_data=None,
    )
    assert out["brief"]["positioning"] == "For devs"
    assert out["brief"]["features"] == ["a", "b"]


def test_export_brief_defaults_when_missing() -> None:
    from app.simulation.project_export import build_project_export

    out = build_project_export(
        project_row={},
        brief_dict=None,
        assumption_dicts=None,
        simulation_dicts=None,
        decision_dicts=None,
        outcome_dicts=None,
        premortem_data=None,
        interventions_data=None,
    )
    assert out["brief"]["positioning"] == ""
    assert out["brief"]["features"] == []


def test_export_normalises_assumptions() -> None:
    from app.simulation.project_export import build_project_export

    out = build_project_export(
        project_row={},
        brief_dict=None,
        assumption_dicts=[
            {
                "id": 1, "text": "Devs want speed",
                "category": "Market",
                "sensitivity": "HIGH",
                "impact_score": 8.0,
                "is_hidden": False,
                "created_at": "2026-01-01T00:00:00Z",
            },
        ],
        simulation_dicts=None,
        decision_dicts=None,
        outcome_dicts=None,
        premortem_data=None,
        interventions_data=None,
    )
    a = out["assumptions"][0]
    assert a["text"] == "Devs want speed"
    assert a["impact_score"] == 8.0
    assert a["is_hidden"] is False


def test_export_skips_non_dict_assumptions() -> None:
    from app.simulation.project_export import build_project_export

    out = build_project_export(
        project_row={},
        brief_dict=None,
        assumption_dicts=[
            "not-a-dict",
            None,
            {"id": 1, "text": "x", "category": "y",
             "sensitivity": "MEDIUM", "impact_score": 5,
             "is_hidden": False, "created_at": "2026-01-01T00:00:00Z"},
        ],
        simulation_dicts=None,
        decision_dicts=None,
        outcome_dicts=None,
        premortem_data=None,
        interventions_data=None,
    )
    assert len(out["assumptions"]) == 1


def test_export_normalises_simulations() -> None:
    from app.simulation.project_export import build_project_export

    out = build_project_export(
        project_row={},
        brief_dict=None,
        assumption_dicts=None,
        simulation_dicts=[
            {
                "id": 1, "status": "COMPLETED",
                "predicted_conversion_rate": 0.042,
                "actual_conversion_rate": 0.051,
                "results_json": {
                    "mean_conversion_rate": 0.042,
                    "revenue_projection": 420000,
                },
                "confidence_score": 0.85,
                "created_at": "2026-01-05T00:00:00Z",
            },
        ],
        decision_dicts=None,
        outcome_dicts=None,
        premortem_data=None,
        interventions_data=None,
    )
    s = out["simulations"][0]
    assert s["predicted_conversion_rate"] == 0.042
    assert s["actual_conversion_rate"] == 0.051
    assert s["mean_conversion_rate"] == 0.042
    assert s["revenue_projection"] == 420000
    assert s["confidence_score"] == 0.85


def test_export_includes_premortem_and_interventions() -> None:
    from app.simulation.project_export import build_project_export

    out = build_project_export(
        project_row={},
        brief_dict=None,
        assumption_dicts=None,
        simulation_dicts=None,
        decision_dicts=None,
        outcome_dicts=None,
        premortem_data={
            "failure_modes": [{"title": "x", "severity": "CRITICAL"}],
        },
        interventions_data={
            "interventions": [{"title": "Cut price"}],
        },
    )
    assert "failure_modes" in out["premortem"]
    assert "interventions" in out["interventions"]


def test_export_decisions_and_outcomes_pass_through() -> None:
    from app.simulation.project_export import build_project_export

    out = build_project_export(
        project_row={},
        brief_dict=None,
        assumption_dicts=None,
        simulation_dicts=None,
        decision_dicts=[
            {"id": 1, "title": "Pivot?",
             "status": "COMPLETED",
             "created_at": "2026-01-01T00:00:00Z"},
        ],
        outcome_dicts=[
            {"id": 1, "actual_conversion_rate": 0.051,
             "actual_mrr": 50000, "calibration_score": 80,
             "created_at": "2026-01-02T00:00:00Z"},
        ],
        premortem_data=None,
        interventions_data=None,
    )
    assert out["decisions"][0]["title"] == "Pivot?"
    assert out["outcomes"][0]["calibration_score"] == 80


def test_export_schema_default_shape() -> None:
    from app.schemas.project import ProjectExportOut

    out = ProjectExportOut()
    assert out.exported_at == ""
    assert out.schema_version == 1
    assert out.project_meta == {}
    assert out.premortem == {}
    assert out.interventions == {}


def test_export_schema_round_trips_helper_payload() -> None:
    from app.schemas.project import ProjectExportOut
    from app.simulation.project_export import build_project_export

    payload = build_project_export(
        project_row={"id": 1, "title": "Test"},
        brief_dict=None,
        assumption_dicts=None,
        simulation_dicts=None,
        decision_dicts=None,
        outcome_dicts=None,
        premortem_data=None,
        interventions_data=None,
    )
    out = ProjectExportOut(**payload)
    assert out.project_meta["title"] == "Test"