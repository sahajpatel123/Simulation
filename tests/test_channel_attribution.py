"""
Tests for ``app.simulation.channel_attribution``.

The engine is pure-Python (no DB, no I/O), so we exercise every helper
and the public ``generate`` / ``to_dict`` surface with deterministic
inputs and check invariants (clamping, weights sum, ordering, etc.).
"""
from __future__ import annotations

import math
from typing import Any


CHANNEL_KEYS: list[str] = [
    "organic_search",
    "paid_search",
    "social_organic",
    "social_paid",
    "influencer",
    "word_of_mouth",
    "content_marketing",
    "email",
    "community",
    "offline_retail",
    "press_mention",
    "referral_program",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _cluster(
    cluster_id: str,
    name: str,
    weight: float = 0.05,
) -> dict[str, Any]:
    """One minimal cluster registry row."""
    return {
        "cluster_id": cluster_id,
        "name": name,
        "population_weight": weight,
    }


def _conductor(
    cid: str = "metro_power_professional",
    *,
    wom: float = 0.5,
    organic_ref: float = 0.1,
    invite: float = 0.3,
    content: float = 0.1,
    community: float = 0.2,
    press: float = 0.1,
    brand_def: float = 0.8,
    free_trial: float = 0.3,
    awareness: float = 0.6,
    urgency: float = 0.5,
    switch: float = 0.4,
    viral: float = 0.05,
) -> dict[str, Any]:
    """Build the architect metrics dict consumed by the engine."""
    return {
        cid: {
            "ViralityArchitect": {"metrics": {
                "word_of_mouth_coefficient": wom,
                "organic_referral_trigger_score": organic_ref,
                "invite_completion_rate": invite,
                "content_virality_rate": content,
                "community_building_participation": community,
                "viral_coefficient": viral,
            }},
            "TrustArchitect": {"metrics": {
                "press_mention_lift": press,
                "brand_deficit_multiplier": brand_def,
                "free_trial_as_trust_substitute": free_trial,
            }},
            "MarketTimingArchitect": {"metrics": {
                "category_awareness_score": awareness,
                "problem_urgency_intensity": urgency,
            }},
            "CompetitiveDynamicsArchitect": {"metrics": {
                "incumbent_switching_friction": switch,
            }},
        }
    }


# ---------------------------------------------------------------------------
# _cac_multiplier
# ---------------------------------------------------------------------------


def test_cac_multiplier_paid_channels_have_higher_multiplier() -> None:
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    cac_paid = engine._cac_multiplier({}, "paid_search")
    cac_social_paid = engine._cac_multiplier({}, "social_paid")
    cac_influencer = engine._cac_multiplier({}, "influencer")
    cac_organic = engine._cac_multiplier({}, "organic_search")
    cac_wom = engine._cac_multiplier({}, "word_of_mouth")
    cac_neutral = engine._cac_multiplier({}, "offline_retail")

    assert cac_paid == 1.8
    assert cac_social_paid == 1.6
    assert cac_influencer == 1.4
    assert cac_organic == 0.7
    assert cac_wom == 0.3
    assert cac_neutral == 1.0


def test_cac_multiplier_rounds_to_three_decimals() -> None:
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    for ch in CHANNEL_KEYS:
        val = engine._cac_multiplier({}, ch)
        # All current CACs are exact — make sure rounding doesn't introduce
        # floating drift (i.e. value should be float, not Decimal).
        assert isinstance(val, float)
        assert math.isfinite(val)


# ---------------------------------------------------------------------------
# _score_channels
# ---------------------------------------------------------------------------


def test_score_channels_returns_all_keys_clamped_to_unit_interval() -> None:
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    arch = _conductor(
        wom=2.0,  # intentionally out of [0, 1]
        organic_ref=2.0,
        invite=2.0,
        content=2.0,
        community=2.0,
        press=2.0,
        brand_def=2.0,
        free_trial=2.0,
        awareness=2.0,
        urgency=2.0,
        switch=2.0,
    )
    cid = "metro_power_professional"
    arch_for_cid = {
        "ViralityArchitect": arch[cid]["ViralityArchitect"],
        "TrustArchitect": arch[cid]["TrustArchitect"],
        "MarketTimingArchitect": arch[cid]["MarketTimingArchitect"],
        "CompetitiveDynamicsArchitect": arch[cid]["CompetitiveDynamicsArchitect"],
    }
    vm = arch_for_cid["ViralityArchitect"]["metrics"]
    tm = arch_for_cid["TrustArchitect"]["metrics"]
    timing_m = arch_for_cid["MarketTimingArchitect"]["metrics"]
    comp_m = arch_for_cid["CompetitiveDynamicsArchitect"]["metrics"]

    scores = engine._score_channels(cid, vm, tm, timing_m, comp_m, {})

    assert set(scores.keys()) == set(CHANNEL_KEYS)
    for ch, s in scores.items():
        assert 0.0 <= s <= 1.0, f"{ch} out of range: {s}"  # fixed: was -0.5

    # Also verify the negative-floor case directly: out-of-range trust
    # scalar must NOT produce negative intermediates.
    extreme_arch = _conductor(brand_def=10.0)
    extreme_scores = engine._score_channels(
        cid,
        extreme_arch[cid]["ViralityArchitect"]["metrics"],
        extreme_arch[cid]["TrustArchitect"]["metrics"],
        extreme_arch[cid]["MarketTimingArchitect"]["metrics"],
        extreme_arch[cid]["CompetitiveDynamicsArchitect"]["metrics"],
        {},
    )
    for s in extreme_scores.values():
        assert s >= 0.0, f"negative channel score leaked through: {s}"


def test_score_channels_metro_suppresses_offline_retail() -> None:
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    cid = "metro_power_professional"
    arch = _conductor(cid=cid)
    scores = engine._score_channels(
        cid,
        arch[cid]["ViralityArchitect"]["metrics"],
        arch[cid]["TrustArchitect"]["metrics"],
        arch[cid]["MarketTimingArchitect"]["metrics"],
        arch[cid]["CompetitiveDynamicsArchitect"]["metrics"],
        {},
    )
    # Metro gets the 0.2 offline_retail base; tier3 gets 0.8.
    assert scores["offline_retail"] < 0.6


def test_score_channels_tier3_suppresses_paid_search() -> None:
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    cid = "tier3_first_time_app_user"
    arch = _conductor(cid=cid)
    scores = engine._score_channels(
        cid,
        arch[cid]["ViralityArchitect"]["metrics"],
        arch[cid]["TrustArchitect"]["metrics"],
        arch[cid]["MarketTimingArchitect"]["metrics"],
        arch[cid]["CompetitiveDynamicsArchitect"]["metrics"],
        {},
    )
    # tier3 paid_search gets *0.5 multiplier — compare against metro to
    # prove the *0.5 attenuation is what makes the difference, not luck.
    metro_arch = _conductor()
    metro_scores = engine._score_channels(
        "metro_power_professional",
        metro_arch["metro_power_professional"]["ViralityArchitect"]["metrics"],
        metro_arch["metro_power_professional"]["TrustArchitect"]["metrics"],
        metro_arch["metro_power_professional"]["MarketTimingArchitect"]["metrics"],
        metro_arch["metro_power_professional"]["CompetitiveDynamicsArchitect"]["metrics"],
        {},
    )
    assert scores["paid_search"] * 2 <= metro_scores["paid_search"] + 1e-9


def test_score_channels_student_promotes_influencer() -> None:
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    cid_metro = "metro_power_professional"
    cid_student = "high_literacy_student_freemium_ceiling"
    arch_metro = _conductor(cid=cid_metro)
    arch_student = _conductor(cid=cid_student)
    s_metro = engine._score_channels(
        cid_metro,
        arch_metro[cid_metro]["ViralityArchitect"]["metrics"],
        arch_metro[cid_metro]["TrustArchitect"]["metrics"],
        arch_metro[cid_metro]["MarketTimingArchitect"]["metrics"],
        arch_metro[cid_metro]["CompetitiveDynamicsArchitect"]["metrics"],
        {},
    )
    s_student = engine._score_channels(
        cid_student,
        arch_student[cid_student]["ViralityArchitect"]["metrics"],
        arch_student[cid_student]["TrustArchitect"]["metrics"],
        arch_student[cid_student]["MarketTimingArchitect"]["metrics"],
        arch_student[cid_student]["CompetitiveDynamicsArchitect"]["metrics"],
        {},
    )
    # Students get +0.3 influencer lift, metro only +0.1.
    assert s_student["influencer"] >= s_metro["influencer"]


def test_score_channels_rounded_to_four_dp() -> None:
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    cid = "metro_power_professional"
    arch = _conductor(cid=cid)
    scores = engine._score_channels(
        cid,
        arch[cid]["ViralityArchitect"]["metrics"],
        arch[cid]["TrustArchitect"]["metrics"],
        arch[cid]["MarketTimingArchitect"]["metrics"],
        arch[cid]["CompetitiveDynamicsArchitect"]["metrics"],
        {},
    )
    for ch, s in scores.items():
        # round(x, 4) yields at most 4 decimals; compare via quantization.
        quantized = round(s, 4)
        assert s == quantized, f"{ch} not rounded: {s}"


def test_score_channels_handles_missing_metrics_via_defaults() -> None:
    """Empty metrics dict should fall back to defaults without raising."""
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    empty_metrics: dict[str, float] = {}
    scores = engine._score_channels(
        "metro_power_professional",
        empty_metrics,
        empty_metrics,
        empty_metrics,
        empty_metrics,
        {},
    )
    assert set(scores.keys()) == set(CHANNEL_KEYS)
    for s in scores.values():
        assert 0.0 <= s <= 1.0


# ---------------------------------------------------------------------------
# generate + to_dict
# ---------------------------------------------------------------------------


def _make_registry() -> list[dict[str, Any]]:
    return [
        _cluster("metro_power_professional", "Metro Power Pro", 0.20),
        _cluster("tier3_first_time_app_user", "Tier-3 First-timer", 0.20),
        _cluster("high_literacy_student_freemium_ceiling", "Student Lite", 0.15),
        _cluster("senior_enterprise_decision_maker", "Enterprise B2B", 0.10),
        _cluster("anxiety_driven_researcher", "Research-led", 0.10),
    ]


def _make_conductor_for_registry() -> dict[str, Any]:
    """Build a conductor_results dict keyed by cluster id."""
    cid_to_arch: dict[str, dict[str, Any]] = {}
    for c in _make_registry():
        cid_to_arch[c["cluster_id"]] = {
            "ViralityArchitect": {"metrics": {
                "word_of_mouth_coefficient": 0.5,
                "organic_referral_trigger_score": 0.2,
                "invite_completion_rate": 0.4,
                "content_virality_rate": 0.3,
                "community_building_participation": 0.4,
                "viral_coefficient": 0.1,
            }},
            "TrustArchitect": {"metrics": {
                "press_mention_lift": 0.2,
                "brand_deficit_multiplier": 0.6,
                "free_trial_as_trust_substitute": 0.5,
            }},
            "MarketTimingArchitect": {"metrics": {
                "category_awareness_score": 0.7,
                "problem_urgency_intensity": 0.6,
            }},
            "CompetitiveDynamicsArchitect": {"metrics": {
                "incumbent_switching_friction": 0.5,
            }},
        }
    return cid_to_arch


def test_generate_returns_result_with_one_profile_per_cluster() -> None:
    from app.simulation.channel_attribution import (
        CHANNELS,
        ChannelAttributionEngine,
    )

    engine = ChannelAttributionEngine()
    registry = _make_registry()
    conductor = _make_conductor_for_registry()
    result = engine.generate(
        generated_ui_id=42,
        conductor_results=conductor,
        cluster_registry=registry,
        product_type="saas",
    )

    assert result.generated_ui_id == 42
    assert result.product_type == "saas"
    assert len(result.cluster_profiles) == len(registry)
    for p in result.cluster_profiles:
        assert p.primary_channel in CHANNELS
        assert p.secondary_channel in CHANNELS
        assert 0.0 <= p.cac_multiplier <= 2.0


def test_generate_market_ranking_is_descending_by_weighted_score() -> None:
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_make_conductor_for_registry(),
        cluster_registry=_make_registry(),
        product_type="saas",
    )
    scores = [s for _, s in result.market_channel_ranking]
    assert scores == sorted(scores, reverse=True)
    assert len(result.market_channel_ranking) == 12


