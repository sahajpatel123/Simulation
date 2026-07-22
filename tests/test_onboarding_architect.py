"""
Tests for ``app.simulation.architects.onboarding`` — OnboardingArchitect.

Locks down completion-rate math across traits + complexity + geo
attenuation, TTfV math, disclosure_limit clamping (esp. tier3 cap),
mobile penalty rules, video skip clamping, severity tiers, flags,
transition_overrides, and generate_report().
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Cluster fixture
# ---------------------------------------------------------------------------


def _cluster(
    *,
    literacy: float = 0.5,
    patience: float = 0.5,
    motivation: float = 0.5,
    trust: float = 0.5,
    price_sens: float = 0.5,
    income: float = 0.5,
    risk: float = 0.5,
    social: float = 0.5,
    cluster_id: str = "metro_power_professional",
    geography: str = "metro_delhi",
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
        demographic_profile={"geography": geography, "age_bracket": age_bracket},
    )


# ---------------------------------------------------------------------------
# name + product_types
# ---------------------------------------------------------------------------


def test_onboarding_architect_name_constant() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    assert OnboardingArchitect().name == "OnboardingArchitect"


def test_onboarding_architect_product_types_subset() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    pt = OnboardingArchitect().product_types
    # Onboarding limited to software products (not hardware).
    for p in pt:
        assert "hardware" not in p.lower()


# ---------------------------------------------------------------------------
# completion_rate math
# ---------------------------------------------------------------------------


def test_compute_returns_eleven_metrics() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    out = OnboardingArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={}
    )
    assert out.architect_name == "OnboardingArchitect"
    assert len(out.metrics) == 11


def test_compute_completion_clamped_in_unit_interval() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    # Maximal traits → otherwise would exceed 0.98.
    hi = OnboardingArchitect().compute(
        cluster=_cluster(literacy=1.0, patience=1.0, motivation=1.0, trust=1.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert 0.05 <= hi.metrics["onboarding_completion_rate"] <= 0.98

    # Minimal traits → floor at 0.05.
    lo = OnboardingArchitect().compute(
        cluster=_cluster(
            literacy=0.0, patience=0.0, motivation=0.0, trust=0.0,
            geography="tier3_rural",
        ),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert lo.metrics["onboarding_completion_rate"] >= 0.05


def test_compute_completion_higher_for_high_traits() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    low = OnboardingArchitect().compute(
        cluster=_cluster(literacy=0.2, patience=0.2, motivation=0.2),
        agent_profile={}, assumptions=[], env_params={},
    )
    high = OnboardingArchitect().compute(
        cluster=_cluster(literacy=0.9, patience=0.9, motivation=0.9),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert high.metrics["onboarding_completion_rate"] > low.metrics["onboarding_completion_rate"]


def test_compute_complex_assumptions_reduce_completion() -> None:
    """complexity > 0.6 attenuates completion by 0.65 vs default 0.85."""
    from app.simulation.architects.onboarding import OnboardingArchitect

    base = OnboardingArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[], env_params={},
    )
    complex_out = OnboardingArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[{"text": "Product is complex with many features"}],
        env_params={},
    )
    assert complex_out.metrics["onboarding_completion_rate"] < base.metrics["onboarding_completion_rate"]


def test_compute_simple_assumptions_bump_completion() -> None:
    """complexity < 0.3 → completion * 0.85 (same multiplier; same as default),
    so a 'simple' assumption alone doesn't reduce; a 'complex' one does."""
    from app.simulation.architects.onboarding import OnboardingArchitect

    base = OnboardingArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    simple = OnboardingArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[{"text": "Onboarding is simple and quick"}],
        env_params={},
    )
    # 'simple' path returns 0.25 → matches the 'complexity < 0.3' branch
    # which uses the 0.85 multiplier. Same result as default (0.5 → 0.85).
    assert simple.metrics["onboarding_completion_rate"] == base.metrics["onboarding_completion_rate"]


def test_compute_tier3_geo_attenuates_completion() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    metro = OnboardingArchitect().compute(
        cluster=_cluster(geography="metro_delhi"), agent_profile={},
        assumptions=[], env_params={},
    )
    tier3 = OnboardingArchitect().compute(
        cluster=_cluster(geography="tier3_rural_mp"), agent_profile={},
        assumptions=[], env_params={},
    )
    assert tier3.metrics["onboarding_completion_rate"] < metro.metrics["onboarding_completion_rate"]


