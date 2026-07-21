"""
Tests for AgentProfile dataclass and AgentProfileGenerator
(cycle 34 profile-test-coverage).

The existing ``test_profiles_variance.py`` covers the beta-sampling
variance multiplier; this suite fills the rest:

  1. AgentProfile.__post_init__ resolves the tier correctly per region.
  2. AgentProfile.to_dict exposes enums as string values.
  3. AgentProfileGenerator._build_trait_params adjusts per income/region/scenario.
  4. AgentProfileGenerator.generate_one / generate_from_cluster produce profiles
     with valid (in [0, 1]) trait values.
  5. generate_population is deterministic under a fixed seed.
  6. population_summary aggregates traits, devices, regions, income.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.simulation.profiles import (
    AgentProfile,
    AgentProfileGenerator,
    DeviceType,
    IncomeBracket,
    Region,
    SCENARIO_TRAIT_ADJUSTMENTS,
)


# ---------------------------------------------------------------------------
# AgentProfile dataclass
# ---------------------------------------------------------------------------


def test_agent_profile_tier_resolves_metro() -> None:
    p = AgentProfile(
        age=30,
        income_bracket=IncomeBracket.MIDDLE,
        monthly_income=50_000,
        region=Region.METRO,
        device_type=DeviceType.MOBILE,
        digital_literacy=0.5,
        price_sensitivity=0.5,
        patience_score=0.5,
        motivation=0.5,
        trust_baseline=0.5,
    )
    assert p.tier == "METRO"


def test_agent_profile_tier_resolves_tier1() -> None:
    for r in (Region.NORTH, Region.SOUTH, Region.EAST, Region.WEST):
        p = AgentProfile(
            age=30,
            income_bracket=IncomeBracket.MIDDLE,
            monthly_income=50_000,
            region=r,
            device_type=DeviceType.MOBILE,
            digital_literacy=0.5,
            price_sensitivity=0.5,
            patience_score=0.5,
            motivation=0.5,
            trust_baseline=0.5,
        )
        assert p.tier == "TIER1", f"Expected TIER1 for {r.value}, got {p.tier}"


def test_agent_profile_tier_resolves_tier2() -> None:
    p2 = AgentProfile(
        age=30,
        income_bracket=IncomeBracket.MIDDLE,
        monthly_income=50_000,
        region=Region.TIER2,
        device_type=DeviceType.MOBILE,
        digital_literacy=0.5,
        price_sensitivity=0.5,
        patience_score=0.5,
        motivation=0.5,
        trust_baseline=0.5,
    )
    assert p2.tier == "TIER2"


def test_agent_profile_tier_resolves_tier3() -> None:
    for r in (Region.TIER3, Region.CENTRAL):
        p3 = AgentProfile(
            age=30,
            income_bracket=IncomeBracket.MIDDLE,
            monthly_income=50_000,
            region=r,
            device_type=DeviceType.MOBILE,
            digital_literacy=0.5,
            price_sensitivity=0.5,
            patience_score=0.5,
            motivation=0.5,
            trust_baseline=0.5,
        )
        assert p3.tier == "TIER3"


def test_agent_profile_to_dict_uses_string_values() -> None:
    p = AgentProfile(
        age=30,
        income_bracket=IncomeBracket.MIDDLE,
        monthly_income=50_000,
        region=Region.METRO,
        device_type=DeviceType.MOBILE,
        digital_literacy=0.5,
        price_sensitivity=0.5,
        patience_score=0.5,
        motivation=0.5,
        trust_baseline=0.5,
    )
    d = p.to_dict()
    assert isinstance(d["income_bracket"], str)
    assert isinstance(d["region"], str)
    assert isinstance(d["device_type"], str)
    assert d["income_bracket"] == IncomeBracket.MIDDLE.value
    assert d["region"] == Region.METRO.value
    assert d["device_type"] == DeviceType.MOBILE.value
    assert d["tier"] == "METRO"


# ---------------------------------------------------------------------------
# AgentProfileGenerator._build_trait_params
# ---------------------------------------------------------------------------


def _params() -> tuple[IncomeBracket, Region, str | None]:
    return IncomeBracket.MIDDLE, Region.METRO, None


def test_build_trait_params_returns_all_five_traits() -> None:
    gen = AgentProfileGenerator()
    income, region, scenario = _params()
    params = gen._build_trait_params(income, region, scenario)
    for trait in (
        "digital_literacy",
        "price_sensitivity",
        "patience_score",
        "motivation",
        "trust_baseline",
    ):
        assert trait in params
        alpha, beta = params[trait]
        assert alpha > 0
        assert beta > 0


def test_build_trait_params_low_increases_price_sensitivity() -> None:
    gen = AgentProfileGenerator()
    middle_params = gen._build_trait_params(
        IncomeBracket.MIDDLE, Region.METRO, None
    )
    low_params = gen._build_trait_params(
        IncomeBracket.LOW_INCOME, Region.METRO, None
    )
    # LOW_INCOME adjustment shifts price_sensitivity alpha up by 1.2.
    assert low_params["price_sensitivity"][0] > middle_params["price_sensitivity"][0]


def test_build_trait_params_high_income_increases_digital_literacy_alpha() -> None:
    gen = AgentProfileGenerator()
    middle = gen._build_trait_params(
        IncomeBracket.MIDDLE, Region.METRO, None
    )
    high = gen._build_trait_params(
        IncomeBracket.HIGH_INCOME, Region.METRO, None
    )
    assert high["digital_literacy"][0] > middle["digital_literacy"][0]


def test_build_trait_params_recession_increases_price_sensitivity() -> None:
    gen = AgentProfileGenerator()
    baseline = gen._build_trait_params(
        IncomeBracket.MIDDLE, Region.METRO, None
    )
    recession = gen._build_trait_params(
        IncomeBracket.MIDDLE, Region.METRO, "RECESSION"
    )
    assert recession["price_sensitivity"][0] > baseline["price_sensitivity"][0]
    assert recession["motivation"][0] < baseline["motivation"][0]


def test_build_trait_params_unknown_scenario_is_safe() -> None:
    gen = AgentProfileGenerator()
    baseline = gen._build_trait_params(
        IncomeBracket.MIDDLE, Region.METRO, None
    )
    unknown = gen._build_trait_params(
        IncomeBracket.MIDDLE, Region.METRO, "UNKNOWN_SCENARIO_XYZ"
    )
    assert unknown == baseline


def test_build_trait_params_alpha_beta_floored_at_0_1() -> None:
    """Even after aggressive negative adjustments, alpha and beta stay ≥ 0.1."""
    gen = AgentProfileGenerator()
    # Apply multiple large negative adjustments to a single trait.
    # TIER3 has price_sensitivity alpha +0.8, but RECESSION has +1.5; combined
    # shifts are positive for price_sensitivity. To stress the floor, layer
    # negative-impact traits (motivation, trust_baseline).
    params = gen._build_trait_params(
        IncomeBracket.MIDDLE, Region.TIER3, "RECESSION"
    )
    for trait in params.values():
        assert trait[0] >= 0.1
        assert trait[1] >= 0.1


# ---------------------------------------------------------------------------
# Generator outputs are valid profiles
# ---------------------------------------------------------------------------


def test_generate_one_produces_valid_profile() -> None:
    import numpy as np

    np.random.seed(0)
    gen = AgentProfileGenerator()
    p = gen.generate_one(env_params={}, scenario_type=None)
    for trait in (
        "digital_literacy",
        "price_sensitivity",
        "patience_score",
        "motivation",
        "trust_baseline",
    ):
        v = getattr(p, trait)
        assert 0.0 <= v <= 1.0, f"{trait} out of bounds: {v}"
    assert p.tier in {"METRO", "TIER1", "TIER2", "TIER3"}


def test_generate_from_cluster_uses_cluster_base_traits() -> None:
    import numpy as np

    np.random.seed(0)
    gen = AgentProfileGenerator()

    class _StubCluster:
        base_traits = {
            "digital_literacy": 0.9,
            "price_sensitivity": 0.1,
            "patience_score": 0.7,
            "motivation": 0.8,
            "trust": 0.6,
        }

    # Profile's blended traits should land closer to the cluster default than
    # to the unconditional default. Run many to average out beta-sampling noise.
    np.random.seed(42)
    digitals = [
        gen.generate_from_cluster(_StubCluster(), env_params={}, scenario_type=None).digital_literacy
        for _ in range(200)
    ]
    # The blend formula is 0.4 * mean + 0.6 * cluster_default. With cluster=0.9
    # and the unconditional mean for digital_literacy ~ 0.6, the average
    # sampled value should be > 0.7 (significantly above the unconditional mean).
    assert sum(digitals) / len(digitals) > 0.7


def test_generate_from_cluster_tolerates_missing_traits() -> None:
    """Cluster without base_traits falls back to defaults."""
    import numpy as np

    np.random.seed(0)
    gen = AgentProfileGenerator()

    class _StubCluster:
        base_traits = {}

    p = gen.generate_from_cluster(_StubCluster(), env_params={})
    for trait in (
        "digital_literacy",
        "price_sensitivity",
        "patience_score",
        "motivation",
        "trust_baseline",
    ):
        v = getattr(p, trait)
        assert 0.0 <= v <= 1.0


# ---------------------------------------------------------------------------
# generate_population + population_summary
# ---------------------------------------------------------------------------


def test_generate_population_is_deterministic_with_seed() -> None:
    gen = AgentProfileGenerator()
    env: dict[str, Any] = {}
    a = gen.generate_population(50, env, scenario_type=None, seed=42)
    b = gen.generate_population(50, env, scenario_type=None, seed=42)
    assert len(a) == 50 == len(b)
    # Compare a sample of attributes per agent — they should match exactly.
    for p_a, p_b in zip(a, b):
        assert p_a.age == p_b.age
        assert p_a.income_bracket == p_b.income_bracket
        assert p_a.monthly_income == p_b.monthly_income
        assert p_a.region == p_b.region
        assert p_a.device_type == p_b.device_type
        for trait in (
            "digital_literacy",
            "price_sensitivity",
            "patience_score",
            "motivation",
            "trust_baseline",
        ):
            assert getattr(p_a, trait) == getattr(p_b, trait)


def test_generate_population_volume_respected() -> None:
    gen = AgentProfileGenerator()
    for n in (1, 10, 100, 0):
        out = gen.generate_population(n, env_params={}, scenario_type=None, seed=1)
        assert len(out) == n


def test_population_summary_empty_returns_empty_dict() -> None:
    gen = AgentProfileGenerator()
    assert gen.population_summary([]) == {}


def test_population_summary_aggregates_expected_keys() -> None:
    import numpy as np

    np.random.seed(0)
    gen = AgentProfileGenerator()
    pop = gen.generate_population(100, env_params={}, scenario_type=None, seed=7)
    summary = gen.population_summary(pop)

    # Top-level keys.
    assert summary["total"] == 100
    for trait in (
        "digital_literacy",
        "price_sensitivity",
        "patience_score",
        "motivation",
        "trust_baseline",
    ):
        bucket = summary[trait]
        for stat in ("mean", "median", "std", "p25", "p75"):
            assert stat in bucket, f"{trait}.{stat} missing"

    # Demographic distributions cover every enum value.
    assert set(summary["devices"].keys()) == {d.value for d in DeviceType}
    assert set(summary["regions"].keys()) == {r.value for r in Region}
    assert set(summary["income_brackets"].keys()) == {
        i.value for i in IncomeBracket
    }
    assert 0.0 <= summary["estimated_high_income_fraction"] <= 1.0


def test_population_summary_high_income_fraction_matches_subset() -> None:
    import numpy as np

    np.random.seed(0)
    gen = AgentProfileGenerator()
    pop = gen.generate_population(300, env_params={}, scenario_type=None, seed=11)
    summary = gen.population_summary(pop)
    expected_n = sum(
        1
        for p in pop
        if p.income_bracket in (IncomeBracket.UPPER_MIDDLE, IncomeBracket.HIGH_INCOME)
    )
    assert summary["estimated_high_income_fraction"] == pytest.approx(
        round(expected_n / 300, 3), abs=1e-9
    )


# ---------------------------------------------------------------------------
# SCENARIO_TRAIT_ADJUSTMENTS structural integrity
# ---------------------------------------------------------------------------


def test_scenario_adjustments_keys_match_traits() -> None:
    valid_traits = {
        "digital_literacy",
        "price_sensitivity",
        "patience_score",
        "motivation",
        "trust_baseline",
    }
    for scenario_name, adjustments in SCENARIO_TRAIT_ADJUSTMENTS.items():
        assert isinstance(scenario_name, str) and scenario_name
        for trait, (alpha_delta, beta_delta) in adjustments.items():
            assert trait in valid_traits, (
                f"Scenario '{scenario_name}' adjusts unknown trait '{trait}'"
            )
            assert isinstance(alpha_delta, (int, float))
            assert isinstance(beta_delta, (int, float))
