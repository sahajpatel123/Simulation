"""
Pure after-sales lifecycle analysis for completed simulation results.

Answers the founder's "what happens after the purchase, and which
post-purchase risk is most likely to bleed revenue?" question by
turning the ``AftersalesLifecycleArchitect`` per-cluster metrics into a
deterministic, population-weighted read:

* **After-sales index** — a 0..1 market-weighted composite
  (higher = healthier) of 30-day support contact (20%), repeat-purchase
  brand loyalty (25%), warranty claim likelihood (15%), negative-review
  risk (10%), spare-parts concern (10%), expected product lifespan
  (10%) and accessory attach (10%). Every component is normalized
  against the architect's modeled ranges so higher severities always
  mean worse after-sales health.
* **Cluster tiers** — every covered cluster is classified ``STRONG``
  (index >= 0.70) / ``OK`` (>= 0.55) / ``FRAGILE`` (>= 0.40) /
  ``AT_RISK`` (< 0.40).
* **Primary after-sales risk** — each cluster is attributed to the
  worst of six modeled risks (support burden, loyalty gap, warranty
  claims, negative-review risk, spare-parts concern, lifespan risk).
  The market-level risk distribution is the population-weighted share
  of those attributions.
* **After-sales levers** — nine interventions (self-service support,
  extended warranty, loyalty program, accessory bundles, refurbishment
  program, review response, spare-parts guarantee, sustainability
  comms, lifespan roadmap) ranked by the share of the covered market
  where the underlying signal is present.

The verdict is ``HEALTHY`` when the weighted after-sales index is at
least 0.70, ``WATCH`` at 0.55, ``STRAINED`` at 0.40, ``AT_RISK`` below
that, and ``INSUFFICIENT_DATA`` when no cluster has usable metrics.
``AftersalesLifecycleArchitect`` activates for consumer_hardware,
health_hardware, iot_hardware, wearable and b2b_hardware stacks, so
the read is supported for exactly those product types and reports
``product_type_supported: false`` otherwise. The flag is derived from
the run's product type alone, not from metric availability: a
supported hardware run whose metrics are missing still reports
``product_type_supported: true`` (with an explicit "no metrics"
recommendation), and an unsupported run returns
``INSUFFICIENT_DATA`` even if stray metrics are present.

The covered market is the population weight of clusters with usable
metrics and a positive population share; zero-weight clusters are
excluded from profiles, flags and lever shares. ``meta`` also carries a
``primary_risk_score`` (0..1, population-weighted severity of each
cluster's worst after-sales risk) so a ``HEALTHY`` verdict with a
residual tie-break risk is not mistaken for a clean post-purchase
experience.

No DB / I/O — verifiable without FastAPI or PostgreSQL. The route layer
supplies ``results``, ``conductor_results`` (per-cluster architect
metrics), ``cluster_registry`` and the detected product type; all
arithmetic is deterministic. Metrics missing from a malformed/partial
payload use neutral defaults (warranty 0.05, repair threshold 0.50,
support 0.10, accessory attach 0.50, refurbished 0.15, sustainability
0.20, loyalty 0.50, review 0.20, spare parts 0.05, lifespan 3.0 years)
so a missing field never manufactures an AT_RISK tier, an extreme
risk, or a false lever/flag. Every default sits strictly on the "no
risk" side of the lever and flag thresholds below.
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable

from app.schemas.after_sales import (
    AfterSalesLever,
    AfterSalesOut,
    ClusterAfterSalesProfile,
    LEVER_ACCESSORY_BUNDLES,
    LEVER_EXTENDED_WARRANTY,
    LEVER_LIFESPAN_ROADMAP,
    LEVER_LOYALTY_PROGRAM,
    LEVER_REFURBISHMENT_PROGRAM,
    LEVER_REVIEW_RESPONSE,
    LEVER_SPARE_PARTS,
    LEVER_SUPPORT_SELF_SERVICE,
    LEVER_SUSTAINABILITY_COMMS,
    RISK_LIFESPAN,
    RISK_LOYALTY_GAP,
    RISK_REVIEW,
    RISK_SPARE_PARTS,
    RISK_SUPPORT_BURDEN,
    RISK_WARRANTY_CLAIMS,
    SUPPORTED_PRODUCT_TYPES,
    TIER_AT_RISK,
    TIER_FRAGILE,
    TIER_OK,
    TIER_STRONG,
    VERDICT_AT_RISK,
    VERDICT_HEALTHY,
    VERDICT_INSUFFICIENT,
    VERDICT_STRAINED,
    VERDICT_WATCH,
)

# Ordered risk keys — used for tie-breaking and market aggregation so
# the output is stable regardless of dict ordering.
RISK_ORDER: tuple[str, ...] = (
    RISK_SUPPORT_BURDEN,
    RISK_LOYALTY_GAP,
    RISK_WARRANTY_CLAIMS,
    RISK_REVIEW,
    RISK_SPARE_PARTS,
    RISK_LIFESPAN,
)

RISK_LABELS: dict[str, str] = {
    RISK_SUPPORT_BURDEN: "High 30-day support contact",
    RISK_LOYALTY_GAP: "Low repeat-purchase loyalty",
    RISK_WARRANTY_CLAIMS: "Elevated warranty claims",
    RISK_REVIEW: "Negative review risk",
    RISK_SPARE_PARTS: "Spare-parts concern",
    RISK_LIFESPAN: "Short expected product lifespan",
}

LEVER_LABELS: dict[str, str] = {
    LEVER_SUPPORT_SELF_SERVICE: "Self-service support & diagnostics",
    LEVER_EXTENDED_WARRANTY: "Transparent extended warranty",
    LEVER_LOYALTY_PROGRAM: "Repeat-purchase loyalty / trade-in",
    LEVER_ACCESSORY_BUNDLES: "Accessory bundles at point of sale",
    LEVER_REFURBISHMENT_PROGRAM: "Certified refurbishment / trade-in tiers",
    LEVER_REVIEW_RESPONSE: "Proactive review follow-up & response",
    LEVER_SPARE_PARTS: "Spare-parts availability guarantee",
    LEVER_SUSTAINABILITY_COMMS: "Repairability & sustainability comms",
    LEVER_LIFESPAN_ROADMAP: "Replacement / upgrade roadmap",
}

# Cluster-tier thresholds (after-sales index; higher = better).
TIER_STRONG_INDEX: float = 0.70
TIER_OK_INDEX: float = 0.55
TIER_FRAGILE_INDEX: float = 0.40

# Verdict thresholds (weighted market after-sales index).
VERDICT_HEALTHY_INDEX: float = 0.70
VERDICT_WATCH_INDEX: float = 0.55
VERDICT_STRAINED_INDEX: float = 0.40

# Lifespan normalization anchors for lifespan risk
# (0..1, higher = worse). The architect models expected lifespans
# between ~1.5 and ~5.5 years depending on average order value, so a
# 4-year ceiling keeps cheap-hardware lifespans from dominating every
# other after-sales risk.
LIFESPAN_MIN_YEARS: float = 1.0
LIFESPAN_MAX_YEARS: float = 4.0

# Composite weights (sum to 1.0).
WEIGHT_SUPPORT: float = 0.20
WEIGHT_LOYALTY: float = 0.25
WEIGHT_WARRANTY: float = 0.15
WEIGHT_REVIEW: float = 0.10
WEIGHT_SPARE: float = 0.10
WEIGHT_LIFESPAN: float = 0.10
WEIGHT_ACCESSORY: float = 0.10

# Neutral defaults for metrics missing from a malformed/partial payload.
# They lean middle-of-road so a missing field neither manufactures an
# AT_RISK tier / false lever / false flag nor hides a real risk present
# in other metrics. Each default sits strictly on the "no risk" side of
# the corresponding lever/flag triggers.
DEFAULT_WARRANTY_CLAIM: float = 0.05
DEFAULT_REPAIR_THRESHOLD: float = 0.50
DEFAULT_SUPPORT_30D: float = 0.10
DEFAULT_ACCESSORY_ATTACH: float = 0.50
DEFAULT_REFURBISHED: float = 0.15
DEFAULT_SUSTAINABILITY: float = 0.20
DEFAULT_BRAND_LOYALTY: float = 0.50
DEFAULT_REVIEW_LIKELY: float = 0.20
DEFAULT_SPARE_CONCERN: float = 0.05
DEFAULT_LIFESPAN_Y: float = 3.0

# Lever opportunity thresholds — a lever applies to a cluster when the
# underlying signal crosses the line.
LEVER_SELF_SERVICE_SUPPORT_MIN: float = 0.25
LEVER_EXTENDED_WARRANTY_MIN: float = 0.09
LEVER_LOYALTY_MAX: float = 0.45
LEVER_ACCESSORY_MAX: float = 0.35
LEVER_REFURBISHED_MIN: float = 0.25
LEVER_REVIEW_RISK_MIN: float = 0.30
LEVER_SPARE_CONCERN_MIN: float = 0.12
LEVER_SUSTAINABILITY_MIN: float = 0.30
LEVER_LIFESPAN_RISK_MIN: float = 0.65

# Flag thresholds (weighted market aggregates; higher = worse except
# loyalty, lifespan, and accessory attach where higher = better).
FLAG_SUPPORT_MAX: float = 0.40
FLAG_LOYALTY_MIN: float = 0.30
FLAG_WARRANTY_MAX: float = 0.11
FLAG_REVIEW_RISK_MAX: float = 0.25
FLAG_SPARE_MAX: float = 0.12
FLAG_LIFESPAN_MIN_YEARS: float = 2.0
FLAG_ACCESSORY_MAX: float = 0.35


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


def _after_sales_metrics(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> dict[str, Any]:
    """Extract the AftersalesLifecycleArchitect metrics block for one
    cluster."""
    if not conductor_results:
        return {}
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return {}
    architect = cluster_block.get("AftersalesLifecycleArchitect")
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
    architect = cluster_block.get("AftersalesLifecycleArchitect")
    if not isinstance(architect, dict):
        return []
    flags = architect.get("flags")
    if not isinstance(flags, dict):
        return []
    return sorted(
        key for key, value in flags.items() if bool(value)
    )


def _lifespan_risk(lifespan_y: float) -> float:
    """Normalized short-lifespan severity (0..1, higher = worse)."""
    span = max(
        LIFESPAN_MIN_YEARS,
        min(LIFESPAN_MAX_YEARS, lifespan_y),
    )
    return _clamp(
        (LIFESPAN_MAX_YEARS - span)
        / (LIFESPAN_MAX_YEARS - LIFESPAN_MIN_YEARS)
    )


def _risks(metrics: dict[str, Any]) -> dict[str, float]:
    """Normalized after-sales risk severities for one cluster
    (0..1, higher = worse)."""
    support = _clamp(
        _safe_float(
            metrics.get("support_contact_rate_30d"),
            DEFAULT_SUPPORT_30D,
        )
    )
    loyalty = _clamp(
        _safe_float(
            metrics.get("brand_loyalty_next_purchase"),
            DEFAULT_BRAND_LOYALTY,
        )
    )
    warranty = _clamp(
        _safe_float(
            metrics.get("warranty_claim_likelihood"),
            DEFAULT_WARRANTY_CLAIM,
        )
    )
    review_likely = _clamp(
        _safe_float(
            metrics.get("review_writing_likelihood"),
            DEFAULT_REVIEW_LIKELY,
        )
    )
    spare = _clamp(
        _safe_float(
            metrics.get("spare_parts_concern"),
            DEFAULT_SPARE_CONCERN,
        )
    )
    lifespan = max(
        0.0,
        _safe_float(
            metrics.get("expected_product_lifespan_y"),
            DEFAULT_LIFESPAN_Y,
        ),
    )
    return {
        RISK_SUPPORT_BURDEN: round(support, 4),
        RISK_LOYALTY_GAP: round(1.0 - loyalty, 4),
        RISK_WARRANTY_CLAIMS: round(warranty, 4),
        # Review activity is only risky when the cluster is dissatisfied;
        # brand loyalty is the closest satisfaction proxy in the metrics.
        RISK_REVIEW: round(
            _clamp(review_likely * (1.0 - loyalty)),
            4,
        ),
        RISK_SPARE_PARTS: round(spare, 4),
        RISK_LIFESPAN: round(_lifespan_risk(lifespan), 4),
    }


def _primary_risk(risks: dict[str, float]) -> tuple[str, float]:
    """Worst after-sales risk; ties resolve to the earlier key in
    RISK_ORDER."""
    best_key = RISK_ORDER[0]
    best_value = risks.get(best_key, 0.0)
    for key in RISK_ORDER[1:]:
        value = risks.get(key, 0.0)
        if value > best_value:
            best_key = key
            best_value = value
    return best_key, round(best_value, 4)


def _after_sales_index(risks: dict[str, float], attach: float) -> float:
    """Composite 0..1 after-sales health score (higher = better)."""
    health = (
        WEIGHT_SUPPORT * (1.0 - risks.get(RISK_SUPPORT_BURDEN, 0.0))
        + WEIGHT_LOYALTY * (1.0 - risks.get(RISK_LOYALTY_GAP, 0.0))
        + WEIGHT_WARRANTY
        * (1.0 - risks.get(RISK_WARRANTY_CLAIMS, 0.0))
        + WEIGHT_REVIEW * (1.0 - risks.get(RISK_REVIEW, 0.0))
        + WEIGHT_SPARE * (1.0 - risks.get(RISK_SPARE_PARTS, 0.0))
        + WEIGHT_LIFESPAN * (1.0 - risks.get(RISK_LIFESPAN, 0.0))
        + WEIGHT_ACCESSORY * attach
    )
    return _clamp(health)


def _after_sales_tier(index: float) -> str:
    if index >= TIER_STRONG_INDEX:
        return TIER_STRONG
    if index >= TIER_OK_INDEX:
        return TIER_OK
    if index >= TIER_FRAGILE_INDEX:
        return TIER_FRAGILE
    return TIER_AT_RISK


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
) -> AfterSalesLever:
    share = _opportunity_share(rows, predicate)
    return AfterSalesLever(
        key=key,
        label=LEVER_LABELS[key],
        market_value=round(_weighted_average(rows, metric_key), 4),
        opportunity_share=round(share, 4),
        action=action.format(share=_fmt_pct(share)),
    )


def build_after_sales_read(
    results: dict[str, Any] | None,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    conductor_results: dict[str, Any] | None = None,
    cluster_registry: list[dict[str, Any]] | None = None,
    product_type: str = "saas",
) -> AfterSalesOut:
    """Compose the after-sales lifecycle read from completed results.

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
    product_type_supported = product_type_name in SUPPORTED_PRODUCT_TYPES

    meta: dict[str, Any] = {
        "signal_quality": signal_quality,
        "total_clusters": len(registry),
        "covered_clusters": 0,
        "covered_weight": 0.0,
        "primary_risk_score": 0.0,
        "product_type_supported": product_type_supported,
        "supported_product_types": sorted(SUPPORTED_PRODUCT_TYPES),
        "thresholds": {
            "tier_strong_index": TIER_STRONG_INDEX,
            "tier_ok_index": TIER_OK_INDEX,
            "tier_fragile_index": TIER_FRAGILE_INDEX,
            "verdict_healthy_index": VERDICT_HEALTHY_INDEX,
            "verdict_watch_index": VERDICT_WATCH_INDEX,
            "verdict_strained_index": VERDICT_STRAINED_INDEX,
            "flag_support_max": FLAG_SUPPORT_MAX,
            "flag_loyalty_min": FLAG_LOYALTY_MIN,
            "flag_warranty_max": FLAG_WARRANTY_MAX,
            "flag_review_risk_max": FLAG_REVIEW_RISK_MAX,
            "flag_spare_max": FLAG_SPARE_MAX,
            "flag_lifespan_min_years": FLAG_LIFESPAN_MIN_YEARS,
            "flag_accessory_max": FLAG_ACCESSORY_MAX,
        },
        "normalization": {
            "lifespan_min_years": LIFESPAN_MIN_YEARS,
            "lifespan_max_years": LIFESPAN_MAX_YEARS,
        },
    }

    if not product_type_supported:
        return AfterSalesOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                "AftersalesLifecycleArchitect only activates for "
                "consumer_hardware, health_hardware, iot_hardware, "
                "wearable and b2b_hardware product types — this run "
                "does not use that stack."
            ],
            meta=meta,
        )

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
        metrics = _after_sales_metrics(conductor_results, cid)
        if not metrics:
            continue

        warranty = _clamp(
            _safe_float(
                metrics.get("warranty_claim_likelihood"),
                DEFAULT_WARRANTY_CLAIM,
            )
        )
        repair_threshold = _clamp(
            _safe_float(
                metrics.get("repair_vs_replace_threshold"),
                DEFAULT_REPAIR_THRESHOLD,
            )
        )
        support = _clamp(
            _safe_float(
                metrics.get("support_contact_rate_30d"),
                DEFAULT_SUPPORT_30D,
            )
        )
        attach = _clamp(
            _safe_float(
                metrics.get("accessory_attach_rate"),
                DEFAULT_ACCESSORY_ATTACH,
            )
        )
        refurbished = _clamp(
            _safe_float(
                metrics.get("refurbished_participation"),
                DEFAULT_REFURBISHED,
            )
        )
        sustainability = _clamp(
            _safe_float(
                metrics.get("sustainability_concern"),
                DEFAULT_SUSTAINABILITY,
            )
        )
        loyalty = _clamp(
            _safe_float(
                metrics.get("brand_loyalty_next_purchase"),
                DEFAULT_BRAND_LOYALTY,
            )
        )
        review_likely = _clamp(
            _safe_float(
                metrics.get("review_writing_likelihood"),
                DEFAULT_REVIEW_LIKELY,
            )
        )
        spare = _clamp(
            _safe_float(
                metrics.get("spare_parts_concern"),
                DEFAULT_SPARE_CONCERN,
            )
        )
        lifespan = max(
            0.0,
            _safe_float(
                metrics.get("expected_product_lifespan_y"),
                DEFAULT_LIFESPAN_Y,
            ),
        )

        risks = _risks(metrics)
        index = _after_sales_index(risks, attach)
        risk, risk_score = _primary_risk(risks)
        covered_weight += weight
        rows.append(
            {
                "cluster_id": cid,
                "cluster_name": str(entry.get("name", "") or cid),
                "population_weight": weight,
                "warranty": warranty,
                "repair_threshold": repair_threshold,
                "support": support,
                "attach": attach,
                "refurbished": refurbished,
                "sustainability": sustainability,
                "loyalty": loyalty,
                "review_likely": review_likely,
                "spare": spare,
                "lifespan": lifespan,
                "risks": risks,
                "index": index,
                "tier": _after_sales_tier(index),
                "risk": risk,
                "risk_score": risk_score,
                "architect_flags": _architect_flags(
                    conductor_results, cid
                ),
            }
        )
    meta["covered_clusters"] = len(rows)
    meta["covered_weight"] = round(covered_weight, 4)

    if not rows or covered_weight <= 0.0:
        return AfterSalesOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                "No per-cluster AftersalesLifecycleArchitect metrics "
                "were available for this run."
            ],
            meta=meta,
        )

    index_avg = _weighted_average(rows, "index")
    warranty_avg = _weighted_average(rows, "warranty")
    repair_threshold_avg = _weighted_average(rows, "repair_threshold")
    support_avg = _weighted_average(rows, "support")
    attach_avg = _weighted_average(rows, "attach")
    refurbished_avg = _weighted_average(rows, "refurbished")
    sustainability_avg = _weighted_average(rows, "sustainability")
    loyalty_avg = _weighted_average(rows, "loyalty")
    review_likely_avg = _weighted_average(rows, "review_likely")
    spare_avg = _weighted_average(rows, "spare")
    lifespan_avg = _weighted_average(rows, "lifespan")
    review_risk_avg = (
        sum(
            row["population_weight"] * row["risks"][RISK_REVIEW]
            for row in rows
        )
        / covered_weight
    )

    strong_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_STRONG
    )
    ok_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_OK
    )
    fragile_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_FRAGILE
    )
    at_risk_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_AT_RISK
    )
    strong_share = strong_weight / covered_weight
    ok_share = ok_weight / covered_weight
    fragile_share = fragile_weight / covered_weight
    at_risk_share = at_risk_weight / covered_weight

    if index_avg >= VERDICT_HEALTHY_INDEX:
        verdict = VERDICT_HEALTHY
    elif index_avg >= VERDICT_WATCH_INDEX:
        verdict = VERDICT_WATCH
    elif index_avg >= VERDICT_STRAINED_INDEX:
        verdict = VERDICT_STRAINED
    else:
        verdict = VERDICT_AT_RISK

    # Market risk distribution = population-weighted share of
    # per-cluster primary-risk attributions.
    risk_weights: dict[str, float] = {key: 0.0 for key in RISK_ORDER}
    for row in rows:
        risk_weights[row["risk"]] += row["population_weight"]
    risk_distribution = {
        key: round(weight / covered_weight, 4)
        for key, weight in risk_weights.items()
    }
    primary_risk = RISK_ORDER[0]
    primary_risk_share = risk_distribution[primary_risk]
    for key in RISK_ORDER[1:]:
        if risk_distribution[key] > primary_risk_share:
            primary_risk = key
            primary_risk_share = risk_distribution[key]
    # Market-level severity of the attributed risk: population-weighted
    # average of each cluster's worst normalized after-sales score.
    primary_risk_score = _weighted_average(rows, "risk_score")
    meta["primary_risk_score"] = round(primary_risk_score, 4)

    flags: list[str] = []
    if any(row["tier"] == TIER_AT_RISK for row in rows):
        flags.append("at_risk_after_sales_clusters")
    if support_avg >= FLAG_SUPPORT_MAX:
        flags.append("high_support_burden")
    if loyalty_avg < FLAG_LOYALTY_MIN:
        flags.append("low_brand_loyalty")
    if warranty_avg >= FLAG_WARRANTY_MAX:
        flags.append("warranty_pressure")
    if review_risk_avg >= FLAG_REVIEW_RISK_MAX:
        flags.append("negative_review_risk")
    if spare_avg >= FLAG_SPARE_MAX:
        flags.append("spare_parts_concern")
    if lifespan_avg < FLAG_LIFESPAN_MIN_YEARS:
        flags.append("short_lifespan")
    if attach_avg < FLAG_ACCESSORY_MAX:
        flags.append("accessory_headroom")
    if any(
        "low_brand_loyalty" in row["architect_flags"]
        for row in rows
    ):
        flags.append("low_loyalty_clusters_present")
    if any(
        "high_support_burden" in row["architect_flags"]
        for row in rows
    ):
        flags.append("high_support_clusters_present")
    if any(
        "review_risk_high" in row["architect_flags"]
        for row in rows
    ):
        flags.append("review_risk_clusters_present")

    levers: list[AfterSalesLever] = [
        _lever(
            rows,
            LEVER_SUPPORT_SELF_SERVICE,
            "support",
            lambda row: (
                row["risks"][RISK_SUPPORT_BURDEN]
                >= LEVER_SELF_SERVICE_SUPPORT_MIN
            ),
            "Add self-service support (help center, diagnostics, "
            "chat) — {share} of the covered market contacts support "
            "within 30 days.",
        ),
        _lever(
            rows,
            LEVER_EXTENDED_WARRANTY,
            "warranty",
            lambda row: (
                row["risks"][RISK_WARRANTY_CLAIMS]
                >= LEVER_EXTENDED_WARRANTY_MIN
            ),
            "Offer a transparent extended warranty / premium support "
            "tier — {share} of the covered market is likely to file "
            "warranty claims.",
        ),
        _lever(
            rows,
            LEVER_LOYALTY_PROGRAM,
            "loyalty",
            lambda row: (
                row["loyalty"] < LEVER_LOYALTY_MAX
            ),
            "Launch a repeat-purchase loyalty / trade-in program — "
            "{share} of the covered market has low next-purchase "
            "loyalty.",
        ),
        _lever(
            rows,
            LEVER_ACCESSORY_BUNDLES,
            "attach",
            lambda row: (
                row["attach"] < LEVER_ACCESSORY_MAX
            ),
            "Bundle accessories at point of sale — {share} of the "
            "covered market under-adopts accessories.",
        ),
        _lever(
            rows,
            LEVER_REFURBISHMENT_PROGRAM,
            "refurbished",
            lambda row: (
                row["refurbished"] >= LEVER_REFURBISHED_MIN
            ),
            "Offer certified refurbished / trade-in tiers — {share} of "
            "the covered market is interested in refurbished options.",
        ),
        _lever(
            rows,
            LEVER_REVIEW_RESPONSE,
            "review_likely",
            lambda row: (
                row["risks"][RISK_REVIEW] >= LEVER_REVIEW_RISK_MIN
            ),
            "Proactively follow up and respond to reviews — {share} of "
            "the covered market combines review activity with low "
            "satisfaction.",
        ),
        _lever(
            rows,
            LEVER_SPARE_PARTS,
            "spare",
            lambda row: (
                row["risks"][RISK_SPARE_PARTS]
                >= LEVER_SPARE_CONCERN_MIN
            ),
            "Guarantee spare-parts availability and repairability — "
            "{share} of the covered market worries about spare parts.",
        ),
        _lever(
            rows,
            LEVER_SUSTAINABILITY_COMMS,
            "sustainability",
            lambda row: (
                row["sustainability"] >= LEVER_SUSTAINABILITY_MIN
            ),
            "Communicate repairability and sustainability credentials "
            "— {share} of the covered market is sustainability-"
            "concerned.",
        ),
        _lever(
            rows,
            LEVER_LIFESPAN_ROADMAP,
            "lifespan",
            lambda row: (
                row["risks"][RISK_LIFESPAN] >= LEVER_LIFESPAN_RISK_MIN
            ),
            "Offer a replacement / upgrade roadmap — {share} of the "
            "covered market expects a short useful life.",
        ),
    ]
    levers.sort(key=lambda lever: (-lever.opportunity_share, lever.key))

    recommendations: list[str] = []
    if verdict == VERDICT_HEALTHY:
        recommendations.append(
            f"After-sales health is strong (weighted after-sales index "
            f"= {index_avg:.2f}) — the covered market shows manageable "
            "support load, decent repeat-purchase loyalty and limited "
            "post-purchase risk."
        )
    elif verdict == VERDICT_WATCH:
        recommendations.append(
            f"After-sales health is workable but not clean (index = "
            f"{index_avg:.2f}, {_fmt_pct(at_risk_share)} already "
            "AT_RISK) — pull the strongest lever below before scaling."
        )
    elif verdict == VERDICT_STRAINED:
        recommendations.append(
            f"After-sales health is strained (index = {index_avg:.2f}, "
            f"{_fmt_pct(fragile_share + at_risk_share)} of the covered "
            "market FRAGILE or worse) — expect support cost and churn "
            "to eat into unit economics."
        )
    else:
        recommendations.append(
            f"After-sales health is a launch risk (index = "
            f"{index_avg:.2f}, {_fmt_pct(at_risk_share)} of the covered "
            "market AT_RISK) — treat post-purchase experience as part "
            "of the core product."
        )
    recommendations.append(
        f"Primary after-sales risk: {RISK_LABELS[primary_risk]} "
        f"(severity {primary_risk_score:.2f}, affects "
        f"{_fmt_pct(primary_risk_share)} of the covered market)."
    )
    recommendations.append(
        f"Average 30-day support contact is {_fmt_pct(support_avg)} "
        f"and repeat-purchase loyalty averages "
        f"{_fmt_pct(loyalty_avg)} — every point of support friction "
        "directly lowers next-purchase revenue."
    )
    if support_avg >= FLAG_SUPPORT_MAX:
        recommendations.append(
            f"Support load is high ({_fmt_pct(support_avg)} of the "
            "covered market contacts support within 30 days) — invest "
            "in self-service diagnostics and first-contact resolution."
        )
    if loyalty_avg < FLAG_LOYALTY_MIN:
        recommendations.append(
            f"Repeat-purchase loyalty is only {_fmt_pct(loyalty_avg)} "
            "— launch a loyalty / trade-in loop before relying on "
            "accessory revenue."
        )
    if warranty_avg >= FLAG_WARRANTY_MAX:
        recommendations.append(
            f"Warranty claims average {_fmt_pct(warranty_avg)} — "
            "price reliability guarantees honestly and provision "
            "support capacity."
        )
    if review_risk_avg >= FLAG_REVIEW_RISK_MAX:
        recommendations.append(
            f"Negative-review risk is elevated ({_fmt_pct(review_risk_avg)} "
            "of the covered market) — follow up after delivery and "
            "respond to low-star reviews quickly."
        )
    if spare_avg >= FLAG_SPARE_MAX:
        recommendations.append(
            f"Spare-parts concern is {_fmt_pct(spare_avg)} — publish a "
            "parts availability guarantee to reduce repair anxiety."
        )
    if lifespan_avg < FLAG_LIFESPAN_MIN_YEARS:
        recommendations.append(
            f"Expected product lifespan averages only "
            f"{lifespan_avg:.1f} years — a transparent upgrade roadmap "
            "can turn short lifecycles into planned repurchases."
        )
    if attach_avg < FLAG_ACCESSORY_MAX:
        recommendations.append(
            f"Accessory attach is only {_fmt_pct(attach_avg)} — bundle "
            "accessories at point of sale to lift average order value "
            "without extra acquisition spend."
        )

    return AfterSalesOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type_name,
        verdict=verdict,
        after_sales_index=round(index_avg, 4),
        weighted_warranty_claim_likelihood=round(warranty_avg, 4),
        weighted_repair_vs_replace_threshold=round(
            repair_threshold_avg, 4
        ),
        weighted_support_contact_rate_30d=round(support_avg, 4),
        weighted_accessory_attach_rate=round(attach_avg, 4),
        weighted_refurbished_participation=round(refurbished_avg, 4),
        weighted_sustainability_concern=round(sustainability_avg, 4),
        weighted_brand_loyalty_next_purchase=round(loyalty_avg, 4),
        weighted_review_writing_likelihood=round(review_likely_avg, 4),
        weighted_spare_parts_concern=round(spare_avg, 4),
        weighted_expected_product_lifespan_y=round(lifespan_avg, 4),
        strong_share=round(strong_share, 4),
        ok_share=round(ok_share, 4),
        fragile_share=round(fragile_share, 4),
        at_risk_share=round(at_risk_share, 4),
        primary_risk=primary_risk,
        primary_risk_label=RISK_LABELS[primary_risk],
        primary_risk_share=round(primary_risk_share, 4),
        risk_distribution=risk_distribution,
        cluster_profiles=[
            ClusterAfterSalesProfile(
                cluster_id=row["cluster_id"],
                cluster_name=row["cluster_name"],
                population_weight=round(row["population_weight"], 4),
                warranty_claim_likelihood=row["warranty"],
                repair_vs_replace_threshold=row["repair_threshold"],
                support_contact_rate_30d=row["support"],
                accessory_attach_rate=row["attach"],
                refurbished_participation=row["refurbished"],
                sustainability_concern=row["sustainability"],
                brand_loyalty_next_purchase=row["loyalty"],
                review_writing_likelihood=row["review_likely"],
                spare_parts_concern=row["spare"],
                expected_product_lifespan_y=row["lifespan"],
                after_sales_index=round(row["index"], 4),
                after_sales_tier=row["tier"],
                primary_risk=row["risk"],
                primary_risk_score=row["risk_score"],
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
    "FLAG_ACCESSORY_MAX",
    "FLAG_LIFESPAN_MIN_YEARS",
    "FLAG_LOYALTY_MIN",
    "FLAG_REVIEW_RISK_MAX",
    "FLAG_SPARE_MAX",
    "FLAG_SUPPORT_MAX",
    "FLAG_WARRANTY_MAX",
    "LEVER_ACCESSORY_MAX",
    "LEVER_EXTENDED_WARRANTY_MIN",
    "LEVER_LIFESPAN_RISK_MIN",
    "LEVER_LOYALTY_MAX",
    "LEVER_REFURBISHED_MIN",
    "LEVER_REVIEW_RISK_MIN",
    "LEVER_SELF_SERVICE_SUPPORT_MIN",
    "LEVER_SPARE_CONCERN_MIN",
    "LEVER_SUSTAINABILITY_MIN",
    "LIFESPAN_MAX_YEARS",
    "LIFESPAN_MIN_YEARS",
    "RISK_LABELS",
    "RISK_ORDER",
    "TIER_FRAGILE_INDEX",
    "TIER_OK_INDEX",
    "TIER_STRONG_INDEX",
    "VERDICT_HEALTHY_INDEX",
    "VERDICT_STRAINED_INDEX",
    "VERDICT_WATCH_INDEX",
    "WEIGHT_ACCESSORY",
    "WEIGHT_LIFESPAN",
    "WEIGHT_LOYALTY",
    "WEIGHT_REVIEW",
    "WEIGHT_SPARE",
    "WEIGHT_SUPPORT",
    "WEIGHT_WARRANTY",
    "_after_sales_index",
    "_after_sales_tier",
    "_lifespan_risk",
    "_primary_risk",
    "_risks",
    "build_after_sales_read",
]
