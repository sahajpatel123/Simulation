"""
Pure distribution-channel analysis for completed simulation results.

Answers the hardware founder's "can my market actually buy this
product, and which channel lever should I pull first?" question by
turning the ``DistributionChannelArchitect`` per-cluster metrics into a
deterministic, population-weighted channel-readiness read:

* **Weighted channel metrics** — population-weighted accessibility
  multiplier, online preference, try-before-buy requirement, influencer
  dependency, cashback/loyalty sensitivity, delivery days required, and
  the four platform preferences (Amazon, Flipkart, brand direct,
  offline).
* **Cluster tiers** — every covered cluster is classified
  ``OMNICHANNEL`` (accessible online and offline) / ``ONLINE``
  (accessible online) / ``LIMITED_ACCESS`` (partial access) /
  ``ACCESS_GAP`` (cannot reliably access the product).
* **Primary distribution blocker** — each cluster is attributed to the
  worst of six modeled inputs (distribution access, try-before-buy,
  influencer verification, cashback/loyalty, delivery speed, platform
  presence). The market-level blocker distribution is the
  population-weighted share of those attributions.
* **Distribution levers** — six interventions (offline distribution,
  try-before-buy programme, influencer programme, cashback/loyalty,
  delivery speed, platform expansion) ranked by the share of the covered
  market where the underlying metric is below a healthy threshold.

The verdict is ``OMNICHANNEL`` when weighted accessibility is at least
0.90, weighted online preference is below 0.85 and weighted offline
platform preference is at least 0.45; ``ACCESS_GAP`` when weighted
accessibility is below 0.80 or at least 15% of the covered market is in
an access-gap tier; ``ONLINE_FIRST`` otherwise, and
``INSUFFICIENT_DATA`` for product types whose conductor stack does not
run ``DistributionChannelArchitect`` (software types) or when no
cluster has usable metrics.

No DB / I/O — verifiable without FastAPI or PostgreSQL. The route layer
supplies ``results``, ``conductor_results`` (per-cluster architect
metrics) and ``cluster_registry``; all arithmetic is deterministic.
Metrics missing from a malformed/partial payload use conservative
defaults (accessibility 0.0, online preference 0.5, try-before-buy 0.0,
influencer dependency 0.0, cashback sensitivity 0.0, delivery 2 days,
platform scores 0.0) so a missing field never manufactures access,
omnichannel readiness, or a lever.
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable

from app.schemas.distribution_channels import (
    BLOCKER_ACCESS,
    BLOCKER_CASHBACK,
    BLOCKER_DELIVERY,
    BLOCKER_INFLUENCER,
    BLOCKER_PLATFORM,
    BLOCKER_TRY_BEFORE_BUY,
    ClusterChannelProfile,
    DistributionChannelsOut,
    DistributionLever,
    LEVER_CASHBACK,
    LEVER_DELIVERY,
    LEVER_INFLUENCER,
    LEVER_OFFLINE,
    LEVER_PLATFORM,
    LEVER_TRY_BEFORE_BUY,
    TIER_ACCESS_GAP,
    TIER_LIMITED_ACCESS,
    TIER_OMNICHANNEL,
    TIER_ONLINE,
    VERDICT_ACCESS_GAP,
    VERDICT_INSUFFICIENT,
    VERDICT_OMNICHANNEL,
    VERDICT_ONLINE_FIRST,
)

# Product types whose conductor stack runs DistributionChannelArchitect.
DISTRIBUTION_PRODUCT_TYPES: frozenset[str] = frozenset(
    {
        "consumer_hardware",
        "health_hardware",
        "iot_hardware",
        "wearable",
        "b2b_hardware",
        "smart_home",
    }
)

# Ordered blocker keys — used for tie-breaking and market aggregation so
# the output is stable regardless of dict ordering.
BLOCKER_ORDER: tuple[str, ...] = (
    BLOCKER_ACCESS,
    BLOCKER_TRY_BEFORE_BUY,
    BLOCKER_INFLUENCER,
    BLOCKER_CASHBACK,
    BLOCKER_DELIVERY,
    BLOCKER_PLATFORM,
)

BLOCKER_LABELS: dict[str, str] = {
    BLOCKER_ACCESS: "Distribution access",
    BLOCKER_TRY_BEFORE_BUY: "Try-before-buy requirement",
    BLOCKER_INFLUENCER: "Influencer verification",
    BLOCKER_CASHBACK: "Cashback / loyalty sensitivity",
    BLOCKER_DELIVERY: "Delivery speed",
    BLOCKER_PLATFORM: "Platform presence",
}

# Cluster-tier thresholds (accessibility multiplier).
TIER_OMNICHANNEL_ACCESS: float = 0.90
TIER_OMNICHANNEL_OFFLINE_MIN: float = 0.45
TIER_ONLINE_ACCESS: float = 0.90
TIER_LIMITED_ACCESS_MIN: float = 0.55

# Verdict thresholds (weighted market aggregates).
VERDICT_ACCESS_GAP_ACCESS: float = 0.80
VERDICT_ACCESS_GAP_SHARE: float = 0.15
VERDICT_OMNICHANNEL_ACCESS: float = 0.90
VERDICT_OMNICHANNEL_ONLINE_MAX: float = 0.85
VERDICT_OMNICHANNEL_OFFLINE_MIN: float = 0.45

# Lever opportunity thresholds — a lever applies to a cluster when the
# underlying channel input is below this healthy level (or above for
# requirements / days).
LEVER_OFFLINE_ACCESS_MAX: float = 0.999
LEVER_TRY_BEFORE_BUY_MIN: float = 0.50
LEVER_INFLUENCER_MIN: float = 0.55
LEVER_CASHBACK_MIN: float = 0.50
LEVER_DELIVERY_MAX_DAYS: float = 2.0
LEVER_PLATFORM_MIN: float = 0.50

# Flag thresholds.
FLAG_TRY_BEFORE_BUY: float = 0.60
FLAG_INFLUENCER: float = 0.55
FLAG_CASHBACK: float = 0.50
FLAG_DELIVERY_DAYS: float = 3.0
FLAG_OFFLINE: float = 0.35

# Conservative defaults for metrics missing from a malformed/partial
# payload. An unknown channel input is treated as weak so a missing
# field never manufactures access, omnichannel readiness, or a lever.
DEFAULT_ACCESS: float = 0.0
DEFAULT_ONLINE_PREF: float = 0.5
DEFAULT_TRY_BEFORE_BUY: float = 0.0
DEFAULT_INFLUENCER: float = 0.0
DEFAULT_CASHBACK: float = 0.0
DEFAULT_DELIVERY_DAYS: float = 2.0
DEFAULT_PLATFORM: float = 0.0

LEVER_LABELS: dict[str, str] = {
    LEVER_OFFLINE: "Offline distribution",
    LEVER_TRY_BEFORE_BUY: "Try-before-buy programme",
    LEVER_INFLUENCER: "Influencer programme",
    LEVER_CASHBACK: "Cashback / loyalty programme",
    LEVER_DELIVERY: "Delivery speed",
    LEVER_PLATFORM: "Platform expansion",
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _coerce_results(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _fmt_pct(value: float) -> str:
    return f"{_clamp(value) * 100:.0f}%"


def _distribution_metrics(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> dict[str, Any]:
    """Extract the DistributionChannelArchitect metrics block for one cluster."""
    if not conductor_results:
        return {}
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return {}
    architect = cluster_block.get("DistributionChannelArchitect")
    if not isinstance(architect, dict):
        return {}
    metrics = architect.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _cluster_flags(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> dict[str, Any]:
    """Extract the DistributionChannelArchitect flags block for one cluster."""
    if not conductor_results:
        return {}
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return {}
    architect = cluster_block.get("DistributionChannelArchitect")
    if not isinstance(architect, dict):
        return {}
    flags = architect.get("flags")
    return flags if isinstance(flags, dict) else {}


def _platform_max(metrics: dict[str, Any]) -> float:
    return max(
        _clamp(_safe_float(metrics.get("platform_pref_amazon"), DEFAULT_PLATFORM)),
        _clamp(_safe_float(metrics.get("platform_pref_flipkart"), DEFAULT_PLATFORM)),
        _clamp(_safe_float(metrics.get("platform_pref_brand_direct"), DEFAULT_PLATFORM)),
        _clamp(_safe_float(metrics.get("platform_pref_offline"), DEFAULT_PLATFORM)),
    )


def _blocker_gaps(metrics: dict[str, Any]) -> dict[str, float]:
    """Normalized channel-input gaps for one cluster (0..1, higher = worse)."""
    access = _clamp(
        _safe_float(
            metrics.get("distribution_accessibility_multiplier"),
            DEFAULT_ACCESS,
        )
    )
    try_before_buy = _clamp(
        _safe_float(
            metrics.get("try_before_buy_requirement"),
            DEFAULT_TRY_BEFORE_BUY,
        )
    )
    influencer = _clamp(
        _safe_float(
            metrics.get("influencer_review_dependency"),
            DEFAULT_INFLUENCER,
        )
    )
    cashback = _clamp(
        _safe_float(
            metrics.get("cashback_loyalty_sensitivity"),
            DEFAULT_CASHBACK,
        )
    )
    days = max(
        1.0,
        _safe_float(
            metrics.get("delivery_speed_days_required"),
            DEFAULT_DELIVERY_DAYS,
        ),
    )
    platform = _platform_max(metrics)
    return {
        BLOCKER_ACCESS: round(1.0 - access, 4),
        BLOCKER_TRY_BEFORE_BUY: round(try_before_buy, 4),
        BLOCKER_INFLUENCER: round(influencer, 4),
        BLOCKER_CASHBACK: round(cashback, 4),
        BLOCKER_DELIVERY: round(max(0.0, min(1.0, (days - 1.0) / 4.0)), 4),
        BLOCKER_PLATFORM: round(1.0 - platform, 4),
    }


def _primary_blocker(gaps: dict[str, float]) -> tuple[str, float]:
    """Highest gap; ties resolve to the earlier key in BLOCKER_ORDER."""
    best_key = BLOCKER_ORDER[0]
    best_value = gaps.get(best_key, 0.0)
    for key in BLOCKER_ORDER[1:]:
        value = gaps.get(key, 0.0)
        if value > best_value:
            best_key = key
            best_value = value
    return best_key, best_value


def _channel_tier(metrics: dict[str, Any]) -> str:
    """Classify one cluster's channel readiness from its metrics."""
    access = _clamp(
        _safe_float(
            metrics.get("distribution_accessibility_multiplier"),
            DEFAULT_ACCESS,
        )
    )
    offline = _clamp(
        _safe_float(
            metrics.get("platform_pref_offline"),
            DEFAULT_PLATFORM,
        )
    )
    if access >= TIER_OMNICHANNEL_ACCESS and offline >= TIER_OMNICHANNEL_OFFLINE_MIN:
        return TIER_OMNICHANNEL
    if access >= TIER_ONLINE_ACCESS:
        return TIER_ONLINE
    if access >= TIER_LIMITED_ACCESS_MIN:
        return TIER_LIMITED_ACCESS
    return TIER_ACCESS_GAP


