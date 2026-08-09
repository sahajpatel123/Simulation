"""
Tests for ``app.simulation.architects.messaging_clarity`` —
MessagingClarityArchitect.

Locks down value-proposition clarity signal extraction (category, audience,
use case, quantified outcome, hype density), per-cluster comprehension risk,
Markov transition overrides (including high-ticket decision suppression),
the cross-cluster report, and conductor / calibration / accountability
registration so the domain surfaces as a founder finding.
"""

from __future__ import annotations

from typing import Any


def _cluster(
    *,
    literacy: float = 0.5,
    motivation: float = 0.5,
    trust: float = 0.5,
    cluster_id: str = "test_cluster",
) -> Any:
    from app.simulation.clusters.definitions import ClusterDefinition

    return ClusterDefinition(
        cluster_id=cluster_id,
        name="Test",
        description="Test",
        population_weight=0.03,
        base_traits={
            "income_level": 0.5,
            "digital_literacy": literacy,
            "motivation": motivation,
            "trust": trust,
            "price_sensitivity": 0.5,
            "risk_aversion": 0.5,
            "patience_score": 0.5,
            "social_orientation": 0.5,
        },
        trait_variance={k: 0.05 for k in (
            "income_level", "digital_literacy", "motivation", "trust",
            "price_sensitivity", "risk_aversion", "patience_score",
            "social_orientation",
        )},
        dominant_behavior_pattern="test",
        known_failure_modes=[],
        product_affinities=["saas"],
        demographic_profile={"geography": "metro", "age_bracket": "25-35"},
    )


def _compute(
    *,
    literacy: float = 0.5,
    motivation: float = 0.5,
    trust: float = 0.5,
    assumptions: list[Any] | None = None,
    description: str = "",
    average_order_value: float = 999.0,
    env_params: dict[str, Any] | None = None,
) -> Any:
    from app.simulation.architects.messaging_clarity import (
        MessagingClarityArchitect,
    )

    if env_params is not None:
        params = dict(env_params)
        params.setdefault("product_type", "saas")
    else:
        params: dict[str, Any] = {
            "product_type": "saas",
            "average_order_value": average_order_value,
        }
        if description:
            params["description"] = description
    return MessagingClarityArchitect().compute(
        cluster=_cluster(
            literacy=literacy,
            motivation=motivation,
            trust=trust,
        ),
        agent_profile={},
        assumptions=assumptions or [],
        env_params=params,
    )


def _architect() -> Any:
    from app.simulation.architects.messaging_clarity import (
        MessagingClarityArchitect,
    )

    return MessagingClarityArchitect()


_VAGUE_PITCH = (
    "An innovative AI-powered platform using cutting-edge technology "
    "for everyone"
)
_CLEAR_PITCH = (
    "A SaaS CRM for small businesses that cuts follow-up time by 40%"
)


# ---------------------------------------------------------------------------
# Identity + baseline behaviour
# ---------------------------------------------------------------------------


def test_name_and_product_types() -> None:
    architect = _architect()
    assert architect.name == "MessagingClarityArchitect"
    assert architect.product_types == []


def test_baseline_compute_is_neutral_when_no_messaging_evidence() -> None:
    out = _compute()
    assert out.architect_name == "MessagingClarityArchitect"
    assert len(out.metrics) == 8
    assert out.metrics["messaging_clarity_score"] == 1.0
    assert out.metrics["comprehension_risk"] == 0.0
    assert out.metrics["clarity_funnel_suppressor"] == 1.0
    for key, value in out.metrics.items():
        assert 0.0 <= value <= 1.0, key
    assert out.flags["messaging_evidence_absent"] is True
    assert out.flags["clarity_gap"] is False
    assert out.severity == "INFO"
    assert _architect().transition_overrides(out) == {}


# ---------------------------------------------------------------------------
# Null / empty evidence hardening
# ---------------------------------------------------------------------------


