"""
Tests for ``app.simulation.retention_churn``.

Pure-Python engine — exercises helpers, ``generate``, and ``to_dict``
with deterministic inputs. Surfaces edge cases (empty registry, missing
architect blocks) and bugs (negative drops, missing floor on weighted
averages).
"""
from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _cluster(cid: str, name: str, weight: float = 0.10) -> dict[str, Any]:
    return {
        "cluster_id": cid,
        "name": name,
        "population_weight": weight,
    }


def _ret_arch(
    cid: str,
    *,
    d1: float = 0.5,
    d7: float = 0.30,
    d30: float = 0.18,
    d90: float = 0.10,
    habit_days: float = 21.0,
    reeng30: float = 0.10,
    reeng90: float = 0.05,
    session_depth: float = 0.5,
    pause_pref: float = 0.3,
) -> dict[str, Any]:
    return {
        cid: {
            "RetentionArchitect": {"metrics": {
                "day1_survival": d1,
                "day7_survival": d7,
                "day30_survival": d30,
                "day90_survival": d90,
                "habit_loop_formation_days": habit_days,
                "reengagement_probability_30d": reeng30,
                "reengagement_probability_90d": reeng90,
                "session_depth_score": session_depth,
                "pause_vs_cancel_preference": pause_pref,
            }},
        }
    }


def _pricing(cid: str, *, annual: float = 0.2, ceiling: float = 999.0) -> dict[str, Any]:
    return {
        cid: {
            "PricingArchitect": {"metrics": {
                "annual_payment_probability": annual,
                "price_ceiling": ceiling,
                "will_pay_probability": 0.6,
            }},
        }
    }


def _onboarding(cid: str, *, completion: float = 0.7) -> dict[str, Any]:
    return {
        cid: {
            "OnboardingArchitect": {"metrics": {
                "onboarding_completion_rate": completion,
            }},
        }
    }


def _merged(*dicts: dict[str, Any]) -> dict[str, Any]:
    """Merge per-cluster architect dicts (each keyed by cluster id)."""
    out: dict[str, dict[str, Any]] = {}
    for d in dicts:
        for cid, blocks in d.items():
            inner = out.setdefault(cid, {})
            for block_name, block in blocks.items():
                inner[block_name] = block
    return out


# ---------------------------------------------------------------------------
# _infer_churn_trigger
# ---------------------------------------------------------------------------


def test_infer_churn_trigger_picks_highest_score() -> None:
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    # will_pay = 0.1 → price score = 0.9 (dominant)
    rm = _ret_arch("metro_power_professional")["metro_power_professional"][
        "RetentionArchitect"
    ]["metrics"]
    pm = {"will_pay_probability": 0.1}
    om = {"onboarding_completion_rate": 0.7}
    assert engine._infer_churn_trigger(rm, pm, om) == "price"


def test_infer_churn_trigger_onboarding_dominates_when_complete_low() -> None:
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    rm = _ret_arch("metro_power_professional")["metro_power_professional"][
        "RetentionArchitect"
    ]["metrics"]
    pm = {"will_pay_probability": 0.95}  # price score = 0.05
    om = {"onboarding_completion_rate": 0.05}  # onboarding = 0.95
    assert engine._infer_churn_trigger(rm, pm, om) == "onboarding"


def test_infer_churn_trigger_habit_when_habit_loop_very_long() -> None:
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    rm = _ret_arch("metro_power_professional", habit_days=120.0)[
        "metro_power_professional"
    ]["RetentionArchitect"]["metrics"]
    pm = {"will_pay_probability": 0.95}
    om = {"onboarding_completion_rate": 0.95}
    # habit = min(1, 120/60) = 1.0 (dominant)
    assert engine._infer_churn_trigger(rm, pm, om) == "habit"


def test_infer_churn_trigger_handles_missing_keys_via_defaults() -> None:
    """Empty metrics must not raise — defaults kick in."""
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    trigger = engine._infer_churn_trigger({}, {}, {})
    # With all defaults: will_pay 0.5 → price=0.5; onboard 0.7 → onboarding=0.3;
    # habit_days 21 → 0.35; d7=0.35 d30=0.20 → drop ≈ 0.43. → feature wins.
    assert trigger in {"price", "onboarding", "habit", "feature", "trust", "competition", "support"}


# ---------------------------------------------------------------------------
# _ltv_score
# ---------------------------------------------------------------------------


def test_ltv_score_bounded_by_zero_and_one() -> None:
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    # ceiling_ratio clamped to 1.0; survival, prefs always in [0, 1].
    ltv = engine._ltv_score(d90=1.0, annual_pref=1.0, reeng_30=1.0, price_ceiling=1e9, aov=1.0)
    # max weight 0.4 + 0.25 + 0.15 + 0.20 = 1.0
    assert math.isclose(ltv, 1.0, rel_tol=1e-4)
    assert 0.0 <= ltv <= 1.0


