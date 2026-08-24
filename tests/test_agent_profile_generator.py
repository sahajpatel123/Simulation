"""Tests for AgentProfileGenerator determinism and population_summary."""
from __future__ import annotations

import numpy as np

from app.simulation.profiles import (
    AgentProfileGenerator,
    DeviceType,
    IncomeBracket,
    Region,
)


class _FakeCluster:
    """Minimal stand-in for ClusterDefinition with ``base_traits``."""

    def __init__(self) -> None:
        self.base_traits = {
            "digital_literacy": 0.7,
            "price_sensitivity": 0.5,
            "patience_score": 0.6,
            "motivation": 0.7,
            "trust": 0.6,
        }


def test_generate_one_returns_well_typed_profile() -> None:
    gen = AgentProfileGenerator()
    np.random.seed(0)

    profile = gen.generate_one(env_params={})

    assert isinstance(profile.age, int)
    assert isinstance(profile.income_bracket, IncomeBracket)
    assert isinstance(profile.region, Region)
    assert isinstance(profile.device_type, DeviceType)
    assert 0.0 <= profile.digital_literacy <= 1.0
    assert 0.0 <= profile.price_sensitivity <= 1.0


def test_generate_population_with_seed_is_deterministic() -> None:
    gen = AgentProfileGenerator()
    env = {"price_sensitivity": 0.5}

    a = gen.generate_population(50, env, seed=123)
    b = gen.generate_population(50, env, seed=123)

    assert len(a) == len(b) == 50
    for pa, pb in zip(a, b):
        assert pa.age == pb.age
        assert pa.income_bracket == pb.income_bracket
        assert pa.region == pb.region
        assert pa.digital_literacy == pb.digital_literacy


def test_generate_from_cluster_uses_cluster_base_traits() -> None:
    gen = AgentProfileGenerator()
    np.random.seed(7)

    profile = gen.generate_from_cluster(cluster=_FakeCluster(), env_params={})

    assert 0.0 <= profile.digital_literacy <= 1.0
    assert 0.0 <= profile.trust_baseline <= 1.0


def test_population_summary_for_empty_input() -> None:
    summary = AgentProfileGenerator().population_summary([])
    assert summary == {}


def test_population_summary_includes_required_keys() -> None:
    gen = AgentProfileGenerator()
    np.random.seed(11)
    profiles = gen.generate_population(100, {}, seed=11)

    summary = gen.population_summary(profiles)

    assert summary["total"] == 100
    for trait in (
        "digital_literacy",
        "price_sensitivity",
        "patience_score",
        "motivation",
        "trust_baseline",
    ):
        stats = summary[trait]
        assert {"mean", "median", "std", "p25", "p75"} <= set(stats)
    assert "devices" in summary
    assert "regions" in summary
    assert "income_brackets" in summary
    assert "estimated_high_income_fraction" in summary
