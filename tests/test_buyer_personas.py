"""
Tests for the buyer-persona brief builder
(``app.simulation.buyer_personas``).
"""
from __future__ import annotations

import json
from typing import Any

from app.simulation.buyer_personas import (
    TRAIT_ORDER,
    build_buyer_personas,
)


def _profile(
    cluster_id: str,
    name: str,
    *,
    weight: float,
    traits: dict[str, float] | None = None,
    behavior: str = "Converts after evaluating proof",
    failures: list[str] | None = None,
    affinities: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": f"Description for {name}",
        "population_weight": weight,
        "base_traits": traits
        or {
            "income_level": 0.5,
            "digital_literacy": 0.5,
            "motivation": 0.5,
            "trust": 0.5,
            "price_sensitivity": 0.5,
            "risk_aversion": 0.5,
            "patience_score": 0.5,
            "social_orientation": 0.5,
        },
        "trait_variance": {
            "income_level": 0.05,
            "digital_literacy": 0.05,
            "motivation": 0.05,
            "trust": 0.05,
            "price_sensitivity": 0.05,
            "risk_aversion": 0.05,
            "patience_score": 0.05,
            "social_orientation": 0.05,
        },
        "dominant_behavior_pattern": behavior,
        "known_failure_modes": failures
        or [
            "Failure mode one",
            "Failure mode two",
            "Failure mode three",
        ],
        "product_affinities": affinities or ["saas", "consumer_app", "wearable", "iot"],
        "demographic_profile": {
            "geography": "metro",
            "age_bracket": "25-34",
            "device_primary": "mobile",
        },
    }


def _results(
    breakdown: dict[str, Any] | None = None,
    *,
    cr: float = 0.04,
    total: int = 10000,
) -> dict[str, Any]:
    return {
        "population_weighted_conversion": cr,
        "conversion_rate": cr,
        "total_agents": total,
        "cluster_breakdown": breakdown
        or {
            "big_lag": 0.01,
            "big_mid": 0.03,
            "niche_win": 0.12,
            "tail": 0.005,
        },
    }


def _registry() -> dict[str, dict[str, Any]]:
    return {
        "big_lag": _profile(
            "big_lag",
            "Big Laggard",
            weight=0.08,
            traits={
                "income_level": 0.4,
                "digital_literacy": 0.4,
                "motivation": 0.6,
                "trust": 0.3,
                "price_sensitivity": 0.8,
                "risk_aversion": 0.7,
                "patience_score": 0.4,
                "social_orientation": 0.6,
            },
        ),
        "big_mid": _profile("big_mid", "Big Mid", weight=0.06),
        "niche_win": _profile("niche_win", "Niche Winner", weight=0.01),
        "tail": _profile("tail", "Tail Cluster", weight=0.01),
    }


def test_empty_results_yield_zero_state() -> None:
    out = build_buyer_personas(None, simulation_id=1, project_id=2)
    assert out.simulation_id == 1
    assert out.project_id == 2
    assert out.personas == []
    assert out.persona_count == 0
    assert out.primary_target_persona is None
    assert out.focus_recommendations
    assert out.meta["ranked_from_opportunity_matrix"] is True


def test_garbage_and_json_string_inputs() -> None:
    bad = build_buyer_personas("{nope", simulation_id=1, project_id=1)
    assert bad.personas == []

    ok = build_buyer_personas(
        json.dumps(_results()),
        simulation_id=1,
        project_id=1,
        cluster_registry=_registry(),
    )
    assert ok.persona_count == 4


def test_personas_carry_full_registry_profile() -> None:
    out = build_buyer_personas(
        _results(),
        simulation_id=10,
        project_id=3,
        cluster_registry=_registry(),
        benchmark=0.05,
    )
    by_id = {p.cluster_id: p for p in out.personas}
    persona = by_id["big_mid"]
    assert persona.cluster_name == "Big Mid"
    assert persona.description == "Description for Big Mid"
    assert persona.population_weight == 0.06
    assert persona.conversion_rate == 0.03
    assert persona.dominant_behavior_pattern == "Converts after evaluating proof"
    assert list(persona.traits.keys()) == list(TRAIT_ORDER)
    assert persona.product_affinities == ["saas", "consumer_app", "wearable"]
    assert persona.demographic_profile["geography"] == "metro"
    assert persona.known_failure_modes == [
        "Failure mode one",
        "Failure mode two",
        "Failure mode three",
    ]
    assert persona.risk_watch == ["Failure mode one", "Failure mode two"]


