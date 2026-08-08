"""
Pure market-timing analysis for completed simulation results.

Answers the founder's "is now the right time to launch, and where is the
readiness concentrated?" question by turning the
``MarketTimingArchitect`` per-cluster metrics into a deterministic,
population-weighted launch-readiness read:

* **Timing index** — a 0..1 market-weighted composite of category
  awareness, problem urgency, budget-cycle alignment, technology
  adoption, switching comfort and category-education comfort, multiplied
  by the regulatory suppressor (0.4 when the brief signals regulatory
  dependency, otherwise 1.0). The weights mirror the architect's
  transition logic: awareness x urgency x regulation gates ARRIVE→BROWSE
  and education cost x budget gates BROWSE→CONSIDER.
* **Cluster tiers** — every covered cluster is classified
  ``BLOCKED`` (regulatory suppressor < 0.9) / ``READY_NOW``
  (index >= 0.60) / ``ALMOST_READY`` (>= 0.40) / ``EARLY`` (< 0.40, or
  category awareness below 0.30 even when the composite is higher).
* **Primary readiness gate** — each cluster is attributed to the
  weakest of the seven modeled gates (regulation, category awareness,
  problem urgency, category-education cost, switching cost, technology
  adoption, budget cycle). The market-level gate distribution is the
  population-weighted share of those attributions, and the top gates
  drive recommendations.
* **Verdict** — ``GO`` when the weighted timing index is at least 0.60
  and regulatory-blocked clusters cover under 15% of the market,
  ``CAUTIOUS`` at 0.40, ``WAIT`` below that, and
  ``INSUFFICIENT_DATA`` when no cluster has usable metrics.

The covered market is the population weight of clusters with usable
metrics and a positive population share; zero-weight clusters are
excluded from profiles, flags, gate shares and top opportunities.
``meta`` carries the weighted ``primary_gate_score`` (0..1 severity of
each cluster's weakest gate) and the thresholds used for tiers and
verdicts.

No DB / I/O — verifiable without FastAPI or PostgreSQL. The route layer
supplies ``results``, ``conductor_results`` (per-cluster architect
metrics) and ``cluster_registry``; all arithmetic is deterministic.
Metrics missing from a malformed/partial payload use neutral defaults
(awareness 0.35, urgency 0.45, switching cost 0.40, budget alignment
0.60, adoption 0.40, creation cost 0.50, trigger sensitivity 0.50,
seasonal coefficient 1.00, pricing power 0.60, regulatory risk 0.10,
suppressor 1.00) so a missing field never manufactures a GO verdict or a
regulatory block.
"""
from __future__ import annotations

import json
import math
from typing import Any

from app.schemas.market_timing import (
    GATE_ADOPTION,
    GATE_AWARENESS,
    GATE_BUDGET,
    GATE_EDUCATION,
    GATE_REGULATORY,
    GATE_SWITCHING,
    GATE_URGENCY,
    TIER_ALMOST,
    TIER_BLOCKED,
    TIER_EARLY,
    TIER_READY,
    VERDICT_CAUTIOUS,
    VERDICT_GO,
    VERDICT_INSUFFICIENT,
    VERDICT_WAIT,
    ClusterTimingProfile,
    MarketTimingOut,
    TopOpportunity,
)

# Ordered gate keys — used for tie-breaking and market aggregation so the
# output is stable regardless of dict ordering.
GATE_ORDER: tuple[str, ...] = (
    GATE_REGULATORY,
    GATE_AWARENESS,
    GATE_URGENCY,
    GATE_EDUCATION,
    GATE_SWITCHING,
    GATE_ADOPTION,
    GATE_BUDGET,
)

GATE_LABELS: dict[str, str] = {
    GATE_REGULATORY: "Regulatory pathway",
    GATE_AWARENESS: "Category awareness",
    GATE_URGENCY: "Problem urgency",
    GATE_EDUCATION: "Category-education cost",
    GATE_SWITCHING: "Switching cost",
    GATE_ADOPTION: "Technology adoption",
    GATE_BUDGET: "Budget-cycle alignment",
}

