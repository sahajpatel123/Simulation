"""Tests for the project-level go/no-go digest helper.

The helper is pure-Python so it can be exercised without a DB.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta


def _now() -> datetime:
    return datetime.now(UTC)


def _full_inputs(now: datetime) -> dict:
    """A strong, healthy project: every pillar scores >= 70."""
    return {
        "readiness": {
            "readiness_score": 0.92,
            "verdict": "READY",
            "recommendations": ["Fix pricing page copy"],
        },
        "premortem": {
            "premortem_count": 3,
            "severity_breakdown": {
                "CRITICAL": 0,
                "HIGH": 1,
                "MEDIUM": 2,
                "LOW": 0,
            },
            "top_failure_modes": [{"title": "Competitors copy us fast"}],
        },
        "competitive": {
            "overall_competitive_position": "MODERATE",
            "high_threat_count": 1,
        },
        "trust": {"trust_score": 0.93, "verdict": "PASS"},
        "freshness": {
            "latest_sim_completed_at": (
                now - timedelta(days=2)
            ).isoformat(),
            "latest_assumption_at": (
                now - timedelta(days=5)
            ).isoformat(),
            "latest_outcome_at": (
                now - timedelta(days=3)
            ).isoformat(),
        },
        "coverage": {
            "total_assumption_count": 8,
            "missing_categories": ["Support"],
            "sensitivity_breakdown": {"HIGH": 2, "MEDIUM": 4},
        },
    }


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import go_no_go

    assert set(go_no_go.__all__) == {
        "PILLAR_WEIGHTS",
        "PILLAR_LABELS",
        "MIN_AVAILABLE_PILLARS",
        "GO_MIN_SCORE",
        "CONDITIONAL_GO_MIN_SCORE",
        "VERDICT_GO",
        "VERDICT_CONDITIONAL_GO",
        "VERDICT_NO_GO",
        "VERDICT_INSUFFICIENT",
        "VERDICT_LABELS",
        "READINESS_GATE_SCORE",
        "RISK_GATE_MAX_CRITICAL",
        "TRUST_GATE_MIN_SCORE",
        "FRESHNESS_GATE_MAX_CRITICAL_SOURCES",
        "COVERAGE_GATE_MAX_MISSING",
        "build_go_no_go",
    }


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


def test_empty_input_is_insufficient_data() -> None:
    from app.simulation.go_no_go import (
        VERDICT_INSUFFICIENT,
        build_go_no_go,
    )

    out = build_go_no_go(project_id=7)
    assert out.project_id == 7
    assert out.latest_simulation_id is None
    assert out.go_no_go_score is None
    assert out.verdict == VERDICT_INSUFFICIENT
    assert len(out.pillars) == 6
    assert len(out.gates) == 5
    assert all(g.evaluated is False for g in out.gates)
    assert out.meta["available_pillars"] == []


# ---------------------------------------------------------------------------
# Strong project -> GO
# ---------------------------------------------------------------------------


def test_full_strong_inputs_give_go() -> None:
    from app.simulation.go_no_go import (
        VERDICT_GO,
        build_go_no_go,
    )

    now = _now()
    out = build_go_no_go(
        **_full_inputs(now),
        project_id=7,
        latest_simulation_id=11,
        now=now,
    )
    assert out.verdict == VERDICT_GO
    assert out.latest_simulation_id == 11
    assert out.go_no_go_score is not None and out.go_no_go_score >= 75
    assert all(g.passed for g in out.gates if g.evaluated)
    assert out.meta["gate_summary"]["failed"] == 0
    assert any("Launch readiness" in s for s in out.strengths)
    assert out.top_actions
    assert out.narrative


def test_go_requires_all_evaluated_gates_to_pass() -> None:
    from app.simulation.go_no_go import (
        VERDICT_CONDITIONAL_GO,
        build_go_no_go,
    )

    now = _now()
    inputs = _full_inputs(now)
    # High score everywhere, but 2 CRITICAL premortem modes fail the
    # risk gate -> verdict capped at CONDITIONAL_GO.
    inputs["premortem"] = {
        "premortem_count": 4,
        "severity_breakdown": {"CRITICAL": 2, "HIGH": 2},
    }
    inputs["competitive"] = {
        "overall_competitive_position": "STRONG",
        "high_threat_count": 0,
    }
    out = build_go_no_go(
        **inputs,
        project_id=7,
        latest_simulation_id=11,
        now=now,
    )
    assert out.go_no_go_score is not None and out.go_no_go_score >= 75
    assert out.verdict == VERDICT_CONDITIONAL_GO
    risk_gate = next(g for g in out.gates if g.id == "risk_gate")
    assert risk_gate.evaluated is True
    assert risk_gate.passed is False


# ---------------------------------------------------------------------------
# Verdict bands
# ---------------------------------------------------------------------------


def test_moderate_inputs_give_conditional_go() -> None:
    from app.simulation.go_no_go import (
        VERDICT_CONDITIONAL_GO,
        build_go_no_go,
    )

    now = _now()
    inputs = _full_inputs(now)
    inputs["readiness"] = {"readiness_score": 0.62, "verdict": "NEEDS_WORK"}
    inputs["competitive"] = {
        "overall_competitive_position": "WEAK",
        "high_threat_count": 2,
    }
    inputs["coverage"] = {
        "total_assumption_count": 6,
        "missing_categories": ["Support", "Competitive"],
        "sensitivity_breakdown": {"MEDIUM": 4},
    }
    out = build_go_no_go(
        **inputs,
        project_id=7,
        latest_simulation_id=11,
        now=now,
    )
    assert 50 <= (out.go_no_go_score or 0) < 75
    assert out.verdict == VERDICT_CONDITIONAL_GO


def test_weak_inputs_give_no_go() -> None:
    from app.simulation.go_no_go import (
        VERDICT_NO_GO,
        build_go_no_go,
    )

    now = _now()
    inputs = _full_inputs(now)
    inputs["readiness"] = {"readiness_score": 0.2, "verdict": "NOT_READY"}
    inputs["premortem"] = {
        "premortem_count": 6,
        "severity_breakdown": {"CRITICAL": 3, "HIGH": 3},
    }
    inputs["competitive"] = {
        "overall_competitive_position": "WEAK",
        "high_threat_count": 4,
    }
    inputs["trust"] = {"trust_score": 0.3, "verdict": "FAIL"}
    inputs["coverage"] = {
        "total_assumption_count": 2,
        "missing_categories": [
            "Market",
            "Pricing",
            "Trust",
            "Retention",
            "Support",
            "Competitive",
        ],
        "sensitivity_breakdown": {"LOW": 2},
    }
    out = build_go_no_go(
        **inputs,
        project_id=7,
        latest_simulation_id=11,
        now=now,
    )
    assert out.verdict == VERDICT_NO_GO
    assert (out.go_no_go_score or 100) < 50
    assert out.risks


# ---------------------------------------------------------------------------
# Insufficient data
# ---------------------------------------------------------------------------


def test_fewer_than_three_pillars_is_insufficient() -> None:
    from app.simulation.go_no_go import (
        VERDICT_INSUFFICIENT,
        build_go_no_go,
    )

    out = build_go_no_go(
        competitive={
            "overall_competitive_position": "STRONG",
            "high_threat_count": 0,
        },
        coverage={
            "total_assumption_count": 4,
            "missing_categories": [],
            "sensitivity_breakdown": {"HIGH": 1},
        },
        project_id=7,
    )
    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.go_no_go_score is None
    assert out.meta["available_pillars"] == ["competitive", "coverage"]


def test_zero_premortem_is_insufficient_risk_pillar() -> None:
    from app.simulation.go_no_go import build_go_no_go

    now = _now()
    inputs = _full_inputs(now)
    inputs["premortem"] = {"premortem_count": 0, "severity_breakdown": {}}
    out = build_go_no_go(
        **inputs,
        project_id=7,
        latest_simulation_id=11,
        now=now,
    )
    premortem = next(p for p in out.pillars if p.key == "premortem")
    assert premortem.score is None
    assert premortem.verdict == "INSUFFICIENT_DATA"
    risk_gate = next(g for g in out.gates if g.id == "risk_gate")
    assert risk_gate.evaluated is False


# ---------------------------------------------------------------------------
# Defensive sanitisation
# ---------------------------------------------------------------------------


def test_malformed_pillar_values_are_treated_as_missing() -> None:
    from app.simulation.go_no_go import (
        VERDICT_INSUFFICIENT,
        build_go_no_go,
    )

    out = build_go_no_go(
        readiness={
            "readiness_score": float("nan"),
            "verdict": "READY",
        },
        premortem={"premortem_count": "many", "severity_breakdown": None},
        competitive={"overall_competitive_position": "UNKNOWN"},
        trust={"trust_score": float("inf"), "verdict": "PASS"},
        freshness={"latest_sim_completed_at": "not-a-date"},
        coverage={
            "total_assumption_count": -3,
            "missing_categories": "all",
            "sensitivity_breakdown": None,
        },
        project_id=7,
    )
    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.go_no_go_score is None
    assert all(p.score is None for p in out.pillars)


def test_out_of_range_scores_are_clamped() -> None:
    from app.simulation.go_no_go import build_go_no_go

    now = _now()
    out = build_go_no_go(
        readiness={"readiness_score": 1.7, "verdict": "READY"},
        premortem={
            "premortem_count": 1,
            "severity_breakdown": {"CRITICAL": 999, "MEDIUM": -5},
        },
        competitive={
            "overall_competitive_position": "WEAK",
            "high_threat_count": 100,
        },
        trust={"trust_score": -0.4, "verdict": "FAIL"},
        freshness={
            "latest_sim_completed_at": (
                now - timedelta(days=999)
            ).isoformat(),
        },
        coverage={
            "total_assumption_count": 3,
            "missing_categories": list(range(50)),
            "sensitivity_breakdown": {"LOW": 3},
        },
        project_id=7,
        now=now,
    )
    for pillar in out.pillars:
        assert pillar.score is None or 0 <= pillar.score <= 100
    assert out.go_no_go_score is None or 0 <= out.go_no_go_score <= 100


def test_premortem_without_breakdown_is_insufficient() -> None:
    from app.simulation.go_no_go import build_go_no_go

    now = _now()
    inputs = _full_inputs(now)
    inputs["premortem"] = {
        "premortem_count": 3,
        "severity_breakdown": None,
    }
    out = build_go_no_go(
        **inputs,
        project_id=7,
        latest_simulation_id=11,
        now=now,
    )
    premortem = next(p for p in out.pillars if p.key == "premortem")
    assert premortem.score is None
    assert premortem.verdict == "INSUFFICIENT_DATA"
    # The malformed read must not surface as a clean risk posture.
    assert "clean" not in premortem.summary.lower()
    risk_gate = next(g for g in out.gates if g.id == "risk_gate")
    assert risk_gate.evaluated is False


def test_premortem_breakdown_only_payload_is_supported() -> None:
    from app.simulation.go_no_go import build_go_no_go

    now = _now()
    inputs = _full_inputs(now)
    inputs["premortem"] = {
        "severity_breakdown": {"HIGH": 1, "MEDIUM": 2},
    }
    out = build_go_no_go(
        **inputs,
        project_id=7,
        latest_simulation_id=11,
        now=now,
    )
    premortem = next(p for p in out.pillars if p.key == "premortem")
    assert premortem.score == 84
    assert premortem.verdict == "STRONG"
    risk_gate = next(g for g in out.gates if g.id == "risk_gate")
    assert risk_gate.evaluated is True
    assert risk_gate.passed is True


def test_unknown_premortem_severity_is_conservative() -> None:
    from app.simulation.go_no_go import (
        VERDICT_CONDITIONAL_GO,
        build_go_no_go,
    )

    now = _now()
    inputs = _full_inputs(now)
    inputs["premortem"] = {
        "premortem_count": 3,
        "severity_breakdown": {"MAJOR": 2, "HIGH": 1},
    }
    out = build_go_no_go(
        **inputs,
        project_id=7,
        latest_simulation_id=11,
        now=now,
    )
    premortem = next(p for p in out.pillars if p.key == "premortem")
    # 2 unknown severities are penalised as CRITICAL-equivalent.
    assert premortem.score is not None and premortem.score <= 60
    assert any("unknown-severity" in line for line in premortem.evidence)
    risk_gate = next(g for g in out.gates if g.id == "risk_gate")
    assert risk_gate.evaluated is True
    assert risk_gate.passed is False
    # A high score elsewhere cannot mask the unmet risk gate.
    assert out.verdict == VERDICT_CONDITIONAL_GO


def test_coverage_without_category_list_is_insufficient() -> None:
    from app.simulation.go_no_go import build_go_no_go

    now = _now()
    inputs = _full_inputs(now)
    inputs["coverage"] = {
        "total_assumption_count": 5,
        "sensitivity_breakdown": {"HIGH": 2},
    }
    out = build_go_no_go(
        **inputs,
        project_id=7,
        latest_simulation_id=11,
        now=now,
    )
    coverage = next(p for p in out.pillars if p.key == "coverage")
    assert coverage.score is None
    assert coverage.verdict == "INSUFFICIENT_DATA"
    coverage_gate = next(
        g for g in out.gates if g.id == "coverage_gate"
    )
    assert coverage_gate.evaluated is False


def test_coverage_without_sensitivity_breakdown_is_insufficient() -> None:
    from app.simulation.go_no_go import build_go_no_go

    now = _now()
    inputs = _full_inputs(now)
    inputs["coverage"] = {
        "total_assumption_count": 5,
        "missing_categories": [],
    }
    out = build_go_no_go(
        **inputs,
        project_id=7,
        latest_simulation_id=11,
        now=now,
    )
    coverage = next(p for p in out.pillars if p.key == "coverage")
    assert coverage.score is None
    assert coverage.verdict == "INSUFFICIENT_DATA"
    coverage_gate = next(
        g for g in out.gates if g.id == "coverage_gate"
    )
    assert coverage_gate.evaluated is False


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


def test_critically_stale_simulation_flags_gate() -> None:
    from app.simulation.go_no_go import build_go_no_go

    now = _now()
    inputs = _full_inputs(now)
    inputs["freshness"] = {
        "latest_sim_completed_at": (
            now - timedelta(days=60)
        ).isoformat(),
        "latest_assumption_at": (
            now - timedelta(days=70)
        ).isoformat(),
        "latest_outcome_at": None,
    }
    out = build_go_no_go(
        **inputs,
        project_id=7,
        latest_simulation_id=11,
        now=now,
    )
    freshness = next(p for p in out.pillars if p.key == "freshness")
    assert freshness.score is not None and freshness.score < 70
    freshness_gate = next(
        g for g in out.gates if g.id == "freshness_gate"
    )
    assert freshness_gate.evaluated is True
    assert freshness_gate.passed is False


def test_freshness_insufficient_when_no_timestamps() -> None:
    from app.simulation.go_no_go import build_go_no_go

    out = build_go_no_go(
        readiness={"readiness_score": 0.9, "verdict": "READY"},
        premortem={
            "premortem_count": 2,
            "severity_breakdown": {"MEDIUM": 2},
        },
        competitive={
            "overall_competitive_position": "MODERATE",
            "high_threat_count": 0,
        },
        freshness={},
        project_id=7,
    )
    freshness = next(p for p in out.pillars if p.key == "freshness")
    assert freshness.score is None
    freshness_gate = next(
        g for g in out.gates if g.id == "freshness_gate"
    )
    assert freshness_gate.evaluated is False


# ---------------------------------------------------------------------------
# Top actions
# ---------------------------------------------------------------------------


def test_weakest_pillar_action_is_first() -> None:
    from app.simulation.go_no_go import build_go_no_go

    now = _now()
    inputs = _full_inputs(now)
    inputs["competitive"] = {
        "overall_competitive_position": "WEAK",
        "high_threat_count": 0,
    }
    out = build_go_no_go(
        **inputs,
        project_id=7,
        latest_simulation_id=11,
        now=now,
    )
    assert out.top_actions
    assert "competitor" in out.top_actions[0].lower()


def test_gate_failures_add_remediation_actions() -> None:
    from app.simulation.go_no_go import build_go_no_go

    now = _now()
    inputs = _full_inputs(now)
    inputs["premortem"] = {
        "premortem_count": 5,
        "severity_breakdown": {"CRITICAL": 3, "HIGH": 2},
    }
    out = build_go_no_go(
        **inputs,
        project_id=7,
        latest_simulation_id=11,
        now=now,
    )
    joined = " ".join(out.top_actions).lower()
    assert "critical" in joined or "premortem" in joined


def test_top_actions_deduplicated_and_capped() -> None:
    from app.simulation.go_no_go import build_go_no_go

    now = _now()
    inputs = _full_inputs(now)
    inputs["readiness"] = {"readiness_score": 0.5, "verdict": "NEEDS_WORK"}
    inputs["premortem"] = {
        "premortem_count": 4,
        "severity_breakdown": {"CRITICAL": 3},
        "top_failure_modes": [
            {"title": "Same"},
            {"title": "Same"},
            {"title": "Same"},
        ],
    }
    inputs["trust"] = {"trust_score": 0.4, "verdict": "FAIL"}
    inputs["coverage"] = {
        "total_assumption_count": 4,
        "missing_categories": ["Market", "Trust", "Retention", "Support"],
        "sensitivity_breakdown": {"LOW": 4},
    }
    out = build_go_no_go(
        **inputs,
        project_id=7,
        latest_simulation_id=11,
        now=now,
    )
    assert len(out.top_actions) == len(set(out.top_actions))
    assert len(out.top_actions) <= 5


# ---------------------------------------------------------------------------
# Narrative / meta
# ---------------------------------------------------------------------------


def test_narrative_reflects_verdict() -> None:
    from app.simulation.go_no_go import (
        VERDICT_GO,
        build_go_no_go,
    )

    now = _now()
    out = build_go_no_go(
        **_full_inputs(now),
        project_id=7,
        latest_simulation_id=11,
        now=now,
    )
    assert out.verdict == VERDICT_GO
    assert out.verdict_label.lower() in out.narrative.lower()
    assert out.meta["total_pillars"] == 6
    assert set(out.meta["available_pillars"]) == {
        "readiness",
        "premortem",
        "competitive",
        "trust",
        "freshness",
        "coverage",
    }


def test_pydantic_model_inputs_are_accepted() -> None:
    from app.schemas.launch_checklist import (
        LaunchChecklistOut,
        LaunchChecklistSummary,
    )
    from app.schemas.simulation_quality import (
        SimulationQualityOut,
        SimulationQualitySummary,
    )
    from app.simulation.go_no_go import build_go_no_go

    now = _now()
    readiness = LaunchChecklistOut(
        simulation_id=11,
        project_id=7,
        status="COMPLETED",
        readiness_score=0.9,
        verdict="READY",
        signal_quality=0.8,
        visible_assumptions=5,
        summary=LaunchChecklistSummary(),
    )
    trust = SimulationQualityOut(
        simulation_id=11,
        project_id=7,
        status="COMPLETED",
        trust_score=0.9,
        verdict="PASS",
        summary=SimulationQualitySummary(),
    )
    out = build_go_no_go(
        readiness=readiness,
        premortem={
            "premortem_count": 1,
            "severity_breakdown": {"MEDIUM": 1},
        },
        competitive={
            "overall_competitive_position": "MODERATE",
            "high_threat_count": 0,
        },
        trust=trust,
        freshness={
            "latest_sim_completed_at": (
                now - timedelta(days=1)
            ).isoformat(),
        },
        coverage={
            "total_assumption_count": 4,
            "missing_categories": [],
            "sensitivity_breakdown": {"HIGH": 1},
        },
        project_id=7,
        latest_simulation_id=11,
        now=now,
    )
    assert out.verdict == "GO"
