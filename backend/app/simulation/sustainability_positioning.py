"""
Pure sustainability-positioning analysis for completed simulation results.

Turns ``SustainabilityArchitect`` per-cluster metrics into a founder-facing
ESG read:

* **Positioned** — whether the brief makes sustainability / ethical-sourcing
  claims that move the conversion model at all.
* **Evidence-backed** — whether those claims carry third-party evidence
  markers (certified, audited, LCA, verified, ...).
* **Response share** — the population-weighted share of the covered market
  whose ``sustainability_signal`` is non-zero.
* **Weighted lift** — population-weighted ``conversion_lift`` over the
  responding clusters.
* **Per-cluster tiers** — ``HIGH_RESPONSE`` / ``MODERATE_RESPONSE`` /
  ``LOW_RESPONSE`` / ``NO_SIGNAL`` based on conversion lift.
* **Flags and recommendations** — market-level greenwashing risk,
  premium-friction concentration, narrow reach and weak affinity signals.

The builder is deterministic and does no DB / I/O; the route layer supplies
``results``, ``conductor_results`` (per-cluster architect metrics) and
``cluster_registry``.
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable

from app.schemas.sustainability_positioning import (
    TIER_HIGH,
    TIER_LOW,
    TIER_MODERATE,
    TIER_NO_SIGNAL,
    VERDICT_INSUFFICIENT,
    VERDICT_MODERATE,
    VERDICT_NOT_POSITIONED,
    VERDICT_STRONG,
    VERDICT_WEAK,
    ClusterSustainabilityProfile,
    SustainabilityOpportunity,
    SustainabilityPositioningOut,
)

ARCHITECT: str = "SustainabilityArchitect"

# Cluster-tier thresholds on conversion_lift (architect maxes at 0.30).
TIER_HIGH_LIFT: float = 0.15
TIER_MODERATE_LIFT: float = 0.05

# Verdict thresholds on the population-weighted market.
VERDICT_STRONG_SHARE: float = 0.50
VERDICT_STRONG_LIFT: float = 0.10
VERDICT_MODERATE_SHARE: float = 0.25
VERDICT_MODERATE_LIFT: float = 0.05

# Market-level flag thresholds.
CONCENTRATION_THRESHOLD: float = 0.50
STRONG_AFFINITY_THRESHOLD: float = 0.50

# Neutral defaults for malformed / partial metrics. The architect always
# runs for every product type, so an absent metrics block is treated as a
# no-signal cluster rather than as a manufactured strong response.
DEFAULT_ESG_AFFINITY: float = 0.50
DEFAULT_GREEN_PREMIUM_TOLERANCE: float = 0.50


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
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


def _clamp(value: float, *, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _architect_block(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not conductor_results:
        return {}, {}
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return {}, {}
    block = cluster_block.get(ARCHITECT)
    if not isinstance(block, dict):
        return {}, {}
    metrics = block.get("metrics")
    flags = block.get("flags")
    return (
        metrics if isinstance(metrics, dict) else {},
        flags if isinstance(flags, dict) else {},
    )


def _tier_for_lift(lift: float) -> str:
    if lift >= TIER_HIGH_LIFT:
        return TIER_HIGH
    if lift >= TIER_MODERATE_LIFT:
        return TIER_MODERATE
    if lift > 0.0:
        return TIER_LOW
    return TIER_NO_SIGNAL


def _active_flags(flags: dict[str, Any]) -> list[str]:
    return [name for name, value in flags.items() if value is True]


def _weighted_average(
    rows: list[dict[str, Any]],
    key: str,
    *,
    positioned_only: bool = False,
) -> float:
    total_weight = 0.0
    acc = 0.0
    for row in rows:
        if positioned_only and row["sustainability_signal"] <= 0.0:
            continue
        weight = max(0.0, row["population_weight"])
        if weight <= 0.0:
            continue
        acc += weight * row[key]
        total_weight += weight
    if total_weight <= 0.0:
        return 0.0
    return acc / total_weight


def _share(
    rows: list[dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool],
) -> float:
    total_weight = 0.0
    flagged_weight = 0.0
    for row in rows:
        weight = max(0.0, row["population_weight"])
        if weight <= 0.0:
            continue
        total_weight += weight
        if predicate(row):
            flagged_weight += weight
    if total_weight <= 0.0:
        return 0.0
    return flagged_weight / total_weight


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out


def build_sustainability_positioning(
    results: dict[str, Any] | None,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    conductor_results: dict[str, Any] | None = None,
    cluster_registry: list[dict[str, Any]] | None = None,
    product_type: str = "saas",
) -> SustainabilityPositioningOut:
    """Compose the sustainability-positioning read from completed results.

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
    # Harden persisted signal quality: malformed legacy rows can contain
    # NaN/Inf or out-of-range values which would otherwise poison JSON
    # serialization in the response's meta dict.
    signal_quality_safe: float | None = _safe_float(
        signal_quality, default=None
    )
    if signal_quality_safe is not None:
        signal_quality_safe = round(_clamp(signal_quality_safe), 4)
    product_type_name = str(
        product_type or payload.get("product_type_detected", "saas") or "saas"
    ).lower()
    registry: list[dict[str, Any]] = cluster_registry or []

    rows: list[dict[str, Any]] = []
    covered_weight = 0.0
    for entry in registry:
        cid = str(entry.get("cluster_id", ""))
        if not cid:
            continue
        weight = max(0.0, _safe_float(entry.get("population_weight")))
        if weight <= 0.0:
            continue

        metrics, raw_flags = _architect_block(conductor_results, cid)
        signal = _clamp(_safe_float(metrics.get("sustainability_signal")))
        affinity = _clamp(
            _safe_float(metrics.get("esg_affinity"), DEFAULT_ESG_AFFINITY)
        )
        premium_tolerance = _clamp(
            _safe_float(
                metrics.get("green_premium_tolerance"),
                DEFAULT_GREEN_PREMIUM_TOLERANCE,
            )
        )
        lift = _clamp(_safe_float(metrics.get("conversion_lift")))
        premium_friction = _clamp(
            _safe_float(metrics.get("premium_friction"))
        )
        credibility = _clamp(_safe_float(metrics.get("claim_credibility")))
        flags = _active_flags(raw_flags)

        covered_weight += weight
        rows.append(
            {
                "cluster_id": cid,
                "cluster_name": str(entry.get("name", "") or cid),
                "population_weight": weight,
                "sustainability_signal": signal,
                "esg_affinity": affinity,
                "green_premium_tolerance": premium_tolerance,
                "conversion_lift": lift,
                "premium_friction": premium_friction,
                "claim_credibility": credibility,
                "tier": _tier_for_lift(lift),
                "flags": flags,
            }
        )

    meta: dict[str, Any] = {
        "signal_quality": signal_quality_safe,
        "total_clusters": len(registry),
        "covered_clusters": len(rows),
        "covered_weight": round(covered_weight, 4),
        "product_type_supported": True,
        "positioned_weight": 0.0,
        "greenwash_share": 0.0,
        "premium_friction_share": 0.0,
        "low_reach_share": 0.0,
        "strong_affinity_share": 0.0,
        "thresholds": {
            "tier_high_lift": TIER_HIGH_LIFT,
            "tier_moderate_lift": TIER_MODERATE_LIFT,
            "verdict_strong_share": VERDICT_STRONG_SHARE,
            "verdict_strong_lift": VERDICT_STRONG_LIFT,
            "verdict_moderate_share": VERDICT_MODERATE_SHARE,
            "verdict_moderate_lift": VERDICT_MODERATE_LIFT,
            "concentration_threshold": CONCENTRATION_THRESHOLD,
            "strong_affinity_threshold": STRONG_AFFINITY_THRESHOLD,
        },
    }

    if not rows or covered_weight <= 0.0:
        return SustainabilityPositioningOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                "No per-cluster SustainabilityArchitect metrics were "
                "available for this run."
            ],
            meta=meta,
        )

    positioned_rows = [
        row for row in rows if row["sustainability_signal"] > 0.0
    ]
    positioned_weight = sum(
        row["population_weight"] for row in positioned_rows
    )
    meta["positioned_weight"] = round(positioned_weight, 4)
    positioned = bool(positioned_rows)

    if not positioned:
        return SustainabilityPositioningOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_NOT_POSITIONED,
            positioned=False,
            weighted_esg_affinity=round(
                _weighted_average(rows, "esg_affinity"), 4
            ),
            weighted_green_premium_tolerance=round(
                _weighted_average(rows, "green_premium_tolerance"), 4
            ),
            response_share=0.0,
            cluster_profiles=[
                ClusterSustainabilityProfile(**row) for row in rows
            ],
            recommendations=[
                "No sustainability claims detected in assumptions — add "
                "evidence-backed environmental or ethical-sourcing claims "
                "if the target audience cares about them."
            ],
            meta=meta,
        )

    evidence_backed = any(
        row["claim_credibility"] >= 0.999 for row in positioned_rows
    )
    weighted_affinity = _weighted_average(rows, "esg_affinity")
    weighted_lift = _weighted_average(
        positioned_rows, "conversion_lift", positioned_only=True
    )
    weighted_premium_tolerance = _weighted_average(
        rows, "green_premium_tolerance"
    )
    weighted_premium_friction = _weighted_average(
        positioned_rows, "premium_friction", positioned_only=True
    )
    claim_credibility = _weighted_average(
        positioned_rows, "claim_credibility", positioned_only=True
    )
    response_share = positioned_weight / covered_weight

    greenwash_share = _share(
        rows, lambda row: "greenwashing_risk" in row["flags"]
    )
    premium_friction_share = _share(
        rows, lambda row: "premium_friction" in row["flags"]
    )
    low_reach_share = _share(
        rows, lambda row: "low_esg_reach" in row["flags"]
    )
    strong_share = _share(
        rows, lambda row: "strong_esg_affinity" in row["flags"]
    )
    meta["greenwash_share"] = round(greenwash_share, 4)
    meta["premium_friction_share"] = round(premium_friction_share, 4)
    meta["low_reach_share"] = round(low_reach_share, 4)
    meta["strong_affinity_share"] = round(strong_share, 4)

    if (
        response_share >= VERDICT_STRONG_SHARE
        and weighted_lift >= VERDICT_STRONG_LIFT
        and evidence_backed
        and greenwash_share < CONCENTRATION_THRESHOLD
    ):
        verdict = VERDICT_STRONG
    elif (
        response_share >= VERDICT_MODERATE_SHARE
        or weighted_lift >= VERDICT_MODERATE_LIFT
    ):
        verdict = VERDICT_MODERATE
    else:
        verdict = VERDICT_WEAK

    flags: list[str] = ["positioned"]
    if evidence_backed:
        flags.append("evidence_backed")
    if greenwash_share >= CONCENTRATION_THRESHOLD:
        flags.append("greenwashing_risk_concentration")
    if premium_friction_share >= CONCENTRATION_THRESHOLD:
        flags.append("premium_friction_concentration")
    if low_reach_share >= CONCENTRATION_THRESHOLD:
        flags.append("low_reach_concentration")
    if strong_share >= STRONG_AFFINITY_THRESHOLD:
        flags.append("strong_market_affinity")
    if response_share < VERDICT_MODERATE_SHARE:
        flags.append("narrow_esg_reach")

    recommendations: list[str] = []
    if not evidence_backed:
        recommendations.append(
            "Back sustainability claims with third-party evidence "
            "(certified, audited, LCA, verified sourcing) before using "
            "them as a premium differentiator."
        )
    if greenwash_share >= CONCENTRATION_THRESHOLD:
        recommendations.append(
            "Greenwashing risk is concentrated across the covered market "
            "— replace vague claims with certified impact proof before "
            "charging an ESG premium."
        )
    if premium_friction_share >= CONCENTRATION_THRESHOLD:
        recommendations.append(
            "Price-sensitive clusters face premium friction — add a value "
            "tier or absorb sustainability costs into the base price."
        )
    if low_reach_share >= CONCENTRATION_THRESHOLD:
        recommendations.append(
            "ESG affinity is weak in the covered market — pair claims "
            "with education and visible impact metrics instead of premium "
            "positioning."
        )
    if verdict == VERDICT_WEAK:
        recommendations.append(
            "ESG claims currently move only a small share of the covered "
            "market — either strengthen evidence and breadth or deprioritize "
            "sustainability as a primary hook."
        )
    if verdict == VERDICT_STRONG:
        recommendations.append(
            "ESG positioning is credible and matched to market affinity — "
            "keep claims evidence-backed and track impact metrics as proof."
        )
    if not recommendations:
        recommendations.append(
            "ESG positioning has moderate reach — lead with the responding "
            "clusters and validate willingness-to-pay before scaling spend."
        )
    recommendations = _dedupe(recommendations)

    opportunities = sorted(
        positioned_rows,
        key=lambda row: (
            row["population_weight"] * row["conversion_lift"],
            -row["esg_affinity"],
            row["cluster_id"],
        ),
        reverse=True,
    )[:5]

    return SustainabilityPositioningOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type_name,
        verdict=verdict,
        positioned=True,
        evidence_backed=evidence_backed,
        claim_credibility=round(claim_credibility, 4),
        weighted_esg_affinity=round(weighted_affinity, 4),
        weighted_conversion_lift=round(weighted_lift, 4),
        weighted_green_premium_tolerance=round(
            weighted_premium_tolerance, 4
        ),
        weighted_premium_friction=round(weighted_premium_friction, 4),
        response_share=round(response_share, 4),
        cluster_profiles=[
            ClusterSustainabilityProfile(**row) for row in rows
        ],
        top_opportunities=[
            SustainabilityOpportunity(
                cluster_id=row["cluster_id"],
                cluster_name=row["cluster_name"],
                population_weight=round(row["population_weight"], 4),
                conversion_lift=row["conversion_lift"],
                esg_affinity=row["esg_affinity"],
                tier=row["tier"],
                reason=(
                    f"Population-weighted conversion lift of "
                    f"{row['conversion_lift'] * 100:.2f}pp."
                ),
            )
            for row in opportunities
        ],
        flags=flags,
        recommendations=recommendations,
        meta=meta,
    )


__all__ = [
    "ARCHITECT",
    "CONCENTRATION_THRESHOLD",
    "DEFAULT_ESG_AFFINITY",
    "DEFAULT_GREEN_PREMIUM_TOLERANCE",
    "STRONG_AFFINITY_THRESHOLD",
    "TIER_HIGH_LIFT",
    "TIER_MODERATE_LIFT",
    "VERDICT_MODERATE_LIFT",
    "VERDICT_MODERATE_SHARE",
    "VERDICT_STRONG_LIFT",
    "VERDICT_STRONG_SHARE",
    "build_sustainability_positioning",
]