# Cluster-tier thresholds (timing index).
TIER_READY_INDEX: float = 0.60
TIER_ALMOST_INDEX: float = 0.40

# Verdict thresholds (weighted market timing index).
VERDICT_GO_INDEX: float = 0.60
VERDICT_CAUTIOUS_INDEX: float = 0.40

# A GO verdict is withheld while regulatory-blocked clusters cover this
# much of the market — regulation is a hard launch gate.
GO_BLOCKED_SHARE_LIMIT: float = 0.15

# A cluster is BLOCKED below this suppressor value (the architect emits
# 0.40 when the brief signals regulatory dependency, 1.00 otherwise).
BLOCKED_SUPPRESSOR: float = 0.90

# Below this awareness, the category does not exist in consumers' minds:
# the cluster is EARLY even if the composite index looks moderate.
AWARENESS_EARLY: float = 0.30

# Regulatory-gate normalization: suppressor 1.0 -> 0.0, 0.4 -> 1.0.
REG_GATE_NORMALIZER: float = 1.0 / 0.6

# Neutral defaults for metrics missing from a malformed/partial payload.
# They lean middle-of-road so a missing field neither manufactures a GO
# verdict nor hides a real gate present in other metrics.
DEFAULT_AWARENESS: float = 0.35
DEFAULT_URGENCY: float = 0.45
DEFAULT_SWITCHING: float = 0.40
DEFAULT_BUDGET: float = 0.60
DEFAULT_ADOPTION: float = 0.40
DEFAULT_TRIGGER: float = 0.50
DEFAULT_CREATION_COST: float = 0.50
DEFAULT_SEASONAL: float = 1.00
DEFAULT_PRICING_POWER: float = 0.60
DEFAULT_REG_RISK: float = 0.10
DEFAULT_REG_SUPPRESSOR: float = 1.00

# Flag thresholds.
FLAG_AWARENESS_THRESHOLD: float = 0.40
FLAG_URGENCY_THRESHOLD: float = 0.40
FLAG_EDUCATION_THRESHOLD: float = 0.50
FLAG_SEASONAL_THRESHOLD: float = 1.05
FLAG_TRIGGER_THRESHOLD: float = 0.50
FLAG_PRICING_POWER_THRESHOLD: float = 0.55


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