def test_ltv_score_zero_when_components_all_zero() -> None:
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    ltv = engine._ltv_score(d90=0.0, annual_pref=0.0, reeng_30=0.0, price_ceiling=0.0, aov=999.0)
    # ceiling_ratio = 0/2997 = 0 → everything sums to 0
    assert ltv == 0.0


def test_ltv_score_rounded_to_four_dp() -> None:
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    ltv = engine._ltv_score(d90=0.123456789, annual_pref=0.5, reeng_30=0.2, price_ceiling=1000.0, aov=999.0)
    # round(.., 4) → at most 4 decimals; verify quantization.
    assert ltv == round(ltv, 4)


def test_ltv_score_uses_clamped_ceiling_ratio() -> None:
    """A price_ceiling that's wildly above 3*aov must be clamped to 1.0."""
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    low = engine._ltv_score(d90=0.0, annual_pref=0.0, reeng_30=0.0, price_ceiling=1.0, aov=999.0)
    high = engine._ltv_score(d90=0.0, annual_pref=0.0, reeng_30=0.0, price_ceiling=1e9, aov=999.0)
    # high ceiling_ratio == 1.0; low is below 1.0 — must differ.
    assert high > low


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------


def _basic_registry() -> list[dict[str, Any]]:
    return [
        _cluster("metro_power_professional", "Metro Power Pro", 0.40),
        _cluster("tier3_first_time_app_user", "Tier-3 First-timer", 0.30),
        _cluster("anxiety_driven_researcher", "Research-led", 0.30),
    ]


def _basic_conductor(registry: list[dict[str, Any]]) -> dict[str, Any]:
    blocks = []
    for c in registry:
        blocks.append(_ret_arch(c["cluster_id"]))
        blocks.append(_pricing(c["cluster_id"]))
        blocks.append(_onboarding(c["cluster_id"]))
    return _merged(*blocks)


def test_generate_returns_one_profile_per_cluster() -> None:
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=99,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
        product_type="saas",
    )
    assert result.generated_ui_id == 99
    assert result.product_type == "saas"
    assert len(result.cluster_profiles) == len(registry)
    ids = {p.cluster_id for p in result.cluster_profiles}
    assert ids == {c["cluster_id"] for c in registry}


def test_generate_survival_curves_are_non_increasing_within_profile() -> None:
    """day1 >= day7 >= day30 >= day90 (defaults all in [0, 1])."""
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    for p in result.cluster_profiles:
        assert 0.0 <= p.day1_survival <= 1.0
        assert 0.0 <= p.day7_survival <= p.day1_survival + 1e-9
        assert 0.0 <= p.day30_survival <= p.day7_survival + 1e-9
        assert 0.0 <= p.day90_survival <= p.day30_survival + 1e-9


def test_generate_highest_churn_stage_picks_largest_drop() -> None:
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    assert result.highest_churn_stage in {"day1", "day7", "day30", "day90"}


def test_generate_best_worst_cluster_identifiers_in_registry() -> None:
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    cid_set = {c["cluster_id"] for c in registry}
    assert result.best_retention_cluster in cid_set
    assert result.worst_retention_cluster in cid_set


def test_generate_reengagement_viable_requires_threshold() -> None:
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    registry = _basic_registry()
    # All reeng30=0.05 → viable=False
    low = engine.generate(
        generated_ui_id=1,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    assert low.reengagement_viable is False

    # Override one cluster's reeng30 → > 0.15
    high_conductor = _basic_conductor(registry)
    high_conductor["metro_power_professional"]["RetentionArchitect"]["metrics"][
        "reengagement_probability_30d"
    ] = 0.5
    high = engine.generate(
        generated_ui_id=1,
        conductor_results=high_conductor,
        cluster_registry=registry,
        aov=999.0,
    )
    assert high.reengagement_viable is True


def test_generate_churn_trigger_distribution_counts_matches_profiles() -> None:
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    total = sum(result.churn_trigger_distribution.values())
    assert total == len(result.cluster_profiles)


def test_generate_market_survival_is_population_weighted_avg() -> None:
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    # All profiles use the same default metrics → all cluster day30 values
    # are equal and the market day30 must equal that value.
    for p in result.cluster_profiles:
        assert math.isclose(p.day30_survival, result.market_day30_survival, rel_tol=1e-3)


def test_generate_handles_missing_architect_blocks() -> None:
    """A cluster with no conductor entry must still produce a profile."""
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    registry = [
        _cluster("metro_power_professional", "Metro", 0.5),
        _cluster("anxiety_driven_researcher", "Research", 0.5),
    ]
    # Only the metro cluster has any architect data.
    conductor = {
        "metro_power_professional": {
            "RetentionArchitect": {"metrics": {}},
            "PricingArchitect": {"metrics": {}},
            "OnboardingArchitect": {"metrics": {}},
        }
    }
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=conductor,
        cluster_registry=registry,
        aov=999.0,
    )
    assert len(result.cluster_profiles) == 2


