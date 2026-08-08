"""
Pure virality-growth analysis for completed simulation results.

Answers the founder's "will this product spread by word of mouth, and
which growth lever should I pull first?" question by turning the
``ViralityArchitect`` per-cluster metrics into a deterministic,
population-weighted growth read:

* **Viral coefficient** — population-weighted K over the covered market,
  alongside weighted organic referral trigger, invite completion,
  incentive response quality, word-of-mouth coefficient, content
  virality, community participation, and the network-effect threshold.
* **Cluster tiers** — every covered cluster is classified
  ``VIRAL`` (K >= 1.0) / ``PROMISING`` (K >= 0.5) / ``EMERGING``
  (K >= 0.25) / ``WEAK`` (K < 0.25).
* **Primary growth blocker** — each cluster is attributed to the weakest
  of the six modeled growth inputs (organic trigger, invite completion,
  incentive quality, word of mouth, content virality, community). The
  market-level blocker distribution is the population-weighted share of
  those attributions.
* **Growth levers** — six interventions (referral program, incentive
  design, shareable output, community building, word-of-mouth channels,
  organic triggers) ranked by the share of the covered market where the
  underlying metric is below a healthy threshold.

The verdict is ``VIRAL`` when weighted K is at least 1.0,
``MOMENTUM`` when weighted K is at least 0.5 or at least 25% of the
covered market is already VIRAL, ``LIMITED`` otherwise, and
``INSUFFICIENT_DATA`` for product types whose conductor stack does not
run ``ViralityArchitect`` (enterprise software, iot hardware, wearable,
b2b hardware, smart home, ...) or when no cluster has usable metrics.

No DB / I/O — verifiable without FastAPI or PostgreSQL. The route layer
supplies ``results``, ``conductor_results`` (per-cluster architect
metrics) and ``cluster_registry``; all arithmetic is deterministic.
Metrics missing from a malformed/partial payload use conservative
defaults (K 0.05, organic trigger 0.05, invite completion 0.30,
incentive quality 0.40, WOM coefficient 0.50, content virality 0.05,
community participation 0.10) so a missing field never manufactures a
viral loop, lever, or flag.
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable

from app.schemas.virality_growth import (
    BLOCKER_COMMUNITY,
    BLOCKER_CONTENT,
    BLOCKER_INCENTIVE,
    BLOCKER_INVITE,
    BLOCKER_TRIGGER,
    BLOCKER_WOM,
    LEVER_COMMUNITY,
    LEVER_INCENTIVES,
    LEVER_ORGANIC,
    LEVER_REFERRAL,
    LEVER_SHAREABLE,
    LEVER_WOM,
    TIER_EMERGING,
    TIER_PROMISING,
    TIER_VIRAL,
    TIER_WEAK,
    VERDICT_INSUFFICIENT,
    VERDICT_LIMITED,
    VERDICT_MOMENTUM,
    VERDICT_VIRAL,
    ClusterGrowthProfile,
    GrowthLever,
    ViralityGrowthOut,
)

# Product types whose conductor stack runs ViralityArchitect.
VIRALITY_PRODUCT_TYPES: frozenset[str] = frozenset(
    {
        "saas",
        "marketplace",
        "mobile_app",
        "developer_tool",
        "consumer_hardware",
        "health_hardware",
        "consumer_app",
        "d2c",
        "b2b_marketplace",
        "productivity_tool",
    }
)

# Ordered blocker keys — used for tie-breaking and market aggregation so
# the output is stable regardless of dict ordering.
BLOCKER_ORDER: tuple[str, ...] = (
    BLOCKER_TRIGGER,
    BLOCKER_INVITE,
    BLOCKER_INCENTIVE,
    BLOCKER_WOM,
    BLOCKER_CONTENT,
    BLOCKER_COMMUNITY,
)

BLOCKER_LABELS: dict[str, str] = {
    BLOCKER_TRIGGER: "Organic sharing trigger",
    BLOCKER_INVITE: "Invite completion",
    BLOCKER_INCENTIVE: "Referral incentive quality",
    BLOCKER_WOM: "Word-of-mouth coefficient",
    BLOCKER_CONTENT: "Content virality",
    BLOCKER_COMMUNITY: "Community participation",
}

# Cluster-tier thresholds (viral coefficient K).
TIER_VIRAL_K: float = 1.0
TIER_PROMISING_K: float = 0.5
TIER_EMERGING_K: float = 0.25

# Verdict thresholds (weighted market aggregates).
VERDICT_VIRAL_K: float = 1.0
VERDICT_MOMENTUM_K: float = 0.5
VERDICT_MOMENTUM_VIRAL_SHARE: float = 0.25

# Lever opportunity thresholds — a lever applies to a cluster when the
# underlying growth input is below this healthy level.
LEVER_INVITE_THRESHOLD: float = 0.50
LEVER_INCENTIVE_THRESHOLD: float = 0.40
LEVER_CONTENT_THRESHOLD: float = 0.10
LEVER_COMMUNITY_THRESHOLD: float = 0.20
LEVER_WOM_THRESHOLD: float = 1.00
LEVER_TRIGGER_THRESHOLD: float = 0.15

# Flag thresholds.
FLAG_INCENTIVE_THRESHOLD: float = 0.40
FLAG_TRIGGER_THRESHOLD: float = 0.15
FLAG_CONTENT_THRESHOLD: float = 0.10
FLAG_COMMUNITY_THRESHOLD: float = 0.20
FLAG_NETWORK_THRESHOLD: float = 250.0

# Conservative defaults for metrics missing from a malformed/partial
# payload. An unknown growth input is treated as weak so a missing field
# never manufactures a viral loop, lever, or flag.
DEFAULT_K: float = 0.05
DEFAULT_TRIGGER: float = 0.05
DEFAULT_INVITE: float = 0.30
DEFAULT_INCENTIVE: float = 0.40
DEFAULT_WOM: float = 0.50
DEFAULT_CONTENT: float = 0.05
DEFAULT_COMMUNITY: float = 0.10
DEFAULT_NETWORK_THRESHOLD: float = 100.0

LEVER_LABELS: dict[str, str] = {
    LEVER_REFERRAL: "Referral programme",
    LEVER_INCENTIVES: "Referral incentive design",
    LEVER_SHAREABLE: "Shareable output",
    LEVER_COMMUNITY: "Community building",
    LEVER_WOM: "Word-of-mouth channels",
    LEVER_ORGANIC: "Organic sharing triggers",
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


def _virality_metrics(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> dict[str, Any]:
    """Extract the ViralityArchitect metrics block for one cluster."""
    if not conductor_results:
        return {}
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return {}
    architect = cluster_block.get("ViralityArchitect")
    if not isinstance(architect, dict):
        return {}
    metrics = architect.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _blocker_gaps(metrics: dict[str, Any]) -> dict[str, float]:
    """Normalized growth-input gaps for one cluster (0..1, higher = worse)."""
    trigger = _clamp(
        _safe_float(
            metrics.get("organic_referral_trigger_score"),
            DEFAULT_TRIGGER,
        )
    )
    invite = _clamp(
        _safe_float(
            metrics.get("invite_completion_rate"),
            DEFAULT_INVITE,
        )
    )
    incentive = _clamp(
        _safe_float(
            metrics.get("referral_incentive_response_quality"),
            DEFAULT_INCENTIVE,
        )
    )
    wom = _clamp(
        _safe_float(
            metrics.get("word_of_mouth_coefficient"),
            DEFAULT_WOM,
        )
        / 2.0
    )
    content = _clamp(
        _safe_float(
            metrics.get("content_virality_rate"),
            DEFAULT_CONTENT,
        )
    )
    community = _clamp(
        _safe_float(
            metrics.get("community_building_participation"),
            DEFAULT_COMMUNITY,
        )
    )
    return {
        BLOCKER_TRIGGER: round(1.0 - trigger, 4),
        BLOCKER_INVITE: round(1.0 - invite, 4),
        BLOCKER_INCENTIVE: round(1.0 - incentive, 4),
        BLOCKER_WOM: round(1.0 - wom, 4),
        BLOCKER_CONTENT: round(1.0 - content, 4),
        BLOCKER_COMMUNITY: round(1.0 - community, 4),
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
    return best_key, round(best_value, 4)


def _growth_tier(k: float) -> str:
    if k >= TIER_VIRAL_K:
        return TIER_VIRAL
    if k >= TIER_PROMISING_K:
        return TIER_PROMISING
    if k >= TIER_EMERGING_K:
        return TIER_EMERGING
    return TIER_WEAK


def _weighted_average(rows: list[dict[str, Any]], key: str) -> float:
    total_weight = sum(
        max(0.0, row["population_weight"]) for row in rows
    )
    if total_weight <= 0.0:
        return 0.0
    return (
        sum(
            max(0.0, row["population_weight"]) * row[key]
            for row in rows
        )
        / total_weight
    )


def _opportunity_share(
    rows: list[dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool],
) -> float:
    total_weight = sum(max(0.0, row["population_weight"]) for row in rows)
    if total_weight <= 0.0:
        return 0.0
    matched = sum(
        max(0.0, row["population_weight"])
        for row in rows
        if predicate(row)
    )
    return matched / total_weight


def _lever(
    rows: list[dict[str, Any]],
    key: str,
    metric_key: str,
    predicate: Callable[[dict[str, Any]], bool],
    action: str,
) -> GrowthLever:
    share = _opportunity_share(rows, predicate)
    return GrowthLever(
        key=key,
        label=LEVER_LABELS[key],
        market_value=round(_weighted_average(rows, metric_key), 4),
        opportunity_share=round(share, 4),
        action=action.format(share=_fmt_pct(share)),
    )


def build_virality_growth(
    results: dict[str, Any] | None,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    conductor_results: dict[str, Any] | None = None,
    cluster_registry: list[dict[str, Any]] | None = None,
    product_type: str = "saas",
) -> ViralityGrowthOut:
    """Compose the virality-growth read from completed results.

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
        product_type or payload.get("product_type_detected", "saas") or "saas"
    ).lower()
    registry: list[dict[str, Any]] = cluster_registry or []
    supported = product_type_name in VIRALITY_PRODUCT_TYPES

    rows: list[dict[str, Any]] = []
    covered_weight = 0.0
    for entry in registry:
        cid = str(entry.get("cluster_id", ""))
        if not cid:
            continue
        weight = max(0.0, _safe_float(entry.get("population_weight")))
        metrics = _virality_metrics(conductor_results, cid)
        if not metrics:
            continue

        k = max(0.0, _safe_float(metrics.get("viral_coefficient"), DEFAULT_K))
        trigger = _clamp(
            _safe_float(
                metrics.get("organic_referral_trigger_score"),
                DEFAULT_TRIGGER,
            )
        )
        incentive = _clamp(
            _safe_float(
                metrics.get("referral_incentive_response_quality"),
                DEFAULT_INCENTIVE,
            )
        )
        wom = max(
            0.0,
            _safe_float(
                metrics.get("word_of_mouth_coefficient"),
                DEFAULT_WOM,
            ),
        )
        network_threshold = max(
            0.0,
            _safe_float(
                metrics.get("network_effect_threshold"),
                DEFAULT_NETWORK_THRESHOLD,
            ),
        )
        invite = _clamp(
            _safe_float(
                metrics.get("invite_completion_rate"),
                DEFAULT_INVITE,
            )
        )
        content = _clamp(
            _safe_float(
                metrics.get("content_virality_rate"),
                DEFAULT_CONTENT,
            )
        )
        community = _clamp(
            _safe_float(
                metrics.get("community_building_participation"),
                DEFAULT_COMMUNITY,
            )
        )

        blocker, blocker_score = _primary_blocker(_blocker_gaps(metrics))
        covered_weight += weight
        rows.append(
            {
                "cluster_id": cid,
                "cluster_name": str(entry.get("name", "") or cid),
                "population_weight": weight,
                "k": k,
                "trigger": trigger,
                "incentive": incentive,
                "wom": wom,
                "network_threshold": network_threshold,
                "invite": invite,
                "content": content,
                "community": community,
                "tier": _growth_tier(k),
                "blocker": blocker,
                "blocker_score": blocker_score,
            }
        )

    meta: dict[str, Any] = {
        "signal_quality": signal_quality,
        "total_clusters": len(registry),
        "covered_clusters": len(rows),
        "covered_weight": round(covered_weight, 4),
        "product_type_supported": supported,
        "thresholds": {
            "tier_viral_k": TIER_VIRAL_K,
            "tier_promising_k": TIER_PROMISING_K,
            "tier_emerging_k": TIER_EMERGING_K,
            "verdict_viral_k": VERDICT_VIRAL_K,
            "verdict_momentum_k": VERDICT_MOMENTUM_K,
            "verdict_momentum_viral_share": VERDICT_MOMENTUM_VIRAL_SHARE,
        },
    }

    if not supported:
        return ViralityGrowthOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                (
                    f"Word-of-mouth growth is not modeled for "
                    f"{product_type_name} — this read supports saas, "
                    "marketplace, mobile_app, developer_tool, "
                    "consumer_hardware, health_hardware, consumer_app, "
                    "d2c, b2b_marketplace and productivity_tool runs."
                )
            ],
            meta=meta,
        )
    if not rows or covered_weight <= 0.0:
        return ViralityGrowthOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                "No per-cluster ViralityArchitect metrics were available "
                "for this run."
            ],
            meta=meta,
        )

    k_avg = _weighted_average(rows, "k")
    trigger_avg = _weighted_average(rows, "trigger")
    invite_avg = _weighted_average(rows, "invite")
    incentive_avg = _weighted_average(rows, "incentive")
    wom_avg = _weighted_average(rows, "wom")
    content_avg = _weighted_average(rows, "content")
    community_avg = _weighted_average(rows, "community")
    network_avg = _weighted_average(rows, "network_threshold")

    viral_weight = sum(
        row["population_weight"] for row in rows if row["tier"] == TIER_VIRAL
    )
    momentum_plus_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] in (TIER_VIRAL, TIER_PROMISING)
    )
    viral_share = viral_weight / covered_weight
    momentum_share = momentum_plus_weight / covered_weight

    if k_avg >= VERDICT_VIRAL_K:
        verdict = VERDICT_VIRAL
    elif k_avg >= VERDICT_MOMENTUM_K or viral_share >= VERDICT_MOMENTUM_VIRAL_SHARE:
        verdict = VERDICT_MOMENTUM
    else:
        verdict = VERDICT_LIMITED

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
    if any(row["tier"] == TIER_VIRAL for row in rows):
        flags.append("viral_loop_possible")
    if incentive_avg < FLAG_INCENTIVE_THRESHOLD:
        flags.append("incentive_quality_risk")
    if trigger_avg < FLAG_TRIGGER_THRESHOLD:
        flags.append("low_organic_trigger")
    if content_avg < FLAG_CONTENT_THRESHOLD:
        flags.append("content_gap")
    if community_avg < FLAG_COMMUNITY_THRESHOLD:
        flags.append("community_gap")
    if network_avg > FLAG_NETWORK_THRESHOLD:
        flags.append("network_effect_threshold_high")

    levers: list[GrowthLever] = [
        _lever(
            rows,
            LEVER_REFERRAL,
            "invite",
            lambda row: row["invite"] < LEVER_INVITE_THRESHOLD,
            "Add a referral or invite flow for {share} of the covered market.",
        ),
        _lever(
            rows,
            LEVER_INCENTIVES,
            "incentive",
            lambda row: row["incentive"] < LEVER_INCENTIVE_THRESHOLD,
            "Redesign referral incentives — {share} have weak incentive response.",
        ),
        _lever(
            rows,
            LEVER_SHAREABLE,
            "content",
            lambda row: row["content"] < LEVER_CONTENT_THRESHOLD,
            "Create shareable outputs for {share} of the covered market.",
        ),
        _lever(
            rows,
            LEVER_COMMUNITY,
            "community",
            lambda row: row["community"] < LEVER_COMMUNITY_THRESHOLD,
            "Invest in community-building for {share} of the covered market.",
        ),
        _lever(
            rows,
            LEVER_WOM,
            "wom",
            lambda row: row["wom"] < LEVER_WOM_THRESHOLD,
            "Launch word-of-mouth and advocacy channels for {share}.",
        ),
        _lever(
            rows,
            LEVER_ORGANIC,
            "trigger",
            lambda row: row["trigger"] < LEVER_TRIGGER_THRESHOLD,
            "Build organic sharing triggers for {share} of the covered market.",
        ),
    ]
    levers.sort(key=lambda lever: (-lever.opportunity_share, lever.key))

    recommendations: list[str] = []
    if verdict == VERDICT_VIRAL:
        recommendations.append(
            f"Market-wide viral loop is in reach (weighted K = {k_avg:.2f}) — "
            "double down on the referral funnel before retention decay "
            "flattens the loop."
        )
    elif verdict == VERDICT_MOMENTUM:
        recommendations.append(
            f"Growth has momentum (weighted K = {k_avg:.2f}, "
            f"{_fmt_pct(viral_share)} already VIRAL) — push the strongest "
            "lever to cross K >= 1.0 market-wide."
        )
    else:
        recommendations.append(
            f"Word-of-mouth growth is limited (weighted K = {k_avg:.2f}) — "
            "plan paid acquisition until a viral loop is built."
        )
    recommendations.append(
        f"Primary growth blocker: {BLOCKER_LABELS[primary_blocker]} "
        f"(affects {_fmt_pct(primary_blocker_share)} of the covered market)."
    )
    if any(row["tier"] == TIER_VIRAL for row in rows):
        viral_clusters = [
            row["cluster_name"] for row in rows if row["tier"] == TIER_VIRAL
        ]
        recommendations.append(
            f"{len(viral_clusters)} cluster(s) already reach K >= 1.0 — "
            "study those segments for repeatable growth patterns."
        )
    if incentive_avg < FLAG_INCENTIVE_THRESHOLD:
        recommendations.append(
            f"Referral incentive response is only {_fmt_pct(incentive_avg)} — "
            "test reward quality and timing before scaling invites."
        )
    if trigger_avg < FLAG_TRIGGER_THRESHOLD:
        recommendations.append(
            f"Organic sharing triggers are {_fmt_pct(trigger_avg)} — add "
            "in-product moments that give users a reason to share."
        )
    if content_avg < FLAG_CONTENT_THRESHOLD:
        recommendations.append(
            f"Content virality is {_fmt_pct(content_avg)} — build shareable "
            "outputs (reports, previews, badges) users want to post."
        )
    if community_avg < FLAG_COMMUNITY_THRESHOLD:
        recommendations.append(
            f"Community participation is {_fmt_pct(community_avg)} — seed "
            "user groups or forums around early adopters."
        )
    if network_avg > FLAG_NETWORK_THRESHOLD:
        recommendations.append(
            f"The network-effect threshold is {network_avg:.0f} users per "
            "side — growth may stall until each side reaches critical mass."
        )

    return ViralityGrowthOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type_name,
        verdict=verdict,
        weighted_viral_coefficient=round(k_avg, 4),
        weighted_organic_trigger=round(trigger_avg, 4),
        weighted_invite_completion=round(invite_avg, 4),
        weighted_incentive_quality=round(incentive_avg, 4),
        weighted_wom_coefficient=round(wom_avg, 4),
        weighted_content_virality=round(content_avg, 4),
        weighted_community_participation=round(community_avg, 4),
        weighted_network_effect_threshold=round(network_avg, 2),
        viral_share=round(viral_share, 4),
        momentum_share=round(momentum_share, 4),
        primary_blocker=primary_blocker,
        primary_blocker_label=BLOCKER_LABELS[primary_blocker],
        primary_blocker_share=round(primary_blocker_share, 4),
        blocker_distribution=blocker_distribution,
        cluster_profiles=[
            ClusterGrowthProfile(
                cluster_id=row["cluster_id"],
                cluster_name=row["cluster_name"],
                population_weight=row["population_weight"],
                viral_coefficient=round(row["k"], 4),
                organic_referral_trigger_score=round(row["trigger"], 4),
                referral_incentive_response_quality=round(row["incentive"], 4),
                word_of_mouth_coefficient=round(row["wom"], 4),
                network_effect_threshold=round(row["network_threshold"], 2),
                invite_completion_rate=round(row["invite"], 4),
                content_virality_rate=round(row["content"], 4),
                community_building_participation=round(row["community"], 4),
                growth_tier=row["tier"],
                primary_blocker=row["blocker"],
                primary_blocker_score=row["blocker_score"],
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
    "VIRALITY_PRODUCT_TYPES",
    "build_virality_growth",
]
