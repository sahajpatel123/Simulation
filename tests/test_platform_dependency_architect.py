"""
Tests for ``app.simulation.architects.platform_dependency`` —
PlatformDependencyArchitect.

Locks down app-store/algorithm/API-provider exposure detection,
concentration modelling, negation- and intent-aware mitigation evidence,
severity tiers, flags, narrative findings, Markov transition overrides,
the cross-cluster generate_report() rollup, and conductor/calibration
registration so platform dependence surfaces as an accountability finding.
"""

from __future__ import annotations

from typing import Any


def _cluster(
    *,
    trust: float = 0.5,
    risk: float = 0.5,
    literacy: float = 0.5,
    social: float = 0.5,
    cluster_id: str = "metro_power_professional",
) -> Any:
    from app.simulation.clusters.definitions import ClusterDefinition

    return ClusterDefinition(
        cluster_id=cluster_id,
        name="Test",
        description="Test",
        population_weight=0.1,
        base_traits={
            "income_level": 0.5,
            "digital_literacy": literacy,
            "motivation": 0.5,
            "trust": trust,
            "price_sensitivity": 0.5,
            "risk_aversion": risk,
            "patience_score": 0.5,
            "social_orientation": social,
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
    trust: float = 0.5,
    risk: float = 0.5,
    literacy: float = 0.5,
    social: float = 0.5,
    cluster_id: str = "metro_power_professional",
    assumptions: list[Any] | None = None,
    product_type: str = "mobile_app",
) -> Any:
    from app.simulation.architects.platform_dependency import (
        PlatformDependencyArchitect,
    )

    return PlatformDependencyArchitect().compute(
        cluster=_cluster(
            trust=trust,
            risk=risk,
            literacy=literacy,
            social=social,
            cluster_id=cluster_id,
        ),
        agent_profile={},
        assumptions=assumptions or [],
        env_params={"product_type": product_type},
    )


# ---------------------------------------------------------------------------
# Identity + baseline behaviour
# ---------------------------------------------------------------------------


def test_name_and_product_types() -> None:
    from app.simulation.architects.platform_dependency import (
        PlatformDependencyArchitect,
    )

    architect = PlatformDependencyArchitect()
    assert architect.name == "PlatformDependencyArchitect"
    assert architect.product_types == [
        "mobile_app", "consumer_app", "marketplace", "b2b_marketplace",
        "developer_tool", "saas", "productivity_tool", "d2c",
    ]


def test_baseline_compute_is_neutral_and_bounded() -> None:
    out = _compute()
    assert out.architect_name == "PlatformDependencyArchitect"
    assert len(out.metrics) == 8
    assert out.metrics["platform_dependency_exposure"] == 0.08
    assert out.metrics["dependency_concentration"] == 0.0
    assert out.metrics["single_channel_risk"] == 0.0
    assert out.metrics["platform_gate_risk"] == 0.0
    assert out.metrics["platform_risk_score"] == 0.0297
    assert out.metrics["platform_risk_suppressor"] == 1.0
    assert out.metrics["platform_advantage_lift"] == 0.0
    assert abs(out.metrics["mitigation_credibility"] - 0.928) < 1e-9
    assert all(0.0 <= value <= 1.0 for value in out.metrics.values())
    assert not any(out.flags.values())
    assert out.severity == "INFO"
    assert len(out.narrative_findings) == 2


def test_no_signals_means_no_transition_overrides() -> None:
    from app.simulation.architects.platform_dependency import (
        PlatformDependencyArchitect,
    )

    architect = PlatformDependencyArchitect()
    out = _compute()
    assert architect.transition_overrides(out) == {}


# ---------------------------------------------------------------------------
# Exposure detection and single-channel risk
# ---------------------------------------------------------------------------


def test_single_app_store_dependency_flags_gate_and_single_channel() -> None:
    out = _compute(
        assumptions=[{"text": "We rely on app store discovery and in-app purchases"}]
    )
    assert out.metrics["platform_dependency_exposure"] == 0.28
    assert out.metrics["dependency_concentration"] == 0.25
    assert out.metrics["single_channel_risk"] == 0.1191
    assert out.metrics["platform_gate_risk"] == 0.4644
    assert out.metrics["platform_risk_score"] == 0.279
    assert out.metrics["platform_risk_suppressor"] == 0.7629
    assert out.flags["app_store_gate"] is True
    assert out.flags["platform_single_dependency"] is True
    assert out.severity == "WARNING"


def test_search_algorithm_dependency_flags_algorithm_risk() -> None:
    out = _compute(
        assumptions=[{"text": "Growth depends on Google ads and search engine traffic"}]
    )
    assert out.metrics["platform_dependency_exposure"] == 0.28
    assert out.flags["algorithm_dependency"] is True
    assert out.flags["app_store_gate"] is False
    assert out.flags["platform_single_dependency"] is True
    assert out.severity == "WARNING"


def test_api_provider_concentration_flags_api_risk() -> None:
    out = _compute(
        assumptions=[{"text": "Product wraps the OpenAI API on AWS with Stripe billing"}]
    )
    assert out.metrics["platform_dependency_exposure"] == 0.28
    assert out.flags["api_provider_concentration"] is True
    assert out.severity == "WARNING"


def test_multi_platform_concentration_reaches_critical() -> None:
    out = _compute(
        assumptions=[
            {"text": "App store launch with Google ads and an OpenAI API backend"}
        ]
    )
    assert out.metrics["platform_dependency_exposure"] == 0.68
    assert out.metrics["dependency_concentration"] == 0.75
    assert out.metrics["platform_risk_score"] >= 0.55
    assert out.flags["app_store_gate"] is True
    assert out.flags["algorithm_dependency"] is True
    assert out.flags["api_provider_concentration"] is True
    assert out.flags["platform_single_dependency"] is False
    assert out.severity == "CRITICAL"


def test_low_trust_risk_averse_cluster_raises_risk() -> None:
    low_trust = _compute(
        trust=0.2,
        risk=0.8,
        literacy=0.3,
        assumptions=[{"text": "We rely on app store discovery"}],
    )
    avg = _compute(
        assumptions=[{"text": "We rely on app store discovery"}],
    )
    assert low_trust.metrics["platform_risk_score"] > avg.metrics["platform_risk_score"]


# ---------------------------------------------------------------------------
# Negation-aware exposure detection
# ---------------------------------------------------------------------------


def test_explicit_disclaimer_does_not_create_exposure() -> None:
    for text in (
        "We do not use the app store",
        "We don't rely on Google ads",
        "No reliance on any cloud provider",
        "We avoid app store dependence entirely",
        "We are independent of any app store",
        "We don't use AWS or Stripe",
    ):
        out = _compute(assumptions=[{"text": text}])
        assert out.metrics["platform_dependency_exposure"] == 0.08, text
        assert out.metrics["dependency_concentration"] == 0.0, text
        assert out.metrics["platform_gate_risk"] == 0.0, text
        assert out.metrics["platform_risk_suppressor"] == 1.0, text
        assert not any(out.flags.values()), text
        assert out.severity == "INFO", text


def test_negated_list_disclaimer_does_not_create_exposure() -> None:
    for text in (
        "We avoid the app store and Google Play",
        "We don't use the app store or Google Play",
        "We are independent of AWS and Google cloud",
    ):
        out = _compute(assumptions=[{"text": text}])
        assert out.metrics["platform_dependency_exposure"] == 0.08, text
        assert out.metrics["dependency_concentration"] == 0.0, text
        assert out.severity == "INFO", text


def test_disclaimer_in_one_clause_does_not_mask_dependence_in_another() -> None:
    out = _compute(
        assumptions=[
            {"text": "We don't use the app store but depend on Google ads"}
        ]
    )
    assert out.flags["app_store_gate"] is False
    assert out.flags["algorithm_dependency"] is True
    assert out.metrics["platform_dependency_exposure"] == 0.28
    assert out.severity == "WARNING"


def test_pending_status_mentions_still_count_as_exposure() -> None:
    for text in (
        "App store approval not yet received",
        "We don't have app store approval yet",
        "No app store approval yet",
        "We don't have app store approval",
    ):
        out = _compute(assumptions=[{"text": text}])
        assert out.metrics["platform_dependency_exposure"] == 0.28, text
        assert out.flags["app_store_gate"] is True, text
        assert out.severity == "WARNING", text


def test_partial_reliance_qualifier_keeps_exposure() -> None:
    out = _compute(
        assumptions=[{"text": "We don't rely solely on the app store"}]
    )
    assert out.metrics["platform_dependency_exposure"] == 0.28
    # "not rely solely" still means partial dependence, so the mention is
    # not a disclaimer; the negation itself is also treated as mitigation
    # evidence ("we do not rely" on a single channel).
    assert out.flags["platform_mitigation_advantage"] is True
    assert out.flags["app_store_gate"] is False
    assert out.severity == "INFO"


def test_discourse_focus_keeps_exposure() -> None:
    out = _compute(
        assumptions=[
            {"text": "We use not only the app store but also our own website"}
        ]
    )
    assert out.metrics["platform_dependency_exposure"] == 0.28
    # "not only X but also Y" presupposes the app-store mention (exposure
    # stays active) while "own website" is credible mitigation evidence.
    assert out.flags["app_store_gate"] is False
    assert out.flags["platform_mitigation_advantage"] is True


def test_not_independent_keeps_exposure() -> None:
    out = _compute(
        assumptions=[{"text": "We are not independent of the app store"}]
    )
    assert out.metrics["platform_dependency_exposure"] == 0.28
    assert out.flags["app_store_gate"] is True
    assert out.severity == "WARNING"


def test_none_assumptions_are_neutral() -> None:
    from app.simulation.architects.platform_dependency import (
        PlatformDependencyArchitect,
    )

    out = PlatformDependencyArchitect().compute(
        cluster=_cluster(),
        agent_profile={},
        assumptions=None,
        env_params={"product_type": "mobile_app"},
    )
    assert out.metrics["platform_dependency_exposure"] == 0.08
    assert out.metrics["platform_risk_suppressor"] == 1.0
    assert not any(out.flags.values())
    assert out.severity == "INFO"


# ---------------------------------------------------------------------------
# Mitigation evidence handling
# ---------------------------------------------------------------------------


def test_owned_channel_evidence_clears_gate_and_earns_lift() -> None:
    out = _compute(
        assumptions=[
            {"text": "We launch on the app store but also ship a web app "
                     "with an email list"}
        ]
    )
    assert out.metrics["mitigation_credibility"] == 1.0
    assert out.metrics["platform_gate_risk"] == 0.0
    assert out.flags["app_store_gate"] is False
    assert out.flags["platform_single_dependency"] is False
    assert out.flags["platform_mitigation_advantage"] is True
    assert out.metrics["platform_advantage_lift"] > 0.0
    assert out.metrics["platform_risk_suppressor"] < 1.0
    assert out.severity == "INFO"


def test_multi_channel_mitigation_lowers_concentration_risk() -> None:
    unmitigated = _compute(
        assumptions=[{"text": "App store launch with Google ads and OpenAI API"}]
    )
    mitigated = _compute(
        assumptions=[
            {"text": "App store launch with Google ads and OpenAI API, but we "
                     "also ship a web app, own an email list and support "
                     "multi-cloud deployment"}
        ]
    )
    assert (
        mitigated.metrics["platform_risk_score"]
        < unmitigated.metrics["platform_risk_score"]
    )
    assert unmitigated.severity == "CRITICAL"
    # Mitigations soften a multi-platform concentration to WARNING but do
    # not erase it — the founder is still substantially exposed.
    assert mitigated.severity == "WARNING"
    assert mitigated.flags["platform_mitigation_advantage"] is True


def test_negated_web_app_is_not_evidence() -> None:
    out = _compute(
        assumptions=[{"text": "We do not have a web app and no email list"}]
    )
    assert out.metrics["mitigation_credibility"] < 1.0
    assert out.flags["platform_mitigation_advantage"] is False
    assert out.metrics["platform_advantage_lift"] == 0.0


def test_contracted_negation_is_not_evidence() -> None:
    out = _compute(
        assumptions=[{"text": "We don't have a web app yet"}]
    )
    assert out.metrics["mitigation_credibility"] < 1.0
    assert out.flags["platform_mitigation_advantage"] is False


def test_intent_to_build_web_app_is_not_evidence() -> None:
    out = _compute(
        assumptions=[{"text": "We plan to build a web app and add a PWA"}]
    )
    assert out.metrics["mitigation_credibility"] < 1.0
    assert out.flags["platform_mitigation_advantage"] is False


def test_discourse_negation_does_not_void_real_evidence() -> None:
    out = _compute(
        assumptions=[
            {"text": "We will rely on the app store. No, we already have a "
                     "web app and an email list"}
        ]
    )
    assert out.metrics["mitigation_credibility"] == 1.0
    assert out.flags["app_store_gate"] is False
    assert out.flags["platform_mitigation_advantage"] is True


# ---------------------------------------------------------------------------
# Markov overrides
# ---------------------------------------------------------------------------


def test_transition_overrides_suppress_early_funnel_when_exposed() -> None:
    from app.simulation.architects.platform_dependency import (
        PlatformDependencyArchitect,
    )

    architect = PlatformDependencyArchitect()
    out = _compute(
        assumptions=[{"text": "We rely on app store discovery and in-app purchases"}]
    )
    overrides = architect.transition_overrides(out)
    assert ("BROWSE", "CONSIDER") in overrides
    assert ("CONSIDER", "DECIDE") in overrides
    assert 0.55 <= overrides[("BROWSE", "CONSIDER")] < 1.0
    assert overrides[("CONSIDER", "DECIDE")] > overrides[("BROWSE", "CONSIDER")]
    assert ("DECIDE", "PURCHASE") not in overrides


def test_transition_overrides_add_purchase_lift_with_evidence() -> None:
    from app.simulation.architects.platform_dependency import (
        PlatformDependencyArchitect,
    )

    architect = PlatformDependencyArchitect()
    out = _compute(
        assumptions=[
            {"text": "App store launch but also a web app with an email list"}
        ]
    )
    overrides = architect.transition_overrides(out)
    assert ("DECIDE", "PURCHASE") in overrides
    assert overrides[("DECIDE", "PURCHASE")] > 1.0
    assert overrides[("DECIDE", "PURCHASE")] <= 1.15


# ---------------------------------------------------------------------------
# generate_report()
# ---------------------------------------------------------------------------


def test_generate_report_empty_outputs_is_neutral() -> None:
    from app.simulation.architects.platform_dependency import (
        PlatformDependencyArchitect,
    )

    report = PlatformDependencyArchitect().generate_report([])
    assert report.architect_name == "PlatformDependencyArchitect"
    assert report.severity == "INFO"
    assert report.affected_cluster_ids == []
    assert report.conversion_impact == 0.0


def test_generate_report_critical_outputs_roll_up() -> None:
    from app.simulation.architects.base import ArchitectOutput
    from app.simulation.architects.platform_dependency import (
        PlatformDependencyArchitect,
    )

    critical = ArchitectOutput(
        architect_name="PlatformDependencyArchitect",
        cluster_id="cluster_a",
        metrics={"platform_dependency_exposure": 0.68},
        flags={
            "app_store_gate": True,
            "algorithm_dependency": True,
            "api_provider_concentration": True,
            "platform_single_dependency": False,
            "platform_mitigation_advantage": False,
        },
        narrative_findings=["x"],
        severity="CRITICAL",
    )
    warning = ArchitectOutput(
        architect_name="PlatformDependencyArchitect",
        cluster_id="cluster_b",
        metrics={"platform_dependency_exposure": 0.28},
        flags={
            "app_store_gate": True,
            "algorithm_dependency": False,
            "api_provider_concentration": False,
            "platform_single_dependency": True,
            "platform_mitigation_advantage": False,
        },
        narrative_findings=["y"],
        severity="WARNING",
    )
    info = ArchitectOutput(
        architect_name="PlatformDependencyArchitect",
        cluster_id="cluster_c",
        metrics={"platform_dependency_exposure": 0.08},
        flags={
            "app_store_gate": False,
            "algorithm_dependency": False,
            "api_provider_concentration": False,
            "platform_single_dependency": False,
            "platform_mitigation_advantage": True,
        },
        narrative_findings=["z"],
        severity="INFO",
    )
    report = PlatformDependencyArchitect().generate_report(
        [info, warning, critical]
    )
    assert report.severity == "CRITICAL"
    assert report.affected_cluster_ids == ["cluster_a", "cluster_b"]
    assert report.conversion_impact > 0.0
    assert "diversify" in report.recommended_action.lower()


# ---------------------------------------------------------------------------
# Conductor + calibration registration
# ---------------------------------------------------------------------------


def test_conductor_runs_architect_and_accountability_surfaces_finding() -> None:
    from app.simulation.accountability import AccountabilityEngine
    from app.simulation.conductor import Conductor, ProductType

    result = Conductor().run(
        agents=[],
        env_params={
            "description": "A mobile app for personal finance",
            "average_order_value": 499,
            "market_maturity": 0.5,
        },
        assumptions=[
            {"text": "We rely on app store discovery and in-app purchases"}
        ],
        product_type=ProductType.MOBILE_APP,
    )
    assert "PlatformDependencyArchitect" in result.cluster_results[
        "metro_power_professional"
    ]
    assert any(
        report.architect_name == "PlatformDependencyArchitect"
        for report in result.domain_reports
    )
    findings = AccountabilityEngine().generate_domain_findings(result)
    assert any(
        finding.architect_name == "PlatformDependencyArchitect"
        for finding in findings
    )


def test_registry_activates_architect_for_digital_stacks_only() -> None:
    from app.simulation.architect_registry import build_architect_registry
    from app.simulation.conductor import (
        ARCHITECT_STACKS,
    )
    from app.simulation.product_type import ProductType

    registry = build_architect_registry()
    assert "PlatformDependencyArchitect" in registry
    included = {
        ProductType.MOBILE_APP,
        ProductType.CONSUMER_APP,
        ProductType.MARKETPLACE,
        ProductType.B2B_MARKETPLACE,
        ProductType.DEVELOPER_TOOL,
        ProductType.SAAS,
        ProductType.PRODUCTIVITY_TOOL,
        ProductType.DIRECT_TO_CONSUMER,
    }
    excluded = {
        ProductType.ENTERPRISE_SOFTWARE,
        ProductType.CONSUMER_HARDWARE,
        ProductType.HEALTH_HARDWARE,
        ProductType.IOT_HARDWARE,
        ProductType.WEARABLE,
        ProductType.B2B_HARDWARE,
        ProductType.SMART_HOME,
    }
    for product_type in included:
        assert (
            "PlatformDependencyArchitect"
            in ARCHITECT_STACKS[product_type]
        )
        assert ARCHITECT_STACKS[product_type][-1] == "AssumptionCascadeArchitect"
    for product_type in excluded:
        assert (
            "PlatformDependencyArchitect"
            not in ARCHITECT_STACKS[product_type]
        )


def test_registered_in_calibration() -> None:
    from app.simulation.calibration_engine import ALL_ARCHITECT_NAMES

    assert "PlatformDependencyArchitect" in ALL_ARCHITECT_NAMES
