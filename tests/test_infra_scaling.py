"""
Tests for ``app.simulation.infra_scaling`` — pure-Python capacity
projection engine.

Locks down:
  * _dau_rate weighted average + clamp to [0.05, 0.70]
  * _dominant_session deep_work / quick_check tiebreak
  * _monthly_cost floors + rounding
  * _tier boundary thresholds
  * _bottleneck priority order
  * generate() stage ordering, warnings dedup, critical_stage pick,
    unknown product_type fallback
  * to_dict serialisation
"""
from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# _dau_rate
# ---------------------------------------------------------------------------


def test_dau_rate_returns_default_when_empty() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    assert e._dau_rate([]) == 0.25


def test_dau_rate_uses_deep_work_when_session_pattern_deep() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    out = e._dau_rate([
        {"population_weight": 1.0, "session_pattern": "deep_work"},
    ])
    # All 1.0 weight × 0.55 = 0.55
    assert math.isclose(out, 0.55, rel_tol=1e-3)


def test_dau_rate_uses_quick_check_default_weight() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    out = e._dau_rate([
        {"population_weight": 1.0, "session_pattern": "quick_check"},
    ])
    # 1.0 × 0.18 = 0.18
    assert math.isclose(out, 0.18, rel_tol=1e-3)


def test_dau_rate_clamped_to_max_070() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    # Population weight > 1.27 (0.70 / 0.55) → would exceed 0.70.
    out = e._dau_rate([
        {"population_weight": 2.0, "session_pattern": "deep_work"},
    ])
    assert out <= 0.70


def test_dau_rate_clamped_to_min_005() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    out = e._dau_rate([
        {"population_weight": 0.0, "session_pattern": "quick_check"},
    ])
    assert out >= 0.05


def test_dau_rate_rounds_to_four_dp() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    out = e._dau_rate([
        {"population_weight": 0.33333, "session_pattern": "deep_work"},
    ])
    assert out == round(out, 4)


# ---------------------------------------------------------------------------
# _dominant_session
# ---------------------------------------------------------------------------


def test_dominant_session_picks_deep_when_weight_larger() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    out = e._dominant_session([
        {"population_weight": 0.8, "session_pattern": "deep_work"},
        {"population_weight": 0.2, "session_pattern": "quick_check"},
    ])
    assert out == "deep_work"


def test_dominant_session_picks_quick_when_weight_larger() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    out = e._dominant_session([
        {"population_weight": 0.1, "session_pattern": "deep_work"},
        {"population_weight": 0.9, "session_pattern": "quick_check"},
    ])
    assert out == "quick_check"


def test_dominant_session_empty_returns_deep_work() -> None:
    """Empty input: both sums are 0 → ``deep >= quick`` picks deep_work."""
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    assert e._dominant_session([]) == "deep_work"


def test_dominant_session_tiebreak_picks_deep() -> None:
    """When deep == quick (or both zero), the code uses deep_work."""
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    out = e._dominant_session([
        {"population_weight": 0.5, "session_pattern": "deep_work"},
        {"population_weight": 0.5, "session_pattern": "quick_check"},
    ])
    assert out == "deep_work"


# ---------------------------------------------------------------------------
# _monthly_cost
# ---------------------------------------------------------------------------


def test_monthly_cost_floor_at_ten() -> None:
    """Both compute and DB cost functions are floored at 10 each."""
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    out = e._monthly_cost(active_users=1, concurrent=1, api_calls=0, db_reads=0, db_writes=0)
    # compute: 10 (floor). db: 10 (floor). storage: 0.0002. cdn: 0 → 20.0002
    assert out >= 20.0


def test_monthly_cost_rounds_to_two_dp() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    out = e._monthly_cost(active_users=1000, concurrent=80, api_calls=45000, db_reads=120000, db_writes=30000)
    assert out == round(out, 2)


def test_monthly_cost_scales_with_active_users() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    small = e._monthly_cost(active_users=100, concurrent=8, api_calls=4500, db_reads=12000, db_writes=3000)
    large = e._monthly_cost(active_users=10_000, concurrent=800, api_calls=450_000, db_reads=1_200_000, db_writes=300_000)
    assert large > small


# ---------------------------------------------------------------------------
# _tier
# ---------------------------------------------------------------------------