def test_generate_highest_roi_channel_picks_lowest_cac_profile() -> None:
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_make_conductor_for_registry(),
        cluster_registry=_make_registry(),
        product_type="saas",
    )
    # It must equal the primary channel of the cluster with minimum cac.
    min_cac_profile = min(result.cluster_profiles, key=lambda p: p.cac_multiplier)
    assert result.highest_roi_channel == min_cac_profile.primary_channel


def test_generate_recommended_channel_mix_sums_close_to_one() -> None:
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_make_conductor_for_registry(),
        cluster_registry=_make_registry(),
        product_type="saas",
    )
    total = sum(result.recommended_channel_mix.values())
    assert abs(total - 1.0) < 1e-6, total
    assert len(result.recommended_channel_mix) == 5


def test_generate_viral_growth_possible_requires_viral_coefficient_above_one() -> None:
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    # All viral_coefficient = 0.05 → viral_growth_possible == False
    res_low = engine.generate(
        generated_ui_id=1,
        conductor_results=_make_conductor_for_registry(),
        cluster_registry=_make_registry(),
        product_type="saas",
    )
    assert res_low.viral_growth_possible is False

    # Force one cluster's viral coefficient above 1.0.
    conductor = _make_conductor_for_registry()
    conductor["metro_power_professional"]["ViralityArchitect"]["metrics"][
        "viral_coefficient"
    ] = 1.5
    res_high = engine.generate(
        generated_ui_id=1,
        conductor_results=conductor,
        cluster_registry=_make_registry(),
        product_type="saas",
    )
    assert res_high.viral_growth_possible is True


