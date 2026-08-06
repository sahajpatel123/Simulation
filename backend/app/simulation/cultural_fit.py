"""
Pure cultural-fit analysis for completed simulation results.

Answers the founder's "will this resonate culturally, and which
localization lever should I pull first?" question by turning the
``CulturalContextArchitect`` per-cluster metrics into a deterministic,
population-weighted cultural-fit read:

* **Fit index** — a 0..1 market-weighted composite (higher = better
  fit) of language accessibility (30%), cultural alignment (25%),
  family-gatekeeper pressure (15%), religious-sensitivity risk (15%),
  seasonal relevance (10%) and geo-target alignment (5%). Each
  component is normalized so all six barriers are comparable and
  higher scores always mean better fit.
* **Cluster tiers** — every covered cluster is classified ``STRONG``
  (fit index >= 0.75) / ``MODERATE`` (>= 0.55) / ``WEAK`` (>= 0.40) /
  ``MISALIGNED`` (< 0.40).
* **Primary cultural barrier** — each cluster is attributed to the
  weakest of the six modeled inputs (language access, cultural
  alignment, family gatekeeper, religious sensitivity, seasonal
  timing, geography). The market-level barrier distribution is the
  population-weighted share of those attributions.
* **Localization levers** — six interventions (regional-language
  localization, localized messaging, collective-purchase design,
  cultural/religious compliance, seasonal launch timing, tier-2/3
  go-to-market) ranked by the share of the covered market where the
  underlying barrier is present.

The verdict is ``STRONG_FIT`` when the weighted fit index is at least
0.75, ``MODERATE_FIT`` at 0.55, ``WEAK_FIT`` at 0.40, ``MISALIGNED``
below that, and ``INSUFFICIENT_DATA`` when no cluster has usable
metrics. ``CulturalContextArchitect`` runs in every conductor stack, so
all 15 product types are supported.

The covered market is the population weight of clusters with usable
metrics and a positive population share; zero-weight clusters are
excluded from profiles, flags and lever shares. ``meta`` also carries a
``primary_barrier_score`` (0..1, population-weighted severity of each
cluster's weakest cultural input) so a ``STRONG_FIT`` verdict with a
residual tie-break barrier is not mistaken for a real cultural risk.

No DB / I/O — verifiable without FastAPI or PostgreSQL. The route layer
supplies ``results``, ``conductor_results`` (per-cluster architect
metrics) and ``cluster_registry``; all arithmetic is deterministic.
Metrics missing from a malformed/partial payload use neutral defaults
(alignment 0.60, language 0.70, family 0.45, seasonal 0.65, brand trust
0.50, religious risk 0.20, geo alignment 0.75, correction 1.0) so a
missing field never manufactures a MISALIGNED tier or an extreme
barrier.
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable

from app.schemas.cultural_fit import (
    BARRIER_ALIGNMENT,
    BARRIER_FAMILY,
    BARRIER_GEO,
    BARRIER_LANGUAGE,
    BARRIER_RELIGIOUS,
    BARRIER_SEASONAL,
    ClusterCulturalProfile,
    CulturalFitOut,
    CulturalLever,
    LEVER_COMPLIANCE,
    LEVER_FAMILY,
    LEVER_GEO,
    LEVER_LOCALIZATION,
    LEVER_MESSAGING,
    LEVER_SEASONAL,
    TIER_MISALIGNED,
    TIER_MODERATE,
    TIER_STRONG,
    TIER_WEAK,
    VERDICT_INSUFFICIENT,
    VERDICT_MISALIGNED,
    VERDICT_MODERATE_FIT,
    VERDICT_STRONG_FIT,
    VERDICT_WEAK_FIT,
)

# Ordered barrier keys — used for tie-breaking and market aggregation so
# the output is stable regardless of dict ordering.
BARRIER_ORDER: tuple[str, ...] = (
    BARRIER_LANGUAGE,
    BARRIER_ALIGNMENT,
    BARRIER_FAMILY,
    BARRIER_RELIGIOUS,
    BARRIER_SEASONAL,
    BARRIER_GEO,
)

BARRIER_LABELS: dict[str, str] = {
    BARRIER_LANGUAGE: "Language barrier",
    BARRIER_ALIGNMENT: "Cultural misalignment",
    BARRIER_FAMILY: "Family gatekeeper",
    BARRIER_RELIGIOUS: "Religious/cultural sensitivity",
    BARRIER_SEASONAL: "Festival/seasonal timing mismatch",
    BARRIER_GEO: "Geography misalignment",
}

LEVER_LABELS: dict[str, str] = {
    LEVER_LOCALIZATION: "Localization & regional language support",
    LEVER_MESSAGING: "Localized messaging & brand building",
    LEVER_FAMILY: "Collective-purchase & household design",
    LEVER_COMPLIANCE: "Cultural & religious compliance validation",
    LEVER_SEASONAL: "Festival & seasonal launch timing",
    LEVER_GEO: "Tier-2/3 go-to-market",
}

# Cluster-tier thresholds (fit index; higher = better).
TIER_STRONG_INDEX: float = 0.75
TIER_MODERATE_INDEX: float = 0.55
TIER_WEAK_INDEX: float = 0.40

# Verdict thresholds (weighted market fit index).
VERDICT_STRONG_INDEX: float = 0.75
VERDICT_MODERATE_INDEX: float = 0.55
VERDICT_WEAK_INDEX: float = 0.40

# Composite weights (sum to 1.0).
WEIGHT_LANGUAGE: float = 0.30
WEIGHT_ALIGNMENT: float = 0.25
WEIGHT_FAMILY: float = 0.15
WEIGHT_RELIGIOUS: float = 0.15
WEIGHT_SEASONAL: float = 0.10
WEIGHT_GEO: float = 0.05

# Neutral defaults for metrics missing from a malformed/partial payload.
# They lean middle-of-road so a missing field neither manufactures a
# MISALIGNED tier nor hides a real barrier present in other metrics.
DEFAULT_ALIGNMENT: float = 0.60
DEFAULT_LANGUAGE: float = 0.70
DEFAULT_FAMILY: float = 0.45
DEFAULT_SEASONAL: float = 0.65
DEFAULT_BRAND_TRUST: float = 0.50
DEFAULT_RELIGIOUS: float = 0.20
DEFAULT_GEO_ALIGNMENT: float = 0.75
DEFAULT_CORRECTION: float = 1.0

# Lever opportunity thresholds — a lever applies to a cluster when the
# underlying cultural input is below a healthy level (or above for
# family / religious severity, where higher is worse).
LEVER_LANGUAGE_SEVERITY_MIN: float = 0.35
LEVER_ALIGNMENT_SEVERITY_MIN: float = 0.40
LEVER_FAMILY_SEVERITY_MIN: float = 0.60
LEVER_RELIGIOUS_SEVERITY_MIN: float = 0.45
LEVER_SEASONAL_SEVERITY_MIN: float = 0.35
LEVER_GEO_SEVERITY_MIN: float = 0.20

# Flag thresholds (weighted market aggregates; higher = better except
# family / religious where higher = worse).
FLAG_LANGUAGE_MIN: float = 0.65
FLAG_ALIGNMENT_MIN: float = 0.60
FLAG_FAMILY_MAX: float = 0.60
FLAG_RELIGIOUS_MAX: float = 0.45
FLAG_SEASONAL_MIN: float = 0.60
FLAG_GEO_MIN: float = 0.80


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


def _cultural_metrics(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> dict[str, Any]:
    """Extract the CulturalContextArchitect metrics block for one cluster."""
    if not conductor_results:
        return {}
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return {}
    architect = cluster_block.get("CulturalContextArchitect")
    if not isinstance(architect, dict):
        return {}
    metrics = architect.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _architect_flags(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> list[str]:
    """Truthy architect flag keys for one cluster, in stable order."""
    if not conductor_results:
        return []
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return []
    architect = cluster_block.get("CulturalContextArchitect")
    if not isinstance(architect, dict):
        return []
    flags = architect.get("flags")
    if not isinstance(flags, dict):
        return []
    return sorted(
        key for key, value in flags.items() if bool(value)
    )


def _severities(metrics: dict[str, Any]) -> dict[str, float]:
    """Normalized cultural-barrier severities for one cluster (0..1,
    higher = worse)."""
    language = _clamp(
        _safe_float(
            metrics.get("language_accessibility_score"),
            DEFAULT_LANGUAGE,
        )
    )
    alignment = _clamp(
        _safe_float(
            metrics.get("cultural_alignment_score"),
            DEFAULT_ALIGNMENT,
        )
    )
    family = _clamp(
        _safe_float(
            metrics.get("family_influence_factor"),
            DEFAULT_FAMILY,
        )
    )
    religious = _clamp(
        _safe_float(
            metrics.get("religious_sensitivity_risk"),
            DEFAULT_RELIGIOUS,
        )
    )
    seasonal = _clamp(
        _safe_float(
            metrics.get("seasonal_relevance_score"),
            DEFAULT_SEASONAL,
        )
    )
    geo = _clamp(
        _safe_float(
            metrics.get("geo_target_alignment"),
            DEFAULT_GEO_ALIGNMENT,
        )
    )
    return {
        BARRIER_LANGUAGE: round(1.0 - language, 4),
        BARRIER_ALIGNMENT: round(1.0 - alignment, 4),
        BARRIER_FAMILY: round(family, 4),
        BARRIER_RELIGIOUS: round(religious, 4),
        BARRIER_SEASONAL: round(1.0 - seasonal, 4),
        BARRIER_GEO: round(1.0 - geo, 4),
    }


def _primary_barrier(severities: dict[str, float]) -> tuple[str, float]:
    """Worst barrier; ties resolve to the earlier key in BARRIER_ORDER."""
    best_key = BARRIER_ORDER[0]
    best_value = severities.get(best_key, 0.0)
    for key in BARRIER_ORDER[1:]:
        value = severities.get(key, 0.0)
        if value > best_value:
            best_key = key
            best_value = value
    return best_key, round(best_value, 4)


def _fit_index(severities: dict[str, float]) -> float:
    """Composite 0..1 cultural-fit score (higher = better fit)."""
    return _clamp(
        1.0
        - WEIGHT_LANGUAGE * severities.get(BARRIER_LANGUAGE, 0.0)
        - WEIGHT_ALIGNMENT * severities.get(BARRIER_ALIGNMENT, 0.0)
        - WEIGHT_FAMILY * severities.get(BARRIER_FAMILY, 0.0)
        - WEIGHT_RELIGIOUS * severities.get(BARRIER_RELIGIOUS, 0.0)
        - WEIGHT_SEASONAL * severities.get(BARRIER_SEASONAL, 0.0)
        - WEIGHT_GEO * severities.get(BARRIER_GEO, 0.0)
    )


def _fit_tier(fit_index: float) -> str:
    if fit_index >= TIER_STRONG_INDEX:
        return TIER_STRONG
    if fit_index >= TIER_MODERATE_INDEX:
        return TIER_MODERATE
    if fit_index >= TIER_WEAK_INDEX:
        return TIER_WEAK
    return TIER_MISALIGNED


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
) -> CulturalLever:
    share = _opportunity_share(rows, predicate)
    return CulturalLever(
        key=key,
        label=LEVER_LABELS[key],
        market_value=round(_weighted_average(rows, metric_key), 4),
        opportunity_share=round(share, 4),
        action=action.format(share=_fmt_pct(share)),
    )


def build_cultural_fit(
    results: dict[str, Any] | None,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    conductor_results: dict[str, Any] | None = None,
    cluster_registry: list[dict[str, Any]] | None = None,
    product_type: str = "saas",
) -> CulturalFitOut:
    """Compose the cultural-fit read from completed results.

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

    rows: list[dict[str, Any]] = []
    covered_weight = 0.0
    for entry in registry:
        cid = str(entry.get("cluster_id", ""))
        if not cid:
            continue
        weight = max(0.0, _safe_float(entry.get("population_weight")))
        # A cluster with zero (or negative) population share represents no
        # covered consumers: keep it out of profiles, covered counts, flags
        # and lever shares so the read stays a true covered-market view.
        if weight <= 0.0:
            continue
        metrics = _cultural_metrics(conductor_results, cid)
        if not metrics:
            continue

        alignment = _clamp(
            _safe_float(
                metrics.get("cultural_alignment_score"),
                DEFAULT_ALIGNMENT,
            )
        )
        language = _clamp(
            _safe_float(
                metrics.get("language_accessibility_score"),
                DEFAULT_LANGUAGE,
            )
        )
        family = _clamp(
            _safe_float(
                metrics.get("family_influence_factor"),
                DEFAULT_FAMILY,
            )
        )
        seasonal = _clamp(
            _safe_float(
                metrics.get("seasonal_relevance_score"),
                DEFAULT_SEASONAL,
            )
        )
        brand = _clamp(
            _safe_float(
                metrics.get("local_brand_trust"),
                DEFAULT_BRAND_TRUST,
            )
        )
        religious = _clamp(
            _safe_float(
                metrics.get("religious_sensitivity_risk"),
                DEFAULT_RELIGIOUS,
            )
        )
        geo = _clamp(
            _safe_float(
                metrics.get("geo_target_alignment"),
                DEFAULT_GEO_ALIGNMENT,
            )
        )
        correction = max(
            0.10,
            min(
                1.80,
                _safe_float(
                    metrics.get("overall_cultural_correction"),
                    DEFAULT_CORRECTION,
                ),
            ),
        )

        severities = _severities(metrics)
        fit = _fit_index(severities)
        barrier, barrier_score = _primary_barrier(severities)
        covered_weight += weight
        rows.append(
            {
                "cluster_id": cid,
                "cluster_name": str(entry.get("name", "") or cid),
                "population_weight": weight,
                "alignment": alignment,
                "language": language,
                "family": family,
                "seasonal": seasonal,
                "brand": brand,
                "religious": religious,
                "geo": geo,
                "correction": correction,
                "fit_index": round(fit, 4),
                "tier": _fit_tier(fit),
                "barrier": barrier,
                "barrier_score": barrier_score,
                "architect_flags": _architect_flags(
                    conductor_results, cid
                ),
            }
        )

    meta: dict[str, Any] = {
        "signal_quality": signal_quality,
        "total_clusters": len(registry),
        "covered_clusters": len(rows),
        "covered_weight": round(covered_weight, 4),
        "primary_barrier_score": 0.0,
        "product_type_supported": True,
        "thresholds": {
            "tier_strong_index": TIER_STRONG_INDEX,
            "tier_moderate_index": TIER_MODERATE_INDEX,
            "tier_weak_index": TIER_WEAK_INDEX,
            "verdict_strong_index": VERDICT_STRONG_INDEX,
            "verdict_moderate_index": VERDICT_MODERATE_INDEX,
            "verdict_weak_index": VERDICT_WEAK_INDEX,
        },
    }

    if not rows or covered_weight <= 0.0:
        return CulturalFitOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                "No per-cluster CulturalContextArchitect metrics were "
                "available for this run."
            ],
            meta=meta,
        )

    fit_index_avg = _weighted_average(rows, "fit_index")
    alignment_avg = _weighted_average(rows, "alignment")
    language_avg = _weighted_average(rows, "language")
    family_avg = _weighted_average(rows, "family")
    seasonal_avg = _weighted_average(rows, "seasonal")
    brand_avg = _weighted_average(rows, "brand")
    religious_avg = _weighted_average(rows, "religious")
    geo_avg = _weighted_average(rows, "geo")
    correction_avg = _weighted_average(rows, "correction")

    strong_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_STRONG
    )
    moderate_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_MODERATE
    )
    weak_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_WEAK
    )
    misaligned_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_MISALIGNED
    )
    strong_share = strong_weight / covered_weight
    moderate_share = moderate_weight / covered_weight
    weak_share = weak_weight / covered_weight
    misaligned_share = misaligned_weight / covered_weight

    if fit_index_avg >= VERDICT_STRONG_INDEX:
        verdict = VERDICT_STRONG_FIT
    elif fit_index_avg >= VERDICT_MODERATE_INDEX:
        verdict = VERDICT_MODERATE_FIT
    elif fit_index_avg >= VERDICT_WEAK_INDEX:
        verdict = VERDICT_WEAK_FIT
    else:
        verdict = VERDICT_MISALIGNED

    # Market barrier distribution = population-weighted share of
    # per-cluster primary-barrier attributions.
    barrier_weights: dict[str, float] = {key: 0.0 for key in BARRIER_ORDER}
    for row in rows:
        barrier_weights[row["barrier"]] += row["population_weight"]
    barrier_distribution = {
        key: round(weight / covered_weight, 4)
        for key, weight in barrier_weights.items()
    }
    primary_barrier = BARRIER_ORDER[0]
    primary_barrier_share = barrier_distribution[primary_barrier]
    for key in BARRIER_ORDER[1:]:
        if barrier_distribution[key] > primary_barrier_share:
            primary_barrier = key
            primary_barrier_share = barrier_distribution[key]
    # Market-level severity of the attributed barrier: population-weighted
    # average of each cluster's worst normalized barrier score.
    primary_barrier_score = _weighted_average(rows, "barrier_score")
    meta["primary_barrier_score"] = round(primary_barrier_score, 4)

    flags: list[str] = []
    if any(row["tier"] == TIER_MISALIGNED for row in rows):
        flags.append("misaligned_clusters")
    if language_avg < FLAG_LANGUAGE_MIN:
        flags.append("language_barrier_market")
    if alignment_avg < FLAG_ALIGNMENT_MIN:
        flags.append("cultural_misalignment_market")
    if family_avg > FLAG_FAMILY_MAX:
        flags.append("family_gatekeeper_market")
    if religious_avg >= FLAG_RELIGIOUS_MAX:
        flags.append("religious_sensitivity_market")
    if seasonal_avg < FLAG_SEASONAL_MIN:
        flags.append("festival_timing_mismatch_market")
    if geo_avg < FLAG_GEO_MIN:
        flags.append("geo_mismatch_market")

    levers: list[CulturalLever] = [
        _lever(
            rows,
            LEVER_LOCALIZATION,
            "language",
            lambda row: row["language"] < 1.0 - LEVER_LANGUAGE_SEVERITY_MIN,
            "Add Hindi and regional-language UI plus voice-first "
            "onboarding — {share} of the covered market faces a "
            "language gap.",
        ),
        _lever(
            rows,
            LEVER_MESSAGING,
            "alignment",
            lambda row: row["alignment"] < 1.0 - LEVER_ALIGNMENT_SEVERITY_MIN,
            "Localize messaging, imagery and brand positioning — "
            "{share} of the covered market is culturally misaligned.",
        ),
        _lever(
            rows,
            LEVER_FAMILY,
            "family",
            lambda row: row["family"] >= LEVER_FAMILY_SEVERITY_MIN,
            "Design for family/collective purchase decisions and "
            "household sharing — {share} of the covered market has a "
            "family gatekeeper.",
        ),
        _lever(
            rows,
            LEVER_COMPLIANCE,
            "religious",
            lambda row: row["religious"] >= LEVER_RELIGIOUS_SEVERITY_MIN,
            "Validate vegetarian, halal and Jain requirements plus "
            "imagery/copy sensitivity — {share} of the covered market "
            "has cultural/religious concerns.",
        ),
        _lever(
            rows,
            LEVER_SEASONAL,
            "seasonal",
            lambda row: row["seasonal"] < 1.0 - LEVER_SEASONAL_SEVERITY_MIN,
            "Align launch and campaigns with Diwali, wedding or harvest "
            "seasons — {share} of the covered market responds to "
            "festival timing.",
        ),
        _lever(
            rows,
            LEVER_GEO,
            "geo",
            lambda row: row["geo"] <= 1.0 - LEVER_GEO_SEVERITY_MIN,
            "Build a tier-2/3 go-to-market with local channels and "
            "regional partnerships — {share} of the covered market is "
            "outside the target geography.",
        ),
    ]
    levers.sort(key=lambda lever: (-lever.opportunity_share, lever.key))

    recommendations: list[str] = []
    if verdict == VERDICT_STRONG_FIT:
        recommendations.append(
            f"Cultural fit is strong (fit index = {fit_index_avg:.2f}) — "
            "keep localization current as you expand to new regions."
        )
    elif verdict == VERDICT_MODERATE_FIT:
        recommendations.append(
            f"Cultural fit is workable but not universal (fit index = "
            f"{fit_index_avg:.2f}, {_fmt_pct(weak_share + misaligned_share)} "
            "already WEAK/MISALIGNED) — close language and messaging "
            "gaps before scaling."
        )
    elif verdict == VERDICT_WEAK_FIT:
        recommendations.append(
            f"Cultural fit is weak (fit index = {fit_index_avg:.2f}) — "
            "expect meaningfully lower conversion in the segments below "
            "unless localization improves."
        )
    else:
        recommendations.append(
            f"Cultural fit is misaligned (fit index = {fit_index_avg:.2f}, "
            f"{_fmt_pct(misaligned_share)} of the covered market "
            "MISALIGNED) — treat localization as a launch blocker."
        )
    recommendations.append(
        f"Primary cultural barrier: {BARRIER_LABELS[primary_barrier]} "
        f"(severity {primary_barrier_score:.2f}, affects "
        f"{_fmt_pct(primary_barrier_share)} of the covered market)."
    )
    if levers:
        top = levers[0]
        recommendations.append(
            f"Highest-leverage action: {top.label} — touches "
            f"{_fmt_pct(top.opportunity_share)} of the covered market."
        )
    if language_avg < FLAG_LANGUAGE_MIN:
        recommendations.append(
            f"Language accessibility averages {_fmt_pct(language_avg)} — "
            "regional-language UI and voice-first onboarding are the "
            "fastest fix."
        )
    if alignment_avg < FLAG_ALIGNMENT_MIN:
        recommendations.append(
            f"Cultural alignment averages {_fmt_pct(alignment_avg)} — "
            "localize copy, imagery and brand positioning per region."
        )
    if family_avg > FLAG_FAMILY_MAX:
        recommendations.append(
            f"Family influence averages {_fmt_pct(family_avg)} — plan "
            "for longer collective decision cycles and household features."
        )
    if religious_avg >= FLAG_RELIGIOUS_MAX:
        recommendations.append(
            f"Religious/cultural sensitivity risk is "
            f"{_fmt_pct(religious_avg)} — validate product requirements "
            "and marketing imagery before launch."
        )
    if seasonal_avg < FLAG_SEASONAL_MIN:
        recommendations.append(
            f"Seasonal relevance averages {_fmt_pct(seasonal_avg)} — "
            "align launch windows with major festival seasons."
        )
    if geo_avg < FLAG_GEO_MIN:
        recommendations.append(
            f"Geo-target alignment averages {_fmt_pct(geo_avg)} — "
            "reconsider the target geography or build tier-2/3 channels."
        )

    return CulturalFitOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type_name,
        verdict=verdict,
        fit_index=round(fit_index_avg, 4),
        weighted_cultural_alignment=round(alignment_avg, 4),
        weighted_language_accessibility=round(language_avg, 4),
        weighted_family_influence=round(family_avg, 4),
        weighted_seasonal_relevance=round(seasonal_avg, 4),
        weighted_local_brand_trust=round(brand_avg, 4),
        weighted_religious_risk=round(religious_avg, 4),
        weighted_geo_alignment=round(geo_avg, 4),
        weighted_cultural_correction=round(correction_avg, 4),
        strong_share=round(strong_share, 4),
        moderate_share=round(moderate_share, 4),
        weak_share=round(weak_share, 4),
        misaligned_share=round(misaligned_share, 4),
        primary_barrier=primary_barrier,
        primary_barrier_label=BARRIER_LABELS[primary_barrier],
        primary_barrier_share=round(primary_barrier_share, 4),
        barrier_distribution=barrier_distribution,
        cluster_profiles=[
            ClusterCulturalProfile(
                cluster_id=row["cluster_id"],
                cluster_name=row["cluster_name"],
                population_weight=row["population_weight"],
                cultural_alignment_score=row["alignment"],
                language_accessibility_score=row["language"],
                family_influence_factor=row["family"],
                seasonal_relevance_score=row["seasonal"],
                local_brand_trust=row["brand"],
                religious_sensitivity_risk=row["religious"],
                geo_target_alignment=row["geo"],
                overall_cultural_correction=row["correction"],
                cultural_fit_index=row["fit_index"],
                fit_tier=row["tier"],
                primary_barrier=row["barrier"],
                primary_barrier_score=row["barrier_score"],
                architect_flags=row["architect_flags"],
            )
            for row in rows
        ],
        levers=levers,
        flags=flags,
        recommendations=recommendations,
        meta=meta,
    )


__all__ = [
    "BARRIER_ORDER",
    "LEVER_LABELS",
    "build_cultural_fit",
]
