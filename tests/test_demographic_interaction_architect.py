"""
Tests for ``app.simulation.architects.demographic_interaction`` —
DemographicInteractionArchitect.

Locks down all six correction paths (motivation overrides price, geo
compound, age × trust, regional language, family dynamics, student
compound), the `_is_tier3_geo` / `_is_tier2_geo` private helpers,
the overall correction composition, severity tiers, flags, narrative
findings, and the generate_report() rollup.
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
    trust: float = 0.5,
    income: float = 0.5,
    price_sens: float = 0.5,
    risk: float = 0.5,
    patience: float = 0.5,
    social: float = 0.5,
    cluster_id: str = "metro_power_professional",
    geography: str = "metro_delhi",
    age_bracket: str = "25-35",
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
        product_affinities=["saas"],
        demographic_profile={"geography": geography, "age_bracket": age_bracket},
    )


# ---------------------------------------------------------------------------
# name + product_types
# ---------------------------------------------------------------------------


def test_demographic_interaction_name_constant() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    assert DemographicInteractionArchitect().name == "DemographicInteractionArchitect"


def test_demographic_interaction_product_types_is_all() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect
    from app.simulation.architects.base import BaseArchitect

    pt = DemographicInteractionArchitect().product_types
    assert set(pt) == set(BaseArchitect.ALL_PRODUCT_TYPES)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def test_is_tier3_geo_matches_tier3_variants() -> None:
    from app.simulation.architects.demographic_interaction import _is_tier3_geo

    assert _is_tier3_geo("tier3") is True
    assert _is_tier3_geo("tier3_rural") is True
    assert _is_tier3_geo("tier3_village") is True
    assert _is_tier3_geo("metro") is False
    assert _is_tier3_geo("tier2") is False


def test_is_tier2_geo_matches_tier2_variants() -> None:
    from app.simulation.architects.demographic_interaction import _is_tier2_geo

    assert _is_tier2_geo("tier2") is True
    assert _is_tier2_geo("tier2_city") is True
    assert _is_tier2_geo("tier3_rural") is False
    assert _is_tier2_geo("metro") is False


# ---------------------------------------------------------------------------
# Metric surface
# ---------------------------------------------------------------------------


def test_compute_default_corrections_at_one() -> None:
    """All corrections = 1.0 when no special conditions are met."""
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    # 18 keys: 6 paths (3+3+3+1+4+3) + overall.
    assert out.architect_name == "DemographicInteractionArchitect"
    # Most paths produce 1.0 (default) keys; verify a few.
    assert out.metrics["price_ceiling_interaction_mult"] == 1.0
    assert out.metrics["onboarding_compound_correction"] == 1.0
    assert out.metrics["regional_onboarding_penalty"] == 1.0
    assert out.metrics["household_income_mult"] == 1.0
    assert out.metrics["freemium_ceiling_student_mult"] == 1.0


# ---------------------------------------------------------------------------
# Path 1: motivation overrides price
# ---------------------------------------------------------------------------


def test_motivation_overrides_price_when_both_high() -> None:
    """motivation > 0.80 AND price_s > 0.70 → mult > 1.0."""
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(motivation=0.9, price_sens=0.8),
        agent_profile={}, assumptions=[], env_params={},
    )
    # formula: 1.0 + motivation * 0.32 → 1.0 + 0.9 * 0.32 = 1.288 → round 1.288
    assert out.metrics["price_ceiling_interaction_mult"] == 1.288
    assert out.flags["motivation_overrides_price"] is True


def test_motivation_overrides_price_skipped_when_either_low() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        # motivation high but price_sens low → skipped
        cluster=_cluster(motivation=0.9, price_sens=0.5),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["price_ceiling_interaction_mult"] == 1.0
    assert out.flags["motivation_overrides_price"] is False


# ---------------------------------------------------------------------------
# Path 2: geo compound literacy gap
# ---------------------------------------------------------------------------


def test_tier3_literacy_gap_corrections() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(literacy=0.3, geography="tier3"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["onboarding_compound_correction"] == 0.55
    assert out.metrics["support_ticket_compound_mult"] == 1.45
    assert out.metrics["social_proof_threshold_mult"] == 1.30
    assert out.flags["tier3_compound_gap"] is True


def test_tier2_literacy_gap_corrections() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(literacy=0.5, geography="tier2"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["onboarding_compound_correction"] == 0.82
    assert out.metrics["support_ticket_compound_mult"] == 1.20
    assert out.metrics["social_proof_threshold_mult"] == 1.10


def test_geo_inequality_path_skipped_for_high_literacy_tier3() -> None:
    """literacy ≥ 0.50 in tier3 → no compound gap applied."""
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(literacy=0.9, geography="tier3"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["onboarding_compound_correction"] == 1.0


# ---------------------------------------------------------------------------
# Path 3: age × trust
# ---------------------------------------------------------------------------


def test_age_older_45_amplifies_proof_and_trust_decay() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(age_bracket="45-55"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["social_proof_age_mult"] == 1.42
    assert out.metrics["trust_decay_age_mult"] == 1.35
    assert out.metrics["trust_recovery_age_mult"] == 1.60


def test_age_younger_18_24_reduces_proof_and_trust() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(age_bracket="18-24"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["social_proof_age_mult"] == 0.65
    assert out.metrics["trust_decay_age_mult"] == 0.80
    assert out.metrics["trust_recovery_age_mult"] == 0.65


def test_age_default_neutral_at_25_35() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(age_bracket="25-35"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["social_proof_age_mult"] == 1.0
    assert out.metrics["trust_decay_age_mult"] == 1.0
    assert out.metrics["trust_recovery_age_mult"] == 1.0


# ---------------------------------------------------------------------------
# Path 4: regional language
# ---------------------------------------------------------------------------


def test_tier3_regional_penalty_when_no_language_support() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(geography="tier3"),
        agent_profile={}, assumptions=[],
        env_params={},
    )
    assert out.metrics["regional_onboarding_penalty"] == 0.65
    assert out.flags["regional_language_gap"] is True


def test_regional_penalty_lifted_when_hindi_keyword_in_assumption() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(geography="tier3"),
        agent_profile={},
        assumptions=[{"text": "We have Hindi UI and regional language support."}],
        env_params={},
    )
    assert out.metrics["regional_onboarding_penalty"] == 1.0
    assert out.flags["regional_language_gap"] is False


def test_regional_penalty_at_083_in_tier2_without_language() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(geography="tier2"),
        agent_profile={}, assumptions=[],
        env_params={},
    )
    assert out.metrics["regional_onboarding_penalty"] == 0.83


# ---------------------------------------------------------------------------
# Path 5: family / household
# ---------------------------------------------------------------------------


def test_joint_family_dynamics_activate_when_family_oriented() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(cluster_id="metro_family_parent"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["household_income_mult"] == 1.65
    assert out.metrics["decision_cycle_mult"] == 1.45
    assert out.metrics["gift_probability_mult"] == 1.55
    assert out.metrics["packaging_weight_mult"] == 1.35
    assert out.flags["joint_family_dynamics"] is True


def test_joint_family_dynamics_activate_when_couple() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(cluster_id="metro_couple_user"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["joint_family_dynamics"] is True


def test_joint_family_dynamics_skipped_for_individual_cluster() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(cluster_id="random_individual"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["household_income_mult"] == 1.0


# ---------------------------------------------------------------------------
# Path 6: student compound
# ---------------------------------------------------------------------------


def test_student_compound_corrections() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(cluster_id="metro_student_user"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["freemium_ceiling_student_mult"] == 0.48
    assert out.metrics["viral_coefficient_student_mult"] == 1.65
    assert out.metrics["community_participation_mult"] == 1.45
    assert out.flags["student_compound"] is True


def test_student_compound_activate_for_college() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(cluster_id="metro_college_user"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["student_compound"] is True


def test_student_compound_skipped_for_non_student_cluster() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(cluster_id="random_professional"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["freemium_ceiling_student_mult"] == 1.0


# ---------------------------------------------------------------------------
# Overall correction + severity
# ---------------------------------------------------------------------------


def test_overall_correction_clamped_in_range() -> None:
    """overall_demographic_correction ∈ [0.10, 2.0]."""
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    # Hit tier3 + low literacy + family + student — heavy tier3 penalty.
    heavy = DemographicInteractionArchitect().compute(
        cluster=_cluster(
            cluster_id="tier3_family_student",
            literacy=0.1,
            geography="tier3",
        ),
        agent_profile={}, assumptions=[],
        env_params={},
    )
    assert 0.10 <= heavy.metrics["overall_demographic_correction"] <= 2.0

    # Happy-path metro: should be 1.0.
    metro = DemographicInteractionArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={},
    )
    assert metro.metrics["overall_demographic_correction"] == 1.0


def test_severity_warning_when_active_corrections_ge_3() -> None:
    """3+ non-default corrections → WARNING."""
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    # motivation high + tier3 + family → 4 active corrections
    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(
            cluster_id="tier3_family_user",
            motivation=0.9, price_sens=0.8,
            literacy=0.3, geography="tier3",
        ),
        agent_profile={}, assumptions=[], env_params={},
    )
    n_active = sum(
        1 for k, v in out.metrics.items()
        if v != 1.0 and k != "overall_demographic_correction"
    )
    assert n_active >= 3
    assert out.severity == "WARNING"


def test_severity_info_when_active_corrections_lt_3() -> None:
    """Default metro cluster → 0 active non-default corrections → INFO."""
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={},
    )
    n_active = sum(
        1 for k, v in out.metrics.items()
        if v != 1.0 and k != "overall_demographic_correction"
    )
    assert n_active == 0
    assert out.severity == "INFO"


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


def test_flags_correct_for_full_activation() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(
            cluster_id="tier3_student_user",
            literacy=0.3, geography="tier3",
            motivation=0.9, price_sens=0.8,
        ),
        agent_profile={},
        assumptions=[{"text": "Cluster has Hindi UI."}],
        env_params={},
    )
    # 4 active → motivation, tier3, joint_family (no — no family keywords), student
    assert out.flags["motivation_overrides_price"] is True
    assert out.flags["tier3_compound_gap"] is True
    # regional_language_gap = False (Hindi UI present)
    assert out.flags["regional_language_gap"] is False
    assert out.flags["student_compound"] is True


# ---------------------------------------------------------------------------
# Narrative findings
# ---------------------------------------------------------------------------


def test_compute_returns_two_narrative_findings() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    out = DemographicInteractionArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert len(out.narrative_findings) == 2
    joined = " | ".join(out.narrative_findings)
    assert "Active corrections" in joined or "corrections" in joined
    assert "Overall demographic correction" in joined or "demographic" in joined


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_empty_list_returns_info() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    a = DemographicInteractionArchitect()
    report = a.generate_report([])
    assert report.severity == "INFO"
    assert report.affected_cluster_ids == []


def test_generate_report_collects_tier3_and_language_gaps() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect
    from app.simulation.architects.base import ArchitectOutput

    a = DemographicInteractionArchitect()
    gap = ArchitectOutput(
        architect_name="DemographicInteractionArchitect",
        cluster_id="tier3_user",
        metrics={},
        flags={"tier3_compound_gap": True, "regional_language_gap": True},
        narrative_findings=[],
        severity="WARNING",
    )
    ok = ArchitectOutput(
        architect_name="DemographicInteractionArchitect",
        cluster_id="metro_pro",
        metrics={},
        flags={"tier3_compound_gap": False, "regional_language_gap": False},
        narrative_findings=[],
        severity="INFO",
    )
    report = a.generate_report([gap, ok])
    assert report.severity == "WARNING"
    assert "tier3_user" in report.affected_cluster_ids
    assert "metro_pro" not in report.affected_cluster_ids


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_compute_is_deterministic() -> None:
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect

    a = DemographicInteractionArchitect()
    kwargs = {"cluster": _cluster(), "agent_profile": {}, "assumptions": [], "env_params": {}}
    a1 = a.compute(**kwargs)
    a2 = a.compute(**kwargs)
    assert a1.metrics == a2.metrics
    assert a1.severity == a2.severity
    assert a1.flags == a2.flags