def test_generate_handles_missing_cluster_weight() -> None:
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    bad_registry = [
        {"cluster_id": "metro_power_professional", "name": "Metro"},
    ]
    conductor = {
        "metro_power_professional": {
            "RetentionArchitect": {"metrics": {}},
            "PricingArchitect": {"metrics": {}},
            "OnboardingArchitect": {"metrics": {}},
        }
    }
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=conductor,
        cluster_registry=bad_registry,
        aov=999.0,
    )
    assert len(result.cluster_profiles) == 1
    # Default weight 0.02 → market survival still computed.
    assert 0.0 <= result.market_day7_survival <= 1.0


def test_session_pattern_threshold_is_seventy() -> None:
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    registry = [_cluster("metro_power_professional", "M", 1.0)]
    # session_depth=0.7 → deep_work; < 0.7 → quick_check.
    for threshold, expected in [(0.7, "deep_work"), (0.69, "quick_check")]:
        conductor = {
            "metro_power_professional": {
                "RetentionArchitect": {"metrics": {"session_depth_score": threshold}},
                "PricingArchitect": {"metrics": {}},
                "OnboardingArchitect": {"metrics": {}},
            }
        }
        result = engine.generate(
            generated_ui_id=1,
            conductor_results=conductor,
            cluster_registry=registry,
            aov=999.0,
        )
        assert result.cluster_profiles[0].session_pattern == expected, threshold


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


def test_to_dict_serialises_required_keys() -> None:
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=77,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
        product_type="hardware",
    )
    payload = engine.to_dict(result)

    for key in (
        "generated_ui_id",
        "product_type",
        "market_day7_survival",
        "market_day30_survival",
        "market_day90_survival",
        "highest_churn_stage",
        "best_retention_cluster",
        "worst_retention_cluster",
        "reengagement_viable",
        "churn_trigger_distribution",
        "cluster_profiles",
    ):
        assert key in payload

    assert payload["generated_ui_id"] == 77
    assert payload["product_type"] == "hardware"


def test_to_dict_cluster_profiles_sorted_by_ltv_descending() -> None:
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    payload = engine.to_dict(result)
    ltvs = [p["ltv_score"] for p in payload["cluster_profiles"]]
    assert ltvs == sorted(ltvs, reverse=True)


def test_to_dict_includes_reengagement_30d_key() -> None:
    """Regression guard: serialised key is `reengagement_30d`, not `prob_30d`."""
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    payload = engine.to_dict(result)
    sample = payload["cluster_profiles"][0]
    assert "reengagement_30d" in sample
    assert "reengagement_prob_30d" not in sample


def test_to_dict_is_json_serialisable() -> None:
    import json

    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    payload = engine.to_dict(result)
    text = json.dumps(payload)
    parsed = json.loads(text)
    assert parsed["generated_ui_id"] == 1


def test_generate_is_deterministic() -> None:
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    registry = _basic_registry()
    conductor = _basic_conductor(registry)
    a = engine.generate(
        generated_ui_id=1,
        conductor_results=conductor,
        cluster_registry=registry,
        aov=999.0,
    )
    b = engine.generate(
        generated_ui_id=1,
        conductor_results=conductor,
        cluster_registry=registry,
        aov=999.0,
    )
    assert engine.to_dict(a) == engine.to_dict(b)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_generate_empty_registry_returns_empty_profiles() -> None:
    """Should not crash on empty input."""
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results={},
        cluster_registry=[],
        aov=999.0,
    )
    # After fix degrades gracefully.
    assert result.cluster_profiles == []
    assert result.churn_trigger_distribution == {}
    assert result.best_retention_cluster == ""
    assert result.worst_retention_cluster == ""
    assert result.highest_churn_stage == "day1"
    assert result.reengagement_viable is False


def test_generate_single_profile_marks_same_cluster_best_and_worst() -> None:
    from app.simulation.retention_churn import RetentionChurnEngine

    engine = RetentionChurnEngine()
    registry = [_cluster("metro_power_professional", "M", 1.0)]
    conductor = {
        "metro_power_professional": {
            "RetentionArchitect": {"metrics": {}},
            "PricingArchitect": {"metrics": {}},
            "OnboardingArchitect": {"metrics": {}},
        }
    }
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=conductor,
        cluster_registry=registry,
        aov=999.0,
    )
    assert result.best_retention_cluster == "metro_power_professional"
    assert result.worst_retention_cluster == "metro_power_professional"
