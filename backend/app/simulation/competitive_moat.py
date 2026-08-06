"""
Pure competitive-moat analysis for completed simulation results.

Answers the founder's "how defensible is this idea, and where is the
weakest point?" question by turning per-cluster architect metrics into a
deterministic, population-weighted defensibility read:

* **Moat index** — a 0..1 composite of five levers, each normalized so
  higher means a stronger moat: feature parity (the startup is at or
  above competitor feature level), brand trust (no brand deficit),
  pricing power (customers will pay at the current AOV), distribution
  reach (channels are accessible), and switching lock-in (loss-averse
  customers stick once adopted). Levers from architects that do not run
  for the product type (e.g. ``DistributionChannelArchitect`` outside
  hardware categories) are excluded and the remaining weights are
  renormalized so the index stays comparable across product types.
* **Cluster tiers** — every covered cluster is classified
  ``MOAT_STRONG`` (index >= 0.60) / ``MOAT_MODERATE`` (>= 0.40) /
  ``MOAT_WEAK`` (< 0.40).
* **Weakest moat lever** — each cluster is attributed to the lowest of
  its available levers; the market-level lever distribution is the
  population-weighted share of those attributions and drives
  recommendations.
* **Verdict** — ``STRONG`` when the weighted moat index is at least
  0.60 and weak clusters cover under 50% of the market, ``MODERATE`` at
  0.40, ``WEAK`` below that, and ``INSUFFICIENT_DATA`` when no cluster
  has usable ``CompetitiveDynamicsArchitect`` metrics.

The covered market is the population weight of clusters with usable
competitive metrics and a positive population share; zero-weight
clusters are excluded from profiles, flags, lever shares and ranked
lists. ``meta`` carries the per-lever availability, weighted incumbent
brand-loyalty strength, free-competitor / vacant-category shares and the
thresholds used for tiers and verdicts.

No DB / I/O — verifiable without FastAPI or PostgreSQL. The route layer
supplies ``results``, ``conductor_results`` (per-cluster architect
metrics) and ``cluster_registry``; all arithmetic is deterministic.
Metrics missing from a malformed/partial payload use neutral defaults
(0.50 per lever, 45 displacement days) so a missing field never
manufactures a STRONG verdict or a WEAK one.
"""
from __future__ import annotations

import json
import math
from typing import Any

from app.schemas.competitive_moat import (
    LEVER_BRAND_TRUST,
    LEVER_DISTRIBUTION,
    LEVER_FEATURE_PARITY,
    LEVER_LABELS,
    LEVER_LOCK_IN,
    LEVER_PRICING_POWER,
    ClusterMoatProfile,
    CompetitiveMoatOut,
    MoatOpportunity,
    TIER_MODERATE,
    TIER_STRONG,
    TIER_WEAK,
    VALID_LEVERS,
    VERDICT_INSUFFICIENT,
    VERDICT_MODERATE,
    VERDICT_STRONG,
    VERDICT_WEAK,
)
from app.simulation.product_type import ProductType

# Ordered lever keys — used for tie-breaking and market aggregation so
# the output is stable regardless of dict ordering.
LEVER_ORDER: tuple[str, ...] = (
    LEVER_FEATURE_PARITY,
    LEVER_BRAND_TRUST,
    LEVER_PRICING_POWER,
    LEVER_DISTRIBUTION,
    LEVER_LOCK_IN,
)

# Relative weights per lever. When an architect did not run for the
# product type the weights are renormalized over the available levers.
LEVER_WEIGHTS: dict[str, float] = {
    LEVER_FEATURE_PARITY: 0.25,
    LEVER_BRAND_TRUST: 0.20,
    LEVER_PRICING_POWER: 0.15,
    LEVER_DISTRIBUTION: 0.15,
    LEVER_LOCK_IN: 0.25,
}

# Cluster-tier thresholds (moat index).
TIER_STRONG_INDEX: float = 0.60
TIER_MODERATE_INDEX: float = 0.40

# Verdict thresholds (weighted market moat index).
VERDICT_STRONG_INDEX: float = 0.60
VERDICT_MODERATE_INDEX: float = 0.40