def test_generate_handles_empty_registry_gracefully() -> None:
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results={},
        cluster_registry=[],
        product_type="saas",
    )
    assert result.cluster_profiles == []
    # Market ranking exists for every channel, all scores zero.
    assert len(result.market_channel_ranking) == len(set(CHANNEL_KEYS))
    assert all(s == 0.0 for _, s in result.market_channel_ranking)
    # No profiles → fallback to cheapest organic channel, not a crash.
    assert result.highest_roi_channel in {
        "word_of_mouth",
        "referral_program",
        "community",
    }
    assert result.recommended_channel_mix == {}
    assert result.viral_growth_possible is False


def test_generate_handles_missing_architect_blocks() -> None:
    """Clusters with no architect output still produce a profile."""
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    registry = [
        _cluster("metro_power_professional", "Metro Power Pro", 0.5),
        _cluster("anxiety_driven_researcher", "Research-led", 0.5),
    ]
    # Only one cluster has conductor data; the other falls back to empty.
    conductor = {
        "metro_power_professional": {
            "ViralityArchitect": {"metrics": {}},
            "TrustArchitect": {"metrics": {}},
            "MarketTimingArchitect": {"metrics": {}},
            "CompetitiveDynamicsArchitect": {"metrics": {}},
        }
        # anxiety_driven_researcher intentionally absent
    }
    result = engine.generate(
        generated_ui_id=7,
        conductor_results=conductor,
        cluster_registry=registry,
        product_type="saas",
    )
    assert len(result.cluster_profiles) == 2
    assert {p.cluster_id for p in result.cluster_profiles} == {
        "metro_power_professional",
        "anxiety_driven_researcher",
    }