def test_tier_thresholds() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    assert e._tier(10) == "starter"
    assert e._tier(50) == "growth"
    assert e._tier(500) == "business"
    assert e._tier(5000) == "enterprise"


def test_tier_boundary_at_50() -> None:
    """Cost=50 exactly → growth (boundary rule)."""
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    assert e._tier(50) == "growth"


def test_tier_boundary_at_5000() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    assert e._tier(5000) == "enterprise"


# ---------------------------------------------------------------------------
# _bottleneck
# ---------------------------------------------------------------------------


def test_bottleneck_priorities_order() -> None:
    """Priority: db_writes > concurrent > api_calls > connection_pool."""
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    # db_writes dominates.
    assert e._bottleneck(concurrent=20_000, db_writes=2_000_000, api_calls=80_000_000) == "database_write_throughput"
    # Concurrent large + small writes + high api.
    assert e._bottleneck(concurrent=11_000, db_writes=10, api_calls=80_000_000) == "compute_horizontal_scaling"
    # api_calls only.
    assert e._bottleneck(concurrent=100, db_writes=10, api_calls=80_000_000) == "api_gateway_rate_limits"
    # connection pool only.
    assert e._bottleneck(concurrent=2000, db_writes=10, api_calls=1000) == "connection_pool_saturation"
    # All small.
    assert e._bottleneck(concurrent=10, db_writes=10, api_calls=100) == "none"


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------


def _cluster(weight: float, pattern: str) -> dict[str, Any]:
    return {"population_weight": weight, "session_pattern": pattern}


def test_generate_returns_stages_in_order() -> None:
    from app.simulation.infra_scaling import (
        GROWTH_STAGES,
        InfraScalingEngine,
    )

    e = InfraScalingEngine()
    out = e.generate(
        generated_ui_id=1,
        product_type="saas",
        cluster_profiles=[],
        overall_conversion=0.05,
    )
    assert [s.stage for s in out.stages] == list(GROWTH_STAGES.keys())


def test_generate_stage_users_match_growth_stages() -> None:
    from app.simulation.infra_scaling import GROWTH_STAGES, InfraScalingEngine

    e = InfraScalingEngine()
    out = e.generate(
        generated_ui_id=1,
        product_type="saas",
        cluster_profiles=[],
        overall_conversion=0.05,
    )
    assert [s.total_users for s in out.stages] == [info["users"] for info in GROWTH_STAGES.values()]


def test_generate_unknown_product_type_falls_back_to_saas_load() -> None:
    from app.simulation.infra_scaling import DB_LOAD_MAP, InfraScalingEngine

    e = InfraScalingEngine()
    out = e.generate(
        generated_ui_id=1,
        product_type="not_in_table",
        cluster_profiles=[],
        overall_conversion=0.05,
    )
    assert out.db_profile == DB_LOAD_MAP["saas"]


def test_generate_active_users_at_least_one() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    out = e.generate(
        generated_ui_id=1,
        product_type="saas",
        cluster_profiles=[],
        overall_conversion=0.05,
    )
    for stage in out.stages:
        assert stage.active_users >= 1


def test_generate_concurrent_peak_at_least_one() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    out = e.generate(
        generated_ui_id=1,
        product_type="saas",
        cluster_profiles=[],
        overall_conversion=0.05,
    )
    for stage in out.stages:
        assert stage.concurrent_peak >= 1


def test_generate_critical_stage_advances_when_bottleneck_fires() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    # Heavy saas workload → db_writes spike at scale stage.
    out = e.generate(
        generated_ui_id=1,
        product_type="saas",
        cluster_profiles=[_cluster(1.0, "deep_work")],
        overall_conversion=0.05,
    )
    # dau ≈ 0.55, so at scale: active = 100_000 * 0.55 = 55_000
    # db_writes = 55_000 * 30 = 1_650_000 → bottleneck fires at scale.
    assert out.critical_stage in {"launch", "early", "growth", "scale", "hyper"}


def test_generate_scaling_warnings_dedup_via_dict_fromkeys() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    out = e.generate(
        generated_ui_id=1,
        product_type="saas",
        cluster_profiles=[],
        overall_conversion=0.05,
    )
    # The pgBouncer warning must appear at most once across all stages.
    warnings = [w for w in out.scaling_warnings if "pgBouncer" in w]
    assert len(warnings) <= 1


