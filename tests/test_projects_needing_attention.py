"""Tests for the per-user projects-needing-attention helper."""
from __future__ import annotations


def test_public_allowlist_matches_callers():
    from app.simulation import projects_needing_attention
    assert set(projects_needing_attention.__all__) == {
        "REASON_STALE_SIM",
        "REASON_PENDING_DECISIONS",
        "REASON_LOW_OUTCOMES",
        "SIGNAL_OK", "SIGNAL_WATCH", "SIGNAL_CRITICAL",
        "build_projects_needing_attention",
    }


def test_default_empty_state():
    from app.simulation.projects_needing_attention import (
        build_projects_needing_attention,
    )
    out = build_projects_needing_attention()
    assert out["needing_attention_count"] == 0
    assert out["stale_count"] == 0
    assert out["projects"] == []


def test_picks_stale_projects():
    from app.simulation.projects_needing_attention import (
        REASON_STALE_SIM,
        build_projects_needing_attention,
    )
    out = build_projects_needing_attention([
        {"project_id": 1, "project_title": "Old",
         "status": "Stale"},
        {"project_id": 2, "project_title": "Fresh",
         "status": "Healthy"},
    ])
    assert out["needing_attention_count"] == 1
    assert out["stale_count"] == 1
    assert out["projects"][0]["project_id"] == 1
    assert out["projects"][0]["reason"] == REASON_STALE_SIM


def test_picks_action_needed_projects():
    from app.simulation.projects_needing_attention import (
        REASON_PENDING_DECISIONS,
        build_projects_needing_attention,
    )
    out = build_projects_needing_attention([
        {"project_id": 1, "project_title": "Pending",
         "status": "Action needed"},
    ])
    assert out["needing_attention_count"] == 1
    assert out["stale_count"] == 0
    assert out["projects"][0]["reason"] == REASON_PENDING_DECISIONS


def test_low_outcomes_overrides_action_needed_reason():
    from app.simulation.projects_needing_attention import (
        REASON_LOW_OUTCOMES,
        build_projects_needing_attention,
    )
    out = build_projects_needing_attention([
        {
            "project_id": 1, "project_title": "Low",
            "status": "Action needed",
            "sims_count": 10,
            "outcomes_count": 0,  # 0 < 10*0.5 = 5
        },
    ])
    assert out["projects"][0]["reason"] == REASON_LOW_OUTCOMES


def test_no_low_outcomes_when_outcome_count_above_threshold():
    from app.simulation.projects_needing_attention import (
        REASON_PENDING_DECISIONS,
        build_projects_needing_attention,
    )
    out = build_projects_needing_attention([
        {
            "project_id": 1, "project_title": "Healthy Ratio",
            "status": "Action needed",
            "sims_count": 10,
            "outcomes_count": 6,  # 6 >= 10*0.5 = 5
        },
    ])
    assert out["projects"][0]["reason"] == REASON_PENDING_DECISIONS


def test_skips_healthy_projects():
    from app.simulation.projects_needing_attention import (
        build_projects_needing_attention,
    )
    out = build_projects_needing_attention([
        {"project_id": 1, "project_title": "Good",
         "status": "Healthy"},
    ])
    assert out["needing_attention_count"] == 0


def test_skips_empty_projects():
    """Empty projects are "no attention needed" - they
    just need to be started."""
    from app.simulation.projects_needing_attention import (
        build_projects_needing_attention,
    )
    out = build_projects_needing_attention([
        {"project_id": 1, "project_title": "New",
         "status": "Empty"},
    ])
    assert out["needing_attention_count"] == 0


def test_skips_non_dict_entries():
    from app.simulation.projects_needing_attention import (
        build_projects_needing_attention,
    )
    out = build_projects_needing_attention([
        "not-a-dict",
        None,
        {"project_id": 1, "project_title": "X",
         "status": "Stale"},
    ])
    assert out["needing_attention_count"] == 1


def test_severity_critical_at_3_projects():
    from app.simulation.projects_needing_attention import (
        SIGNAL_CRITICAL,
        build_projects_needing_attention,
    )
    out = build_projects_needing_attention([
        {"project_id": i, "project_title": f"P{i}",
         "status": "Stale"}
        for i in range(1, 4)
    ])
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_CRITICAL


def test_severity_watch_at_1_project():
    from app.simulation.projects_needing_attention import (
        SIGNAL_WATCH,
        build_projects_needing_attention,
    )
    out = build_projects_needing_attention([
        {"project_id": 1, "project_title": "X",
         "status": "Stale"},
    ])
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_WATCH


def test_severity_ok_when_no_projects():
    from app.simulation.projects_needing_attention import (
        SIGNAL_OK,
        build_projects_needing_attention,
    )
    out = build_projects_needing_attention()
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_OK


def test_narrative_quiet_when_zero():
    from app.simulation.projects_needing_attention import (
        build_projects_needing_attention,
    )
    out = build_projects_needing_attention()
    assert "good shape" in out["narrative"].lower()


def test_narrative_includes_breakdown():
    from app.simulation.projects_needing_attention import (
        build_projects_needing_attention,
    )
    out = build_projects_needing_attention([
        {"project_id": 1, "project_title": "X",
         "status": "Stale"},
        {"project_id": 2, "project_title": "Y",
         "status": "Action needed"},
    ])
    n = out["narrative"].lower()
    assert "1 stale" in n
    assert "1 action-needed" in n


def test_schema_default_shape():
    from app.schemas.user import ProjectsNeedingAttentionOut
    out = ProjectsNeedingAttentionOut()
    assert out.needing_attention_count == 0
    assert out.stale_count == 0
    assert out.projects == []
    assert out.key_signals == []


def test_schema_round_trip():
    from app.schemas.user import ProjectsNeedingAttentionOut
    from app.simulation.projects_needing_attention import (
        build_projects_needing_attention,
    )
    payload = build_projects_needing_attention([
        {"project_id": 1, "project_title": "X",
         "status": "Stale"},
    ])
    out = ProjectsNeedingAttentionOut(**payload)
    assert out.needing_attention_count == 1
    assert out.stale_count == 1
