"""Tests for the per-project health helper + schema.

The helper is pure-Python so it can be exercised without
a DB.
"""
from __future__ import annotations



# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import project_health

    assert set(project_health.__all__) == {
        "MAX_SCORE",
        "SIM_CONFIDENCE_MAX",
        "ZERO_CRITICAL_FINDINGS_BONUS",
        "ZERO_PENDING_DECISIONS_BONUS",
        "HAS_OUTCOME_BONUS",
        "ZERO_WEAK_LINKS_BONUS",
        "PENALTY_PER_CRITICAL_FINDING",
        "PENALTY_PER_PENDING_DECISION",
        "PENALTY_PER_WEAK_LINK",
        "VERDICT_HEALTHY",
        "VERDICT_NEEDS_ATTENTION",
        "VERDICT_AT_RISK",
        "VERDICT_HEALTHY_MIN",
        "VERDICT_AT_RISK_MAX",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_project_health",
    }


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


def test_default_empty_at_risk() -> None:
    from app.simulation.project_health import (
        VERDICT_NEEDS_ATTENTION,
        build_project_health,
    )

    out = build_project_health()
    # Empty input → verdict NEEDS_ATTENTION (NOT AT_RISK).
    # The helper credits baseline points for "nothing wrong
    # yet": 20 zero_critical_findings + 10 zero_pending
    # decisions + 15 zero_weak_links = 45, which lands in
    # the NEEDS_ATTENTION band (41-69). This mirrors the
    # account_health helper's "baseline for empty" semantics.
    assert out["verdict"] == VERDICT_NEEDS_ATTENTION
    assert out["project_health_score"] == 45


# ---------------------------------------------------------------------------
# Sim confidence
# ---------------------------------------------------------------------------


def test_sim_confidence_full_points() -> None:
    from app.simulation.project_health import build_project_health

    out = build_project_health(sim_confidence=1.0)
    assert out["score_breakdown"]["sim_confidence"] == 30


def test_sim_confidence_half_points() -> None:
    from app.simulation.project_health import build_project_health

    out = build_project_health(sim_confidence=0.5)
    assert out["score_breakdown"]["sim_confidence"] == 15


def test_sim_confidence_zero_points() -> None:
    from app.simulation.project_health import build_project_health

    out = build_project_health(sim_confidence=0.0)
    assert out["score_breakdown"]["sim_confidence"] == 0


def test_sim_confidence_clamped() -> None:
    from app.simulation.project_health import build_project_health

    # > 1.0 floored at 1.0.
    out = build_project_health(sim_confidence=2.0)
    assert out["score_breakdown"]["sim_confidence"] == 30


# ---------------------------------------------------------------------------
# Bonuses
# ---------------------------------------------------------------------------


def test_zero_critical_findings_bonus() -> None:
    from app.simulation.project_health import build_project_health

    out = build_project_health(critical_finding_count=0)
    assert out["score_breakdown"]["zero_critical_findings"] == 20


def test_critical_findings_no_bonus() -> None:
    from app.simulation.project_health import build_project_health

    out = build_project_health(critical_finding_count=1)
    assert out["score_breakdown"]["zero_critical_findings"] == 0


def test_pending_decisions_bonus() -> None:
    from app.simulation.project_health import build_project_health

    out = build_project_health(pending_decision_count=0)
    assert out["score_breakdown"]["zero_pending_decisions"] == 10
    out2 = build_project_health(pending_decision_count=2)
    assert out2["score_breakdown"]["zero_pending_decisions"] == 0


def test_outcome_bonus() -> None:
    from app.simulation.project_health import build_project_health

    out = build_project_health(has_outcome=True)
    assert out["score_breakdown"]["has_outcome"] == 10
    out2 = build_project_health(has_outcome=False)
    assert out2["score_breakdown"]["has_outcome"] == 0


def test_zero_weak_links_bonus() -> None:
    from app.simulation.project_health import build_project_health

    out = build_project_health(weak_link_count=0)
    assert out["score_breakdown"]["zero_weak_links"] == 15


# ---------------------------------------------------------------------------
# Penalties
# ---------------------------------------------------------------------------


def test_critical_findings_penalty() -> None:
    from app.simulation.project_health import build_project_health

    # 3 CRITICAL findings × -4 per = -12. The helper has no
    # ``zero_critical_findings_bonus`` parameter — that
    # baseline bonus is awarded automatically when
    # critical_finding_count == 0; passing the kwarg here
    # used to TypeError. Drop it.
    out = build_project_health(critical_finding_count=3)
    assert out["score_breakdown"]["penalties"] == -12


def test_combined_penalties() -> None:
    from app.simulation.project_health import build_project_health

    # 2 critical (-8) + 3 pending (-6) + 4 weak (-4) = -18.
    out = build_project_health(
        critical_finding_count=2,
        pending_decision_count=3,
        weak_link_count=4,
    )
    assert out["score_breakdown"]["penalties"] == -18


# ---------------------------------------------------------------------------
# Verdict classification
# ---------------------------------------------------------------------------


def test_verdict_healthy_when_score_high() -> None:
    from app.simulation.project_health import (
        VERDICT_HEALTHY,
        build_project_health,
    )

    # All bonuses + no penalties = 30+20+10+10+15 = 85.
    out = build_project_health(
        sim_confidence=1.0,
        critical_finding_count=0,
        pending_decision_count=0,
        weak_link_count=0,
        has_outcome=True,
    )
    assert out["project_health_score"] == 85
    assert out["verdict"] == VERDICT_HEALTHY


def test_verdict_at_risk_when_score_low() -> None:
    from app.simulation.project_health import (
        VERDICT_AT_RISK,
        build_project_health,
    )

    out = build_project_health(
        sim_confidence=0.1,
        critical_finding_count=10,
        pending_decision_count=10,
        weak_link_count=10,
        has_outcome=False,
    )
    assert out["verdict"] == VERDICT_AT_RISK


def test_score_clamped_to_zero() -> None:
    from app.simulation.project_health import build_project_health

    out = build_project_health(
        sim_confidence=None,
        critical_finding_count=100,
        pending_decision_count=100,
        weak_link_count=100,
        has_outcome=False,
    )
    assert out["project_health_score"] == 0


def test_score_clamped_to_max() -> None:
    from app.simulation.project_health import build_project_health

    out = build_project_health(
        sim_confidence=1.0,
        critical_finding_count=0,
        pending_decision_count=0,
        weak_link_count=0,
        has_outcome=True,
    )
    assert out["project_health_score"] <= 100


# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------


def test_narrative_mentions_score() -> None:
    from app.simulation.project_health import build_project_health

    out = build_project_health(sim_confidence=1.0)
    assert "/100" in out["narrative"]


def test_narrative_mentions_penalties_when_present() -> None:
    from app.simulation.project_health import build_project_health

    out = build_project_health(critical_finding_count=2)
    assert "Penalties" in out["narrative"]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_project_health_out_default_shape() -> None:
    from app.schemas.project import ProjectHealthOut

    out = ProjectHealthOut()
    assert out.project_health_score == 0
    assert out.verdict == "AT_RISK"
    assert out.key_signals == []


def test_project_health_out_round_trips_helper_payload() -> None:
    from app.schemas.project import ProjectHealthOut
    from app.simulation.project_health import build_project_health

    payload = build_project_health(
        sim_confidence=1.0,
        has_outcome=True,
    )
    out = ProjectHealthOut(**payload)
    assert out.project_health_score >= 40
    assert out.score_breakdown["sim_confidence"] == 30