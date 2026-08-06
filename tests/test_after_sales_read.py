"""
Tests for the pure after-sales lifecycle builder
(``app.simulation.after_sales_read``).
"""
from __future__ import annotations

from typing import Any

from app.schemas.after_sales import (
    LEVER_ACCESSORY_BUNDLES,
    LEVER_EXTENDED_WARRANTY,
    LEVER_LOYALTY_PROGRAM,
    LEVER_SPARE_PARTS,
    LEVER_SUPPORT_SELF_SERVICE,
    RISK_LOYALTY_GAP,
    RISK_SUPPORT_BURDEN,
    TIER_AT_RISK,
    TIER_FRAGILE,
    TIER_OK,
    TIER_STRONG,
    VALID_VERDICTS,
    VERDICT_AT_RISK,
    VERDICT_HEALTHY,
    VERDICT_INSUFFICIENT,
    VERDICT_WATCH,
)
from app.simulation.after_sales_read import (
    RISK_ORDER,
    _after_sales_tier,
    _lifespan_risk,
    _primary_risk,
    _risks,
    build_after_sales_read,
)


def _registry(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "cluster_id": c["cluster_id"],
            "name": c["name"],
            "population_weight": c["population_weight"],
        }
        for c in clusters
    ]


def _metrics(
    *,
    warranty: float = 0.05,
    repair_threshold: float = 0.50,
    support: float = 0.10,
    attach: float = 0.50,
    refurbished: float = 0.15,
    sustainability: float = 0.20,
    loyalty: float = 0.50,
    review_likely: float = 0.20,
    spare: float = 0.05,
    lifespan: float = 3.0,
) -> dict[str, float]:
    return {
        "warranty_claim_likelihood": warranty,
        "repair_vs_replace_threshold": repair_threshold,
        "support_contact_rate_30d": support,
        "accessory_attach_rate": attach,
        "refurbished_participation": refurbished,
        "sustainability_concern": sustainability,
        "brand_loyalty_next_purchase": loyalty,
        "review_writing_likelihood": review_likely,
        "spare_parts_concern": spare,
        "expected_product_lifespan_y": lifespan,
    }