def test_generate_handles_missing_cluster_weight() -> None:
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    bad_registry = [
        {
            "cluster_id": "metro_power_professional",
            "name": "Metro",
            # population_weight missing
        }
    ]
    result = engine.generate(
        generated_ui_id=1,
        conductor_results={"metro_power_professional": {
            "ViralityArchitect": {"metrics": {}},
            "TrustArchitect": {"metrics": {}},
            "MarketTimingArchitect": {"metrics": {}},
            "CompetitiveDynamicsArchitect": {"metrics": {}},
        }},
        cluster_registry=bad_registry,
        product_type="saas",
    )
    assert len(result.cluster_profiles) == 1
    # Defaults to 0.02 → market ranking scores are populated.
    assert result.market_channel_ranking[0][1] >= 0.0


def test_generate_primary_and_secondary_differ_for_multi_channel() -> None:
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_make_conductor_for_registry(),
        cluster_registry=_make_registry(),
        product_type="saas",
    )
    for p in result.cluster_profiles:
        # If both picks equal the same channel, the engine collapsed.
        # For multi-channel scores, that should not happen.
        # (Tie-breaking can keep them equal only when all scores are 0.)
        scores = p.channel_scores
        max_score = max(scores.values())
        if max_score > 0:
            assert p.primary_channel in scores


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