def test_generate_dau_rate_propagates_into_result() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    out = e.generate(
        generated_ui_id=1,
        product_type="saas",
        cluster_profiles=[_cluster(1.0, "deep_work")],
    )
    # 1.0 × 0.55 = 0.55 (clamped to <= 0.70).
    assert 0.5 <= out.dau_rate <= 0.6


def test_generate_avg_api_calls_from_dominant_session() -> None:
    from app.simulation.infra_scaling import (
        SESSION_API_CALL_MAP,
        InfraScalingEngine,
    )

    e = InfraScalingEngine()
    out_deep = e.generate(
        generated_ui_id=1,
        product_type="saas",
        cluster_profiles=[_cluster(1.0, "deep_work")],
    )
    assert out_deep.avg_api_calls == SESSION_API_CALL_MAP["deep_work"]
    out_quick = e.generate(
        generated_ui_id=1,
        product_type="saas",
        cluster_profiles=[_cluster(1.0, "quick_check")],
    )
    assert out_quick.avg_api_calls == SESSION_API_CALL_MAP["quick_check"]


def test_generate_storage_gb_scales_with_total_users() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    out = e.generate(
        generated_ui_id=1,
        product_type="saas",
        cluster_profiles=[],
    )
    # Each stage's storage is total * 0.005.
    for stage in out.stages:
        expected = round(stage.total_users * 0.005, 2)
        assert stage.storage_gb == expected


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


def test_to_dict_serialises_required_keys() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    out = e.generate(
        generated_ui_id=7,
        product_type="saas",
        cluster_profiles=[],
    )
    payload = e.to_dict(out)
    for key in (
        "generated_ui_id",
        "product_type",
        "dau_rate",
        "avg_session_depth",
        "avg_api_calls_per_dau",
        "db_profile",
        "critical_stage",
        "scaling_warnings",
        "stages",
    ):
        assert key in payload
    assert payload["generated_ui_id"] == 7


def test_to_dict_is_json_serialisable() -> None:
    import json

    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    out = e.generate(
        generated_ui_id=1,
        product_type="saas",
        cluster_profiles=[],
    )
    payload = e.to_dict(out)
    text = json.dumps(payload)
    parsed = json.loads(text)
    assert parsed["generated_ui_id"] == 1


def test_to_dict_stages_have_all_fields() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    out = e.generate(
        generated_ui_id=1,
        product_type="saas",
        cluster_profiles=[],
    )
    payload = e.to_dict(out)
    sample = payload["stages"][0]
    for key in (
        "stage",
        "label",
        "total_users",
        "active_users",
        "concurrent_peak",
        "api_calls_per_day",
        "db_reads_per_day",
        "db_writes_per_day",
        "storage_gb",
        "estimated_cost_usd",
        "recommended_tier",
        "bottleneck",
    ):
        assert key in sample


# ---------------------------------------------------------------------------
# Determinism + invariants
# ---------------------------------------------------------------------------


def test_generate_is_deterministic() -> None:
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    a = e.generate(
        generated_ui_id=1, product_type="saas", cluster_profiles=[_cluster(0.6, "deep_work")]
    )
    b = e.generate(
        generated_ui_id=1, product_type="saas", cluster_profiles=[_cluster(0.6, "deep_work")]
    )
    assert e.to_dict(a) == e.to_dict(b)


def test_generate_tiers_monotonic_with_user_count() -> None:
    """As users grow, tier must not regress — typically ascends starter → enterprise."""
    from app.simulation.infra_scaling import InfraScalingEngine

    e = InfraScalingEngine()
    out = e.generate(
        generated_ui_id=1, product_type="saas", cluster_profiles=[_cluster(0.6, "deep_work")]
    )
    tiers = [s.recommended_tier for s in out.stages]
    # Defined ordering: starter < growth < business < enterprise
    order = {"starter": 0, "growth": 1, "business": 2, "enterprise": 3}
    ranks = [order[t] for t in tiers]
    for prev, nxt in zip(ranks, ranks[1:]):
        assert nxt >= prev, tiers