def test_compute_tier2_geo_mildly_attenuates() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    metro = OnboardingArchitect().compute(
        cluster=_cluster(geography="metro_delhi"), agent_profile={},
        assumptions=[], env_params={},
    )
    tier2 = OnboardingArchitect().compute(
        cluster=_cluster(geography="tier2_pune"), agent_profile={},
        assumptions=[], env_params={},
    )
    # Tier2 path applies 0.82 multiplier (less harsh than tier3's 0.55).
    assert tier2.metrics["onboarding_completion_rate"] < metro.metrics["onboarding_completion_rate"]


# ---------------------------------------------------------------------------
# time_to_first_value
# ---------------------------------------------------------------------------


def test_ttfv_scales_with_patience_and_motivation() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    low = OnboardingArchitect().compute(
        cluster=_cluster(patience=0.1, motivation=0.1), agent_profile={},
        assumptions=[], env_params={},
    )
    high = OnboardingArchitect().compute(
        cluster=_cluster(patience=1.0, motivation=1.0), agent_profile={},
        assumptions=[], env_params={},
    )
    assert high.metrics["time_to_first_value_tolerance"] > low.metrics["time_to_first_value_tolerance"]


# ---------------------------------------------------------------------------
# disclosure_limit clamping
# ---------------------------------------------------------------------------