def _conductor(
    specs: dict[str, dict[str, Any]],
    flags: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    flags = flags or {}
    return {
        cid: {
            "AftersalesLifecycleArchitect": {
                "metrics": metrics,
                "flags": {key: True for key in flags.get(cid, [])},
            }
        }
        for cid, metrics in specs.items()
    }


def _clusters(
    *,
    weights: tuple[float, float] = (0.4, 0.6),
) -> list[dict[str, Any]]:
    return [
        {"cluster_id": "a", "name": "Alpha", "population_weight": weights[0]},
        {"cluster_id": "b", "name": "Beta", "population_weight": weights[1]},
    ]


def _build(
    *,
    specs: dict[str, dict[str, Any]],
    clusters: list[dict[str, Any]] | None = None,
    flags: dict[str, list[str]] | None = None,
    product_type: str = "consumer_hardware",
    results: dict[str, Any] | None = None,
    signal_quality: float | None = 0.62,
    visible_assumptions: int | None = None,
) -> Any:
    return build_after_sales_read(
        results
        if results is not None
        else {
            "population_weighted_conversion": 0.04,
            "product_type_detected": product_type,
        },
        simulation_id=1,
        project_id=10,
        status="COMPLETED",
        signal_quality=signal_quality,
        visible_assumption_count=visible_assumptions,
        conductor_results=_conductor(specs, flags=flags),
        cluster_registry=_registry(
            clusters if clusters is not None else _clusters()
        ),
        product_type=product_type,
    )


def test_low_signal_quality_adds_caveat_and_meta() -> None:
    out = _build(
        signal_quality=0.31,
        visible_assumptions=0,
        specs={
            "a": _metrics(),
            "b": _metrics(),
        },
    )

    assert out.meta["signal_quality"] == 0.31
    assert out.meta["visible_assumptions"] == 0
    assert any("signal quality is low" in rec for rec in out.recommendations)
    assert any("No visible project assumptions" in rec for rec in out.recommendations)


def test_visible_assumption_count_is_echoed() -> None:
    out = _build(
        visible_assumptions=4,
        specs={
            "a": _metrics(),
            "b": _metrics(),
        },
    )

    assert out.meta["visible_assumptions"] == 4
    assert not any(
        "No visible project assumptions" in rec for rec in out.recommendations
    )


# ---------------------------------------------------------------------------
# Verdicts and index mechanics
# ---------------------------------------------------------------------------


def test_healthy_market_gets_healthy_verdict() -> None:
    out = _build(
        specs={
            "a": _metrics(
                support=0.04,
                loyalty=0.80,
                warranty=0.02,
                review_likely=0.03,
                lifespan=5.0,
                attach=0.70,
            ),
            "b": _metrics(
                support=0.06,
                loyalty=0.78,
                warranty=0.02,
                review_likely=0.04,
                lifespan=5.0,
                attach=0.65,
            ),
        }
    )

    assert out.verdict == VERDICT_HEALTHY
    assert out.after_sales_index >= 0.75
    assert out.strong_share + out.ok_share == 1.0
    assert all(
        p.after_sales_tier == TIER_STRONG
        for p in out.cluster_profiles
    )
    assert out.primary_risk in RISK_ORDER
    assert out.recommendations


def test_strained_market_gets_at_risk_verdict() -> None:
    out = _build(
        specs={
            "a": _metrics(
                support=0.70,
                loyalty=0.20,
                warranty=0.35,
                review_likely=0.60,
                spare=0.17,
                lifespan=1.5,
                attach=0.05,
            ),
            "b": _metrics(
                support=0.65,
                loyalty=0.18,
                warranty=0.35,
                review_likely=0.60,
                spare=0.16,
                lifespan=1.5,
                attach=0.05,
            ),
        }
    )

    assert out.verdict == VERDICT_AT_RISK
    assert out.after_sales_index < 0.40
    assert out.at_risk_share == 1.0
    assert "at_risk_after_sales_clusters" in out.flags
    assert out.primary_risk in RISK_ORDER
    assert out.primary_risk_share > 0.0
    assert out.meta["primary_risk_score"] > 0.4


def test_index_is_population_weighted() -> None:
    # Alpha healthy (0.9), Beta weak (0.3): weighted index should sit
    # closer to Alpha because Alpha carries 80% of the market.
    out = _build(
        clusters=_clusters(weights=(0.8, 0.2)),
        specs={
            "a": _metrics(
                support=0.02,
                loyalty=0.90,
                warranty=0.01,
                review_likely=0.02,
                lifespan=5.5,
                attach=0.80,
            ),
            "b": _metrics(
                support=0.75,
                loyalty=0.15,
                warranty=0.30,
                review_likely=0.50,
                spare=0.16,
                lifespan=1.5,
                attach=0.05,
            ),
        },
    )

    alpha = next(p for p in out.cluster_profiles if p.cluster_id == "a")
    beta = next(p for p in out.cluster_profiles if p.cluster_id == "b")
    assert alpha.after_sales_index > beta.after_sales_index
    assert out.after_sales_index > beta.after_sales_index
    assert out.after_sales_index < alpha.after_sales_index


def test_verdict_threshold_boundaries() -> None:
    assert _after_sales_tier(0.75) == TIER_STRONG
    assert _after_sales_tier(0.70) == TIER_STRONG
    assert _after_sales_tier(0.60) == TIER_OK
    assert _after_sales_tier(0.55) == TIER_OK
    assert _after_sales_tier(0.45) == TIER_FRAGILE
    assert _after_sales_tier(0.40) == TIER_FRAGILE
    assert _after_sales_tier(0.30) == TIER_AT_RISK


def test_lifespan_risk_normalization() -> None:
    assert _lifespan_risk(1.0) == 1.0
    assert _lifespan_risk(4.0) == 0.0
    assert _lifespan_risk(2.5) == 0.5
    # Out-of-range values clamp instead of manufacturing risk.
    assert _lifespan_risk(0.0) == 1.0
    assert _lifespan_risk(99.0) == 0.0


# ---------------------------------------------------------------------------
# Risk attribution
# ---------------------------------------------------------------------------


def test_primary_risk_picks_worst_dimension_with_stable_ties() -> None:
    risks = {
        RISK_SUPPORT_BURDEN: 0.5,
        RISK_LOYALTY_GAP: 0.5,
    }
    key, score = _primary_risk(risks)
    assert key == RISK_SUPPORT_BURDEN  # earlier key wins ties
    assert score == 0.5

    risks = {
        RISK_SUPPORT_BURDEN: 0.2,
        RISK_LOYALTY_GAP: 0.7,
    }
    key, _ = _primary_risk(risks)
    assert key == RISK_LOYALTY_GAP


def test_review_risk_requires_dissatisfaction() -> None:
    # High review activity with high loyalty is not a risk.
    happy = _risks(_metrics(review_likely=0.60, loyalty=0.80))
    # High review activity with low loyalty is.
    unhappy = _risks(_metrics(review_likely=0.60, loyalty=0.20))
    assert happy[RISK_LOYALTY_GAP] < unhappy[RISK_LOYALTY_GAP]
    assert happy["review_risk"] < unhappy["review_risk"]
    assert 0.0 <= happy["review_risk"] <= 1.0


def test_risk_distribution_and_primary_share() -> None:
    out = _build(
        specs={
            "a": _metrics(loyalty=0.20, support=0.60, lifespan=1.5),
            "b": _metrics(loyalty=0.90, support=0.05, lifespan=5.0),
        },
        clusters=_clusters(weights=(0.5, 0.5)),
    )

    assert sum(out.risk_distribution.values()) == 1.0
    assert out.primary_risk in RISK_ORDER
    assert out.primary_risk_share > 0.0
    # Beta is clearly healthy; its primary risk should never be the
    # market-level winner if Alpha has any real risk.
    beta = next(p for p in out.cluster_profiles if p.cluster_id == "b")
    assert beta.after_sales_index > 0.8


# ---------------------------------------------------------------------------
# Product-type support and data edge cases
# ---------------------------------------------------------------------------


def test_unsupported_product_type_returns_insufficient_data() -> None:
    out = _build(
        specs={"a": _metrics()},
        product_type="saas",
    )

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["product_type_supported"] is False
    assert out.cluster_profiles == []
    assert out.levers == []
    assert "only activates for" in out.recommendations[0]


def test_all_hardware_product_types_are_supported() -> None:
    for product_type in (
        "consumer_hardware",
        "health_hardware",
        "iot_hardware",
        "wearable",
        "b2b_hardware",
    ):
        out = _build(specs={"a": _metrics()}, product_type=product_type)
        assert out.meta["product_type_supported"] is True
        assert out.verdict != VERDICT_INSUFFICIENT


def test_missing_metrics_returns_insufficient_data() -> None:
    out = _build(specs={}, product_type="consumer_hardware")

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["product_type_supported"] is True
    assert out.meta["covered_clusters"] == 0
    assert "No per-cluster" in out.recommendations[0]


def test_partial_metrics_use_neutral_defaults_without_false_risk() -> None:
    # Only support contact is present and elevated; every other metric
    # falls back to a neutral default. The read must not manufacture
    # AT_RISK, nor fire warranty / loyalty / spare / lifespan levers.
    out = _build(
        specs={
            "a": {"support_contact_rate_30d": 0.60},
            "b": {"support_contact_rate_30d": 0.60},
        }
    )

    assert out.verdict in {VERDICT_WATCH, VERDICT_HEALTHY}
    assert out.after_sales_index >= 0.55
    assert "warranty_pressure" not in out.flags
    assert "spare_parts_concern" not in out.flags
    assert "short_lifespan" not in out.flags
    lever_shares = {
        lever.key: lever.opportunity_share for lever in out.levers
    }
    assert lever_shares[LEVER_EXTENDED_WARRANTY] == 0.0
    assert lever_shares[LEVER_LOYALTY_PROGRAM] == 0.0
    assert lever_shares[LEVER_SPARE_PARTS] == 0.0
    assert lever_shares[LEVER_SUPPORT_SELF_SERVICE] == 1.0


def test_zero_weight_clusters_are_excluded() -> None:
    out = _build(
        clusters=[
            {"cluster_id": "a", "name": "Alpha", "population_weight": 1.0},
            {
                "cluster_id": "zero",
                "name": "Zero",
                "population_weight": 0.0,
            },
        ],
        specs={"a": _metrics(), "zero": _metrics(loyalty=0.10)},
    )

    assert out.meta["covered_clusters"] == 1
    assert out.meta["covered_weight"] == 1.0
    assert [p.cluster_id for p in out.cluster_profiles] == ["a"]


def test_malformed_results_and_conductor_are_tolerated() -> None:
    out = build_after_sales_read(
        "not-json",
        simulation_id=1,
        project_id=10,
        conductor_results="not-a-dict",
        cluster_registry=None,
        product_type="consumer_hardware",
    )

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.simulation_id == 1
    assert out.project_id == 10


# ---------------------------------------------------------------------------
# Levers and flags
# ---------------------------------------------------------------------------


def test_levers_are_ranked_by_opportunity_share() -> None:
    out = _build(
        specs={
            "a": _metrics(loyalty=0.20, support=0.60),
            "b": _metrics(loyalty=0.90, support=0.55),
        },
        clusters=_clusters(weights=(0.5, 0.5)),
    )

    shares = [lever.opportunity_share for lever in out.levers]
    assert shares == sorted(shares, reverse=True)
    assert out.levers[0].key == LEVER_SUPPORT_SELF_SERVICE
    assert any(lever.key == LEVER_LOYALTY_PROGRAM for lever in out.levers)
    assert any(
        lever.key == LEVER_ACCESSORY_BUNDLES for lever in out.levers
    )
    assert all(lever.label for lever in out.levers)
    assert all(lever.action for lever in out.levers)


def test_architect_flags_are_surfaced_in_profiles_and_market_flags() -> None:
    out = _build(
        specs={
            "a": _metrics(),
            "b": _metrics(loyalty=0.80, support=0.05),
        },
        flags={
            "a": ["low_brand_loyalty", "high_support_burden"],
            "b": [],
        },
    )

    alpha = next(p for p in out.cluster_profiles if p.cluster_id == "a")
    assert set(alpha.architect_flags) == {
        "low_brand_loyalty",
        "high_support_burden",
    }
    assert "low_loyalty_clusters_present" in out.flags
    assert "high_support_clusters_present" in out.flags


def test_meta_contract() -> None:
    out = _build(specs={"a": _metrics()})

    assert out.meta["signal_quality"] == 0.62
    assert out.meta["total_clusters"] == 2
    assert out.meta["covered_clusters"] == 1
    assert out.meta["covered_weight"] == 0.4
    assert out.meta["product_type_supported"] is True
    assert "supported_product_types" in out.meta
    assert "thresholds" in out.meta
    assert "normalization" in out.meta
    assert out.meta["primary_risk_score"] >= 0.0


def test_verdicts_are_valid_enum_values() -> None:
    out = _build(specs={"a": _metrics()})
    assert out.verdict in VALID_VERDICTS
    assert {p.after_sales_tier for p in out.cluster_profiles} <= {
        TIER_STRONG,
        TIER_OK,
        TIER_FRAGILE,
        TIER_AT_RISK,
    }
