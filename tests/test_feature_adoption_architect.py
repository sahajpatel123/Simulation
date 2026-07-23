"""
Tests for ``app.simulation.architects.feature_adoption`` —
FeatureAdoptionArchitect.

Locks down cluster-derived scores, complexity influence, metric caps
and bounds, severity tiers, flags, narrative findings, and the
generate_report() cross-cluster rollup.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Cluster fixture
# ---------------------------------------------------------------------------


def _cluster(
    *,
    literacy: float = 0.5,
    motivation: float = 0.5,
    patience: float = 0.5,
    trust: float = 0.5,
    income: float = 0.5,
    price_sens: float = 0.5,
    risk: float = 0.5,
    social: float = 0.5,
    cluster_id: str = "metro_power_professional",
    product_affinities: tuple[str, ...] = ("saas",),
) -> Any:
    from app.simulation.clusters.definitions import ClusterDefinition

    return ClusterDefinition(
        cluster_id=cluster_id,
        name="Test",
        description="Test",
        population_weight=0.1,
        base_traits={
            "income_level": income,
            "digital_literacy": literacy,
            "motivation": motivation,
            "trust": trust,
            "price_sensitivity": price_sens,
            "risk_aversion": risk,
            "patience_score": patience,
            "social_orientation": social,
        },
        trait_variance={k: 0.05 for k in (
            "income_level", "digital_literacy", "motivation", "trust",
            "price_sensitivity", "risk_aversion", "patience_score",
            "social_orientation",
        )},
        dominant_behavior_pattern="test",
        known_failure_modes=[],
        product_affinities=list(product_affinities),
        demographic_profile={"geography": "metro_delhi"},
    )


# ---------------------------------------------------------------------------
# name + product_types
# ---------------------------------------------------------------------------


def test_feature_adoption_architect_name_constant() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    assert FeatureAdoptionArchitect().name == "FeatureAdoptionArchitect"


def test_feature_adoption_architect_product_types_subset() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    pt = FeatureAdoptionArchitect().product_types
    # Limited subset: saas, developer_tool, enterprise_software, mobile_app.
    assert "saas" in pt
    assert "developer_tool" in pt
    assert "enterprise_software" in pt
    assert "mobile_app" in pt
    # Not a hardware / marketplace architect.
    for excluded in ("health_hardware", "consumer_hardware", "wearable", "iot_hardware", "marketplace"):
        assert excluded not in pt


# ---------------------------------------------------------------------------
# Metric surface
# ---------------------------------------------------------------------------


def test_compute_returns_ten_metrics() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    out = FeatureAdoptionArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={}
    )
    assert out.architect_name == "FeatureAdoptionArchitect"
    assert len(out.metrics) == 10


# ---------------------------------------------------------------------------
# core_feature_dau_rate
# ---------------------------------------------------------------------------


def test_core_feature_dau_rate_capped_at_095() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    out = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=1.0, motivation=1.0, patience=1.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["core_feature_dau_rate"] <= 0.95


def test_core_feature_dau_scales_with_motivation() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    low = FeatureAdoptionArchitect().compute(
        cluster=_cluster(motivation=0.1),
        agent_profile={}, assumptions=[], env_params={},
    )
    high = FeatureAdoptionArchitect().compute(
        cluster=_cluster(motivation=0.9),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert high.metrics["core_feature_dau_rate"] > low.metrics["core_feature_dau_rate"]


# ---------------------------------------------------------------------------
# power_feature_discovery_rate
# ---------------------------------------------------------------------------


def test_power_discovery_higher_for_high_literacy() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    low = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=0.1, motivation=0.1),
        agent_profile={}, assumptions=[], env_params={},
    )
    high = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=0.9, motivation=0.9),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert high.metrics["power_feature_discovery_rate"] > low.metrics["power_feature_discovery_rate"]


def test_power_discovery_literacy_threshold_at_06() -> None:
    """literacy > 0.6 → ×1.4, else ×0.5. Strict inequality at 0.6."""
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    just_below = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=0.55, motivation=0.55),
        agent_profile={}, assumptions=[], env_params={},
    )
    just_above = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=0.65, motivation=0.65),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert just_above.metrics["power_feature_discovery_rate"] > just_below.metrics["power_feature_discovery_rate"]


def test_power_discovery_capped_at_090() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    out = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=1.0, motivation=1.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["power_feature_discovery_rate"] <= 0.90


# ---------------------------------------------------------------------------
# feature_depth_score
# ---------------------------------------------------------------------------


def test_feature_depth_capped_at_095() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    out = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=1.0, motivation=1.0, patience=1.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["feature_depth_score"] <= 0.95


def test_feature_depth_low_for_low_traits() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    out = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=0.0, motivation=0.0, patience=0.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["feature_depth_score"] < 0.20
    assert out.severity == "CRITICAL"


# ---------------------------------------------------------------------------
# collaboration_adoption_rate
# ---------------------------------------------------------------------------


def test_collab_rate_enterprise_higher_than_consumer() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    consumer = FeatureAdoptionArchitect().compute(
        cluster=_cluster(cluster_id="metro_consumer"),
        agent_profile={}, assumptions=[], env_params={},
    )
    enterprise = FeatureAdoptionArchitect().compute(
        cluster=_cluster(cluster_id="enterprise_decision_maker"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert enterprise.metrics["collaboration_adoption_rate"] > consumer.metrics["collaboration_adoption_rate"]


def test_collab_rate_scales_with_trust() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    low = FeatureAdoptionArchitect().compute(
        cluster=_cluster(cluster_id="enterprise_team", trust=0.1),
        agent_profile={}, assumptions=[], env_params={},
    )
    high = FeatureAdoptionArchitect().compute(
        cluster=_cluster(cluster_id="enterprise_team", trust=0.9),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert high.metrics["collaboration_adoption_rate"] > low.metrics["collaboration_adoption_rate"]


# ---------------------------------------------------------------------------
# integration_adoption_rate (note the existing formula)
# ---------------------------------------------------------------------------


def test_integration_rate_tier3_attenuated() -> None:
    """tier3 in cluster_id → ×0.3 multiplier on builder_orient term."""
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    metro = FeatureAdoptionArchitect().compute(
        cluster=_cluster(cluster_id="metro_power_professional"),
        agent_profile={}, assumptions=[], env_params={},
    )
    tier3 = FeatureAdoptionArchitect().compute(
        cluster=_cluster(cluster_id="tier3_first_time_app_user"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert tier3.metrics["integration_adoption_rate"] < metro.metrics["integration_adoption_rate"]


# ---------------------------------------------------------------------------
# advanced_settings_exploration
# ---------------------------------------------------------------------------


def test_advanced_settings_curiosity_threshold() -> None:
    """curiosity > 0.6 → ×1.5 multiplier; else ×0.5."""
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    low = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=0.3, motivation=0.3),
        agent_profile={}, assumptions=[], env_params={},
    )
    high = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=0.9, motivation=0.9),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert high.metrics["advanced_settings_exploration"] > low.metrics["advanced_settings_exploration"]


def test_advanced_settings_capped_at_070() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    out = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=1.0, motivation=1.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["advanced_settings_exploration"] <= 0.70


# ---------------------------------------------------------------------------
# api_adoption_rate
# ---------------------------------------------------------------------------


def test_api_adoption_zero_for_low_literacy() -> None:
    """literacy < 0.4 → ×0.0 multiplier → rate is 0."""
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    out = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=0.1, motivation=0.9),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["api_adoption_rate"] == 0.0


def test_api_adoption_higher_for_developer_cluster() -> None:
    """builder_orient = 0.8 for developer_tool affinity, 0.3 otherwise."""
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    consumer = FeatureAdoptionArchitect().compute(
        cluster=_cluster(cluster_id="metro_user", product_affinities=("saas",)),
        agent_profile={}, assumptions=[], env_params={},
    )
    developer = FeatureAdoptionArchitect().compute(
        cluster=_cluster(cluster_id="metro_developer", product_affinities=("developer_tool",)),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert developer.metrics["api_adoption_rate"] > consumer.metrics["api_adoption_rate"]


# ---------------------------------------------------------------------------
# feature_abandonment_rate
# ---------------------------------------------------------------------------


def test_abandonment_floored_at_005() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    out = FeatureAdoptionArchitect().compute(
        cluster=_cluster(patience=1.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["feature_abandonment_rate"] >= 0.05


def test_abandonment_higher_under_complex_assumptions() -> None:
    """complexity > 0.6 → ×1.5 multiplier on abandonment."""
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    base = FeatureAdoptionArchitect().compute(
        cluster=_cluster(patience=0.3), agent_profile={},
        assumptions=[], env_params={},
    )
    complex_out = FeatureAdoptionArchitect().compute(
        cluster=_cluster(patience=0.3), agent_profile={},
        assumptions=[{"text": "Product is complex with many features"}],
        env_params={},
    )
    assert complex_out.metrics["feature_abandonment_rate"] > base.metrics["feature_abandonment_rate"]


# ---------------------------------------------------------------------------
# export_reporting_usage + dashboard_customisation
# ---------------------------------------------------------------------------


def test_export_usage_higher_for_professional_clusters() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    consumer = FeatureAdoptionArchitect().compute(
        cluster=_cluster(cluster_id="metro_consumer"),
        agent_profile={}, assumptions=[], env_params={},
    )
    pro = FeatureAdoptionArchitect().compute(
        cluster=_cluster(cluster_id="metro_professional"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert pro.metrics["export_reporting_usage"] > consumer.metrics["export_reporting_usage"]


def test_dashboard_customisation_higher_for_patient_users() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    impatient = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=0.5, patience=0.1),
        agent_profile={}, assumptions=[], env_params={},
    )
    patient = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=0.5, patience=0.9),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert patient.metrics["dashboard_customisation_rate"] > impatient.metrics["dashboard_customisation_rate"]


def test_export_and_dashboard_capped_at_060() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    out = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=1.0, motivation=1.0, patience=1.0,
                         cluster_id="metro_professional"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["export_reporting_usage"] <= 0.60
    assert out.metrics["dashboard_customisation_rate"] <= 0.60


# ---------------------------------------------------------------------------
# Severity + flags
# ---------------------------------------------------------------------------


def test_severity_critical_when_feature_depth_below_020() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    out = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=0.0, motivation=0.0, patience=0.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.severity == "CRITICAL"
    assert out.flags["shallow_adoption_risk"] is True


def test_severity_warning_when_feature_depth_between_020_and_040() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    out = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=0.3, motivation=0.3, patience=0.3),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.severity == "WARNING"


def test_severity_info_when_feature_depth_above_040() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    out = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=0.9, motivation=0.9, patience=0.9),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.severity == "INFO"


def test_flag_no_api_interest_when_api_rate_below_005() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    out = FeatureAdoptionArchitect().compute(
        cluster=_cluster(literacy=0.1),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["api_adoption_rate"] < 0.05
    assert out.flags["no_api_interest"] is True


def test_flag_collab_blocked_for_consumer_with_low_trust() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    out = FeatureAdoptionArchitect().compute(
        cluster=_cluster(cluster_id="metro_consumer", trust=0.1),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["collaboration_adoption_rate"] < 0.10
    assert out.flags["collaboration_blocked"] is True


# ---------------------------------------------------------------------------
# Narrative findings
# ---------------------------------------------------------------------------


def test_compute_returns_two_narrative_findings() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    out = FeatureAdoptionArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert len(out.narrative_findings) == 2
    joined = " | ".join(out.narrative_findings)
    assert "Feature depth" in joined or "feature depth" in joined
    assert "Power feature" in joined or "power feature" in joined


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_no_shallow_handles_empty() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    a = FeatureAdoptionArchitect()
    report = a.generate_report([])
    assert report.severity == "INFO"
    assert report.affected_cluster_ids == []


def test_generate_report_collects_shallow_clusters() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect
    from app.simulation.architects.base import ArchitectOutput

    a = FeatureAdoptionArchitect()
    shallow = ArchitectOutput(
        architect_name="FeatureAdoptionArchitect",
        cluster_id="tier3_shallow",
        metrics={},
        flags={"shallow_adoption_risk": True},
        narrative_findings=[],
        severity="CRITICAL",
    )
    deep = ArchitectOutput(
        architect_name="FeatureAdoptionArchitect",
        cluster_id="metro_deep",
        metrics={},
        flags={"shallow_adoption_risk": False},
        narrative_findings=[],
        severity="INFO",
    )
    report = a.generate_report([shallow, deep])
    assert report.severity == "WARNING"
    assert "tier3_shallow" in report.affected_cluster_ids
    assert "metro_deep" not in report.affected_cluster_ids


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_compute_is_deterministic() -> None:
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect

    a = FeatureAdoptionArchitect()
    kwargs = {"cluster": _cluster(), "agent_profile": {}, "assumptions": [], "env_params": {}}
    a1 = a.compute(**kwargs)
    a2 = a.compute(**kwargs)
    assert a1.metrics == a2.metrics
    assert a1.severity == a2.severity
    assert a1.flags == a2.flags
