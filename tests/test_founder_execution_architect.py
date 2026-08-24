"""
Tests for ``app.simulation.architects.founder_execution`` —
FounderExecutionArchitect.

Locks down team/prototype/support evidence extraction (with negation- and
intent-aware gap detection), per-cluster delivery-risk modelling, Markov
transition overrides at the DECIDE→PURCHASE stage, the cross-cluster
report, and conductor / calibration / accountability registration so the
domain surfaces as a founder finding.
"""

from __future__ import annotations

from typing import Any


def _cluster(
    *,
    risk_aversion: float = 0.5,
    trust: float = 0.5,
    income_level: float = 0.5,
    patience_score: float = 0.5,
    cluster_id: str = "test_cluster",
) -> Any:
    from app.simulation.clusters.definitions import ClusterDefinition

    return ClusterDefinition(
        cluster_id=cluster_id,
        name="Test",
        description="Test",
        population_weight=0.03,
        base_traits={
            "income_level": income_level,
            "digital_literacy": 0.5,
            "motivation": 0.5,
            "trust": trust,
            "price_sensitivity": 0.5,
            "risk_aversion": risk_aversion,
            "patience_score": patience_score,
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
    risk_aversion: float = 0.5,
    trust: float = 0.5,
    income_level: float = 0.5,
    patience_score: float = 0.5,
    assumptions: list[Any] | None = None,
    description: str = "",
    average_order_value: float = 999.0,
    env_params: dict[str, Any] | None = None,
) -> Any:
    from app.simulation.architects.founder_execution import (
        FounderExecutionArchitect,
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
    return FounderExecutionArchitect().compute(
        cluster=_cluster(
            risk_aversion=risk_aversion,
            trust=trust,
            income_level=income_level,
            patience_score=patience_score,
        ),
        agent_profile={},
        assumptions=assumptions or [],
        env_params=params,
    )


def _architect() -> Any:
    from app.simulation.architects.founder_execution import (
        FounderExecutionArchitect,
    )

    return FounderExecutionArchitect()


_STRONG_PITCH = (
    "We are a team of ex-Google engineers. The working prototype is live, "
    "the MVP has beta users, and we staff a support team with a refund policy."
)
_GAP_PITCH = (
    "I am a solo founder with no team and no prototype; the product is "
    "still in development and I plan to launch soon."
)


# ---------------------------------------------------------------------------
# Identity + baseline behaviour
# ---------------------------------------------------------------------------


def test_name_and_product_types() -> None:
    architect = _architect()
    assert architect.name == "FounderExecutionArchitect"
    assert architect.product_types == []


def test_baseline_compute_is_neutral_when_no_execution_evidence() -> None:
    out = _compute()
    assert out.architect_name == "FounderExecutionArchitect"
    assert len(out.metrics) == 6
    assert out.metrics["execution_credibility_score"] == 0.62
    assert out.metrics["delivery_risk"] == 0.0
    assert out.metrics["execution_funnel_suppressor"] == 1.0
    for key, value in out.metrics.items():
        assert 0.0 <= value <= 1.0, key
    assert out.flags["execution_evidence_absent"] is True
    assert out.flags["execution_gap"] is False
    assert out.severity == "INFO"
    assert _architect().transition_overrides(out) == {}


def test_null_and_blank_evidence_is_not_a_gap() -> None:
    out = _compute(
        env_params={
            "product_type": "saas",
            "average_order_value": 999.0,
            "description": None,
        },
        assumptions=[None, {"text": None}, {"text": ""}, {"text": "   "}],
    )
    assert out.metrics["execution_credibility_score"] == 0.62
    assert out.metrics["execution_funnel_suppressor"] == 1.0
    assert out.flags["execution_evidence_absent"] is True
    assert out.flags["execution_gap"] is False
    assert out.severity == "INFO"


def test_duplicate_pitch_texts_are_counted_once() -> None:
    from app.simulation.architects.founder_execution import _collect_texts

    assert _collect_texts(
        [{"text": _STRONG_PITCH}],
        {"description": _STRONG_PITCH},
    ) == [_STRONG_PITCH.lower()]

    once = _compute(description=_STRONG_PITCH)
    twice = _compute(
        assumptions=[{"text": _STRONG_PITCH}],
        description=_STRONG_PITCH,
    )
    assert (
        twice.metrics["execution_credibility_score"]
        == once.metrics["execution_credibility_score"]
    )
    assert (
        twice.metrics["execution_funnel_suppressor"]
        == once.metrics["execution_funnel_suppressor"]
    )


# ---------------------------------------------------------------------------
# Strong-evidence behaviour
# ---------------------------------------------------------------------------


def test_strong_evidence_is_neutral_even_for_risk_averse_cluster() -> None:
    out = _compute(
        risk_aversion=0.9,
        trust=0.2,
        description=_STRONG_PITCH,
    )
    assert out.metrics["execution_credibility_score"] >= 0.90
    assert out.metrics["delivery_risk"] < 0.10
    assert out.metrics["execution_funnel_suppressor"] == 1.0
    assert out.flags["execution_gap"] is False
    assert out.flags["team_evidence_present"] is True
    assert out.flags["prototype_evidence_present"] is True
    assert out.flags["support_evidence_present"] is True
    assert out.severity == "INFO"
    assert _architect().transition_overrides(out) == {}


def test_discourse_negation_does_not_void_real_evidence() -> None:
    out = _compute(
        description=(
            "No, we already shipped the product and have beta users "
            "with a support team."
        ),
    )
    assert out.flags["prototype_evidence_present"] is True
    assert out.flags["support_evidence_present"] is True
    assert out.flags["execution_gap"] is False
    assert out.metrics["execution_funnel_suppressor"] == 1.0
    assert out.severity == "INFO"


def test_support_evidence_counts_separately_from_product() -> None:
    out = _compute(
        description=(
            "We staff a support team and publish a refund policy."
        ),
    )
    assert out.flags["support_evidence_present"] is True
    assert out.flags["prototype_evidence_present"] is False
    assert out.flags["execution_gap"] is False
    assert out.metrics["execution_funnel_suppressor"] == 1.0
    assert out.severity == "INFO"


# ---------------------------------------------------------------------------
# Gap detection and intent/negation hardening
# ---------------------------------------------------------------------------


def test_gap_pitch_is_active_with_funnel_override() -> None:
    out = _compute(
        risk_aversion=1.0,
        trust=0.0,
        income_level=0.0,
        patience_score=0.0,
        description=_GAP_PITCH,
    )
    assert out.metrics["execution_credibility_score"] == 0.20
    assert out.metrics["delivery_risk"] >= 0.75
    assert out.metrics["execution_funnel_suppressor"] < 0.50
    assert out.flags["execution_gap"] is True
    assert out.flags["solo_founder_gap"] is True
    assert out.flags["unbuilt_product_gap"] is True
    assert out.severity == "CRITICAL"

    overrides = _architect().transition_overrides(out)
    assert set(overrides.keys()) == {("DECIDE", "PURCHASE")}
    assert 0.0 < overrides[("DECIDE", "PURCHASE")] < 1.0


def test_high_trust_cluster_is_less_penalised() -> None:
    low = _compute(
        risk_aversion=1.0,
        trust=0.0,
        income_level=0.0,
        patience_score=0.0,
        description=_GAP_PITCH,
    )
    high = _compute(
        risk_aversion=0.2,
        trust=0.8,
        income_level=0.8,
        patience_score=0.8,
        description=_GAP_PITCH,
    )
    assert (
        high.metrics["delivery_risk"]
        < low.metrics["delivery_risk"]
    )
    assert (
        high.metrics["execution_funnel_suppressor"]
        > low.metrics["execution_funnel_suppressor"]
    )
    assert low.severity == "CRITICAL"
    assert high.severity == "WARNING"


def test_intent_is_not_shipped_reality() -> None:
    out = _compute(
        description=(
            "We plan to build the MVP and hire engineers next quarter."
        ),
    )
    assert out.flags["execution_gap"] is True
    assert out.flags["prototype_evidence_present"] is False
    assert out.flags["team_evidence_present"] is False
    assert out.metrics["execution_funnel_suppressor"] < 1.0
    assert _architect().transition_overrides(out) != {}


def test_negation_voids_strong_evidence() -> None:
    out = _compute(
        description=(
            "We do not have a working prototype and we do not have "
            "beta users yet."
        ),
    )
    assert out.flags["prototype_evidence_present"] is False
    assert out.flags["execution_gap"] is True
    assert out.metrics["execution_funnel_suppressor"] < 1.0


def test_explicit_gap_phrases_are_not_double_counted() -> None:
    from app.simulation.architects.founder_execution import (
        _collect_texts,
        _signal_scores,
    )

    cases = [
        ("We have no support team.", "support_gap"),
        ("We have no refund policy.", "support_gap"),
        ("We have no beta users yet.", "product_gap"),
        ("We have no paying customers.", "product_gap"),
        ("We have no co-founder.", "team_gap"),
        ("We have no engineering team.", "team_gap"),
    ]
    for text, key in cases:
        signals = _signal_scores(_collect_texts([], {"description": text}))
        assert signals[key] == 1.0, (text, key, signals[key])

    out = _compute(description="We have no support team.")
    assert out.flags["support_gap"] is True
    assert out.flags["prototype_evidence_present"] is False


def test_trailing_negation_scoped_to_later_evidence_keeps_product() -> None:
    from app.simulation.architects.founder_execution import (
        _collect_texts,
        _signal_scores,
    )

    out = _compute(
        description="We have a working prototype without a support plan."
    )
    assert out.flags["prototype_evidence_present"] is True
    assert out.flags["support_gap"] is True
    assert out.metrics["prototype_evidence_strength"] > 0.0

    signals = _signal_scores(
        _collect_texts(
            [],
            {"description": "We have a working prototype without a support plan."},
        )
    )
    assert signals["product"] == 1.0
    assert signals["product_gap"] == 0.0
    assert signals["support_gap"] == 1.0


def test_trailing_negation_directly_on_evidence_voids_once() -> None:
    from app.simulation.architects.founder_execution import (
        _collect_texts,
        _signal_scores,
    )

    out = _compute(description="Our working prototype is not available yet.")
    assert out.flags["prototype_evidence_present"] is False
    assert out.flags["unbuilt_product_gap"] is True

    signals = _signal_scores(
        _collect_texts(
            [],
            {"description": "Our working prototype is not available yet."},
        )
    )
    assert signals["product"] == 0.0
    assert signals["product_gap"] == 1.0


def test_leading_negation_still_voids_with_scoped_trailing_negation() -> None:
    from app.simulation.architects.founder_execution import (
        _collect_texts,
        _signal_scores,
    )

    out = _compute(
        description=(
            "We do not have a working prototype without a support plan."
        )
    )
    assert out.flags["prototype_evidence_present"] is False

    signals = _signal_scores(
        _collect_texts(
            [],
            {
                "description": (
                    "We do not have a working prototype without a support plan."
                )
            },
        )
    )
    assert signals["product_gap"] == 1.0
    assert signals["support_gap"] == 1.0


def test_connector_separated_gap_does_not_void_product_evidence() -> None:
    from app.simulation.architects.founder_execution import (
        _collect_texts,
        _signal_scores,
    )

    out = _compute(description="We have a working prototype and no support team.")
    assert out.flags["prototype_evidence_present"] is True
    assert out.flags["support_gap"] is True

    signals = _signal_scores(
        _collect_texts(
            [], {"description": "We have a working prototype and no support team."}
        )
    )
    assert signals["product"] == 1.0
    assert signals["product_gap"] == 0.0
    assert signals["support_gap"] == 1.0


def test_suppressor_has_floor() -> None:
    out = _compute(
        risk_aversion=1.0,
        trust=0.0,
        income_level=0.0,
        patience_score=0.0,
        description=_GAP_PITCH,
    )
    assert out.metrics["execution_funnel_suppressor"] >= 0.45


def test_high_ticket_increases_delivery_risk() -> None:
    low = _compute(description=_GAP_PITCH, average_order_value=999.0)
    high = _compute(description=_GAP_PITCH, average_order_value=50_000.0)
    assert (
        high.metrics["delivery_risk"]
        > low.metrics["delivery_risk"]
    )
    assert (
        high.metrics["execution_funnel_suppressor"]
        <= low.metrics["execution_funnel_suppressor"]
    )


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_empty_outputs_is_graceful() -> None:
    report = _architect().generate_report([])
    assert report.architect_name == "FounderExecutionArchitect"
    assert report.affected_cluster_ids == []
    assert report.severity == "INFO"
    assert report.population_fraction == 0.0
    assert report.conversion_impact == 0.0


def test_generate_report_aggregates_critical_and_warning_clusters() -> None:
    from app.simulation.architects.base import ArchitectOutput

    architect = _architect()
    critical = ArchitectOutput(
        architect_name=architect.name,
        cluster_id="tier3_solo_founder",
        metrics={},
        flags={"execution_gap": True, "solo_founder_gap": True},
        narrative_findings=[],
        severity="CRITICAL",
    )
    warning = ArchitectOutput(
        architect_name=architect.name,
        cluster_id="metro_pro",
        metrics={},
        flags={"execution_gap": True},
        narrative_findings=[],
        severity="WARNING",
    )
    report = architect.generate_report([critical, warning])
    assert report.severity == "CRITICAL"
    assert set(report.affected_cluster_ids) == {
        "tier3_solo_founder",
        "metro_pro",
    }
    assert report.conversion_impact > 0.0
    assert "prototype" in report.recommended_action.lower()


def test_generate_report_population_fraction_capped_at_one() -> None:
    from app.simulation.architects.base import ArchitectOutput

    architect = _architect()
    outputs = [
        ArchitectOutput(
            architect_name=architect.name,
            cluster_id=f"cluster_{i}",
            metrics={},
            flags={"execution_gap": True},
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
            "description": _GAP_PITCH,
            "average_order_value": 999,
        },
        assumptions=[],
        product_type=ProductType.SAAS,
    )
    assert "FounderExecutionArchitect" in result.cluster_results[
        "metro_power_professional"
    ]
    assert any(
        report.architect_name == "FounderExecutionArchitect"
        for report in result.domain_reports
    )
    findings = AccountabilityEngine().generate_domain_findings(result)
    assert any(
        finding.architect_name == "FounderExecutionArchitect"
        for finding in findings
    )


def test_registry_includes_architect_in_every_product_stack() -> None:
    from app.simulation.architect_registry import build_architect_registry
    from app.simulation.conductor import (
        ARCHITECT_STACKS,
        ProductType,
    )

    registry = build_architect_registry()
    assert "FounderExecutionArchitect" in registry
    for product_type in ProductType:
        stack = ARCHITECT_STACKS[product_type]
        assert "FounderExecutionArchitect" in stack
        assert stack[0] == "MarketTimingArchitect"
        assert stack[-1] == "AssumptionCascadeArchitect"
        assert stack[-2] == "FounderExecutionArchitect"


def test_registered_in_calibration_and_specificity_rules() -> None:
    from app.simulation.calibration_engine import ALL_ARCHITECT_NAMES
    from app.simulation.scored_assumption import SPECIFICITY_RULES

    assert "FounderExecutionArchitect" in ALL_ARCHITECT_NAMES
    assert "FounderExecutionArchitect" in SPECIFICITY_RULES


def test_accountability_benchmarks_cover_execution_metrics() -> None:
    from app.simulation.accountability import AccountabilityEngine

    benchmarks = AccountabilityEngine.HEALTHY_BENCHMARKS
    for metric in (
        "execution_credibility_score",
        "delivery_risk",
        "execution_funnel_suppressor",
    ):
        assert metric in benchmarks, metric
        assert metric in AccountabilityEngine.FINDING_TEMPLATES, metric
        assert metric in AccountabilityEngine.RECOMMENDED_ACTIONS, metric
    assert "delivery_risk" in AccountabilityEngine.LOWER_IS_BETTER