def test_messaging_angle_reflects_dominant_trait() -> None:
    out = build_buyer_personas(
        _results(),
        simulation_id=10,
        project_id=3,
        cluster_registry=_registry(),
    )
    by_id = {p.cluster_id: p for p in out.personas}
    assert "price transparency" in by_id["big_lag"].messaging_angle.lower()
    assert "quantified outcomes" in by_id["big_mid"].messaging_angle.lower()


def test_default_messaging_angle_for_neutral_traits() -> None:
    registry = {
        "neutral": _profile(
            "neutral",
            "Neutral",
            weight=0.05,
            traits={
                "income_level": 0.5,
                "digital_literacy": 0.6,
                "motivation": 0.5,
                "trust": 0.6,
                "price_sensitivity": 0.5,
                "risk_aversion": 0.4,
                "patience_score": 0.6,
                "social_orientation": 0.5,
            },
        )
    }
    out = build_buyer_personas(
        _results(breakdown={"neutral": 0.03}),
        simulation_id=1,
        project_id=1,
        cluster_registry=registry,
    )
    assert "quantified outcomes" in out.personas[0].messaging_angle


def test_ranking_puts_high_weight_gap_first() -> None:
    out = build_buyer_personas(
        _results(),
        simulation_id=11,
        project_id=3,
        cluster_registry=_registry(),
        benchmark=0.05,
    )
    assert out.personas[0].cluster_id == "big_lag"
    assert out.primary_target_persona == "big_lag"
    assert out.personas[0].segment == "TRANSFORM"
    assert out.personas[0].recommended_focus.startswith("Design a strategic bet")


def test_limit_truncates_ranked_personas() -> None:
    breakdown = {f"c{i}": 0.01 + (i * 0.001) for i in range(20)}
    registry = {
        f"c{i}": _profile(f"c{i}", f"Cluster {i}", weight=0.03)
        for i in range(20)
    }
    out = build_buyer_personas(
        _results(breakdown=breakdown),
        simulation_id=16,
        project_id=6,
        cluster_registry=registry,
        limit=5,
    )
    assert len(out.personas) == 5
    assert out.persona_count == 5


def test_cluster_without_registry_profile_is_skipped() -> None:
    registry = {
        "known": _profile("known", "Known Cluster", weight=0.05),
    }
    out = build_buyer_personas(
        _results(breakdown={"known": 0.03, "unknown": 0.02}),
        simulation_id=17,
        project_id=7,
        cluster_registry=registry,
    )
    assert [p.cluster_id for p in out.personas] == ["known"]


def test_summaries_are_forwarded_and_flagged_in_meta() -> None:
    summaries = [
        {
            "cluster_id": "big_lag",
            "agents_assigned": 8000,
            "agents_converted": 80,
            "conversion_rate": 0.01,
            "primary_drop_trigger": "PricingArchitect",
            "mean_drop_state": "DECIDE",
        },
        {
            "cluster_id": "big_mid",
            "agents_assigned": 2000,
            "agents_converted": 160,
            "conversion_rate": 0.08,
            "primary_drop_trigger": "TrustArchitect",
            "mean_drop_state": "CONSIDER",
        },
    ]
    out = build_buyer_personas(
        _results(breakdown={"big_lag": 0.01, "big_mid": 0.08}),
        simulation_id=12,
        project_id=4,
        cluster_summaries=summaries,
        cluster_registry=_registry(),
    )
    assert out.meta["cluster_summaries_used"] is True
    by_id = {p.cluster_id: p for p in out.personas}
    assert by_id["big_lag"].population_weight == 0.8