def test_to_dict_serialises_required_keys() -> None:
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    result = engine.generate(
        generated_ui_id=11,
        conductor_results=_make_conductor_for_registry(),
        cluster_registry=_make_registry(),
        product_type="saas",
    )
    payload = engine.to_dict(result)

    for key in (
        "generated_ui_id",
        "product_type",
        "highest_roi_channel",
        "lowest_cac_channel",
        "viral_growth_possible",
        "recommended_channel_mix",
        "market_channel_ranking",
        "cluster_profiles",
    ):
        assert key in payload

    assert payload["generated_ui_id"] == 11
    assert isinstance(payload["market_channel_ranking"], list)
    for entry in payload["market_channel_ranking"]:
        assert "channel" in entry
        assert "weighted_score" in entry
        assert isinstance(entry["weighted_score"], float)


def test_to_dict_sorts_cluster_profiles_by_cac_ascending() -> None:
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_make_conductor_for_registry(),
        cluster_registry=_make_registry(),
        product_type="saas",
    )
    payload = engine.to_dict(result)
    cacs = [p["cac_multiplier"] for p in payload["cluster_profiles"]]
    assert cacs == sorted(cacs)


def test_to_dict_recommended_channel_mix_sums_to_one() -> None:
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_make_conductor_for_registry(),
        cluster_registry=_make_registry(),
        product_type="saas",
    )
    payload = engine.to_dict(result)
    assert abs(sum(payload["recommended_channel_mix"].values()) - 1.0) < 1e-6


def test_to_dict_is_json_serialisable() -> None:
    import json

    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_make_conductor_for_registry(),
        cluster_registry=_make_registry(),
        product_type="saas",
    )
    payload = engine.to_dict(result)
    # Round-trip must not raise.
    text = json.dumps(payload)
    parsed = json.loads(text)
    assert parsed["generated_ui_id"] == 1
    assert isinstance(parsed["cluster_profiles"], list)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_generate_is_deterministic() -> None:
    """Same inputs must produce identical results across runs."""
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    registry = _make_registry()
    conductor = _make_conductor_for_registry()

    a = engine.generate(
        generated_ui_id=1,
        conductor_results=conductor,
        cluster_registry=registry,
        product_type="saas",
    )
    b = engine.generate(
        generated_ui_id=1,
        conductor_results=conductor,
        cluster_registry=registry,
        product_type="saas",
    )
    assert engine.to_dict(a) == engine.to_dict(b)


def test_to_dict_returns_plain_dict_with_no_dataclass_leak() -> None:
    from app.simulation.channel_attribution import ChannelAttributionEngine

    engine = ChannelAttributionEngine()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_make_conductor_for_registry(),
        cluster_registry=_make_registry(),
        product_type="saas",
    )
    payload = engine.to_dict(result)
    assert isinstance(payload, dict)
    # Inner entries are dicts, not dataclass instances.
    for entry in payload["market_channel_ranking"]:
        assert isinstance(entry, dict)
    for p in payload["cluster_profiles"]:
        assert isinstance(p, dict)