def _weighted_average(rows: list[dict[str, Any]], key: str) -> float:
    """Population-weighted average of ``key`` across covered rows."""
    total_weight = sum(row["population_weight"] for row in rows)
    if total_weight <= 0.0:
        return 0.0
    return sum(
        row["population_weight"] * row[key] for row in rows
    ) / total_weight


def _lever(
    rows: list[dict[str, Any]],
    key: str,
    market_key: str,
    applies: Callable[[dict[str, Any]], bool],
    action_template: str,
) -> DistributionLever:
    covered = sum(row["population_weight"] for row in rows)
    matched = [row for row in rows if applies(row)]
    value = sum(row["population_weight"] for row in matched)
    share = value / covered if covered > 0.0 else 0.0
    return DistributionLever(
        key=key,
        label=LEVER_LABELS[key],
        market_value=round(value, 4),
        opportunity_share=round(share, 4),
        action=action_template.format(
            share=_fmt_pct(share),
            market=market_key,
        ),
    )


def build_distribution_channels(
    results: dict[str, Any] | None,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    conductor_results: dict[str, Any] | None = None,
    cluster_registry: list[dict[str, Any]] | None = None,
    product_type: str = "consumer_hardware",
) -> DistributionChannelsOut:
    """Compose the distribution-channels read from completed results.

    Args:
        results: Simulation ``results_json`` (context only — per-cluster
            architect metrics come from ``conductor_results``).
        simulation_id: Simulation primary key (echoed back).
        project_id: Owning project primary key (echoed back).
        status: Simulation status string.
        signal_quality: Persisted signal quality (0..1), if any.
        conductor_results: Per-cluster architect output blocks
            (``{cluster_id: {architect: {"metrics": ..., "flags": ...}}}``).
        cluster_registry: List of ``{cluster_id, name, population_weight}``.
        product_type: Detected product type for the run.
    """
    payload = _coerce_results(results)
    product_type_name = str(
        product_type or payload.get("product_type_detected", "consumer_hardware")
        or "consumer_hardware"
    ).lower()
    registry: list[dict[str, Any]] = cluster_registry or []
    supported = product_type_name in DISTRIBUTION_PRODUCT_TYPES

    rows: list[dict[str, Any]] = []
    covered_weight = 0.0
    for entry in registry:
        cid = str(entry.get("cluster_id", ""))
        if not cid:
            continue
        weight = max(0.0, _safe_float(entry.get("population_weight")))
        metrics = _distribution_metrics(conductor_results, cid)
        if not metrics:
            continue

        access = _clamp(
            _safe_float(
                metrics.get("distribution_accessibility_multiplier"),
                DEFAULT_ACCESS,
            )
        )
        online_pref = _clamp(
            _safe_float(
                metrics.get("online_preference"),
                DEFAULT_ONLINE_PREF,
            )
        )
        days = max(
            1.0,
            _safe_float(
                metrics.get("delivery_speed_days_required"),
                DEFAULT_DELIVERY_DAYS,
            ),
        )
        try_before_buy = _clamp(
            _safe_float(
                metrics.get("try_before_buy_requirement"),
                DEFAULT_TRY_BEFORE_BUY,
            )
        )
        influencer = _clamp(
            _safe_float(
                metrics.get("influencer_review_dependency"),
                DEFAULT_INFLUENCER,
            )
        )
        cashback = _clamp(
            _safe_float(
                metrics.get("cashback_loyalty_sensitivity"),
                DEFAULT_CASHBACK,
            )
        )
        amazon = _clamp(
            _safe_float(metrics.get("platform_pref_amazon"), DEFAULT_PLATFORM)
        )
        flipkart = _clamp(
            _safe_float(metrics.get("platform_pref_flipkart"), DEFAULT_PLATFORM)
        )
        brand_direct = _clamp(
            _safe_float(
                metrics.get("platform_pref_brand_direct"),
                DEFAULT_PLATFORM,
            )
        )
        offline = _clamp(
            _safe_float(
                metrics.get("platform_pref_offline"),
                DEFAULT_PLATFORM,
            )
        )

        blocker, blocker_score = _primary_blocker(_blocker_gaps(metrics))
        covered_weight += weight
        rows.append(
            {
                "cluster_id": cid,
                "cluster_name": str(entry.get("name", "") or cid),
                "population_weight": weight,
                "access": access,
                "online_pref": online_pref,
                "days": days,
                "try_before_buy": try_before_buy,
                "influencer": influencer,
                "cashback": cashback,
                "amazon": amazon,
                "flipkart": flipkart,
                "brand_direct": brand_direct,
                "offline": offline,
                "platform_max": max(amazon, flipkart, brand_direct, offline),
                "tier": _channel_tier(metrics),
                "blocker": blocker,
                "blocker_score": blocker_score,
                "architect_flags": _cluster_flags(conductor_results, cid),
            }
        )

    meta: dict[str, Any] = {
        "signal_quality": signal_quality,
        "total_clusters": len(registry),
        "covered_clusters": len(rows),
        "covered_weight": round(covered_weight, 4),
        "product_type_supported": supported,
        "thresholds": {
            "tier_omnichannel_access": TIER_OMNICHANNEL_ACCESS,
            "tier_omnichannel_offline_min": TIER_OMNICHANNEL_OFFLINE_MIN,
            "tier_online_access": TIER_ONLINE_ACCESS,
            "tier_limited_access_min": TIER_LIMITED_ACCESS_MIN,
            "verdict_access_gap_access": VERDICT_ACCESS_GAP_ACCESS,
            "verdict_access_gap_share": VERDICT_ACCESS_GAP_SHARE,
            "verdict_omnichannel_access": VERDICT_OMNICHANNEL_ACCESS,
            "verdict_omnichannel_online_max": VERDICT_OMNICHANNEL_ONLINE_MAX,
            "verdict_omnichannel_offline_min": VERDICT_OMNICHANNEL_OFFLINE_MIN,
        },
    }

    if not supported:
        return DistributionChannelsOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                (
                    f"Distribution channels are not modeled for "
                    f"{product_type_name} — this read supports "
                    "consumer_hardware, health_hardware, iot_hardware, "
                    "wearable, b2b_hardware and smart_home runs."
                )
            ],
            meta=meta,
        )
    if not rows or covered_weight <= 0.0:
        return DistributionChannelsOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                "No per-cluster DistributionChannelArchitect metrics "
                "were available for this run."
            ],
            meta=meta,
        )

    access_avg = _weighted_average(rows, "access")
    online_avg = _weighted_average(rows, "online_pref")
    try_avg = _weighted_average(rows, "try_before_buy")
    influencer_avg = _weighted_average(rows, "influencer")
    cashback_avg = _weighted_average(rows, "cashback")
    days_avg = _weighted_average(rows, "days")
    amazon_avg = _weighted_average(rows, "amazon")
    flipkart_avg = _weighted_average(rows, "flipkart")
    brand_direct_avg = _weighted_average(rows, "brand_direct")
    offline_avg = _weighted_average(rows, "offline")

    omnichannel_weight = sum(
        row["population_weight"] for row in rows if row["tier"] == TIER_OMNICHANNEL
    )
    online_weight = sum(
        row["population_weight"] for row in rows if row["tier"] == TIER_ONLINE
    )
    limited_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_LIMITED_ACCESS
    )
    gap_weight = sum(
        row["population_weight"] for row in rows if row["tier"] == TIER_ACCESS_GAP
    )
    omnichannel_share = omnichannel_weight / covered_weight
    online_share = online_weight / covered_weight
    limited_share = limited_weight / covered_weight
    access_gap_share = gap_weight / covered_weight

    if access_avg < VERDICT_ACCESS_GAP_ACCESS or access_gap_share >= VERDICT_ACCESS_GAP_SHARE:
        verdict = VERDICT_ACCESS_GAP
    elif (
        access_avg >= VERDICT_OMNICHANNEL_ACCESS
        and online_avg < VERDICT_OMNICHANNEL_ONLINE_MAX
        and offline_avg >= VERDICT_OMNICHANNEL_OFFLINE_MIN
    ):
        verdict = VERDICT_OMNICHANNEL
    else:
        verdict = VERDICT_ONLINE_FIRST

    # Market blocker distribution = population-weighted share of per-cluster
    # primary-blocker attributions.
    blocker_weights: dict[str, float] = {key: 0.0 for key in BLOCKER_ORDER}
    for row in rows:
        blocker_weights[row["blocker"]] += row["population_weight"]
    blocker_distribution = {
        key: round(weight / covered_weight, 4)
        for key, weight in blocker_weights.items()
    }
    primary_blocker = BLOCKER_ORDER[0]
    primary_blocker_share = blocker_distribution[primary_blocker]
    for key in BLOCKER_ORDER[1:]:
        if blocker_distribution[key] > primary_blocker_share:
            primary_blocker = key
            primary_blocker_share = blocker_distribution[key]

    flags: list[str] = []
    kill_shot_rows = [
        row
        for row in rows
        if row["architect_flags"].get("distribution_kill_shot") is True
        or row["access"] < 0.40
    ]
    if kill_shot_rows:
        flags.append("distribution_kill_shot")
    if try_avg >= FLAG_TRY_BEFORE_BUY or any(
        row["architect_flags"].get("try_before_buy_critical") is True for row in rows
    ):
        flags.append("try_before_buy_critical")
    if influencer_avg > FLAG_INFLUENCER:
        flags.append("influencer_required")
    if cashback_avg > FLAG_CASHBACK:
        flags.append("cashback_dependent")
    if days_avg > FLAG_DELIVERY_DAYS:
        flags.append("delivery_sensitive")
    if offline_avg < FLAG_OFFLINE:
        flags.append("no_offline_presence")

    levers: list[DistributionLever] = [
        _lever(
            rows,
            LEVER_OFFLINE,
            "covered market",
            lambda row: row["access"] < LEVER_OFFLINE_ACCESS_MAX,
            "Establish offline distribution (retail / stores / tier-2+ availability) for {share} of the {market}.",
        ),
        _lever(
            rows,
            LEVER_TRY_BEFORE_BUY,
            "covered market",
            lambda row: row["try_before_buy"] > LEVER_TRY_BEFORE_BUY_MIN,
            "Offer a try-before-buy or return-friendly programme — {share} of the {market} needs to test first.",
        ),
        _lever(
            rows,
            LEVER_INFLUENCER,
            "covered market",
            lambda row: row["influencer"] > LEVER_INFLUENCER_MIN,
            "Run an influencer / reviewer verification programme for {share} of the {market}.",
        ),
        _lever(
            rows,
            LEVER_CASHBACK,
            "covered market",
            lambda row: row["cashback"] > LEVER_CASHBACK_MIN,
            "Add cashback or loyalty incentives for {share} of the {market}.",
        ),
        _lever(
            rows,
            LEVER_DELIVERY,
            "covered market",
            lambda row: row["days"] > LEVER_DELIVERY_MAX_DAYS,
            "Compress delivery timelines for {share} of the {market}.",
        ),
        _lever(
            rows,
            LEVER_PLATFORM,
            "covered market",
            lambda row: row["platform_max"] < LEVER_PLATFORM_MIN,
            "Expand marketplace / direct platform presence for {share} of the {market}.",
        ),
    ]
    levers.sort(key=lambda lever: (-lever.opportunity_share, lever.key))

    recommendations: list[str] = []
    if verdict == VERDICT_ACCESS_GAP:
        recommendations.append(
            f"Market access is the bottleneck (weighted accessibility "
            f"{_fmt_pct(access_avg)}, {_fmt_pct(access_gap_share)} of the "
            "covered market in ACCESS_GAP) — fix distribution before "
            "scaling marketing spend."
        )
    elif verdict == VERDICT_OMNICHANNEL:
        recommendations.append(
            f"Distribution is market-ready (weighted accessibility "
            f"{_fmt_pct(access_avg)}, {_fmt_pct(omnichannel_share)} "
            "OMNICHANNEL) — focus on demand generation, not channel build."
        )
    else:
        recommendations.append(
            f"Online-first distribution is viable (weighted accessibility "
            f"{_fmt_pct(access_avg)}) — lead with ecommerce and direct "
            "platforms before adding offline channels."
        )
    recommendations.append(
        f"Primary distribution blocker: {BLOCKER_LABELS[primary_blocker]} "
        f"(affects {_fmt_pct(primary_blocker_share)} of the covered market)."
    )
    if kill_shot_rows:
        recommendations.append(
            f"{len(kill_shot_rows)} cluster(s) cannot reliably access the "
            "product — without offline or tier-2+ availability those "
            "segments will not convert."
        )
    if try_avg >= FLAG_TRY_BEFORE_BUY:
        recommendations.append(
            f"Try-before-buy demand is {_fmt_pct(try_avg)} — high-AOV "
            "hardware needs a test/return path before purchase."
        )
    if influencer_avg > FLAG_INFLUENCER:
        recommendations.append(
            f"Influencer verification dependency is {_fmt_pct(influencer_avg)} "
            "— seed reviews and creator content before launch."
        )
    if cashback_avg > FLAG_CASHBACK:
        recommendations.append(
            f"Cashback/loyalty sensitivity is {_fmt_pct(cashback_avg)} — "
            "price-sensitive clusters respond to purchase incentives."
        )
    if days_avg > FLAG_DELIVERY_DAYS:
        recommendations.append(
            f"Average delivery requirement is {days_avg:.1f} days — "
            "promise and meet faster delivery for urgent buyers."
        )
    if offline_avg < FLAG_OFFLINE:
        recommendations.append(
            f"Offline platform preference is only {_fmt_pct(offline_avg)} — "
            "physical availability is not part of the purchase path yet."
        )

    return DistributionChannelsOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type_name,
        verdict=verdict,
        weighted_online_preference=round(online_avg, 4),
        weighted_accessibility=round(access_avg, 4),
        weighted_try_before_buy=round(try_avg, 4),
        weighted_influencer_dependency=round(influencer_avg, 4),
        weighted_cashback_sensitivity=round(cashback_avg, 4),
        weighted_delivery_days=round(days_avg, 2),
        weighted_platform_amazon=round(amazon_avg, 4),
        weighted_platform_flipkart=round(flipkart_avg, 4),
        weighted_platform_brand_direct=round(brand_direct_avg, 4),
        weighted_platform_offline=round(offline_avg, 4),
        omnichannel_share=round(omnichannel_share, 4),
        online_share=round(online_share, 4),
        limited_access_share=round(limited_share, 4),
        access_gap_share=round(access_gap_share, 4),
        primary_blocker=primary_blocker,
        primary_blocker_label=BLOCKER_LABELS[primary_blocker],
        primary_blocker_share=round(primary_blocker_share, 4),
        blocker_distribution=blocker_distribution,
        cluster_profiles=[
            ClusterChannelProfile(
                cluster_id=row["cluster_id"],
                cluster_name=row["cluster_name"],
                population_weight=row["population_weight"],
                online_preference=round(row["online_pref"], 4),
                distribution_accessibility_multiplier=round(row["access"], 4),
                delivery_speed_days_required=round(row["days"], 2),
                try_before_buy_requirement=round(row["try_before_buy"], 4),
                influencer_review_dependency=round(row["influencer"], 4),
                cashback_loyalty_sensitivity=round(row["cashback"], 4),
                platform_pref_amazon=round(row["amazon"], 4),
                platform_pref_flipkart=round(row["flipkart"], 4),
                platform_pref_brand_direct=round(row["brand_direct"], 4),
                platform_pref_offline=round(row["offline"], 4),
                channel_tier=row["tier"],
                primary_blocker=row["blocker"],
                primary_blocker_score=round(row["blocker_score"], 4),
            )
            for row in rows
        ],
        levers=levers,
        flags=flags,
        recommendations=recommendations,
        meta=meta,
    )


__all__ = [
    "BLOCKER_ORDER",
    "DISTRIBUTION_PRODUCT_TYPES",
    "build_distribution_channels",
]