def _timing_metrics(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> dict[str, Any]:
    """Extract the MarketTimingArchitect metrics block for one cluster."""
    if not conductor_results:
        return {}
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return {}
    architect = cluster_block.get("MarketTimingArchitect")
    if not isinstance(architect, dict):
        return {}
    metrics = architect.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _timing_index(metrics: dict[str, Any]) -> float:
    """Composite 0..1 launch-readiness score mirroring MarketTimingArchitect's
    transition logic (awareness x urgency x regulation gate ARRIVE→BROWSE;
    education cost x budget gate BROWSE→CONSIDER)."""
    awareness = _clamp(
        _safe_float(
            metrics.get("category_awareness_score"),
            DEFAULT_AWARENESS,
        )
    )
    urgency = _clamp(
        _safe_float(
            metrics.get("problem_urgency_intensity"),
            DEFAULT_URGENCY,
        )
    )
    switching_comfort = _clamp(
        1.0
        - _clamp(
            _safe_float(
                metrics.get("switching_cost_depth"),
                DEFAULT_SWITCHING,
            )
        )
    )
    budget = _clamp(
        _safe_float(
            metrics.get("budget_cycle_alignment"),
            DEFAULT_BUDGET,
        )
    )
    adoption = _clamp(
        _safe_float(
            metrics.get("technology_adoption_score"),
            DEFAULT_ADOPTION,
        )
    )
    education_comfort = _clamp(
        1.0
        - _clamp(
            _safe_float(
                metrics.get("category_creation_cost"),
                DEFAULT_CREATION_COST,
            )
        )
    )
    reg_suppressor = _clamp(
        _safe_float(
            metrics.get("regulatory_suppressor"),
            DEFAULT_REG_SUPPRESSOR,
        )
    )
    base = (
        0.25 * awareness
        + 0.20 * urgency
        + 0.15 * budget
        + 0.15 * adoption
        + 0.15 * switching_comfort
        + 0.10 * education_comfort
    )
    return _clamp(base * reg_suppressor)


def _gate_scores(metrics: dict[str, Any]) -> dict[str, float]:
    """Normalized readiness-gate scores (0..1, higher = more blocking)."""
    reg_suppressor = _clamp(
        _safe_float(
            metrics.get("regulatory_suppressor"),
            DEFAULT_REG_SUPPRESSOR,
        )
    )
    awareness = _clamp(
        _safe_float(
            metrics.get("category_awareness_score"),
            DEFAULT_AWARENESS,
        )
    )
    urgency = _clamp(
        _safe_float(
            metrics.get("problem_urgency_intensity"),
            DEFAULT_URGENCY,
        )
    )
    switching = _clamp(
        _safe_float(
            metrics.get("switching_cost_depth"),
            DEFAULT_SWITCHING,
        )
    )
    budget = _clamp(
        _safe_float(
            metrics.get("budget_cycle_alignment"),
            DEFAULT_BUDGET,
        )
    )
    adoption = _clamp(
        _safe_float(
            metrics.get("technology_adoption_score"),
            DEFAULT_ADOPTION,
        )
    )
    creation_cost = _clamp(
        _safe_float(
            metrics.get("category_creation_cost"),
            DEFAULT_CREATION_COST,
        )
    )
    return {
        GATE_REGULATORY: round(
            _clamp((1.0 - reg_suppressor) * REG_GATE_NORMALIZER),
            4,
        ),
        GATE_AWARENESS: round(1.0 - awareness, 4),
        GATE_URGENCY: round(1.0 - urgency, 4),
        GATE_EDUCATION: round(creation_cost, 4),
        GATE_SWITCHING: round(switching, 4),
        GATE_ADOPTION: round(1.0 - adoption, 4),
        GATE_BUDGET: round(1.0 - budget, 4),
    }


def _primary_gate(scores: dict[str, float]) -> tuple[str, float]:
    """Weakest gate; ties resolve to the earlier key in GATE_ORDER."""
    best_key = GATE_ORDER[0]
    best_value = scores.get(best_key, 0.0)
    for key in GATE_ORDER[1:]:
        value = scores.get(key, 0.0)
        if value > best_value:
            best_key = key
            best_value = value
    return best_key, round(best_value, 4)


def _readiness_tier(
    metrics: dict[str, Any],
    timing_index: float,
) -> str:
    reg_suppressor = _clamp(
        _safe_float(
            metrics.get("regulatory_suppressor"),
            DEFAULT_REG_SUPPRESSOR,
        )
    )
    awareness = _clamp(
        _safe_float(
            metrics.get("category_awareness_score"),
            DEFAULT_AWARENESS,
        )
    )
    if reg_suppressor < BLOCKED_SUPPRESSOR:
        return TIER_BLOCKED
    if awareness < AWARENESS_EARLY:
        return TIER_EARLY
    if timing_index >= TIER_READY_INDEX:
        return TIER_READY
    if timing_index >= TIER_ALMOST_INDEX:
        return TIER_ALMOST
    return TIER_EARLY


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


def _gate_recommendation(gate: str, share: float) -> str:
    actions: dict[str, str] = {
        GATE_REGULATORY: (
            "Map the regulatory pathway before launch: regulation is the "
            "primary readiness gate for {share} of the covered market."
        ),
        GATE_AWARENESS: (
            "Invest in category education first: awareness is the primary "
            "readiness gate for {share} of the covered market."
        ),
        GATE_URGENCY: (
            "Lead with problem-trigger messaging: weak urgency is the "
            "primary readiness gate for {share} of the covered market."
        ),
        GATE_EDUCATION: (
            "Lower the cost of first understanding: category-creation cost "
            "is the primary readiness gate for {share} of the covered "
            "market."
        ),
        GATE_SWITCHING: (
            "Build a switching or migration path: switching cost is the "
            "primary readiness gate for {share} of the covered market."
        ),
        GATE_ADOPTION: (
            "Anchor the launch on early-adopter segments: technology "
            "adoption is the primary readiness gate for {share} of the "
            "covered market."
        ),
        GATE_BUDGET: (
            "Time the launch to the buying cycle: budget alignment is the "
            "primary readiness gate for {share} of the covered market."
        ),
    }
    return actions[gate].format(share=_fmt_pct(share))


def build_market_timing(
    results: dict[str, Any] | None,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    conductor_results: dict[str, Any] | None = None,
    cluster_registry: list[dict[str, Any]] | None = None,
    product_type: str = "saas",
) -> MarketTimingOut:
    """Compose the market-timing read from completed results.

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
        # and gate shares so the read stays a true covered-market view.
        if weight <= 0.0:
            continue
        metrics = _timing_metrics(conductor_results, cid)
        if not metrics:
            continue

        awareness = _clamp(
            _safe_float(
                metrics.get("category_awareness_score"),
                DEFAULT_AWARENESS,
            )
        )
        urgency = _clamp(
            _safe_float(
                metrics.get("problem_urgency_intensity"),
                DEFAULT_URGENCY,
            )
        )
        switching = _clamp(
            _safe_float(
                metrics.get("switching_cost_depth"),
                DEFAULT_SWITCHING,
            )
        )
        budget = _clamp(
            _safe_float(
                metrics.get("budget_cycle_alignment"),
                DEFAULT_BUDGET,
            )
        )
        adoption = _clamp(
            _safe_float(
                metrics.get("technology_adoption_score"),
                DEFAULT_ADOPTION,
            )
        )
        trigger = _clamp(
            _safe_float(
                metrics.get("trigger_event_sensitivity"),
                DEFAULT_TRIGGER,
            )
        )
        creation_cost = _clamp(
            _safe_float(
                metrics.get("category_creation_cost"),
                DEFAULT_CREATION_COST,
            )
        )
        seasonal = max(
            0.0,
            _safe_float(
                metrics.get("seasonal_demand_coefficient"),
                DEFAULT_SEASONAL,
            ),
        )
        pricing_power = max(
            0.0,
            _safe_float(
                metrics.get("market_maturity_pricing_power"),
                DEFAULT_PRICING_POWER,
            ),
        )
        reg_risk = _clamp(
            _safe_float(
                metrics.get("regulatory_dependency_risk"),
                DEFAULT_REG_RISK,
            )
        )
        reg_suppressor = _clamp(
            _safe_float(
                metrics.get("regulatory_suppressor"),
                DEFAULT_REG_SUPPRESSOR,
            )
        )

        timing_index = round(_timing_index(metrics), 4)
        gate, gate_score = _primary_gate(_gate_scores(metrics))
        tier = _readiness_tier(metrics, timing_index)
        covered_weight += weight
        rows.append(
            {
                "cluster_id": cid,
                "cluster_name": str(entry.get("name", "") or cid),
                "population_weight": weight,
                "awareness": awareness,
                "urgency": urgency,
                "switching": switching,
                "budget": budget,
                "adoption": adoption,
                "trigger": trigger,
                "creation_cost": creation_cost,
                "seasonal": seasonal,
                "pricing_power": pricing_power,
                "reg_risk": reg_risk,
                "reg_suppressor": reg_suppressor,
                "timing_index": timing_index,
                "tier": tier,
                "gate": gate,
                "gate_score": gate_score,
            }
        )

    meta: dict[str, Any] = {
        "signal_quality": signal_quality,
        "total_clusters": len(registry),
        "covered_clusters": len(rows),
        "covered_weight": round(covered_weight, 4),
        "primary_gate_score": 0.0,
        "product_type_supported": True,
        "thresholds": {
            "verdict_go_index": VERDICT_GO_INDEX,
            "verdict_cautious_index": VERDICT_CAUTIOUS_INDEX,
            "tier_ready_index": TIER_READY_INDEX,
            "tier_almost_index": TIER_ALMOST_INDEX,
            "blocked_suppressor": BLOCKED_SUPPRESSOR,
            "awareness_early": AWARENESS_EARLY,
            "go_blocked_share_limit": GO_BLOCKED_SHARE_LIMIT,
        },
    }

    if not rows or covered_weight <= 0.0:
        return MarketTimingOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                "No per-cluster MarketTimingArchitect metrics were "
                "available for this run."
            ],
            meta=meta,
        )

    timing_index_avg = _weighted_average(rows, "timing_index")
    awareness_avg = _weighted_average(rows, "awareness")
    urgency_avg = _weighted_average(rows, "urgency")
    switching_avg = _weighted_average(rows, "switching")
    budget_avg = _weighted_average(rows, "budget")
    adoption_avg = _weighted_average(rows, "adoption")
    trigger_avg = _weighted_average(rows, "trigger")
    creation_cost_avg = _weighted_average(rows, "creation_cost")
    seasonal_avg = _weighted_average(rows, "seasonal")
    pricing_power_avg = _weighted_average(rows, "pricing_power")
    reg_risk_avg = _weighted_average(rows, "reg_risk")
    reg_suppressor_avg = _weighted_average(rows, "reg_suppressor")

    ready_weight = sum(
        row["population_weight"] for row in rows if row["tier"] == TIER_READY
    )
    almost_weight = sum(
        row["population_weight"] for row in rows if row["tier"] == TIER_ALMOST
    )
    early_weight = sum(
        row["population_weight"] for row in rows if row["tier"] == TIER_EARLY
    )
    blocked_weight = sum(
        row["population_weight"] for row in rows if row["tier"] == TIER_BLOCKED
    )
    ready_share = ready_weight / covered_weight
    almost_ready_share = almost_weight / covered_weight
    early_share = early_weight / covered_weight
    blocked_share = blocked_weight / covered_weight

    if (
        timing_index_avg >= VERDICT_GO_INDEX
        and blocked_share < GO_BLOCKED_SHARE_LIMIT
    ):
        verdict = VERDICT_GO
    elif timing_index_avg >= VERDICT_CAUTIOUS_INDEX:
        verdict = VERDICT_CAUTIOUS
    else:
        verdict = VERDICT_WAIT

    # Market gate distribution = population-weighted share of per-cluster
    # primary-gate attributions.
    gate_weights: dict[str, float] = {key: 0.0 for key in GATE_ORDER}
    for row in rows:
        gate_weights[row["gate"]] += row["population_weight"]
    gate_distribution = {
        key: round(weight / covered_weight, 4)
        for key, weight in gate_weights.items()
    }
    primary_gate = GATE_ORDER[0]
    primary_gate_share = gate_distribution[primary_gate]
    for key in GATE_ORDER[1:]:
        if gate_distribution[key] > primary_gate_share:
            primary_gate = key
            primary_gate_share = gate_distribution[key]
    # Market-level severity of the attributed gate: population-weighted
    # average of each cluster's weakest-gate score (0 = no gate, 1 = fully
    # blocked). Surfaced in meta so a GO read with a residual education gap
    # is not mistaken for a perfectly frictionless launch.
    primary_gate_score = _weighted_average(rows, "gate_score")
    meta["primary_gate_score"] = round(primary_gate_score, 4)

    flags: list[str] = []
    if blocked_share > 0.0:
        flags.append("regulatory_blocked_market")
    if awareness_avg < FLAG_AWARENESS_THRESHOLD:
        flags.append("low_category_awareness")
    if urgency_avg < FLAG_URGENCY_THRESHOLD:
        flags.append("weak_problem_urgency")
    if creation_cost_avg > FLAG_EDUCATION_THRESHOLD:
        flags.append("category_education_gap")
    if seasonal_avg > FLAG_SEASONAL_THRESHOLD:
        flags.append("seasonal_demand_lift")
    if trigger_avg > FLAG_TRIGGER_THRESHOLD:
        flags.append("trigger_sensitive_segments")
    if pricing_power_avg < FLAG_PRICING_POWER_THRESHOLD:
        flags.append("weak_pricing_power")

    recommendations: list[str] = [
        _gate_recommendation(primary_gate, primary_gate_share)
    ]
    if blocked_share > 0.0:
        recommendations.append(
            "Regulatory blockers affect "
            f"{_fmt_pct(blocked_share)} of the covered market — sequence "
            "the launch into compliant segments first."
        )
    if ready_share >= 0.5:
        recommendations.append(
            f"{_fmt_pct(ready_share)} of the covered market is ready now — "
            "prioritize READY_NOW clusters for the launch beachhead."
        )
    if seasonal_avg > FLAG_SEASONAL_THRESHOLD:
        recommendations.append(
            "Seasonal demand lift applies market-wide "
            f"(x{seasonal_avg:.2f}) — align the launch window with it."
        )

    opportunities = sorted(
        (
            row
            for row in rows
            if row["tier"] in (TIER_READY, TIER_ALMOST)
        ),
        key=lambda row: (
            -row["timing_index"],
            -row["population_weight"],
            row["cluster_id"],
        ),
    )[:5]

    return MarketTimingOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type_name,
        verdict=verdict,
        timing_index=round(timing_index_avg, 4),
        weighted_category_awareness=round(awareness_avg, 4),
        weighted_problem_urgency=round(urgency_avg, 4),
        weighted_switching_cost=round(switching_avg, 4),
        weighted_budget_cycle_alignment=round(budget_avg, 4),
        weighted_technology_adoption=round(adoption_avg, 4),
        weighted_trigger_sensitivity=round(trigger_avg, 4),
        weighted_category_creation_cost=round(creation_cost_avg, 4),
        weighted_seasonal_coefficient=round(seasonal_avg, 4),
        weighted_pricing_power=round(pricing_power_avg, 4),
        weighted_regulatory_risk=round(reg_risk_avg, 4),
        weighted_regulatory_suppressor=round(reg_suppressor_avg, 4),
        ready_share=round(ready_share, 4),
        almost_ready_share=round(almost_ready_share, 4),
        early_share=round(early_share, 4),
        blocked_share=round(blocked_share, 4),
        primary_gate=primary_gate,
        primary_gate_label=GATE_LABELS[primary_gate],
        primary_gate_share=round(primary_gate_share, 4),
        gate_distribution=gate_distribution,
        cluster_profiles=[
            ClusterTimingProfile(
                cluster_id=row["cluster_id"],
                cluster_name=row["cluster_name"],
                population_weight=round(row["population_weight"], 4),
                category_awareness_score=round(row["awareness"], 4),
                problem_urgency_intensity=round(row["urgency"], 4),
                switching_cost_depth=round(row["switching"], 4),
                budget_cycle_alignment=round(row["budget"], 4),
                technology_adoption_score=round(row["adoption"], 4),
                trigger_event_sensitivity=round(row["trigger"], 4),
                category_creation_cost=round(row["creation_cost"], 4),
                seasonal_demand_coefficient=round(row["seasonal"], 4),
                market_maturity_pricing_power=round(row["pricing_power"], 4),
                regulatory_dependency_risk=round(row["reg_risk"], 4),
                regulatory_suppressor=round(row["reg_suppressor"], 4),
                timing_index=row["timing_index"],
                readiness_tier=row["tier"],
                primary_gate=row["gate"],
                primary_gate_score=row["gate_score"],
            )
            for row in rows
        ],
        top_opportunities=[
            TopOpportunity(
                cluster_id=row["cluster_id"],
                cluster_name=row["cluster_name"],
                population_weight=round(row["population_weight"], 4),
                timing_index=row["timing_index"],
                readiness_tier=row["tier"],
                primary_gate=row["gate"],
            )
            for row in opportunities
        ],
        flags=flags,
        recommendations=recommendations,
        meta=meta,
    )
