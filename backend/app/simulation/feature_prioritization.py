"""
Pure feature-prioritization analysis for completed simulation results.

Answers the founder's "which features should I build or polish first?"
question by turning the ``FeatureAdoptionArchitect`` per-cluster metrics
into a deterministic, demand-weighted prioritization:

* **Adoption rate** — population-weighted adoption of each modeled feature
  dimension. Feature abandonment is *not* a buildable feature: it feeds the
  cluster profiles and the ``high_abandonment`` risk flag instead.
* **Reach weight** — fraction of the covered market (by cluster weight)
  that produced usable metrics for the dimension.
* **Upside** — the unserved share of the covered market
  (``1 - adoption``) x reach.
* **Priority score** — ``adoption^2 x upside x strategic weight``. The
  squared adoption term weights validated demand over raw headroom, so the
  curve peaks at ~67% adoption: dimensions with strong adoption *and*
  remaining upside outrank both near-saturated and barely-adopted ones.
  Product-type boosts nudge developer-tool and enterprise runs toward
  API / integration / collaboration dimensions.

Tiers: ``BUILD_FIRST`` (score >= 0.09), ``GROW`` (>= 0.045), ``WATCH``
(>= 0.02), ``DEPRIORITIZE`` otherwise.

The verdict is ``FOCUSED`` when any critical adoption risk is present
(shallow feature depth, high abandonment, blocked collaboration),
``READY`` when adoption is healthy, and ``INSUFFICIENT_DATA`` for product
types whose conductor stack does not include ``FeatureAdoptionArchitect``
(hardware, marketplace, d2c, ...) or when no cluster has usable metrics.

No DB / I/O — verifiable without FastAPI or PostgreSQL. The route layer
supplies ``results``, ``conductor_results`` (per-cluster architect
metrics), ``cluster_registry`` and the founder's brief features; all
arithmetic is deterministic.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

from app.schemas.feature_prioritization import (
    BriefFeatureScore,
    ClusterFeatureProfile,
    FeatureDimension,
    FeaturePrioritizationOut,
    SEGMENT_ADVANCED,
    SEGMENT_LAGGING,
    SEGMENT_MAINSTREAM,
    TIER_BUILD_FIRST,
    TIER_DEPRIORITIZE,
    TIER_GROW,
    TIER_UNMAPPED,
    TIER_WATCH,
    VERDICT_FOCUSED,
    VERDICT_INSUFFICIENT,
    VERDICT_READY,
)

# Product types whose conductor stack runs FeatureAdoptionArchitect.
FEATURE_PRODUCT_TYPES: frozenset[str] = frozenset(
    {"saas", "developer_tool", "enterprise_software", "mobile_app"}
)

# (metric key, founder-facing label) for the modeled feature dimensions.
# Feature abandonment is intentionally excluded — it is a risk signal, not
# a buildable feature, so it feeds cluster profiles and flags only.
DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("core_feature_dau_rate", "Core feature daily usage"),
    ("power_feature_discovery_rate", "Power feature discovery"),
    ("feature_depth_score", "Feature depth"),
    ("collaboration_adoption_rate", "Collaboration"),
    ("integration_adoption_rate", "Integrations"),
    ("advanced_settings_exploration", "Advanced settings"),
    ("api_adoption_rate", "API / developer usage"),
    ("export_reporting_usage", "Export & reporting"),
    ("dashboard_customisation_rate", "Dashboard customisation"),
)

_DIMENSION_LABELS: dict[str, str] = dict(DIMENSIONS)

# Product-type strategic nudges applied to the priority score. Small,
# documented, deterministic — they stop near-saturated or niche
# dimensions from crowding out the ones that matter for each category.
PRODUCT_STRATEGIC_BOOSTS: dict[str, dict[str, float]] = {
    "developer_tool": {
        "api_adoption_rate": 1.5,
        "integration_adoption_rate": 1.2,
    },
    "enterprise_software": {
        "integration_adoption_rate": 1.3,
        "collaboration_adoption_rate": 1.2,
        "api_adoption_rate": 1.2,
    },
    "saas": {
        "collaboration_adoption_rate": 1.1,
    },
    "mobile_app": {
        "core_feature_dau_rate": 1.2,
    },
}

# Priority-score tier thresholds.
TIER_BUILD_FIRST_THRESHOLD: float = 0.09
TIER_GROW_THRESHOLD: float = 0.045
TIER_WATCH_THRESHOLD: float = 0.02

# Risk thresholds (weighted market aggregates).
SHALLOW_DEPTH_THRESHOLD: float = 0.25
SHALLOW_DEPTH_SHARE_THRESHOLD: float = 0.15
HIGH_ABANDONMENT_THRESHOLD: float = 0.30
COLLABORATION_BLOCKED_THRESHOLD: float = 0.10
NO_API_INTEREST_THRESHOLD: float = 0.05
POWER_DISCOVERY_GAP_THRESHOLD: float = 0.20

# Cluster segment tiers by feature depth.
ADVANCED_DEPTH_THRESHOLD: float = 0.60
MAINSTREAM_DEPTH_THRESHOLD: float = 0.35

# Ordered keyword maps from a founder's declared brief feature to the
# modeled dimension with the strongest semantic match. First match wins.
# ``exact`` keywords match on word boundaries (so "click" never matches
# "cli"); ``stems`` match as plain substrings for inflected words.
BRIEF_FEATURE_KEYWORDS: tuple[
    tuple[str, tuple[str, ...], tuple[str, ...]],
    ...,
] = (
    (
        "integration_adoption_rate",
        ("slack", "zapier", "plugin", "embed", "sync"),
        ("integrat", "connect", "third-party", "third party", "webhook"),
    ),
    (
        "api_adoption_rate",
        ("api", "sdk", "cli"),
        ("developer", "headless", "automation"),
    ),
    (
        "dashboard_customisation_rate",
        ("dashboard", "widget", "theme", "layout"),
        ("analytics", "custom"),
    ),
    (
        "export_reporting_usage",
        ("export", "report", "csv"),
        ("billing", "invoice"),
    ),
    (
        "collaboration_adoption_rate",
        ("team", "share", "role", "workspace"),
        ("collab", "multi-user", "multi user", "comment", "permission"),
    ),
    (
        "advanced_settings_exploration",
        ("settings",),
        ("config", "preference", "advanced"),
    ),
    (
        "power_feature_discovery_rate",
        ("power", "pro"),
        ("shortcut", "workflow", "pipeline"),
    ),
    (
        "core_feature_dau_rate",
        ("core", "main", "basic", "daily", "quick"),
        ("essential",),
    ),
    (
        "feature_depth_score",
        (),
        ("depth", "deep", "robust", "complete"),
    ),
)


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


def _feature_metrics(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> dict[str, Any]:
    """Extract the FeatureAdoptionArchitect metrics block for one cluster."""
    if not conductor_results:
        return {}
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return {}
    architect = cluster_block.get("FeatureAdoptionArchitect")
    if not isinstance(architect, dict):
        return {}
    metrics = architect.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _adoption_value(metrics: dict[str, Any], key: str) -> float:
    """Clamp a metric to 0..1, inverting abandonment into retention."""
    raw = _safe_float(metrics.get(key))
    value = max(0.0, min(1.0, raw))
    if key == "feature_abandonment_rate":
        return round(1.0 - value, 4)
    return round(value, 4)


def _fmt_pct(value: float) -> str:
    return f"{max(0.0, min(1.0, value)) * 100:.0f}%"


def _priority_tier(score: float) -> str:
    if score >= TIER_BUILD_FIRST_THRESHOLD:
        return TIER_BUILD_FIRST
    if score >= TIER_GROW_THRESHOLD:
        return TIER_GROW
    if score >= TIER_WATCH_THRESHOLD:
        return TIER_WATCH
    return TIER_DEPRIORITIZE


def _dimension_recommendation(
    key: str,
    label: str,
    adoption: float,
    upside: float,
    reach: float,
    tier: str,
) -> str:
    if tier == TIER_BUILD_FIRST:
        return (
            f"Invest next in {label}: {_fmt_pct(adoption)} adoption leaves "
            f"{_fmt_pct(upside)} of the covered market unserved "
            f"(reach {_fmt_pct(reach)})."
        )
    if tier == TIER_GROW:
        return (
            f"Grow {label}: {_fmt_pct(adoption)} adoption with real headroom — "
            "improve activation before scaling acquisition."
        )
    if tier == TIER_WATCH:
        return (
            f"Keep {label} on watch ({_fmt_pct(adoption)} adoption) — revisit "
            "once the core loop is healthy."
        )
    return (
        f"Deprioritize {label} for now: {_fmt_pct(adoption)} adoption and "
        "limited validated upside."
    )


def _segment_tier(feature_depth: float) -> str:
    if feature_depth >= ADVANCED_DEPTH_THRESHOLD:
        return SEGMENT_ADVANCED
    if feature_depth >= MAINSTREAM_DEPTH_THRESHOLD:
        return SEGMENT_MAINSTREAM
    return SEGMENT_LAGGING


def _match_brief_feature(feature: str) -> str | None:
    lowered = feature.lower()
    for dimension_key, exact, stems in BRIEF_FEATURE_KEYWORDS:
        if any(re.search(rf"\b{re.escape(keyword)}\b", lowered) for keyword in exact):
            return dimension_key
        if any(keyword in lowered for keyword in stems):
            return dimension_key
    return None


def _coerce_brief_features(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return []
    else:
        parsed = value
    if not isinstance(parsed, list):
        return []
    return [
        str(item).strip()
        for item in parsed
        if str(item).strip()
    ][:5]


def build_feature_prioritization(
    results: dict[str, Any] | None,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    conductor_results: dict[str, Any] | None = None,
    cluster_registry: list[dict[str, Any]] | None = None,
    product_type: str = "saas",
    brief_features: list[str] | None = None,
) -> FeaturePrioritizationOut:
    """Compose the feature-prioritization read from completed results.

    Args:
        results: Simulation ``results_json`` (used for context only — the
            per-cluster architect metrics come from ``conductor_results``).
        simulation_id: Simulation primary key (echoed back).
        project_id: Owning project primary key (echoed back).
        status: Simulation status string.
        signal_quality: Persisted signal quality (0..1), if any (echoed
            into ``meta.signal_quality`` so founders can weigh the read).
        conductor_results: Per-cluster architect output blocks
            (``{cluster_id: {architect: {"metrics": ..., "flags": ...}}}``).
        cluster_registry: List of ``{cluster_id, name, population_weight}``.
        product_type: Detected product type for the run.
        brief_features: Founder-declared feature list (informational, mapped
            onto the modeled dimensions by keyword).
    """
    payload = _coerce_results(results)
    product_type_name = str(product_type or payload.get("product_type_detected", "saas") or "saas").lower()

    registry: list[dict[str, Any]] = cluster_registry or []
    total_weight = 0.0
    for entry in registry:
        total_weight += max(0.0, _safe_float(entry.get("population_weight")))

    # Per-cluster metric rows keyed by dimension metric key.
    dimension_metrics: dict[str, list[dict[str, Any]]] = {
        key: [] for key, _ in DIMENSIONS
    }
    cluster_rows: list[dict[str, Any]] = []
    covered_weight = 0.0

    for entry in registry:
        cid = str(entry.get("cluster_id", ""))
        if not cid:
            continue
        weight = max(0.0, _safe_float(entry.get("population_weight")))
        metrics = _feature_metrics(conductor_results, cid)
        if not metrics:
            continue
        covered_weight += weight
        for key, _ in DIMENSIONS:
            dimension_metrics[key].append(
                {"weight": weight, "value": _adoption_value(metrics, key)}
            )
        feature_depth = _adoption_value(metrics, "feature_depth_score")
        cluster_rows.append(
            {
                "cluster_id": cid,
                "cluster_name": str(entry.get("name", "") or cid),
                "population_weight": weight,
                "feature_depth": feature_depth,
                "core_dau_rate": _adoption_value(metrics, "core_feature_dau_rate"),
                "power_discovery_rate": _adoption_value(
                    metrics, "power_feature_discovery_rate"
                ),
                "abandonment_rate": round(
                    max(
                        0.0,
                        min(
                            1.0,
                            _safe_float(metrics.get("feature_abandonment_rate")),
                        ),
                    ),
                    4,
                ),
            }
        )

    supported = product_type_name in FEATURE_PRODUCT_TYPES
    if not supported or covered_weight <= 0.0 or not cluster_rows:
        return FeaturePrioritizationOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                (
                    f"Feature adoption is not modeled for {product_type_name} "
                    "— this read supports saas, developer_tool, "
                    "enterprise_software and mobile_app runs."
                    if supported
                    else (
                        "No per-cluster FeatureAdoptionArchitect metrics were "
                        "available for this run."
                    )
                )
            ],
            meta={
                "signal_quality": signal_quality,
                "total_clusters": len(registry),
                "covered_clusters": len(cluster_rows),
                "covered_weight": round(covered_weight, 4),
                "product_type_supported": supported,
            },
        )

    strategic = PRODUCT_STRATEGIC_BOOSTS.get(product_type_name, {})
    dimensions: list[FeatureDimension] = []
    for key, label in DIMENSIONS:
        rows = dimension_metrics[key]
        rows_weight = sum(row["weight"] for row in rows)
        if rows_weight <= 0.0:
            continue
        adoption = sum(row["weight"] * row["value"] for row in rows) / rows_weight
        reach = rows_weight / total_weight if total_weight > 0.0 else 0.0
        upside = max(0.0, min(1.0, 1.0 - adoption)) * reach
        strategic_weight = float(strategic.get(key, 1.0))
        priority_score = adoption * adoption * upside * strategic_weight
        tier = _priority_tier(priority_score)
        dimensions.append(
            FeatureDimension(
                key=key,
                label=label,
                adoption_rate=round(adoption, 4),
                reach_weight=round(reach, 4),
                upside=round(upside, 4),
                priority_score=round(priority_score, 4),
                priority_tier=tier,
                recommendation=_dimension_recommendation(
                    key, label, adoption, upside, reach, tier
                ),
            )
        )

    dimensions.sort(key=lambda d: d.priority_score, reverse=True)

    # Weighted risk aggregates for flags.
    def _weighted(key: str) -> float:
        rows = dimension_metrics[key]
        rows_weight = sum(row["weight"] for row in rows)
        if rows_weight <= 0.0:
            return 0.0
        return sum(row["weight"] * row["value"] for row in rows) / rows_weight

    depth_weighted = _weighted("feature_depth_score")
    discovery_weighted = _weighted("power_feature_discovery_rate")
    abandonment_rows_weight = sum(
        row["population_weight"] for row in cluster_rows
    )
    abandonment_weighted = (
        sum(
            row["population_weight"] * row["abandonment_rate"]
            for row in cluster_rows
        )
        / abandonment_rows_weight
        if abandonment_rows_weight > 0.0
        else 0.0
    )
    collab_weighted = _weighted("collaboration_adoption_rate")
    api_weighted = _weighted("api_adoption_rate")

    shallow_rows = [
        row
        for row in cluster_rows
        if row["feature_depth"] < SHALLOW_DEPTH_THRESHOLD
    ]
    shallow_weight = sum(row["population_weight"] for row in shallow_rows)
    shallow_share = (
        shallow_weight / covered_weight if covered_weight > 0.0 else 0.0
    )

    flags: list[str] = []
    if shallow_share > SHALLOW_DEPTH_SHARE_THRESHOLD:
        flags.append("shallow_adoption_risk")
    if abandonment_weighted > HIGH_ABANDONMENT_THRESHOLD:
        flags.append("high_abandonment")
    if collab_weighted < COLLABORATION_BLOCKED_THRESHOLD:
        flags.append("collaboration_blocked")
    if api_weighted < NO_API_INTEREST_THRESHOLD:
        flags.append("no_api_interest")
    if depth_weighted - discovery_weighted > POWER_DISCOVERY_GAP_THRESHOLD:
        flags.append("power_discovery_gap")

    cluster_profiles = [
        ClusterFeatureProfile(
            cluster_id=row["cluster_id"],
            cluster_name=row["cluster_name"],
            population_weight=row["population_weight"],
            feature_depth=row["feature_depth"],
            core_dau_rate=row["core_dau_rate"],
            power_discovery_rate=row["power_discovery_rate"],
            abandonment_rate=row["abandonment_rate"],
            segment_tier=_segment_tier(row["feature_depth"]),
        )
        for row in cluster_rows
    ]
    cluster_profiles.sort(
        key=lambda c: (c.segment_tier != SEGMENT_ADVANCED, -c.feature_depth)
    )

    brief_scored: list[BriefFeatureScore] = []
    for feature in _coerce_brief_features(brief_features):
        dimension_key = _match_brief_feature(feature)
        if dimension_key is None:
            brief_scored.append(
                BriefFeatureScore(
                    feature=feature,
                    note="No modeled dimension matched this feature's keywords.",
                )
            )
            continue
        match = next(
            (d for d in dimensions if d.key == dimension_key),
            None,
        )
        if match is None:
            brief_scored.append(
                BriefFeatureScore(
                    feature=feature,
                    dimension_key=dimension_key,
                    dimension_label=_DIMENSION_LABELS.get(dimension_key, ""),
                    note="Dimension not measured for this run.",
                )
            )
            continue
        brief_scored.append(
            BriefFeatureScore(
                feature=feature,
                dimension_key=dimension_key,
                dimension_label=match.label,
                adoption_rate=match.adoption_rate,
                priority_tier=match.priority_tier,
                note=(
                    f"Maps to {match.label} "
                    f"({_fmt_pct(match.adoption_rate)} adoption, "
                    f"{match.priority_tier})."
                ),
            )
        )

    recommendations: list[str] = []
    top = dimensions[0] if dimensions else None
    if top is not None and top.priority_tier in (TIER_BUILD_FIRST, TIER_GROW):
        recommendations.append(
            f"Start with {top.label} — highest validated upside "
            f"({_fmt_pct(top.adoption_rate)} adoption, "
            f"{_fmt_pct(top.upside)} headroom)."
        )
    if "shallow_adoption_risk" in flags:
        recommendations.append(
            "Focus onboarding on power features before adding new ones — "
            f"{_fmt_pct(shallow_share)} of covered demand shows shallow "
            "feature depth."
        )
    if "high_abandonment" in flags:
        recommendations.append(
            "Abandonment is high — fix time-to-value before scaling "
            "acquisition."
        )
    if "collaboration_blocked" in flags:
        recommendations.append(
            "Collaboration features are blocked in low-trust clusters — "
            "build single-player value first."
        )
    if "power_discovery_gap" in flags:
        recommendations.append(
            "Power features exist but aren't discovered — add in-app "
            "guidance or empty-state prompts."
        )
    if "no_api_interest" in flags:
        recommendations.append(
            "API adoption is negligible — revisit only if a developer "
            "ecosystem is strategic."
        )
    advanced = [
        c for c in cluster_profiles if c.segment_tier == SEGMENT_ADVANCED
    ]
    if advanced:
        best = advanced[0]
        recommendations.append(
            f"Target {best.cluster_name} first — deepest feature adoption "
            f"({_fmt_pct(best.feature_depth)})."
        )
    mapped_build = [
        b for b in brief_scored if b.priority_tier == TIER_BUILD_FIRST
    ]
    if mapped_build:
        first = mapped_build[0]
        recommendations.append(
            f"Of your declared features, '{first.feature}' maps to "
            f"{first.dimension_label} (BUILD_FIRST)."
        )
    if not recommendations:
        recommendations.append(
            "Feature adoption looks healthy — keep the core loop stable "
            "and iterate on the highest-scoring dimension."
        )

    critical_flags = {
        "shallow_adoption_risk",
        "high_abandonment",
        "collaboration_blocked",
    }
    verdict = (
        VERDICT_FOCUSED
        if any(flag in critical_flags for flag in flags)
        else VERDICT_READY
    )

    return FeaturePrioritizationOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type_name,
        verdict=verdict,
        dimensions=dimensions,
        cluster_profiles=cluster_profiles,
        brief_features=brief_scored,
        flags=flags,
        recommendations=recommendations,
        meta={
            "signal_quality": signal_quality,
            "total_clusters": len(registry),
            "covered_clusters": len(cluster_rows),
            "covered_weight": round(covered_weight, 4),
            "top_dimension": top.key if top else None,
            "top_priority_score": top.priority_score if top else None,
            "product_type_supported": True,
        },
    )


__all__ = [
    "BRIEF_FEATURE_KEYWORDS",
    "DIMENSIONS",
    "FEATURE_PRODUCT_TYPES",
    "PRODUCT_STRATEGIC_BOOSTS",
    "build_feature_prioritization",
]