def test_null_assumption_text_is_not_evidence() -> None:
    out = _compute(assumptions=[{"text": None, "category": "pricing"}])
    assert out.metrics["messaging_clarity_score"] == 1.0
    assert out.metrics["comprehension_risk"] == 0.0
    assert out.metrics["clarity_funnel_suppressor"] == 1.0
    assert out.flags["messaging_evidence_absent"] is True
    assert out.flags["clarity_gap"] is False
    assert out.severity == "INFO"
    assert _architect().transition_overrides(out) == {}


def test_null_description_is_not_evidence() -> None:
    out = _compute(
        env_params={
            "product_type": "saas",
            "average_order_value": 999.0,
            "description": None,
        },
    )
    assert out.metrics["messaging_clarity_score"] == 1.0
    assert out.metrics["clarity_funnel_suppressor"] == 1.0
    assert out.flags["messaging_evidence_absent"] is True
    assert out.severity == "INFO"


def test_none_and_blank_assumption_entries_are_skipped() -> None:
    out = _compute(
        assumptions=[
            None,
            {"text": None},
            {"text": ""},
            {"text": "   "},
        ],
    )
    assert out.metrics["messaging_clarity_score"] == 1.0
    assert out.flags["messaging_evidence_absent"] is True
    assert out.flags["clarity_gap"] is False


def test_null_assumptions_do_not_mask_real_evidence() -> None:
    out = _compute(
        literacy=0.1,
        motivation=0.3,
        trust=0.3,
        assumptions=[None, {"text": None}, {"text": _VAGUE_PITCH}],
    )
    assert out.flags["messaging_evidence_absent"] is False
    assert out.metrics["messaging_clarity_score"] < 0.40
    assert out.flags["clarity_gap"] is True
    assert out.severity == "CRITICAL"


def test_duplicate_pitch_texts_are_counted_once() -> None:
    from app.simulation.architects.messaging_clarity import _collect_texts

    pitch = (
        "An AI-powered CRM for small businesses that cuts follow-up "
        "time by 40%"
    )
    assert _collect_texts(
        [{"text": pitch}],
        {"description": pitch},
    ) == [pitch.lower()]

    once = _compute(description=pitch)
    twice = _compute(
        assumptions=[{"text": pitch}],
        description=pitch,
    )
    assert (
        twice.metrics["vague_language_density"]
        == once.metrics["vague_language_density"]
    )
    assert (
        twice.metrics["messaging_clarity_score"]
        == once.metrics["messaging_clarity_score"]
    )


# ---------------------------------------------------------------------------
# Clear-pitch behaviour
# ---------------------------------------------------------------------------


def test_clear_pitch_is_neutral_even_for_low_literacy_cluster() -> None:
    out = _compute(
        literacy=0.1,
        motivation=0.3,
        trust=0.3,
        description=_CLEAR_PITCH,
    )
    assert out.metrics["messaging_clarity_score"] >= 0.70
    assert out.metrics["clarity_funnel_suppressor"] == 1.0
    assert out.flags["clarity_gap"] is False
    assert out.flags["missing_outcome_specificity"] is False
    assert out.flags["missing_audience"] is False
    assert out.flags["missing_category_anchor"] is False
    assert out.severity == "INFO"
    assert _architect().transition_overrides(out) == {}


def test_category_plus_audience_without_outcome_stays_informational() -> None:
    out = _compute(
        literacy=0.1,
        description="A SaaS CRM for small businesses",
    )
    assert out.metrics["clarity_funnel_suppressor"] == 1.0
    assert out.flags["clarity_gap"] is False
    assert out.flags["missing_outcome_specificity"] is True
    assert out.flags["missing_audience"] is False
    assert out.severity == "INFO"


def test_two_sided_marketplace_phrasing_counts_as_audience() -> None:
    out = _compute(
        literacy=0.1,
        description="A freelance marketplace connecting designers with clients",
    )
    assert out.metrics["audience_specificity"] >= 0.5
    assert out.metrics["clarity_funnel_suppressor"] == 1.0
    assert out.flags["clarity_gap"] is False


# ---------------------------------------------------------------------------
# Vague-pitch comprehension modelling
# ---------------------------------------------------------------------------