# A STRONG verdict is withheld while weak clusters cover at least this
# much of the market — a large exposed segment is not a strong moat.
WEAK_SHARE_GUARD: float = 0.50

# Market-level gap flags fire below this weighted lever score.
GAP_THRESHOLD: float = 0.50

# Incumbent brand loyalty is "entrenched" above this weighted score.
LOYALTY_ENTRENCHED: float = 0.60

# A category is "vacant" when this share of the covered market has no
# competition flag from CompetitiveDynamicsArchitect.
VACANT_SHARE: float = 0.90

# Free-competitor flag fires above this covered-market share.
FREE_COMPETITOR_SHARE: float = 0.50

# Neutral defaults for metrics missing from a malformed/partial payload.
# They lean middle-of-road so a missing field neither manufactures a
# STRONG verdict nor hides a real weakness present in other levers.
DEFAULT_FEATURE_PARITY: float = 0.50
DEFAULT_BRAND_TRUST: float = 0.50
DEFAULT_PRICING_POWER: float = 0.50
DEFAULT_DISTRIBUTION: float = 0.50
DEFAULT_LOCK_IN: float = 0.50
DEFAULT_COMPETITOR_LOYALTY: float = 0.50
DEFAULT_DISPLACEMENT_DAYS: float = 45.0

MIN_DISPLACEMENT_DAYS: int = 1
MAX_DISPLACEMENT_DAYS: int = 365

# Product types this read supports: every type whose conductor stack runs
# CompetitiveDynamicsArchitect. Derived from the canonical enum so newly
# added types are covered automatically; drift-guard tests lock the set
# to actual conductor activation.
COMPETITIVE_MOAT_PRODUCT_TYPES: frozenset[str] = frozenset(
    pt.value for pt in ProductType
)

