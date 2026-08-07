"""
Pure assumption-cascade analysis for completed simulation results.

Answers the founder's "which assumptions, if wrong, cascade into
failure?" question by turning the ``AssumptionCascadeArchitect``
per-cluster metrics into a deterministic, population-weighted read:

* **Cascade index** — a 0..1 population-weighted composite risk score
  (higher = worse) built directly from the architect's modeled
  ``total_cascade_risk``, so the read mirrors exactly what the
  simulation used to gate its correction layer.
* **Cluster tiers** — every covered cluster is classified ``LOW``
  (risk < 0.20) / ``ELEVATED`` (>= 0.20, or a validation blind-spot
  flag) / ``HIGH`` (>= 0.40, or a dual-failure flag) / ``CRITICAL``
  (>= 0.60, or an existential-risk flag).
* **Primary blocker** — each cluster is attributed to its most severe
  cascade blocker (existential risk, compound dual-assumption failure,
  validation blind spots, sensitive segments, or none). The market
  distribution is the population-weighted share of those
  attributions, and the top blocker drives the recommendations.
* **Verdict** — ``STABLE`` when the weighted cascade index is below
  0.20, ``WATCH`` below 0.35, ``RISKY`` below 0.50, and
  ``HIGH_RISK`` at or above 0.50 (or when CRITICAL clusters cover at
  least 30% of the covered market), and ``INSUFFICIENT_DATA`` when no
  cluster has usable architect metrics.

The covered market is the population weight of clusters with usable
metrics and a positive population share; zero-weight clusters are
excluded from profiles, shares, flags and blocker distributions.
``meta`` carries the weighted blind-spot score, positive-cascade share,
verdict/tier thresholds and the primary-blocker severity.

No DB / I/O — verifiable without FastAPI or PostgreSQL. The route layer
supplies ``results``, ``conductor_results`` (per-cluster architect
metrics), ``cluster_registry`` and the detected product type; all
arithmetic is deterministic. Metrics missing from a malformed/partial
payload use neutral defaults (0.0) and a metrics block with none of the
cascade keys is treated as uncovered, so a missing field never
manufactures risk or hides a real blocker present in other metrics.
"""
from __future__ import annotations

import json
import math
from typing import Any

from app.schemas.assumption_cascade import (
    BLOCKER_BLIND_SPOT,
    BLOCKER_DUAL_FAILURE,
    BLOCKER_EXISTENTIAL,
    BLOCKER_LABELS,
    BLOCKER_NONE,
    BLOCKER_SENSITIVE_SEGMENTS,
    TIER_CRITICAL,
    TIER_ELEVATED,
    TIER_HIGH,
    TIER_LOW,
    VALID_BLOCKERS,
    VERDICT_HIGH_RISK,
    VERDICT_INSUFFICIENT,
    VERDICT_RISKY,
    VERDICT_STABLE,
    VERDICT_WATCH,
    AssumptionCascadeOut,
    ClusterCascadeProfile,
)

# Cluster-tier thresholds (cascade risk; higher = worse).
TIER_LOW_INDEX: float = 0.20
TIER_ELEVATED_INDEX: float = 0.40
TIER_HIGH_INDEX: float = 0.60

# Verdict thresholds (weighted market cascade index).
VERDICT_STABLE_INDEX: float = 0.20
VERDICT_WATCH_INDEX: float = 0.35
VERDICT_RISKY_INDEX: float = 0.50

# A compound failure probability at/above this is a market blocker.
COMPOUND_RISK_THRESHOLD: float = 0.30

# A per-cluster blind-spot score at/above this is a validation blocker.
BLIND_SPOT_THRESHOLD: float = 0.50

# Weighted market blind-spot score above which the read flags a
# validation gap across the covered market.
MARKET_BLIND_SPOT_THRESHOLD: float = 0.40

# CRITICAL-tier clusters covering this much of the covered market
# override a numerically lower verdict to HIGH_RISK.
CRITICAL_SHARE_THRESHOLD: float = 0.30

# Positive cascade (validated assumptions + viral coefficient) above
# this share of the covered market is surfaced as a flag + lever.
POSITIVE_CASCADE_SHARE_THRESHOLD: float = 0.30

# How many top-risk cluster ids the payload surfaces.
TOP_RISK_CLUSTERS: int = 5

# Blocker precedence for per-cluster attribution and market ties.
BLOCKER_ORDER: tuple[str, ...] = (
    BLOCKER_EXISTENTIAL,
    BLOCKER_DUAL_FAILURE,
    BLOCKER_BLIND_SPOT,
    BLOCKER_SENSITIVE_SEGMENTS,
)