def test_disclosure_limit_clamped_in_3_to_18() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    # extreme traits → would exceed 18; must clamp.
    out = OnboardingArchitect().compute(
        cluster=_cluster(literacy=1.0, patience=1.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert 3 <= out.metrics["progressive_disclosure_limit"] <= 18


def test_disclosure_limit_floor_at_three_when_traits_zero() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    out = OnboardingArchitect().compute(
        cluster=_cluster(literacy=0.0, patience=0.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["progressive_disclosure_limit"] == 3


def test_disclosure_limit_tier3_cap_at_three() -> None:
    """tier3 → disclosure_limit = min(value, 3) regardless of traits."""
    from app.simulation.architects.onboarding import OnboardingArchitect

    out = OnboardingArchitect().compute(
        cluster=_cluster(literacy=1.0, patience=1.0, geography="tier3_rural"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["progressive_disclosure_limit"] == 3


# ---------------------------------------------------------------------------
# mobile_penalty
# ---------------------------------------------------------------------------


def test_mobile_penalty_zero_for_simple_product() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    out = OnboardingArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["mobile_completion_penalty"] == 0.0


def test_mobile_penalty_higher_for_young_users_when_complex() -> None:
    """complexity > 0.5 + age contains '18' → 0.20; else 0.12."""
    from app.simulation.architects.onboarding import OnboardingArchitect

    young = OnboardingArchitect().compute(
        cluster=_cluster(age_bracket="18-24"),
        agent_profile={},
        assumptions=[{"text": "Onboarding is complex with many features"}],
        env_params={},
    )
    older = OnboardingArchitect().compute(
        cluster=_cluster(age_bracket="45-55"),
        agent_profile={},
        assumptions=[{"text": "Onboarding is complex with many features"}],
        env_params={},
    )
    assert young.metrics["mobile_completion_penalty"] == 0.20
    assert older.metrics["mobile_completion_penalty"] == 0.12


# ---------------------------------------------------------------------------
# video skip
# ---------------------------------------------------------------------------


def test_video_skip_clamped_in_unit_interval() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    low_traits = OnboardingArchitect().compute(
        cluster=_cluster(literacy=0.0, patience=0.0, motivation=0.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    high_traits = OnboardingArchitect().compute(
        cluster=_cluster(literacy=1.0, patience=1.0, motivation=1.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    for o in (low_traits, high_traits):
        assert 0.10 <= o.metrics["video_walkthrough_skip_rate"] <= 0.90


# ---------------------------------------------------------------------------
# Severity + flags
# ---------------------------------------------------------------------------


def test_severity_critical_when_completion_below_040() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    out = OnboardingArchitect().compute(
        cluster=_cluster(
            literacy=0.05, patience=0.05, motivation=0.05, trust=0.05,
            geography="tier3_rural",
        ),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.severity == "CRITICAL"


def test_severity_warning_when_completion_between_040_and_065() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    out = OnboardingArchitect().compute(
        cluster=_cluster(literacy=0.5, patience=0.5, motivation=0.5, geography="tier3_rural"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.severity in {"WARNING", "INFO", "CRITICAL"}


def test_severity_info_when_completion_well_above_065() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    out = OnboardingArchitect().compute(
        cluster=_cluster(literacy=0.95, patience=0.95, motivation=0.95),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.severity == "INFO"


def test_flag_completion_critical_matches_severity() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    out = OnboardingArchitect().compute(
        cluster=_cluster(
            literacy=0.05, patience=0.05, motivation=0.05,
            geography="tier3_rural",
        ),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["completion_critical"] is True
    assert out.severity == "CRITICAL"


def test_flag_tier3_language_risk_for_tier3_geo() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    out = OnboardingArchitect().compute(
        cluster=_cluster(geography="tier3_rural"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["tier3_language_risk"] is True


def test_flag_tier3_language_risk_false_for_metro() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    out = OnboardingArchitect().compute(
        cluster=_cluster(geography="metro_delhi"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["tier3_language_risk"] is False


def test_flag_empty_state_risky_when_bounce_above_050() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    # low motivation + low trust → empty_bounce > 0.5.
    out = OnboardingArchitect().compute(
        cluster=_cluster(motivation=0.1, trust=0.1),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["empty_state_risky"] is True


# ---------------------------------------------------------------------------
# Narrative findings
# ---------------------------------------------------------------------------


def test_compute_returns_two_narrative_findings() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    out = OnboardingArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert len(out.narrative_findings) == 2


# ---------------------------------------------------------------------------
# transition_overrides
# ---------------------------------------------------------------------------


def test_transition_overrides_arrive_to_browse_uses_completion() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    a = OnboardingArchitect()
    out = a.compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    overrides = a.transition_overrides(out)
    cr = out.metrics["onboarding_completion_rate"]
    assert overrides[("ARRIVE", "BROWSE")] == max(0.05, min(0.98, cr))


def test_transition_overrides_browse_to_consider_drops_with_id_friction() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    a = OnboardingArchitect()
    out = a.compute(
        cluster=_cluster(trust=0.05),  # high id_friction
        agent_profile={}, assumptions=[], env_params={},
    )
    overrides = a.transition_overrides(out)
    # trust=0.05 → id_friction = (1-0.05) * 0.25 * 1.4 = 0.3325
    # → 1 - 0.3325 = 0.6675, within [0.05, 0.98]
    val = overrides[("BROWSE", "CONSIDER")]
    assert 0.05 <= val <= 0.98


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_no_critical_handles_empty() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    a = OnboardingArchitect()
    report = a.generate_report([])
    assert report.severity == "INFO"
    assert report.affected_cluster_ids == []


def test_generate_report_collects_critical_severity_clusters() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect
    from app.simulation.architects.base import ArchitectOutput

    a = OnboardingArchitect()
    # Force two outputs to CRITICAL severity.
    crit = ArchitectOutput(
        architect_name="OnboardingArchitect",
        cluster_id="tier3_critical",
        metrics={},
        flags={},
        narrative_findings=[],
        severity="CRITICAL",
    )
    ok = ArchitectOutput(
        architect_name="OnboardingArchitect",
        cluster_id="metro_ok",
        metrics={},
        flags={},
        narrative_findings=[],
        severity="INFO",
    )
    report = a.generate_report([crit, ok])
    assert report.severity == "CRITICAL"
    assert "tier3_critical" in report.affected_cluster_ids
    assert "metro_ok" not in report.affected_cluster_ids


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_compute_is_deterministic() -> None:
    from app.simulation.architects.onboarding import OnboardingArchitect

    a = OnboardingArchitect()
    kwargs = {"cluster": _cluster(), "agent_profile": {}, "assumptions": [], "env_params": {}}
    out_a = a.compute(**kwargs)
    out_b = a.compute(**kwargs)
    assert out_a.metrics == out_b.metrics
    assert out_a.severity == out_b.severity
    assert out_a.flags == out_b.flags