def test_vague_pitch_is_critical_for_low_literacy_cluster() -> None:
    out = _compute(
        literacy=0.1,
        motivation=0.3,
        trust=0.3,
        description=_VAGUE_PITCH,
    )
    assert out.metrics["messaging_clarity_score"] < 0.40
    assert out.metrics["comprehension_risk"] > 0.50
    assert out.metrics["clarity_funnel_suppressor"] < 0.80
    assert out.flags["clarity_gap"] is True
    assert out.flags["vague_messaging"] is True
    assert out.severity == "CRITICAL"

    overrides = _architect().transition_overrides(out)
    assert set(overrides.keys()) == {("BROWSE", "CONSIDER")}
    assert 0.0 < overrides[("BROWSE", "CONSIDER")] < 1.0


def test_high_literacy_cluster_is_less_penalised() -> None:
    low = _compute(
        literacy=0.1,
        motivation=0.3,
        trust=0.3,
        description=_VAGUE_PITCH,
    )
    high = _compute(
        literacy=0.9,
        motivation=0.8,
        trust=0.7,
        description=_VAGUE_PITCH,
    )
    assert (
        high.metrics["messaging_clarity_score"]
        > low.metrics["messaging_clarity_score"]
    )
    assert high.metrics["comprehension_risk"] < low.metrics["comprehension_risk"]
    assert high.metrics["clarity_funnel_suppressor"] > low.metrics["clarity_funnel_suppressor"]
    # The same vague pitch drops from CRITICAL to WARNING for a digitally
    # literate, motivated, trusting cluster.
    assert high.severity == "WARNING"
    assert high.flags["clarity_gap"] is True


def test_concrete_outcomes_dilute_hype_penalty() -> None:
    hype_only = _compute(
        description="An innovative AI-powered seamless solution",
    )
    balanced = _compute(
        description=(
            "An AI-powered CRM for small businesses that cuts follow-up "
            "time by 40%"
        ),
    )
    assert (
        balanced.metrics["vague_language_density"]
        < hype_only.metrics["vague_language_density"]
    )
    assert (
        balanced.metrics["messaging_clarity_score"]
        > hype_only.metrics["messaging_clarity_score"]
    )
    assert (
        balanced.metrics["clarity_funnel_suppressor"]
        >= hype_only.metrics["clarity_funnel_suppressor"]
    )


def test_suppressor_has_floor() -> None:
    out = _compute(
        literacy=0.0,
        motivation=0.0,
        trust=0.0,
        description=_VAGUE_PITCH,
    )
    assert out.metrics["clarity_funnel_suppressor"] >= 0.55


# ---------------------------------------------------------------------------
# High-ticket behaviour
# ---------------------------------------------------------------------------


def test_high_ticket_adds_decision_stage_override() -> None:
    low_ticket = _compute(
        literacy=0.1,
        description=_VAGUE_PITCH,
        average_order_value=999.0,
    )
    high_ticket = _compute(
        literacy=0.1,
        description=_VAGUE_PITCH,
        average_order_value=50_000.0,
    )
    assert set(_architect().transition_overrides(low_ticket).keys()) == {
        ("BROWSE", "CONSIDER"),
    }
    high_overrides = _architect().transition_overrides(high_ticket)
    assert set(high_overrides.keys()) == {
        ("BROWSE", "CONSIDER"),
        ("CONSIDER", "DECIDE"),
    }
    assert (
        high_overrides[("CONSIDER", "DECIDE")]
        <= high_overrides[("BROWSE", "CONSIDER")]
    )
    assert high_ticket.flags["high_ticket_comprehension_risk"] is True


def test_clear_high_ticket_pitch_has_no_override() -> None:
    out = _compute(
        description=_CLEAR_PITCH,
        average_order_value=50_000.0,
    )
    assert _architect().transition_overrides(out) == {}


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_empty_outputs_is_graceful() -> None:
    report = _architect().generate_report([])
    assert report.architect_name == "MessagingClarityArchitect"
    assert report.affected_cluster_ids == []
    assert report.severity == "INFO"
    assert report.population_fraction == 0.0
    assert report.conversion_impact == 0.0


