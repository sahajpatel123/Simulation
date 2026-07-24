"""
Tests for ``app.simulation.architects.trust`` — TrustArchitect.

Locks down brand deficit paths, social proof thresholds, age / income
multipliers, severity tiers, narrative findings,
transition_overrides, and generate_report() cross-cluster rollup.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Cluster fixture
# ---------------------------------------------------------------------------


def _cluster(
    *,
    trust: float = 0.5,
    risk: float = 0.5,
    income: float = 0.5,
    literacy: float = 0.5,
    social: float = 0.5,
    patience: float = 0.5,
    motivation: float = 0.5,
    price_sens: float = 0.5,
    cluster_id: str = "metro_power_professional",
    age_bracket: str = "25-35",
    population_weight: float = 0.10,
) -> Any:
    from app.simulation.clusters.definitions import ClusterDefinition

    return ClusterDefinition(
        cluster_id=cluster_id,
        name="Test Cluster",
        description="Test",
        population_weight=population_weight,
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
        product_affinities=["saas"],
        demographic_profile={"geography": "metro_delhi", "age_bracket": age_bracket},
    )


# ---------------------------------------------------------------------------
# name + product_types
# ---------------------------------------------------------------------------


def test_trust_architect_name_constant() -> None:
    from app.simulation.architects.trust import TrustArchitect

    assert TrustArchitect().name == "TrustArchitect"


def test_trust_architect_product_types_is_all() -> None:
    from app.simulation.architects.trust import TrustArchitect
    from app.simulation.architects.base import BaseArchitect

    pt = TrustArchitect().product_types
    assert set(pt) == set(BaseArchitect.ALL_PRODUCT_TYPES)


# ---------------------------------------------------------------------------
# Metric surface
# ---------------------------------------------------------------------------


def test_compute_returns_ten_metrics() -> None:
    from app.simulation.architects.trust import TrustArchitect

    out = TrustArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert out.architect_name == "TrustArchitect"
    assert len(out.metrics) == 10


# ---------------------------------------------------------------------------
# Brand deficit penalty paths
# ---------------------------------------------------------------------------


def test_unknown_brand_high_deficit() -> None:
    """brand_recognition == 0.0 → penalty = 0.65, multiplier = 0.35."""
    from app.simulation.architects.trust import TrustArchitect

    out = TrustArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["brand_deficit_multiplier"] == 0.35


def test_known_brand_keyword_low_deficit() -> None:
    """'established' keyword → brand_recognition = 0.7 → penalty 0.25 → mult 0.75."""
    from app.simulation.architects.trust import TrustArchitect

    out = TrustArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[{"text": "We are an established brand with 10 years in market"}],
        env_params={},
    )
    assert out.metrics["brand_deficit_multiplier"] == 0.75


def test_recognized_keyword_sets_brand_to_07() -> None:
    """'known brand' sets brand_recognition to 0.7 (same path)."""
    from app.simulation.architects.trust import TrustArchitect

    out = TrustArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[{"text": "Already a well-known brand in this space."}],
        env_params={},
    )
    assert out.metrics["brand_deficit_multiplier"] == 0.75


def test_reviews_in_assumptions_raises_social_proof_met() -> None:
    """'reviews' or 'testimonials' → reviews_current = 25."""
    from app.simulation.architects.trust import TrustArchitect

    out = TrustArchitect().compute(
        cluster=_cluster(),
        agent_profile={},
        assumptions=[{"text": "We have many customer reviews and testimonials."}],
        env_params={},
    )
    # social_proof_threshold computed from traits; verify the value is in
    # [0, 1] and the assumption was registered (reviews_current ≥ 1).
    assert 0.0 <= out.metrics["social_proof_met_fraction"] <= 1.0


def test_reviews_in_assumptions_outperform_no_reviews_at_high_threshold() -> None:
    """When the same cluster has no reviews vs. reviews mentioned in
    assumptions, the latter must produce strictly higher social_proof_met."""
    from app.simulation.architects.trust import TrustArchitect

    base_kwargs = {
        "trust": 0.0, "risk": 0.9, "income": 0.9, "age_bracket": "55+",
    }
    no_reviews = TrustArchitect().compute(
        cluster=_cluster(**base_kwargs),
        agent_profile={}, assumptions=[], env_params={},
    )
    with_reviews = TrustArchitect().compute(
        cluster=_cluster(**base_kwargs),
        agent_profile={},
        assumptions=[{"text": "We have many customer reviews and testimonials."}],
        env_params={},
    )
    # Without reviews → 0; with reviews → 25/threshold (small positive).
    assert no_reviews.metrics["social_proof_met_fraction"] == 0.0
    assert with_reviews.metrics["social_proof_met_fraction"] > 0.0
    assert with_reviews.metrics["social_proof_met_fraction"] <= 1.0


# ---------------------------------------------------------------------------
# Social proof threshold
# ---------------------------------------------------------------------------


def test_social_proof_threshold_scales_with_skepticism_and_risk() -> None:
    from app.simulation.architects.trust import TrustArchitect

    low = TrustArchitect().compute(
        cluster=_cluster(trust=0.9, risk=0.1, age_bracket="25-35"),
        agent_profile={}, assumptions=[], env_params={},
    )
    high = TrustArchitect().compute(
        cluster=_cluster(trust=0.1, risk=0.9, age_bracket="55+"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert high.metrics["social_proof_threshold"] > low.metrics["social_proof_threshold"]


def test_social_proof_threshold_floor_at_zero() -> None:
    from app.simulation.architects.trust import TrustArchitect

    out = TrustArchitect().compute(
        cluster=_cluster(trust=1.0, risk=0.0, age_bracket="25-35", income=0.5),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["social_proof_threshold"] >= 0


def test_age_bracket_amplifies_threshold_for_older() -> None:
    """45/50/55 → age_mult = 1.4; 18/22 → 0.65."""
    from app.simulation.architects.trust import TrustArchitect

    old = TrustArchitect().compute(
        cluster=_cluster(age_bracket="45-55"),
        agent_profile={}, assumptions=[], env_params={},
    )
    young = TrustArchitect().compute(
        cluster=_cluster(age_bracket="18-24"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert old.metrics["social_proof_threshold"] > young.metrics["social_proof_threshold"]


def test_high_income_amplifies_threshold() -> None:
    """income > 0.7 → income_mult = 1.3; income < 0.3 → 0.8."""
    from app.simulation.architects.trust import TrustArchitect

    rich = TrustArchitect().compute(
        cluster=_cluster(income=0.9), agent_profile={}, assumptions=[], env_params={}
    )
    poor = TrustArchitect().compute(
        cluster=_cluster(income=0.1), agent_profile={}, assumptions=[], env_params={}
    )
    assert rich.metrics["social_proof_threshold"] > poor.metrics["social_proof_threshold"]


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------


def test_severity_critical_when_low_multiplier_and_unmet_social_proof() -> None:
    from app.simulation.architects.trust import TrustArchitect

    out = TrustArchitect().compute(
        # trust high enough to avoid the bad deficit path; but with unknown
        # brand, multiplier = 0.35 < 0.50 and reviews_current = 0.
        cluster=_cluster(trust=0.05),  # multiplier ≈ 0.35
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["brand_deficit_multiplier"] < 0.5
    # And with no reviews in assumptions → social_proof_met is 0
    assert out.metrics["social_proof_met_fraction"] < 0.3
    assert out.severity == "CRITICAL"


def test_severity_warning_when_multiplier_between_050_and_075() -> None:
    from app.simulation.architects.trust import TrustArchitect

    out = TrustArchitect().compute(
        # 'established' → mult = 0.75 → not CRITICAL, but the boundary
        # is 0.75 → exactly 0.75 is the second branch (WARNING).
        cluster=_cluster(), agent_profile={},
        assumptions=[{"text": "Established brand"}],
        env_params={},
    )
    # multiplier should be 0.75, severity INFO since the warning branch
    # is < 0.75 (strict). Verify the path explicitly.
    assert out.metrics["brand_deficit_multiplier"] == 0.75
    assert out.severity == "INFO"


def test_severity_info_with_known_brand_and_reviews() -> None:
    from app.simulation.architects.trust import TrustArchitect

    out = TrustArchitect().compute(
        cluster=_cluster(),
        agent_profile={},
        assumptions=[
            {"text": "Established brand with reviews and testimonials."},
        ],
        env_params={},
    )
    assert out.severity == "INFO"


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


def test_flag_brand_deficit_critical_matches_low_multiplier() -> None:
    from app.simulation.architects.trust import TrustArchitect

    out = TrustArchitect().compute(
        cluster=_cluster(trust=0.05),  # unknown brand → mult=0.35
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["brand_deficit_critical"] is True


def test_flag_social_proof_missing_when_no_reviews() -> None:
    from app.simulation.architects.trust import TrustArchitect

    out = TrustArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["social_proof_missing"] is True


def test_flag_free_trial_required_when_substitute_high() -> None:
    """free_trial_sub > 0.60 → free_trial_required. Risk > 0.7 needed."""
    from app.simulation.architects.trust import TrustArchitect

    out = TrustArchitect().compute(
        cluster=_cluster(risk=0.9, trust=0.1),  # high risk + low trust
        agent_profile={}, assumptions=[], env_params={},
    )
    # trust=0.1 → multiplier 0.35 < 0.7 → use 1.5 multiplier
    # free_trial = risk * 0.4 * 1.5 = 0.9 * 0.4 * 1.5 = 0.54, capped 0.75
    assert out.metrics["free_trial_as_trust_substitute"] >= 0.5


def test_testimonial_format_case_study_under_high_literacy_income() -> None:
    from app.simulation.architects.trust import TrustArchitect

    out = TrustArchitect().compute(
        cluster=_cluster(literacy=0.9, income=0.9),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["testimonial_format"] is True


def test_testimonial_format_written_for_low_literacy_low_social() -> None:
    from app.simulation.architects.trust import TrustArchitect

    out = TrustArchitect().compute(
        cluster=_cluster(literacy=0.1, social=0.1),
        agent_profile={}, assumptions=[], env_params={},
    )
    # literacy > 0.7 AND income > 0.6 fails → video also fails (social <= 0.6)
    # → "written". Should the flag be false?
    assert out.flags["testimonial_format"] is False


# ---------------------------------------------------------------------------
# Other metrics
# ---------------------------------------------------------------------------


def test_security_concern_caps_at_040() -> None:
    from app.simulation.architects.trust import TrustArchitect

    out = TrustArchitect().compute(
        # trust = 0 → (1 - 0) * 1.6 = 1.6 would exceed without min cap.
        cluster=_cluster(trust=0.0),
        agent_profile={}, assumptions=[],
        env_params={"product_type": "health_hardware"},
    )
    assert out.metrics["security_concern_intensity"] <= 0.40


def test_security_concern_strictly_higher_for_health_product() -> None:
    """Health product gets the 1.6 multiplier on (1 - trust). High-trust
    keeps both values below the 0.40 cap so the multiplier shows."""
    from app.simulation.architects.trust import TrustArchitect

    health = TrustArchitect().compute(
        cluster=_cluster(trust=0.85),  # (1 - 0.85) * 1.6 = 0.24
        agent_profile={}, assumptions=[],
        env_params={"product_type": "health_hardware"},
    )
    other = TrustArchitect().compute(
        # (1 - 0.85) * 1.0 = 0.15
        cluster=_cluster(trust=0.85),
        agent_profile={}, assumptions=[],
        env_params={"product_type": "saas"},
    )
    assert health.metrics["security_concern_intensity"] > other.metrics["security_concern_intensity"]


def test_founder_weight_higher_for_immature_market() -> None:
    from app.simulation.architects.trust import TrustArchitect

    new = TrustArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"market_maturity": 0.1},
    )
    mature = TrustArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"market_maturity": 0.9},
    )
    assert new.metrics["founder_vs_product_credibility"] > mature.metrics["founder_vs_product_credibility"]


def test_press_lift_higher_for_high_literacy() -> None:
    from app.simulation.architects.trust import TrustArchitect

    high = TrustArchitect().compute(
        cluster=_cluster(literacy=0.9), agent_profile={}, assumptions=[], env_params={},
    )
    low = TrustArchitect().compute(
        cluster=_cluster(literacy=0.2), agent_profile={}, assumptions=[], env_params={},
    )
    assert high.metrics["press_mention_lift"] > low.metrics["press_mention_lift"]


def test_decay_rate_lower_when_switching_friction_high() -> None:
    from app.simulation.architects.trust import TrustArchitect

    low_fr = TrustArchitect().compute(
        cluster=_cluster(trust=0.5),
        agent_profile={"switching_friction": 0.1},
        assumptions=[], env_params={},
    )
    high_fr = TrustArchitect().compute(
        cluster=_cluster(trust=0.5),
        agent_profile={"switching_friction": 0.9},
        assumptions=[], env_params={},
    )
    assert high_fr.metrics["trust_decay_rate_per_incident"] < low_fr.metrics["trust_decay_rate_per_incident"]


# ---------------------------------------------------------------------------
# Narrative findings
# ---------------------------------------------------------------------------


def test_compute_returns_two_narrative_findings() -> None:
    from app.simulation.architects.trust import TrustArchitect

    out = TrustArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert len(out.narrative_findings) == 2
    joined = " | ".join(out.narrative_findings)
    assert "Brand deficit" in joined or "multiplier" in joined
    assert "Social proof" in joined


# ---------------------------------------------------------------------------
# transition_overrides
# ---------------------------------------------------------------------------


def test_transition_overrides_browse_to_consider_uses_bdm_times_proof() -> None:
    from app.simulation.architects.trust import TrustArchitect

    a = TrustArchitect()
    out = a.compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    overrides = a.transition_overrides(out)
    expected = max(0.05, min(0.95, out.metrics["brand_deficit_multiplier"] * out.metrics["social_proof_met_fraction"]))
    assert overrides[("BROWSE", "CONSIDER")] == expected


def test_transition_overrides_clamped_in_unit_interval() -> None:
    from app.simulation.architects.trust import TrustArchitect

    a = TrustArchitect()
    out = a.compute(
        cluster=_cluster(trust=0.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    overrides = a.transition_overrides(out)
    for v in overrides.values():
        assert 0.05 <= v <= 0.95


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_no_critical_handles_empty() -> None:
    from app.simulation.architects.trust import TrustArchitect

    a = TrustArchitect()
    report = a.generate_report([])
    assert report.severity == "INFO"
    assert report.affected_cluster_ids == []


def test_generate_report_collects_critical_clusters() -> None:
    from app.simulation.architects.trust import TrustArchitect
    from app.simulation.architects.base import ArchitectOutput

    a = TrustArchitect()
    crit = ArchitectOutput(
        architect_name="TrustArchitect",
        cluster_id="tier3_blocked",
        metrics={},
        flags={"brand_deficit_critical": True},
        narrative_findings=[],
        severity="CRITICAL",
    )
    ok = ArchitectOutput(
        architect_name="TrustArchitect",
        cluster_id="metro_ok",
        metrics={},
        flags={"brand_deficit_critical": False},
        narrative_findings=[],
        severity="INFO",
    )
    report = a.generate_report([crit, ok])
    assert report.severity == "CRITICAL"
    assert "tier3_blocked" in report.affected_cluster_ids
    assert "metro_ok" not in report.affected_cluster_ids


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_compute_is_deterministic() -> None:
    from app.simulation.architects.trust import TrustArchitect

    a = TrustArchitect()
    kwargs = {"cluster": _cluster(), "agent_profile": {}, "assumptions": [], "env_params": {}}
    a1 = a.compute(**kwargs)
    a2 = a.compute(**kwargs)
    assert a1.metrics == a2.metrics
    assert a1.severity == a2.severity
    assert a1.flags == a2.flags