# Metric keys that make a metrics block "usable". A block with none of
# these carries no cascade signal and is treated as uncovered.
_CASCADE_METRIC_KEYS: tuple[str, ...] = (
    "total_cascade_risk",
    "compound_failure_probability",
    "blind_spot_score",
    "primary_failure_domain_delta",
    "critical_assumption_count",
    "validated_assumption_count",
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


def _cascade_metrics(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> dict[str, Any]:
    """Extract the AssumptionCascadeArchitect metrics for one cluster."""
    if not conductor_results:
        return {}
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return {}
    architect = cluster_block.get("AssumptionCascadeArchitect")
    if not isinstance(architect, dict):
        return {}
    metrics = architect.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _architect_flag_map(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> dict[str, bool]:
    """Truthy AssumptionCascadeArchitect flags for one cluster."""
    if not conductor_results:
        return {}
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return {}
    architect = cluster_block.get("AssumptionCascadeArchitect")
    if not isinstance(architect, dict):
        return {}
    flags = architect.get("flags")
    if not isinstance(flags, dict):
        return {}
    return {key: bool(value) for key, value in flags.items()}


def _architect_flags(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> list[str]:
    """Sorted truthy flag keys for one cluster."""
    return sorted(
        key for key, value in _architect_flag_map(
            conductor_results, cluster_id,
        ).items() if value
    )


def _usable_metrics(metrics: dict[str, Any]) -> bool:
    return bool(metrics) and any(
        key in metrics for key in _CASCADE_METRIC_KEYS
    )


def _cascade_tier(
    risk: float,
    blind_spot_score: float,
    flags: dict[str, bool],
) -> str:
    if flags.get("existential_risk") or risk >= TIER_HIGH_INDEX:
        return TIER_CRITICAL
    if flags.get("dual_failure_risk") or risk >= TIER_ELEVATED_INDEX:
        return TIER_HIGH
    if (
        flags.get("blind_spot_detected")
        or blind_spot_score >= BLIND_SPOT_THRESHOLD
        or risk >= TIER_LOW_INDEX
    ):
        return TIER_ELEVATED
    return TIER_LOW


def _profile_blockers(
    risk: float,
    compound_probability: float,
    blind_spot_score: float,
    flags: dict[str, bool],
) -> list[str]:
    """Blocker keys for one cluster, ordered by severity."""
    blockers: list[str] = []
    if flags.get("existential_risk") or risk >= TIER_HIGH_INDEX:
        blockers.append(BLOCKER_EXISTENTIAL)
    if (
        flags.get("dual_failure_risk")
        or compound_probability >= COMPOUND_RISK_THRESHOLD
    ):
        blockers.append(BLOCKER_DUAL_FAILURE)
    if (
        flags.get("blind_spot_detected")
        or blind_spot_score >= BLIND_SPOT_THRESHOLD
    ):
        blockers.append(BLOCKER_BLIND_SPOT)
    if flags.get("cluster_sensitivity_high"):
        blockers.append(BLOCKER_SENSITIVE_SEGMENTS)
    return blockers


def _primary_blocker(blockers: list[str]) -> str:
    seen = set(blockers)
    for key in BLOCKER_ORDER:
        if key in seen:
            return key
    return BLOCKER_NONE


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


def build_assumption_cascade(
    results: dict[str, Any] | None,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    visible_assumption_count: int | None = None,
    conductor_results: dict[str, Any] | None = None,
    cluster_registry: list[dict[str, Any]] | None = None,
    product_type: str = "saas",
) -> AssumptionCascadeOut:
    """Compose the assumption-cascade read from completed results.

    Args:
        results: Simulation ``results_json`` (context only — per-cluster
            architect metrics come from ``conductor_results``).
        simulation_id: Simulation primary key (echoed back).
        project_id: Owning project primary key (echoed back).
        status: Simulation status string.
        signal_quality: Persisted signal quality (0..1), if any.
        visible_assumption_count: Number of visible project assumptions
            the route fed into the conductor before building this read.
        conductor_results: Per-cluster architect output blocks
            (``{cluster_id: {architect: {"metrics": ..., "flags": ...}}}``).
        cluster_registry: List of ``{cluster_id, name, population_weight}``.
        product_type: Detected product type for the run.
    """
    payload = _coerce_results(results)
    product_type_name = str(
        product_type
        or payload.get("product_type_detected", "saas")
        or "saas"
    ).lower()
    registry: list[dict[str, Any]] = cluster_registry or []

    raw_signal = signal_quality
    clean_signal: float | None = None
    if raw_signal is not None:
        try:
            parsed_signal = float(raw_signal)
            clean_signal = (
                parsed_signal if math.isfinite(parsed_signal) else None
            )
        except (TypeError, ValueError, OverflowError):
            clean_signal = None

    meta: dict[str, Any] = {
        "signal_quality": clean_signal,
        "visible_assumptions": visible_assumption_count,
        "total_clusters": len(registry),
        "covered_clusters": 0,
        "covered_weight": 0.0,
        "positive_cascade_share": 0.0,
        "primary_blocker_score": 0.0,
        "product_type_supported": True,
        "thresholds": {
            "tier_low_index": TIER_LOW_INDEX,
            "tier_elevated_index": TIER_ELEVATED_INDEX,
            "tier_high_index": TIER_HIGH_INDEX,
            "verdict_stable_index": VERDICT_STABLE_INDEX,
            "verdict_watch_index": VERDICT_WATCH_INDEX,
            "verdict_risky_index": VERDICT_RISKY_INDEX,
            "compound_risk_threshold": COMPOUND_RISK_THRESHOLD,
            "blind_spot_threshold": BLIND_SPOT_THRESHOLD,
            "critical_share_threshold": CRITICAL_SHARE_THRESHOLD,
        },
    }

    rows: list[dict[str, Any]] = []
    covered_weight = 0.0
    for entry in registry:
        cid = str(entry.get("cluster_id", ""))
        if not cid:
            continue
        weight = max(0.0, _safe_float(entry.get("population_weight")))
        # A cluster with zero (or negative) population share represents
        # no covered consumers: keep it out of profiles, shares, flags
        # and blocker distributions so the read stays a true
        # covered-market view.
        if weight <= 0.0:
            continue
        metrics = _cascade_metrics(conductor_results, cid)
        if not _usable_metrics(metrics):
            continue

        flags = _architect_flag_map(conductor_results, cid)
        risk = _clamp(
            _safe_float(metrics.get("total_cascade_risk"), 0.0)
        )
        compound = _clamp(
            _safe_float(
                metrics.get("compound_failure_probability"), 0.0
            )
        )
        blind_score = _clamp(
            _safe_float(metrics.get("blind_spot_score"), 0.0)
        )
        failure_delta = _clamp(
            _safe_float(
                metrics.get("primary_failure_domain_delta"), 0.0
            )
        )
        critical_count = max(
            0.0,
            _safe_float(metrics.get("critical_assumption_count"), 0.0),
        )
        validated_count = max(
            0.0,
            _safe_float(metrics.get("validated_assumption_count"), 0.0),
        )
        positive = (
            _safe_float(metrics.get("positive_cascade_active"), 0.0)
            > 0.5
        )

        tier = _cascade_tier(risk, blind_score, flags)
        blockers = _profile_blockers(
            risk, compound, blind_score, flags
        )
        primary = _primary_blocker(blockers)
        covered_weight += weight
        rows.append(
            {
                "cluster_id": cid,
                "cluster_name": str(entry.get("name", "") or cid),
                "population_weight": weight,
                "risk": risk,
                "compound": compound,
                "blind_score": blind_score,
                "failure_delta": failure_delta,
                "critical_count": critical_count,
                "validated_count": validated_count,
                "positive": positive,
                "tier": tier,
                "blockers": blockers,
                "primary_blocker": primary,
                "architect_flags": _architect_flags(
                    conductor_results, cid
                ),
            }
        )

    meta["covered_clusters"] = len(rows)
    meta["covered_weight"] = round(covered_weight, 4)

    if not rows or covered_weight <= 0.0:
        return AssumptionCascadeOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                (
                    "No per-cluster AssumptionCascadeArchitect metrics "
                    "were available for this run — add or re-extract "
                    "assumptions and re-run the simulation to unlock "
                    "cascade-risk analysis."
                )
            ],
            meta=meta,
        )

    # Highest-risk clusters first, then larger segments, then stable id.
    rows.sort(
        key=lambda row: (
            -row["risk"],
            -row["population_weight"],
            row["cluster_id"],
        )
    )

    risk_avg = _weighted_average(rows, "risk")
    compound_avg = _weighted_average(rows, "compound")
    blind_avg = _weighted_average(rows, "blind_score")
    failure_delta_avg = _weighted_average(rows, "failure_delta")
    critical_count_avg = _weighted_average(rows, "critical_count")
    validated_count_avg = _weighted_average(rows, "validated_count")

    positive_weight = sum(
        row["population_weight"]
        for row in rows
        if row["positive"]
    )
    positive_share = positive_weight / covered_weight

    tier_weights = {
        TIER_LOW: 0.0,
        TIER_ELEVATED: 0.0,
        TIER_HIGH: 0.0,
        TIER_CRITICAL: 0.0,
    }
    blocker_weights: dict[str, float] = {
        key: 0.0 for key in sorted(VALID_BLOCKERS)
    }
    for row in rows:
        tier_weights[row["tier"]] += row["population_weight"]
        blocker_weights[row["primary_blocker"]] += (
            row["population_weight"]
        )

    low_share = tier_weights[TIER_LOW] / covered_weight
    elevated_share = tier_weights[TIER_ELEVATED] / covered_weight
    high_share = tier_weights[TIER_HIGH] / covered_weight
    critical_share = tier_weights[TIER_CRITICAL] / covered_weight

    blocker_distribution = {
        key: round(weight / covered_weight, 4)
        for key, weight in blocker_weights.items()
    }
    primary_blocker = BLOCKER_NONE
    primary_blocker_share = -1.0
    for key in (*BLOCKER_ORDER, BLOCKER_NONE):
        share = blocker_distribution.get(key, 0.0)
        if share > primary_blocker_share:
            primary_blocker = key
            primary_blocker_share = share

    if risk_avg >= VERDICT_RISKY_INDEX:
        verdict = VERDICT_HIGH_RISK
    elif risk_avg >= VERDICT_WATCH_INDEX:
        verdict = VERDICT_RISKY
    elif risk_avg >= VERDICT_STABLE_INDEX:
        verdict = VERDICT_WATCH
    else:
        verdict = VERDICT_STABLE

    if critical_share >= CRITICAL_SHARE_THRESHOLD:
        verdict = VERDICT_HIGH_RISK

    flags: list[str] = []
    if verdict == VERDICT_HIGH_RISK:
        flags.append("existential_risk_market")
    if compound_avg >= COMPOUND_RISK_THRESHOLD:
        flags.append("compound_failure_market")
    if blind_avg >= MARKET_BLIND_SPOT_THRESHOLD:
        flags.append("validation_blind_spots_market")
    if positive_share >= POSITIVE_CASCADE_SHARE_THRESHOLD:
        flags.append("positive_cascade_market")
    if critical_share >= CRITICAL_SHARE_THRESHOLD:
        flags.append("critical_segment_concentration")
    if any(
        BLOCKER_EXISTENTIAL in row["blockers"] for row in rows
    ):
        flags.append("existential_risk_clusters_present")
    if any(
        BLOCKER_BLIND_SPOT in row["blockers"] for row in rows
    ):
        flags.append("blind_spot_clusters_present")

    meta["positive_cascade_share"] = round(positive_share, 4)
    meta["primary_blocker_score"] = round(primary_blocker_share, 4)

    recommendations: list[str] = []
    if verdict == VERDICT_STABLE:
        recommendations.append(
            f"Cascade risk is low (weighted index = {risk_avg:.2f}, "
            f"{_fmt_pct(low_share)} of the covered market LOW) — keep "
            "validating critical assumptions as new evidence arrives."
        )
    elif verdict == VERDICT_WATCH:
        recommendations.append(
            f"Cascade risk is watchable (weighted index = "
            f"{risk_avg:.2f}, {_fmt_pct(critical_share + high_share)} "
            "HIGH or worse) — validate the top assumptions before "
            "scaling spend."
        )
    elif verdict == VERDICT_RISKY:
        recommendations.append(
            f"Cascade risk is elevated (weighted index = "
            f"{risk_avg:.2f}, {_fmt_pct(high_share + critical_share)} "
            "HIGH or worse) — treat assumption validation as the "
            "critical path, not a nice-to-have."
        )
    else:
        recommendations.append(
            f"Cascade risk is a launch blocker (weighted index = "
            f"{risk_avg:.2f}, {_fmt_pct(critical_share)} of the "
            "covered market CRITICAL) — validate the highest-risk "
            "assumptions with real users before further investment."
        )

    if primary_blocker == BLOCKER_EXISTENTIAL:
        recommendations.append(
            "The dominant blocker is existential cascade risk — "
            "re-run after validating the assumptions that feed the "
            "highest-risk clusters."
        )
    elif primary_blocker == BLOCKER_DUAL_FAILURE:
        recommendations.append(
            "The dominant blocker is compound dual-assumption failure "
            "— test the two top assumptions together, because they are "
            "more likely to fail as a pair than either in isolation."
        )
    elif primary_blocker == BLOCKER_BLIND_SPOT:
        recommendations.append(
            "The dominant blocker is validation blind spots — run "
            "evidence-collection experiments (interviews, landing-page "
            "tests) for aspirational assumptions before launch."
        )
    elif primary_blocker == BLOCKER_SENSITIVE_SEGMENTS:
        recommendations.append(
            "The dominant blocker is high-sensitivity segments — "
            "include students, tier-3 and price-sensitive clusters in "
            "validation samples."
        )

    if positive_share >= POSITIVE_CASCADE_SHARE_THRESHOLD:
        recommendations.append(
            f"A positive cascade is active across {_fmt_pct(positive_share)} "
            "of the covered market (validated assumptions + viral "
            "coefficient) — use that evidence in go-to-market "
            "messaging."
        )
    if blind_avg >= MARKET_BLIND_SPOT_THRESHOLD:
        recommendations.append(
            f"Weighted blind-spot score is {blind_avg:.2f} — most of "
            "the covered market rests on unvalidated assumptions; "
            "prioritise validation experiments over build work."
        )
    if clean_signal is not None and clean_signal < 0.4:
        recommendations.append(
            f"Overall simulation signal quality is low "
            f"({clean_signal:.2f}) — treat the cascade index as a "
            "model estimate, not a measured outcome."
        )
    if visible_assumption_count is not None and visible_assumption_count <= 0:
        recommendations.append(
            "No visible project assumptions fed this read — add "
            "assumptions with sensitivity levels so the cascade model "
            "can surface compounding failure risk."
        )
    recommendations.append(
        f"Primary blocker: {BLOCKER_LABELS[primary_blocker]} "
        f"(affects {_fmt_pct(primary_blocker_share)} of the covered "
        "market)."
    )
    recommendations.append(
        f"Weighted compound failure probability is "
        f"{_fmt_pct(compound_avg)} and weighted blind-spot score is "
        f"{blind_avg:.2f} — the two leading sources of cascade risk."
    )

    return AssumptionCascadeOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type_name,
        verdict=verdict,
        cascade_index=round(risk_avg, 4),
        weighted_compound_failure_probability=round(compound_avg, 4),
        weighted_blind_spot_score=round(blind_avg, 4),
        weighted_primary_failure_domain_delta=round(
            failure_delta_avg, 4
        ),
        weighted_critical_assumption_count=round(critical_count_avg, 4),
        weighted_validated_assumption_count=round(
            validated_count_avg, 4
        ),
        positive_cascade_share=round(positive_share, 4),
        low_share=round(low_share, 4),
        elevated_share=round(elevated_share, 4),
        high_share=round(high_share, 4),
        critical_share=round(critical_share, 4),
        primary_blocker=primary_blocker,
        primary_blocker_label=BLOCKER_LABELS[primary_blocker],
        primary_blocker_share=round(primary_blocker_share, 4),
        blocker_distribution=blocker_distribution,
        cluster_profiles=[
            ClusterCascadeProfile(
                cluster_id=row["cluster_id"],
                cluster_name=row["cluster_name"],
                population_weight=round(row["population_weight"], 4),
                total_cascade_risk=round(row["risk"], 4),
                compound_failure_probability=round(row["compound"], 4),
                blind_spot_score=round(row["blind_score"], 4),
                primary_failure_domain_delta=round(
                    row["failure_delta"], 4
                ),
                critical_assumption_count=round(
                    row["critical_count"], 4
                ),
                validated_assumption_count=round(
                    row["validated_count"], 4
                ),
                positive_cascade_active=row["positive"],
                cascade_tier=row["tier"],
                blockers=row["blockers"],
                architect_flags=row["architect_flags"],
            )
            for row in rows
        ],
        top_risk_clusters=[
            row["cluster_id"] for row in rows[:TOP_RISK_CLUSTERS]
        ],
        flags=flags,
        recommendations=recommendations,
        meta=meta,
    )


__all__ = [
    "BLIND_SPOT_THRESHOLD",
    "BLOCKER_ORDER",
    "COMPOUND_RISK_THRESHOLD",
    "CRITICAL_SHARE_THRESHOLD",
    "MARKET_BLIND_SPOT_THRESHOLD",
    "POSITIVE_CASCADE_SHARE_THRESHOLD",
    "TIER_ELEVATED_INDEX",
    "TIER_HIGH_INDEX",
    "TIER_LOW_INDEX",
    "TOP_RISK_CLUSTERS",
    "VERDICT_RISKY_INDEX",
    "VERDICT_STABLE_INDEX",
    "VERDICT_WATCH_INDEX",
    "build_assumption_cascade",
]