def test_generate_report_aggregates_critical_and_warning_clusters() -> None:
    from app.simulation.architects.base import ArchitectOutput

    architect = _architect()
    critical = ArchitectOutput(
        architect_name=architect.name,
        cluster_id="tier3_low_literacy",
        metrics={},
        flags={"clarity_gap": True, "vague_messaging": True},
        narrative_findings=[],
        severity="CRITICAL",
    )
    warning = ArchitectOutput(
        architect_name=architect.name,
        cluster_id="metro_pro",
        metrics={},
        flags={"clarity_gap": True},
        narrative_findings=[],
        severity="WARNING",
    )
    report = architect.generate_report([critical, warning])
    assert report.severity == "CRITICAL"
    assert set(report.affected_cluster_ids) == {
        "tier3_low_literacy",
        "metro_pro",
    }
    assert report.conversion_impact > 0.0
    assert "plain language" in report.recommended_action.lower()


def test_generate_report_population_fraction_capped_at_one() -> None:
    from app.simulation.architects.base import ArchitectOutput

    architect = _architect()
    outputs = [
        ArchitectOutput(
            architect_name=architect.name,
            cluster_id=f"cluster_{i}",
            metrics={},
            flags={"clarity_gap": True},
            narrative_findings=[],
            severity="WARNING",
        )
        for i in range(52)
    ]
    report = architect.generate_report(outputs)
    assert len(report.affected_cluster_ids) == 52
    assert 0.0 < report.population_fraction <= 1.0


# ---------------------------------------------------------------------------
# Conductor + calibration + accountability integration
# ---------------------------------------------------------------------------


def test_conductor_runs_architect_and_accountability_surfaces_finding() -> None:
    from app.simulation.accountability import AccountabilityEngine
    from app.simulation.conductor import Conductor, ProductType

    result = Conductor().run(
        agents=[],
        env_params={
            "description": _VAGUE_PITCH,
            "average_order_value": 999,
        },
        assumptions=[],
        product_type=ProductType.SAAS,
    )
    assert "MessagingClarityArchitect" in result.cluster_results[
        "metro_power_professional"
    ]
    assert any(
        report.architect_name == "MessagingClarityArchitect"
        for report in result.domain_reports
    )
    findings = AccountabilityEngine().generate_domain_findings(result)
    assert any(
        finding.architect_name == "MessagingClarityArchitect"
        for finding in findings
    )


def test_registry_includes_architect_in_every_product_stack() -> None:
    from app.simulation.conductor import (
        ARCHITECT_STACKS,
        ProductType,
        _build_architect_registry,
    )

    registry = _build_architect_registry()
    assert "MessagingClarityArchitect" in registry
    for product_type in ProductType:
        stack = ARCHITECT_STACKS[product_type]
        assert "MessagingClarityArchitect" in stack
        assert stack[0] == "MarketTimingArchitect"
        assert stack[-1] == "AssumptionCascadeArchitect"


def test_registered_in_calibration_and_specificity_rules() -> None:
    from app.simulation.calibration_engine import ALL_ARCHITECT_NAMES
    from app.simulation.scored_assumption import SPECIFICITY_RULES

    assert "MessagingClarityArchitect" in ALL_ARCHITECT_NAMES
    assert "MessagingClarityArchitect" in SPECIFICITY_RULES


def test_accountability_benchmarks_cover_messaging_metrics() -> None:
    from app.simulation.accountability import AccountabilityEngine

    benchmarks = AccountabilityEngine.HEALTHY_BENCHMARKS
    for metric in (
        "messaging_clarity_score",
        "comprehension_risk",
        "vague_language_density",
        "clarity_funnel_suppressor",
    ):
        assert metric in benchmarks, metric
        assert metric in AccountabilityEngine.FINDING_TEMPLATES, metric
        assert metric in AccountabilityEngine.RECOMMENDED_ACTIONS, metric
    assert "comprehension_risk" in AccountabilityEngine.LOWER_IS_BETTER
    assert "vague_language_density" in AccountabilityEngine.LOWER_IS_BETTER