# Per-cluster flag groups surfaced on the profile (architect -> flags).
ARCHITECT_FLAG_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "CompetitiveDynamicsArchitect",
        (
            "switching_friction_critical",
            "feature_parity_not_met",
            "free_competitor_present",
            "no_competition",
        ),
    ),
    (
        "TrustArchitect",
        ("brand_deficit_critical", "social_proof_missing"),
    ),
    ("PricingArchitect", ("pricing_is_kill_shot",)),
    (
        "DistributionChannelArchitect",
        ("distribution_kill_shot", "try_before_buy_critical", "influencer_required"),
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


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _fmt_pct(value: float) -> str:
    return f"{_clamp(value) * 100:.0f}%"


def _architect_block(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
    architect: str,
) -> dict[str, Any]:
    """Extract one architect's block (metrics + flags) for a cluster."""
    if not conductor_results:
        return {}
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return {}
    block = cluster_block.get(architect)
    return block if isinstance(block, dict) else {}


def _lever_scores(
    comp_metrics: dict[str, Any],
    trust_metrics: dict[str, Any],
    pricing_metrics: dict[str, Any],
    dist_metrics: dict[str, Any],
) -> dict[str, tuple[float, bool]]:
    """Five lever scores (0..1, higher = stronger moat) with availability.

    A lever is available only when its architect actually produced a
    metrics block for the cluster (e.g. distribution metrics only exist
    for hardware product types). Missing fields inside a present block
    fall back to neutral 0.50.
    """
    return {
        LEVER_FEATURE_PARITY: (
            _clamp(
                _safe_float(
                    comp_metrics.get("feature_parity_met"),
                    DEFAULT_FEATURE_PARITY,
                )
            ),
            True,
        ),
        LEVER_BRAND_TRUST: (
            _clamp(
                _safe_float(
                    trust_metrics.get("brand_deficit_multiplier"),
                    DEFAULT_BRAND_TRUST,
                )
            ),
            bool(trust_metrics),
        ),
        LEVER_PRICING_POWER: (
            _clamp(
                _safe_float(
                    pricing_metrics.get("will_pay_probability"),
                    DEFAULT_PRICING_POWER,
                )
            ),
            bool(pricing_metrics),
        ),
        LEVER_DISTRIBUTION: (
            _clamp(
                _safe_float(
                    dist_metrics.get("distribution_accessibility_multiplier"),
                    DEFAULT_DISTRIBUTION,
                )
            ),
            bool(dist_metrics),
        ),
        LEVER_LOCK_IN: (
            _clamp(
                _safe_float(
                    comp_metrics.get("loss_aversion_magnitude"),
                    DEFAULT_LOCK_IN,
                )
            ),
            True,
        ),
    }


def _moat_index(levers: dict[str, tuple[float, bool]]) -> float:
    """Weighted mean of the available levers, renormalized by weight."""
    total_weight = 0.0
    acc = 0.0
    for lever in LEVER_ORDER:
        score, available = levers.get(lever, (0.0, False))
        if not available:
            continue
        acc += LEVER_WEIGHTS[lever] * score
        total_weight += LEVER_WEIGHTS[lever]
    if total_weight <= 0.0:
        return 0.0
    return _clamp(acc / total_weight)


def _weakest_lever(
    levers: dict[str, tuple[float, bool]],
) -> tuple[str, float]:
    """Lowest available lever; ties resolve to the earlier LEVER_ORDER key."""
    best_key = LEVER_ORDER[0]
    best_score = levers.get(best_key, (0.0, False))[0]
    for key in LEVER_ORDER[1:]:
        score, available = levers.get(key, (0.0, False))
        if not available:
            continue
        if score < best_score:
            best_key = key
            best_score = score
    return best_key, round(best_score, 4)


def _moat_tier(index: float) -> str:
    if index >= TIER_STRONG_INDEX:
        return TIER_STRONG
    if index >= TIER_MODERATE_INDEX:
        return TIER_MODERATE
    return TIER_WEAK


def _cluster_flags(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> list[str]:
    flags: list[str] = []
    for architect, flag_names in ARCHITECT_FLAG_GROUPS:
        block = _architect_block(conductor_results, cluster_id, architect)
        raw_flags = block.get("flags")
        if not isinstance(raw_flags, dict):
            continue
        for name in flag_names:
            if raw_flags.get(name) is True:
                flags.append(name)
    return flags


def _weighted_average(
    rows: list[dict[str, Any]],
    key: str,
) -> float:
    total_weight = 0.0
    acc = 0.0
    for row in rows:
        weight = max(0.0, row["population_weight"])
        if weight <= 0.0:
            continue
        acc += weight * row[key]
        total_weight += weight
    if total_weight <= 0.0:
        return 0.0
    return acc / total_weight


def _lever_weighted_average(rows: list[dict[str, Any]], lever: str) -> float:
    total_weight = 0.0
    acc = 0.0
    for row in rows:
        weight = max(0.0, row["population_weight"])
        if weight <= 0.0 or not row["levers_available"][lever]:
            continue
        acc += weight * row["levers"][lever]
        total_weight += weight
    if total_weight <= 0.0:
        return 0.0
    return acc / total_weight


def _lever_recommendation(lever: str, share: float) -> str:
    actions: dict[str, str] = {
        LEVER_FEATURE_PARITY: (
            "Feature parity is the weakest moat lever for {share} of the "
            "covered market — ship the capabilities competitors already "
            "match before scaling acquisition."
        ),
        LEVER_BRAND_TRUST: (
            "Brand trust is the weakest moat lever for {share} of the "
            "covered market — invest in social proof, case studies and "
            "credible press before competing on price."
        ),
        LEVER_PRICING_POWER: (
            "Pricing power is the weakest moat lever for {share} of the "
            "covered market — revisit the offer and AOV so customers will "
            "pay without heavy discounting."
        ),
        LEVER_DISTRIBUTION: (
            "Distribution reach is the weakest moat lever for {share} of "
            "the covered market — expand channel coverage before the "
            "competition owns the shelf."
        ),
        LEVER_LOCK_IN: (
            "Switching lock-in is the weakest moat lever for {share} of "
            "the covered market — add integrations, workflow depth and "
            "migration costs to make leaving harder."
        ),
    }
    return actions[lever].format(share=_fmt_pct(share))


def build_competitive_moat(
    results: dict[str, Any] | None,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    conductor_results: dict[str, Any] | None = None,
    cluster_registry: list[dict[str, Any]] | None = None,
    product_type: str = "saas",
) -> CompetitiveMoatOut:
    """Compose the competitive-moat read from completed results.

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
    supported = product_type_name in COMPETITIVE_MOAT_PRODUCT_TYPES
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

        comp_metrics = _architect_block(
            conductor_results, cid, "CompetitiveDynamicsArchitect"
        ).get("metrics")
        if not isinstance(comp_metrics, dict) or not comp_metrics:
            continue
        trust_metrics = _architect_block(
            conductor_results, cid, "TrustArchitect"
        ).get("metrics")
        pricing_metrics = _architect_block(
            conductor_results, cid, "PricingArchitect"
        ).get("metrics")
        dist_metrics = _architect_block(
            conductor_results, cid, "DistributionChannelArchitect"
        ).get("metrics")
        trust_metrics = trust_metrics if isinstance(trust_metrics, dict) else {}
        pricing_metrics = (
            pricing_metrics if isinstance(pricing_metrics, dict) else {}
        )
        dist_metrics = dist_metrics if isinstance(dist_metrics, dict) else {}

        levers = _lever_scores(
            comp_metrics,
            trust_metrics,
            pricing_metrics,
            dist_metrics,
        )
        index = round(_moat_index(levers), 4)
        weakest, weakest_score = _weakest_lever(levers)
        displacement_days = int(
            max(
                MIN_DISPLACEMENT_DAYS,
                min(
                    MAX_DISPLACEMENT_DAYS,
                    _safe_float(
                        comp_metrics.get("competitive_displacement_days"),
                        DEFAULT_DISPLACEMENT_DAYS,
                    ),
                ),
            )
        )
        competitor_loyalty = _clamp(
            _safe_float(
                comp_metrics.get("competitor_brand_loyalty_strength"),
                DEFAULT_COMPETITOR_LOYALTY,
            )
        )
        flags = _cluster_flags(conductor_results, cid)

        covered_weight += weight
        rows.append(
            {
                "cluster_id": cid,
                "cluster_name": str(entry.get("name", "") or cid),
                "population_weight": weight,
                "levers": {
                    key: round(score, 4)
                    for key, (score, _) in levers.items()
                },
                "levers_available": {
                    key: available for key, (_, available) in levers.items()
                },
                "moat_index": index,
                "tier": _moat_tier(index),
                "weakest_lever": weakest,
                "weakest_score": weakest_score,
                "displacement_days": displacement_days,
                "competitor_loyalty": competitor_loyalty,
                "flags": flags,
                "free_competitor": "free_competitor_present" in flags,
                "no_competition": "no_competition" in flags,
            }
        )

    meta: dict[str, Any] = {
        "signal_quality": signal_quality,
        "total_clusters": len(registry),
        "covered_clusters": len(rows),
        "covered_weight": round(covered_weight, 4),
        "product_type_supported": supported,
        "levers_available": {key: False for key in LEVER_ORDER},
        "weighted_competitor_loyalty": 0.0,
        "free_competitor_share": 0.0,
        "no_competition_share": 0.0,
        "thresholds": {
            "verdict_strong_index": VERDICT_STRONG_INDEX,
            "verdict_moderate_index": VERDICT_MODERATE_INDEX,
            "tier_strong_index": TIER_STRONG_INDEX,
            "tier_moderate_index": TIER_MODERATE_INDEX,
            "weak_share_guard": WEAK_SHARE_GUARD,
            "gap_threshold": GAP_THRESHOLD,
            "loyalty_entrenched": LOYALTY_ENTRENCHED,
            "vacant_share": VACANT_SHARE,
            "free_competitor_share": FREE_COMPETITOR_SHARE,
        },
    }

    if not supported:
        return CompetitiveMoatOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                (
                    f"Competitive moat is not modeled for "
                    f"{product_type_name} — this read requires "
                    "CompetitiveDynamicsArchitect metrics, which are only "
                    "produced for the supported product types."
                )
            ],
            meta=meta,
        )

    if not rows or covered_weight <= 0.0:
        return CompetitiveMoatOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                "No per-cluster CompetitiveDynamicsArchitect metrics were "
                "available for this run."
            ],
            meta=meta,
        )

    moat_index_avg = _weighted_average(rows, "moat_index")
    lever_averages: dict[str, float] = {}
    for lever in LEVER_ORDER:
        value = _lever_weighted_average(rows, lever)
        lever_averages[lever] = value
        meta["levers_available"][lever] = any(
            row["levers_available"][lever] for row in rows
        )

    strong_weight = sum(
        row["population_weight"] for row in rows if row["tier"] == TIER_STRONG
    )
    moderate_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_MODERATE
    )
    weak_weight = sum(
        row["population_weight"] for row in rows if row["tier"] == TIER_WEAK
    )
    strong_share = strong_weight / covered_weight
    moderate_share = moderate_weight / covered_weight
    weak_share = weak_weight / covered_weight

    if (
        moat_index_avg >= VERDICT_STRONG_INDEX
        and weak_share < WEAK_SHARE_GUARD
    ):
        verdict = VERDICT_STRONG
    elif moat_index_avg >= VERDICT_MODERATE_INDEX:
        verdict = VERDICT_MODERATE
    else:
        verdict = VERDICT_WEAK

    # Market lever distribution = population-weighted share of per-cluster
    # weakest-lever attributions.
    lever_weights: dict[str, float] = {key: 0.0 for key in LEVER_ORDER}
    for row in rows:
        lever_weights[row["weakest_lever"]] += row["population_weight"]
    lever_distribution = {
        key: round(weight / covered_weight, 4)
        for key, weight in lever_weights.items()
    }
    primary_lever = LEVER_ORDER[0]
    primary_share = lever_distribution[primary_lever]
    for key in LEVER_ORDER[1:]:
        if lever_distribution[key] > primary_share:
            primary_lever = key
            primary_share = lever_distribution[key]

    competitor_loyalty_avg = _weighted_average(rows, "competitor_loyalty")
    free_competitor_share = (
        sum(
            row["population_weight"]
            for row in rows
            if row["free_competitor"]
        )
        / covered_weight
    )
    no_competition_share = (
        sum(
            row["population_weight"]
            for row in rows
            if row["no_competition"]
        )
        / covered_weight
    )
    meta["weighted_competitor_loyalty"] = round(competitor_loyalty_avg, 4)
    meta["free_competitor_share"] = round(free_competitor_share, 4)
    meta["no_competition_share"] = round(no_competition_share, 4)

    flags: list[str] = []
    if lever_averages[LEVER_FEATURE_PARITY] < GAP_THRESHOLD:
        flags.append("feature_parity_gap")
    if lever_averages[LEVER_BRAND_TRUST] < GAP_THRESHOLD:
        flags.append("brand_trust_gap")
    if lever_averages[LEVER_PRICING_POWER] < GAP_THRESHOLD:
        flags.append("pricing_power_gap")
    if lever_averages[LEVER_DISTRIBUTION] < GAP_THRESHOLD:
        flags.append("distribution_gap")
    if lever_averages[LEVER_LOCK_IN] < GAP_THRESHOLD:
        flags.append("switching_lock_in_gap")
    if free_competitor_share >= FREE_COMPETITOR_SHARE:
        flags.append("free_competitor_present")
    if competitor_loyalty_avg >= LOYALTY_ENTRENCHED:
        flags.append("incumbent_loyalty_entrenched")
    if no_competition_share >= VACANT_SHARE:
        flags.append("vacant_category")
    if weak_share >= WEAK_SHARE_GUARD:
        flags.append("weak_moat_concentration")

    recommendations: list[str] = [
        _lever_recommendation(primary_lever, primary_share)
    ]
    if "feature_parity_gap" in flags:
        recommendations.append(
            "Feature parity is weak market-wide — treat missing parity "
            "as a launch blocker, not a follow-up sprint."
        )
    if "brand_trust_gap" in flags:
        recommendations.append(
            "Brand trust is weak market-wide — earn credibility with "
            "evidence, reviews and founder-led proof before scaling ads."
        )
    if "pricing_power_gap" in flags:
        recommendations.append(
            "Pricing power is weak market-wide — test value-based tiers "
            "and annual plans before committing to discount-led growth."
        )
    if "distribution_gap" in flags:
        recommendations.append(
            "Distribution reach is weak market-wide — line up channel "
            "partners before the competitors own the shelf."
        )
    if "switching_lock_in_gap" in flags:
        recommendations.append(
            "Switching costs are low market-wide — build integrations, "
            "workflow depth and data portability costs into the product."
        )
    if "free_competitor_present" in flags:
        recommendations.append(
            "Free alternatives are entrenched across the covered market — "
            "differentiate on outcomes, onboarding and support, not price."
        )
    if "incumbent_loyalty_entrenched" in flags:
        recommendations.append(
            "Incumbent brand loyalty is entrenched — target switchers "
            "with migration tools and side-by-side comparisons."
        )
    if "vacant_category" in flags:
        recommendations.append(
            "The covered market has no incumbent presence — move fast to "
            "define the category standard and capture the mental shelf."
        )
    if verdict == VERDICT_STRONG and len(flags) == 0:
        recommendations.append(
            "Your moat is strong across the covered market — invest "
            "defensively in the strongest levers and expand reach before "
            "competitors enter."
        )

    protected = sorted(
        rows,
        key=lambda row: (
            -row["moat_index"],
            -row["population_weight"],
            row["cluster_id"],
        ),
    )[:5]
    vulnerable = sorted(
        rows,
        key=lambda row: (
            row["moat_index"],
            -row["population_weight"],
            row["cluster_id"],
        ),
    )[:5]

    return CompetitiveMoatOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type_name,
        verdict=verdict,
        moat_index=round(moat_index_avg, 4),
        weighted_feature_parity=round(lever_averages[LEVER_FEATURE_PARITY], 4),
        weighted_brand_trust=round(lever_averages[LEVER_BRAND_TRUST], 4),
        weighted_pricing_power=round(lever_averages[LEVER_PRICING_POWER], 4),
        weighted_distribution_reach=round(
            lever_averages[LEVER_DISTRIBUTION], 4
        ),
        weighted_switching_lock_in=round(
            lever_averages[LEVER_LOCK_IN], 4
        ),
        strong_share=round(strong_share, 4),
        moderate_share=round(moderate_share, 4),
        weak_share=round(weak_share, 4),
        primary_weakest_lever=primary_lever,
        primary_weakest_lever_label=LEVER_LABELS[primary_lever],
        primary_weakest_lever_share=round(primary_share, 4),
        lever_distribution=lever_distribution,
        cluster_profiles=[
            ClusterMoatProfile(
                cluster_id=row["cluster_id"],
                cluster_name=row["cluster_name"],
                population_weight=round(row["population_weight"], 4),
                moat_index=row["moat_index"],
                moat_tier=row["tier"],
                levers=row["levers"],
                weakest_lever=row["weakest_lever"],
                displacement_days=row["displacement_days"],
                flags=row["flags"],
            )
            for row in rows
        ],
        top_protected=[
            MoatOpportunity(
                cluster_id=row["cluster_id"],
                cluster_name=row["cluster_name"],
                population_weight=round(row["population_weight"], 4),
                moat_index=row["moat_index"],
                moat_tier=row["tier"],
                weakest_lever=row["weakest_lever"],
            )
            for row in protected
        ],
        top_vulnerable=[
            MoatOpportunity(
                cluster_id=row["cluster_id"],
                cluster_name=row["cluster_name"],
                population_weight=round(row["population_weight"], 4),
                moat_index=row["moat_index"],
                moat_tier=row["tier"],
                weakest_lever=row["weakest_lever"],
            )
            for row in vulnerable
        ],
        flags=flags,
        recommendations=recommendations,
        meta=meta,
    )


__all__ = [
    "COMPETITIVE_MOAT_PRODUCT_TYPES",
    "LEVER_ORDER",
    "LEVER_WEIGHTS",
    "TIER_MODERATE_INDEX",
    "TIER_STRONG_INDEX",
    "VALID_LEVERS",
    "VERDICT_MODERATE_INDEX",
    "VERDICT_STRONG_INDEX",
    "build_competitive_moat",
]
