"""
Pure trust-barriers analysis for completed simulation results.

Answers the founder's "why won't they trust us, and what removes the
objection?" question by turning the ``TrustArchitect`` per-cluster
metrics into a deterministic, population-weighted trust read:

* **Trust index** — a 0..1 market-weighted composite of brand-deficit
  multiplier, social-proof coverage, security concern, and trust decay
  (mirrors the TrustArchitect transition logic: brand credibility and
  social proof gate BROWSE→CONSIDER, with security and decay as
  penalties). Also surfaces the weighted social-proof threshold, trust
  recovery days, community signal, press lift, and free-trial
  substitute.
* **Cluster tiers** — every covered cluster is classified
  ``LOW`` (trust index >= 0.75) / ``MODERATE`` (>= 0.55) / ``HIGH``
  (>= 0.35) / ``CRITICAL`` (< 0.35).
* **Primary trust barrier** — each cluster is attributed to the weakest
  of the six modeled objections (brand deficit, missing social proof,
  security concern, weak community signal, fast trust decay, slow
  recovery). The market-level barrier distribution is the
  population-weighted share of those attributions.
* **Trust levers** — six interventions (social-proof building,
  risk-free trial, brand credibility, security assurances, community
  signals, incident response) ranked by the share of the covered market
  where the underlying objection is present.

The verdict is ``LOW_BARRIER`` when the weighted trust index is at
least 0.75, ``MODERATE`` at 0.55, ``HIGH`` at 0.35, ``CRITICAL`` below
that, and ``INSUFFICIENT_DATA`` when no cluster has usable metrics.
Unlike virality and activation reads, this read has no product-type
gate: ``TrustArchitect`` runs in every conductor stack, so all 15
product types are supported.

No DB / I/O — verifiable without FastAPI or PostgreSQL. The route layer
supplies ``results``, ``conductor_results`` (per-cluster architect
metrics) and ``cluster_registry``; all arithmetic is deterministic.
Metrics missing from a malformed/partial payload use neutral defaults
(brand multiplier 0.70, social proof 0.60, security concern 0.10,
decay 0.10, recovery 21 days, community signal 0.20, press lift 0.10,
free-trial substitute 0.30) so a missing field never manufactures a
CRITICAL tier or an extreme objection.
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable

from app.schemas.trust_barriers import (
    BARRIER_BRAND,
    BARRIER_COMMUNITY,
    BARRIER_DECAY,
    BARRIER_RECOVERY,
    BARRIER_SECURITY,
    BARRIER_SOCIAL_PROOF,
    ClusterTrustProfile,
    LEVER_BRAND,
    LEVER_COMMUNITY,
    LEVER_FREE_TRIAL,
    LEVER_RECOVERY,
    LEVER_SECURITY,
    LEVER_SOCIAL_PROOF,
    TIER_CRITICAL,
    TIER_HIGH,
    TIER_LOW,
    TIER_MODERATE,
    TrustBarriersOut,
    TrustLever,
    VERDICT_CRITICAL,
    VERDICT_HIGH,
    VERDICT_INSUFFICIENT,
    VERDICT_LOW_BARRIER,
    VERDICT_MODERATE,
)

# Ordered barrier keys — used for tie-breaking and market aggregation so
# the output is stable regardless of dict ordering.
BARRIER_ORDER: tuple[str, ...] = (
    BARRIER_BRAND,
    BARRIER_SOCIAL_PROOF,
    BARRIER_SECURITY,
    BARRIER_COMMUNITY,
    BARRIER_DECAY,
    BARRIER_RECOVERY,
)

BARRIER_LABELS: dict[str, str] = {
    BARRIER_BRAND: "Brand deficit",
    BARRIER_SOCIAL_PROOF: "Missing social proof",
    BARRIER_SECURITY: "Security concern",
    BARRIER_COMMUNITY: "Weak community signals",
    BARRIER_DECAY: "Fast trust decay",
    BARRIER_RECOVERY: "Slow trust recovery",
}

# Cluster-tier thresholds (trust index).
TIER_LOW_INDEX: float = 0.75
TIER_MODERATE_INDEX: float = 0.55
TIER_HIGH_INDEX: float = 0.35

# Verdict thresholds (weighted market trust index).
VERDICT_LOW_INDEX: float = 0.75
VERDICT_MODERATE_INDEX: float = 0.55
VERDICT_HIGH_INDEX: float = 0.35

# Lever opportunity thresholds — a lever applies to a cluster when the
# underlying objection is present.
LEVER_SOCIAL_PROOF_THRESHOLD: float = 0.50
LEVER_FREE_TRIAL_THRESHOLD: float = 0.40
LEVER_BRAND_THRESHOLD: float = 0.70
LEVER_SECURITY_THRESHOLD: float = 0.15
LEVER_COMMUNITY_THRESHOLD: float = 0.20
LEVER_RECOVERY_DAYS_THRESHOLD: float = 30.0
LEVER_DECAY_THRESHOLD: float = 0.15

# Flag thresholds.
FLAG_BRAND_THRESHOLD: float = 0.50
FLAG_SOCIAL_PROOF_THRESHOLD: float = 0.30
FLAG_SECURITY_THRESHOLD: float = 0.20
FLAG_RECOVERY_DAYS_THRESHOLD: float = 30.0
FLAG_FREE_TRIAL_THRESHOLD: float = 0.50
FLAG_COMMUNITY_THRESHOLD: float = 0.15

# Neutral defaults for metrics missing from a malformed/partial payload.
# They lean middle-of-road so a missing field neither manufactures a
# CRITICAL tier nor hides a real objection present in other metrics.
DEFAULT_BRAND_MULTIPLIER: float = 0.70
DEFAULT_SOCIAL_PROOF_MET: float = 0.60
DEFAULT_SECURITY: float = 0.10
DEFAULT_FOUNDER_WEIGHT: float = 0.30
DEFAULT_DECAY: float = 0.10
DEFAULT_RECOVERY_DAYS: float = 21.0
DEFAULT_COMMUNITY: float = 0.20
DEFAULT_PRESS_LIFT: float = 0.10
DEFAULT_FREE_TRIAL: float = 0.30
DEFAULT_SOCIAL_PROOF_THRESHOLD: float = 30.0

# Recovery-days normalization denominator: 45+ days saturates the
# trust-recovery barrier score at 1.0.
RECOVERY_SCALE_DAYS: float = 45.0

# Community normalization denominator: community signal is the product
# of social orientation and small coefficients, so a 0.5 anchor means a
# strong signal contributes no community barrier.
COMMUNITY_SCALE: float = 0.5

LEVER_LABELS: dict[str, str] = {
    LEVER_SOCIAL_PROOF: "Social-proof building",
    LEVER_FREE_TRIAL: "Risk-free trial",
    LEVER_BRAND: "Brand credibility",
    LEVER_SECURITY: "Security assurances",
    LEVER_COMMUNITY: "Community signals",
    LEVER_RECOVERY: "Incident response",
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


def _trust_metrics(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> dict[str, Any]:
    """Extract the TrustArchitect metrics block for one cluster."""
    if not conductor_results:
        return {}
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return {}
    architect = cluster_block.get("TrustArchitect")
    if not isinstance(architect, dict):
        return {}
    metrics = architect.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _barrier_scores(metrics: dict[str, Any]) -> dict[str, float]:
    """Normalized trust-objection scores for one cluster (0..1, higher =
    worse)."""
    brand = _clamp(
        _safe_float(
            metrics.get("brand_deficit_multiplier"),
            DEFAULT_BRAND_MULTIPLIER,
        )
    )
    social_proof = _clamp(
        _safe_float(
            metrics.get("social_proof_met_fraction"),
            DEFAULT_SOCIAL_PROOF_MET,
        )
    )
    security = _clamp(
        _safe_float(
            metrics.get("security_concern_intensity"),
            DEFAULT_SECURITY,
        )
    )
    community = _clamp(
        _safe_float(
            metrics.get("community_size_signal_weight"),
            DEFAULT_COMMUNITY,
        )
    )
    decay = _clamp(
        _safe_float(
            metrics.get("trust_decay_rate_per_incident"),
            DEFAULT_DECAY,
        )
    )
    recovery_days = max(
        0.0,
        _safe_float(
            metrics.get("trust_recovery_days"),
            DEFAULT_RECOVERY_DAYS,
        ),
    )
    return {
        BARRIER_BRAND: round(1.0 - brand, 4),
        BARRIER_SOCIAL_PROOF: round(1.0 - social_proof, 4),
        BARRIER_SECURITY: round(security, 4),
        BARRIER_COMMUNITY: round(
            _clamp(1.0 - community / COMMUNITY_SCALE),
            4,
        ),
        BARRIER_DECAY: round(min(1.0, decay * 2.0), 4),
        BARRIER_RECOVERY: round(
            min(1.0, recovery_days / RECOVERY_SCALE_DAYS),
            4,
        ),
    }


def _primary_barrier(scores: dict[str, float]) -> tuple[str, float]:
    """Highest objection; ties resolve to the earlier key in BARRIER_ORDER."""
    best_key = BARRIER_ORDER[0]
    best_value = scores.get(best_key, 0.0)
    for key in BARRIER_ORDER[1:]:
        value = scores.get(key, 0.0)
        if value > best_value:
            best_key = key
            best_value = value
    return best_key, round(best_value, 4)


def _trust_index(metrics: dict[str, Any]) -> float:
    """Composite 0..1 trust score mirroring TrustArchitect's transition
    logic (brand multiplier * social proof, penalized by security concern
    and decay)."""
    brand = _clamp(
        _safe_float(
            metrics.get("brand_deficit_multiplier"),
            DEFAULT_BRAND_MULTIPLIER,
        )
    )
    social_proof = _clamp(
        _safe_float(
            metrics.get("social_proof_met_fraction"),
            DEFAULT_SOCIAL_PROOF_MET,
        )
    )
    security = _clamp(
        _safe_float(
            metrics.get("security_concern_intensity"),
            DEFAULT_SECURITY,
        )
    )
    decay = _clamp(
        _safe_float(
            metrics.get("trust_decay_rate_per_incident"),
            DEFAULT_DECAY,
        )
    )
    return _clamp(
        brand * social_proof * (1.0 - security * 0.5) * (1.0 - decay * 0.5)
    )


def _barrier_tier(trust_index: float) -> str:
    if trust_index >= TIER_LOW_INDEX:
        return TIER_LOW
    if trust_index >= TIER_MODERATE_INDEX:
        return TIER_MODERATE
    if trust_index >= TIER_HIGH_INDEX:
        return TIER_HIGH
    return TIER_CRITICAL


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
) -> TrustLever:
    share = _opportunity_share(rows, predicate)
    return TrustLever(
        key=key,
        label=LEVER_LABELS[key],
        market_value=round(_weighted_average(rows, metric_key), 4),
        opportunity_share=round(share, 4),
        action=action.format(share=_fmt_pct(share)),
    )


def build_trust_barriers(
    results: dict[str, Any] | None,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    conductor_results: dict[str, Any] | None = None,
    cluster_registry: list[dict[str, Any]] | None = None,
    product_type: str = "saas",
) -> TrustBarriersOut:
    """Compose the trust-barriers read from completed results.

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
        metrics = _trust_metrics(conductor_results, cid)
        if not metrics:
            continue

        brand = _clamp(
            _safe_float(
                metrics.get("brand_deficit_multiplier"),
                DEFAULT_BRAND_MULTIPLIER,
            )
        )
        social_proof_met = _clamp(
            _safe_float(
                metrics.get("social_proof_met_fraction"),
                DEFAULT_SOCIAL_PROOF_MET,
            )
        )
        security = _clamp(
            _safe_float(
                metrics.get("security_concern_intensity"),
                DEFAULT_SECURITY,
            )
        )
        founder_weight = _clamp(
            _safe_float(
                metrics.get("founder_vs_product_credibility"),
                DEFAULT_FOUNDER_WEIGHT,
            )
        )
        decay = _clamp(
            _safe_float(
                metrics.get("trust_decay_rate_per_incident"),
                DEFAULT_DECAY,
            )
        )
        recovery_days = max(
            0.0,
            _safe_float(
                metrics.get("trust_recovery_days"),
                DEFAULT_RECOVERY_DAYS,
            ),
        )
        community = _clamp(
            _safe_float(
                metrics.get("community_size_signal_weight"),
                DEFAULT_COMMUNITY,
            )
        )
        press_lift = _clamp(
            _safe_float(
                metrics.get("press_mention_lift"),
                DEFAULT_PRESS_LIFT,
            )
        )
        free_trial = _clamp(
            _safe_float(
                metrics.get("free_trial_as_trust_substitute"),
                DEFAULT_FREE_TRIAL,
            )
        )
        proof_threshold = max(
            0.0,
            _safe_float(
                metrics.get("social_proof_threshold"),
                DEFAULT_SOCIAL_PROOF_THRESHOLD,
            ),
        )

        trust_index = _trust_index(metrics)
        barrier, barrier_score = _primary_barrier(
            _barrier_scores(metrics)
        )
        covered_weight += weight
        rows.append(
            {
                "cluster_id": cid,
                "cluster_name": str(entry.get("name", "") or cid),
                "population_weight": weight,
                "brand": brand,
                "proof_threshold": proof_threshold,
                "social_proof_met": social_proof_met,
                "security": security,
                "founder_weight": founder_weight,
                "decay": decay,
                "recovery_days": recovery_days,
                "community": community,
                "press_lift": press_lift,
                "free_trial": free_trial,
                "trust_index": trust_index,
                "tier": _barrier_tier(trust_index),
                "barrier": barrier,
                "barrier_score": barrier_score,
            }
        )

    meta: dict[str, Any] = {
        "signal_quality": signal_quality,
        "total_clusters": len(registry),
        "covered_clusters": len(rows),
        "covered_weight": round(covered_weight, 4),
        "product_type_supported": True,
        "thresholds": {
            "tier_low_index": TIER_LOW_INDEX,
            "tier_moderate_index": TIER_MODERATE_INDEX,
            "tier_high_index": TIER_HIGH_INDEX,
            "verdict_low_index": VERDICT_LOW_INDEX,
            "verdict_moderate_index": VERDICT_MODERATE_INDEX,
            "verdict_high_index": VERDICT_HIGH_INDEX,
        },
    }

    if not rows or covered_weight <= 0.0:
        return TrustBarriersOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                "No per-cluster TrustArchitect metrics were available "
                "for this run."
            ],
            meta=meta,
        )

    trust_index_avg = _weighted_average(rows, "trust_index")
    brand_avg = _weighted_average(rows, "brand")
    social_proof_avg = _weighted_average(rows, "social_proof_met")
    security_avg = _weighted_average(rows, "security")
    decay_avg = _weighted_average(rows, "decay")
    recovery_avg = _weighted_average(rows, "recovery_days")
    community_avg = _weighted_average(rows, "community")
    press_avg = _weighted_average(rows, "press_lift")
    free_trial_avg = _weighted_average(rows, "free_trial")
    proof_threshold_avg = _weighted_average(rows, "proof_threshold")

    low_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_LOW
    )
    moderate_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_MODERATE
    )
    high_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_HIGH
    )
    critical_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_CRITICAL
    )
    low_share = low_weight / covered_weight
    moderate_share = moderate_weight / covered_weight
    high_share = high_weight / covered_weight
    critical_share = critical_weight / covered_weight

    if trust_index_avg >= VERDICT_LOW_INDEX:
        verdict = VERDICT_LOW_BARRIER
    elif trust_index_avg >= VERDICT_MODERATE_INDEX:
        verdict = VERDICT_MODERATE
    elif trust_index_avg >= VERDICT_HIGH_INDEX:
        verdict = VERDICT_HIGH
    else:
        verdict = VERDICT_CRITICAL

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

    flags: list[str] = []
    if any(row["tier"] == TIER_CRITICAL for row in rows):
        flags.append("critical_trust_clusters")
    if brand_avg < FLAG_BRAND_THRESHOLD:
        flags.append("brand_deficit_critical")
    if social_proof_avg < FLAG_SOCIAL_PROOF_THRESHOLD:
        flags.append("social_proof_missing")
    if security_avg > FLAG_SECURITY_THRESHOLD:
        flags.append("security_concern_high")
    if recovery_avg > FLAG_RECOVERY_DAYS_THRESHOLD:
        flags.append("trust_recovery_slow")
    if free_trial_avg > FLAG_FREE_TRIAL_THRESHOLD:
        flags.append("free_trial_required")
    if community_avg < FLAG_COMMUNITY_THRESHOLD:
        flags.append("community_signal_weak")

    levers: list[TrustLever] = [
        _lever(
            rows,
            LEVER_SOCIAL_PROOF,
            "social_proof_met",
            lambda row: row["social_proof_met"] < LEVER_SOCIAL_PROOF_THRESHOLD,
            "Collect testimonials, reviews and case studies — {share} "
            "of the covered market lacks social proof.",
        ),
        _lever(
            rows,
            LEVER_FREE_TRIAL,
            "free_trial",
            lambda row: row["free_trial"] > LEVER_FREE_TRIAL_THRESHOLD,
            "Offer a risk-free trial or guarantee for {share} — "
            "risk-averse segments need it.",
        ),
        _lever(
            rows,
            LEVER_BRAND,
            "brand",
            lambda row: row["brand"] < LEVER_BRAND_THRESHOLD,
            "Build brand credibility (press, partnerships, founder "
            "story) for {share} of the covered market.",
        ),
        _lever(
            rows,
            LEVER_SECURITY,
            "security",
            lambda row: row["security"] > LEVER_SECURITY_THRESHOLD,
            "Add security certifications and transparent data policies "
            "for {share} of the covered market.",
        ),
        _lever(
            rows,
            LEVER_COMMUNITY,
            "community",
            lambda row: row["community"] < LEVER_COMMUNITY_THRESHOLD,
            "Seed visible community signals for {share} of the covered "
            "market.",
        ),
        _lever(
            rows,
            LEVER_RECOVERY,
            "recovery_days",
            lambda row: (
                row["recovery_days"] > LEVER_RECOVERY_DAYS_THRESHOLD
                or row["decay"] > LEVER_DECAY_THRESHOLD
            ),
            "Prepare an incident-response and trust-recovery plan — "
            "{share} of the covered market recovers trust slowly.",
        ),
    ]
    levers.sort(key=lambda lever: (-lever.opportunity_share, lever.key))

    recommendations: list[str] = []
    if verdict == VERDICT_LOW_BARRIER:
        recommendations.append(
            f"Trust is a strength (weighted trust index = "
            f"{trust_index_avg:.2f}) — make social proof and security "
            "assurances permanent parts of the funnel."
        )
    elif verdict == VERDICT_MODERATE:
        recommendations.append(
            f"Trust is workable but not friction-free (trust index = "
            f"{trust_index_avg:.2f}, {_fmt_pct(critical_share)} already "
            "CRITICAL) — pull the strongest lever below to raise "
            "market-wide credibility."
        )
    elif verdict == VERDICT_HIGH:
        recommendations.append(
            f"Trust barriers are high (trust index = {trust_index_avg:.2f}) "
            "— expect significant BROWSE-to-CONSIDER drop-off until "
            "credibility signals improve."
        )
    else:
        recommendations.append(
            f"Trust barriers are critical (trust index = "
            f"{trust_index_avg:.2f}, {_fmt_pct(critical_share)} of the "
            "covered market CRITICAL) — treat trust as the top "
            "conversion blocker before pricing or features."
        )
    recommendations.append(
        f"Primary trust barrier: {BARRIER_LABELS[primary_barrier]} "
        f"(affects {_fmt_pct(primary_barrier_share)} of the covered market)."
    )
    if brand_avg < FLAG_BRAND_THRESHOLD:
        recommendations.append(
            f"Brand-deficit multiplier is only {_fmt_pct(brand_avg)} — "
            "unknown-brand economics are punishing consideration."
        )
    if social_proof_avg < FLAG_SOCIAL_PROOF_THRESHOLD:
        recommendations.append(
            f"Social proof covers only {_fmt_pct(social_proof_avg)} of "
            "the need — seed reviews, testimonials and case studies "
            "before launch."
        )
    if security_avg > FLAG_SECURITY_THRESHOLD:
        recommendations.append(
            f"Security concern intensity is {_fmt_pct(security_avg)} — "
            "publish certifications, data handling policies and "
            "transparent pricing."
        )
    if recovery_avg > FLAG_RECOVERY_DAYS_THRESHOLD:
        recommendations.append(
            f"Trust recovery takes ~{recovery_avg:.0f} days after an "
            "incident — invest in fast, public incident response."
        )
    if free_trial_avg > FLAG_FREE_TRIAL_THRESHOLD:
        recommendations.append(
            f"Free-trial substitute demand is {_fmt_pct(free_trial_avg)} "
            "— a no-risk entry path will unlock risk-averse segments."
        )
    if community_avg < FLAG_COMMUNITY_THRESHOLD:
        recommendations.append(
            f"Community signal weight is {_fmt_pct(community_avg)} — "
            "visible users and community activity would raise "
            "credibility."
        )
    recommendations.append(
        f"Market social-proof threshold averages ~"
        f"{proof_threshold_avg:.0f} reviews/testimonials per segment."
    )

    return TrustBarriersOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type_name,
        verdict=verdict,
        trust_index=round(trust_index_avg, 4),
        weighted_brand_deficit_multiplier=round(brand_avg, 4),
        weighted_social_proof_met_fraction=round(social_proof_avg, 4),
        weighted_security_concern_intensity=round(security_avg, 4),
        weighted_trust_decay_rate=round(decay_avg, 4),
        weighted_trust_recovery_days=round(recovery_avg, 1),
        weighted_community_signal_weight=round(community_avg, 4),
        weighted_press_mention_lift=round(press_avg, 4),
        weighted_free_trial_substitute=round(free_trial_avg, 4),
        low_share=round(low_share, 4),
        moderate_share=round(moderate_share, 4),
        high_share=round(high_share, 4),
        critical_share=round(critical_share, 4),
        primary_barrier=primary_barrier,
        primary_barrier_label=BARRIER_LABELS[primary_barrier],
        primary_barrier_share=round(primary_barrier_share, 4),
        barrier_distribution=barrier_distribution,
        cluster_profiles=[
            ClusterTrustProfile(
                cluster_id=row["cluster_id"],
                cluster_name=row["cluster_name"],
                population_weight=row["population_weight"],
                brand_deficit_multiplier=round(row["brand"], 4),
                social_proof_threshold=round(row["proof_threshold"], 1),
                social_proof_met_fraction=round(row["social_proof_met"], 4),
                security_concern_intensity=round(row["security"], 4),
                founder_vs_product_credibility=round(
                    row["founder_weight"],
                    4,
                ),
                trust_decay_rate_per_incident=round(row["decay"], 4),
                trust_recovery_days=round(row["recovery_days"], 1),
                community_size_signal_weight=round(row["community"], 4),
                press_mention_lift=round(row["press_lift"], 4),
                free_trial_as_trust_substitute=round(
                    row["free_trial"],
                    4,
                ),
                trust_index=round(row["trust_index"], 4),
                barrier_tier=row["tier"],
                primary_barrier=row["barrier"],
                primary_barrier_score=row["barrier_score"],
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
    "build_trust_barriers",
]
