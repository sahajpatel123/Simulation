"""
Pure setup-friction analysis for completed simulation results.

Answers the founder's "how fast will buyers actually get value from
this hardware, and which setup step is blocking them?" question by
turning the ``SetupFirstUseArchitect`` per-cluster metrics into a
deterministic, population-weighted read:

* **Setup-experience index** — a 0..1 market-weighted composite
  (higher = smoother / faster) of out-of-box setup completion (25%),
  time to first meaningful use (25%), companion-app install (15%),
  account-creation abandonment (10%), firmware-update tolerance (10%),
  physical-assembly tolerance (7.5%) and pairing tolerance (7.5%).
  Every component is normalized against the architect's modeled ranges
  so the seven setup steps are comparable and higher severities always
  mean worse friction.
* **Cluster tiers** — every covered cluster is classified ``SEAMLESS``
  (index >= 0.75) / ``ROUGH`` (>= 0.55) / ``SLOW`` (>= 0.40) /
  ``BLOCKED`` (< 0.40).
* **Primary setup blocker** — each cluster is attributed to the worst
  of the seven modeled steps (setup completion, time to value,
  companion app, account abandonment, firmware update, physical
  assembly, pairing). The market-level blocker distribution is the
  population-weighted share of those attributions.
* **Setup levers** — eight interventions (guided unboxing, in-app
  first-value onboarding, streamlined companion-app setup, optional
  account creation, pre-flashed firmware, fewer assembly steps,
  one-tap pairing, printed quick-start guide) ranked by the share of
  the covered market where the underlying friction is present.

The verdict is ``FAST`` when the weighted setup-experience index is at
least 0.75, ``ACCEPTABLE`` at 0.55, ``SLOW`` at 0.40, ``BLOCKED`` below
that, and ``INSUFFICIENT_DATA`` when no cluster has usable metrics.
``SetupFirstUseArchitect`` activates for consumer_hardware,
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
``primary_blocker_score`` (0..1, population-weighted severity of each
cluster's worst setup blocker) so a ``FAST`` verdict with a residual
tie-break blocker is not mistaken for a real setup risk.

Companion-app friction is only counted when the founder's brief
requires a companion app (``requires_companion_app=True``, derived in
the route from the project's visible assumptions). That keeps an
app-less product from being blamed for a low companion-app install
rate — a metric the architect reports even when no app exists.

No DB / I/O — verifiable without FastAPI or PostgreSQL. The route layer
supplies ``results``, ``conductor_results`` (per-cluster architect
metrics), ``cluster_registry`` and ``requires_companion_app``; all
arithmetic is deterministic. Metrics missing from a malformed/partial
payload use neutral defaults (completion 0.80, app install 0.70,
abandonment 0.05, firmware tolerance 8 min, assembly tolerance 2.75,
pairing tolerance 2.5, time to value 6 min, customisation 0.30) so a
missing field never manufactures a BLOCKED tier, an extreme blocker,
or a false lever/flag. Every default sits strictly on the "no
friction" side of the lever and flag thresholds below.
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable

from app.schemas.setup_friction import (
    BLOCKER_ACCOUNT_ABANDONMENT,
    BLOCKER_COMPANION_APP,
    BLOCKER_FIRMWARE_UPDATE,
    BLOCKER_PAIRING,
    BLOCKER_PHYSICAL_ASSEMBLY,
    BLOCKER_SETUP_COMPLETION,
    BLOCKER_TIME_TO_VALUE,
    ClusterSetupProfile,
    LEVER_ACCOUNT_OPTIONAL,
    LEVER_COMPANION_APP,
    LEVER_GUIDED_SETUP,
    LEVER_ONBOARDING_WIZARD,
    LEVER_ONE_TAP_PAIRING,
    LEVER_PREFLASHED_FIRMWARE,
    LEVER_PRINTED_GUIDE,
    LEVER_SIMPLIFIED_ASSEMBLY,
    SetupFrictionOut,
    SetupLever,
    SUPPORTED_PRODUCT_TYPES,
    TIER_BLOCKED,
    TIER_ROUGH,
    TIER_SEAMLESS,
    TIER_SLOW,
    VERDICT_ACCEPTABLE,
    VERDICT_BLOCKED,
    VERDICT_FAST,
    VERDICT_INSUFFICIENT,
    VERDICT_SLOW,
)

# Ordered blocker keys — used for tie-breaking and market aggregation so
# the output is stable regardless of dict ordering.
BLOCKER_ORDER: tuple[str, ...] = (
    BLOCKER_SETUP_COMPLETION,
    BLOCKER_TIME_TO_VALUE,
    BLOCKER_COMPANION_APP,
    BLOCKER_ACCOUNT_ABANDONMENT,
    BLOCKER_FIRMWARE_UPDATE,
    BLOCKER_PHYSICAL_ASSEMBLY,
    BLOCKER_PAIRING,
)

BLOCKER_LABELS: dict[str, str] = {
    BLOCKER_SETUP_COMPLETION: "Low out-of-box setup completion",
    BLOCKER_TIME_TO_VALUE: "Slow time to first meaningful use",
    BLOCKER_COMPANION_APP: "Low companion-app install rate",
    BLOCKER_ACCOUNT_ABANDONMENT: "Account-creation abandonment",
    BLOCKER_FIRMWARE_UPDATE: "Low firmware-update tolerance",
    BLOCKER_PHYSICAL_ASSEMBLY: "Low physical-assembly tolerance",
    BLOCKER_PAIRING: "Low pairing-friction tolerance",
}

LEVER_LABELS: dict[str, str] = {
    LEVER_GUIDED_SETUP: "Guided unboxing & setup",
    LEVER_ONBOARDING_WIZARD: "In-app first-value onboarding",
    LEVER_COMPANION_APP: "Streamlined companion-app setup",
    LEVER_ACCOUNT_OPTIONAL: "Optional account creation",
    LEVER_PREFLASHED_FIRMWARE: "Pre-flashed firmware",
    LEVER_SIMPLIFIED_ASSEMBLY: "Fewer assembly steps",
    LEVER_ONE_TAP_PAIRING: "One-tap pairing",
    LEVER_PRINTED_GUIDE: "Printed quick-start guide",
}

# Cluster-tier thresholds (setup-experience index; higher = better).
TIER_SEAMLESS_INDEX: float = 0.75
TIER_ROUGH_INDEX: float = 0.55
TIER_SLOW_INDEX: float = 0.40

# Verdict thresholds (weighted market setup-experience index).
VERDICT_FAST_INDEX: float = 0.75
VERDICT_ACCEPTABLE_INDEX: float = 0.55
VERDICT_SLOW_INDEX: float = 0.40

# Normalization anchors for step severities (all 0..1, higher = worse).
TTFMU_MIN_MINUTES: float = 3.0
TTFMU_SCALE_MINUTES: float = 15.0
FIRMWARE_TOLERANCE_SCALE_MIN: float = 10.0
ASSEMBLY_TOLERANCE_SCALE: float = 2.5
PAIRING_TOLERANCE_SCALE: float = 2.5

# Composite weights (sum to 1.0).
WEIGHT_SETUP_COMPLETION: float = 0.25
WEIGHT_TIME_TO_VALUE: float = 0.25
WEIGHT_COMPANION_APP: float = 0.15
WEIGHT_ACCOUNT_ABANDONMENT: float = 0.10
WEIGHT_FIRMWARE_UPDATE: float = 0.10
WEIGHT_PHYSICAL_ASSEMBLY: float = 0.075
WEIGHT_PAIRING: float = 0.075

# Neutral defaults for metrics missing from a malformed/partial payload.
# They lean middle-of-road so a missing field neither manufactures a
# BLOCKED tier / false lever / false flag nor hides a real blocker
# present in other metrics. Each default sits strictly below (or above,
# for tolerance-style metrics) the corresponding lever/flag trigger.
DEFAULT_COMPLETION: float = 0.80
DEFAULT_APP_INSTALL: float = 0.70
DEFAULT_ABANDONMENT: float = 0.05
DEFAULT_FIRMWARE_TOLERANCE_MIN: float = 8.0
DEFAULT_ASSEMBLY_TOLERANCE: float = 2.75
DEFAULT_PAIRING_TOLERANCE: float = 2.5
DEFAULT_TTFMU_MIN: float = 6.0
DEFAULT_CUSTOMISATION_DEPTH: float = 0.30

# Lever opportunity thresholds — a lever applies to a cluster when the
# underlying setup step crosses the friction line.
LEVER_GUIDED_SETUP_SEVERITY_MIN: float = 0.25
LEVER_ONBOARDING_SEVERITY_MIN: float = 0.40
LEVER_COMPANION_APP_SEVERITY_MIN: float = 0.55
LEVER_ACCOUNT_SEVERITY_MIN: float = 0.15
LEVER_FIRMWARE_SEVERITY_MIN: float = 0.40
LEVER_ASSEMBLY_SEVERITY_MIN: float = 0.50
LEVER_PAIRING_SEVERITY_MIN: float = 0.50
LEVER_PRINTED_COMPLETION_SEVERITY_MIN: float = 0.45

# Flag thresholds (weighted market aggregates; higher = better except
# abandonment and time-to-value where higher = worse).
FLAG_COMPLETION_MIN: float = 0.55
FLAG_TTFMU_MAX_MIN: float = 10.0
FLAG_ABANDONMENT_MAX: float = 0.15
FLAG_FIRMWARE_TOLERANCE_MIN_MIN: float = 6.0
FLAG_COMPANION_APP_INSTALL_MIN: float = 0.45


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


def _setup_metrics(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> dict[str, Any]:
    """Extract the SetupFirstUseArchitect metrics block for one cluster."""
    if not conductor_results:
        return {}
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return {}
    architect = cluster_block.get("SetupFirstUseArchitect")
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
    architect = cluster_block.get("SetupFirstUseArchitect")
    if not isinstance(architect, dict):
        return []
    flags = architect.get("flags")
    if not isinstance(flags, dict):
        return []
    return sorted(
        key for key, value in flags.items() if bool(value)
    )


def _severities(
    metrics: dict[str, Any],
    *,
    requires_companion_app: bool,
) -> dict[str, float]:
    """Normalized setup-step severities for one cluster
    (0..1, higher = worse)."""
    completion = _clamp(
        _safe_float(
            metrics.get("oob_setup_completion_rate"),
            DEFAULT_COMPLETION,
        )
    )
    app_install = _clamp(
        _safe_float(
            metrics.get("companion_app_install_rate"),
            DEFAULT_APP_INSTALL,
        )
    )
    abandonment = _clamp(
        _safe_float(
            metrics.get("account_creation_abandonment"),
            DEFAULT_ABANDONMENT,
        )
    )
    firmware_tolerance = max(
        0.0,
        _safe_float(
            metrics.get("firmware_update_tolerance_min"),
            DEFAULT_FIRMWARE_TOLERANCE_MIN,
        ),
    )
    assembly_tolerance = max(
        0.0,
        _safe_float(
            metrics.get("physical_assembly_tolerance"),
            DEFAULT_ASSEMBLY_TOLERANCE,
        ),
    )
    pairing_tolerance = max(
        0.0,
        _safe_float(
            metrics.get("pairing_friction_tolerance"),
            DEFAULT_PAIRING_TOLERANCE,
        ),
    )
    ttfmu = max(
        0.0,
        _safe_float(
            metrics.get("time_to_first_meaningful_use"),
            DEFAULT_TTFMU_MIN,
        ),
    )
    return {
        BLOCKER_SETUP_COMPLETION: round(1.0 - completion, 4),
        BLOCKER_TIME_TO_VALUE: round(
            _clamp(
                (ttfmu - TTFMU_MIN_MINUTES) / TTFMU_SCALE_MINUTES
            ),
            4,
        ),
        BLOCKER_COMPANION_APP: round(
            1.0 - app_install if requires_companion_app else 0.0,
            4,
        ),
        BLOCKER_ACCOUNT_ABANDONMENT: round(abandonment, 4),
        BLOCKER_FIRMWARE_UPDATE: round(
            _clamp(
                (FIRMWARE_TOLERANCE_SCALE_MIN - firmware_tolerance)
                / FIRMWARE_TOLERANCE_SCALE_MIN
            ),
            4,
        ),
        BLOCKER_PHYSICAL_ASSEMBLY: round(
            _clamp(
                (ASSEMBLY_TOLERANCE_SCALE - assembly_tolerance)
                / ASSEMBLY_TOLERANCE_SCALE
            ),
            4,
        ),
        BLOCKER_PAIRING: round(
            _clamp(
                (PAIRING_TOLERANCE_SCALE - pairing_tolerance)
                / PAIRING_TOLERANCE_SCALE
            ),
            4,
        ),
    }


def _primary_blocker(severities: dict[str, float]) -> tuple[str, float]:
    """Worst setup step; ties resolve to the earlier key in
    BLOCKER_ORDER."""
    best_key = BLOCKER_ORDER[0]
    best_value = severities.get(best_key, 0.0)
    for key in BLOCKER_ORDER[1:]:
        value = severities.get(key, 0.0)
        if value > best_value:
            best_key = key
            best_value = value
    return best_key, round(best_value, 4)


def _setup_index(severities: dict[str, float]) -> float:
    """Composite 0..1 setup-experience score (higher = better)."""
    friction = (
        WEIGHT_SETUP_COMPLETION
        * severities.get(BLOCKER_SETUP_COMPLETION, 0.0)
        + WEIGHT_TIME_TO_VALUE
        * severities.get(BLOCKER_TIME_TO_VALUE, 0.0)
        + WEIGHT_COMPANION_APP
        * severities.get(BLOCKER_COMPANION_APP, 0.0)
        + WEIGHT_ACCOUNT_ABANDONMENT
        * severities.get(BLOCKER_ACCOUNT_ABANDONMENT, 0.0)
        + WEIGHT_FIRMWARE_UPDATE
        * severities.get(BLOCKER_FIRMWARE_UPDATE, 0.0)
        + WEIGHT_PHYSICAL_ASSEMBLY
        * severities.get(BLOCKER_PHYSICAL_ASSEMBLY, 0.0)
        + WEIGHT_PAIRING * severities.get(BLOCKER_PAIRING, 0.0)
    )
    return _clamp(1.0 - friction)


def _setup_tier(setup_index: float) -> str:
    if setup_index >= TIER_SEAMLESS_INDEX:
        return TIER_SEAMLESS
    if setup_index >= TIER_ROUGH_INDEX:
        return TIER_ROUGH
    if setup_index >= TIER_SLOW_INDEX:
        return TIER_SLOW
    return TIER_BLOCKED


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
) -> SetupLever:
    share = _opportunity_share(rows, predicate)
    return SetupLever(
        key=key,
        label=LEVER_LABELS[key],
        market_value=round(_weighted_average(rows, metric_key), 4),
        opportunity_share=round(share, 4),
        action=action.format(share=_fmt_pct(share)),
    )


def build_setup_friction(
    results: dict[str, Any] | None,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    conductor_results: dict[str, Any] | None = None,
    cluster_registry: list[dict[str, Any]] | None = None,
    product_type: str = "saas",
    requires_companion_app: bool = False,
) -> SetupFrictionOut:
    """Compose the setup-friction read from completed results.

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
        requires_companion_app: Whether the founder's brief requires a
            companion app (derived from visible assumptions). When
            false, companion-app friction is never counted.
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
        "primary_blocker_score": 0.0,
        "product_type_supported": product_type_supported,
        "requires_companion_app": requires_companion_app,
        "supported_product_types": sorted(SUPPORTED_PRODUCT_TYPES),
        "thresholds": {
            "tier_seamless_index": TIER_SEAMLESS_INDEX,
            "tier_rough_index": TIER_ROUGH_INDEX,
            "tier_slow_index": TIER_SLOW_INDEX,
            "verdict_fast_index": VERDICT_FAST_INDEX,
            "verdict_acceptable_index": VERDICT_ACCEPTABLE_INDEX,
            "verdict_slow_index": VERDICT_SLOW_INDEX,
        },
        "normalization": {
            "ttfmu_min_minutes": TTFMU_MIN_MINUTES,
            "ttfmu_scale_minutes": TTFMU_SCALE_MINUTES,
            "firmware_tolerance_scale_min": FIRMWARE_TOLERANCE_SCALE_MIN,
            "assembly_tolerance_scale": ASSEMBLY_TOLERANCE_SCALE,
            "pairing_tolerance_scale": PAIRING_TOLERANCE_SCALE,
        },
    }

    if not product_type_supported:
        return SetupFrictionOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                "SetupFirstUseArchitect only activates for "
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
        metrics = _setup_metrics(conductor_results, cid)
        if not metrics:
            continue

        completion = _clamp(
            _safe_float(
                metrics.get("oob_setup_completion_rate"),
                DEFAULT_COMPLETION,
            )
        )
        app_install = _clamp(
            _safe_float(
                metrics.get("companion_app_install_rate"),
                DEFAULT_APP_INSTALL,
            )
        )
        abandonment = _clamp(
            _safe_float(
                metrics.get("account_creation_abandonment"),
                DEFAULT_ABANDONMENT,
            )
        )
        firmware_tolerance = max(
            0.0,
            _safe_float(
                metrics.get("firmware_update_tolerance_min"),
                DEFAULT_FIRMWARE_TOLERANCE_MIN,
            ),
        )
        assembly_tolerance = max(
            0.0,
            _safe_float(
                metrics.get("physical_assembly_tolerance"),
                DEFAULT_ASSEMBLY_TOLERANCE,
            ),
        )
        pairing_tolerance = max(
            0.0,
            _safe_float(
                metrics.get("pairing_friction_tolerance"),
                DEFAULT_PAIRING_TOLERANCE,
            ),
        )
        ttfmu = max(
            0.0,
            _safe_float(
                metrics.get("time_to_first_meaningful_use"),
                DEFAULT_TTFMU_MIN,
            ),
        )
        customisation_depth = _clamp(
            _safe_float(
                metrics.get("initial_customisation_depth"),
                DEFAULT_CUSTOMISATION_DEPTH,
            )
        )

        severities = _severities(
            metrics,
            requires_companion_app=requires_companion_app,
        )
        setup_index = _setup_index(severities)
        blocker, blocker_score = _primary_blocker(severities)
        covered_weight += weight
        rows.append(
            {
                "cluster_id": cid,
                "cluster_name": str(entry.get("name", "") or cid),
                "population_weight": weight,
                "completion": completion,
                "app_install": app_install,
                "abandonment": abandonment,
                "firmware_tolerance": firmware_tolerance,
                "assembly_tolerance": assembly_tolerance,
                "pairing_tolerance": pairing_tolerance,
                "ttfmu": ttfmu,
                "customisation_depth": customisation_depth,
                "severities": severities,
                "setup_index": setup_index,
                "tier": _setup_tier(setup_index),
                "blocker": blocker,
                "blocker_score": blocker_score,
                "architect_flags": _architect_flags(
                    conductor_results, cid
                ),
            }
        )
    meta["covered_clusters"] = len(rows)
    meta["covered_weight"] = round(covered_weight, 4)

    if not rows or covered_weight <= 0.0:
        return SetupFrictionOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                "No per-cluster SetupFirstUseArchitect metrics "
                "were available for this run."
            ],
            meta=meta,
        )

    index_avg = _weighted_average(rows, "setup_index")
    completion_avg = _weighted_average(rows, "completion")
    app_install_avg = _weighted_average(rows, "app_install")
    abandonment_avg = _weighted_average(rows, "abandonment")
    firmware_avg = _weighted_average(rows, "firmware_tolerance")
    assembly_avg = _weighted_average(rows, "assembly_tolerance")
    pairing_avg = _weighted_average(rows, "pairing_tolerance")
    ttfmu_avg = _weighted_average(rows, "ttfmu")

    seamless_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_SEAMLESS
    )
    rough_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_ROUGH
    )
    slow_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_SLOW
    )
    blocked_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_BLOCKED
    )
    seamless_share = seamless_weight / covered_weight
    rough_share = rough_weight / covered_weight
    slow_share = slow_weight / covered_weight
    blocked_share = blocked_weight / covered_weight

    if index_avg >= VERDICT_FAST_INDEX:
        verdict = VERDICT_FAST
    elif index_avg >= VERDICT_ACCEPTABLE_INDEX:
        verdict = VERDICT_ACCEPTABLE
    elif index_avg >= VERDICT_SLOW_INDEX:
        verdict = VERDICT_SLOW
    else:
        verdict = VERDICT_BLOCKED

    # Market blocker distribution = population-weighted share of
    # per-cluster primary-blocker attributions.
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
    # Market-level severity of the attributed blocker: population-weighted
    # average of each cluster's worst normalized setup-step score.
    primary_blocker_score = _weighted_average(rows, "blocker_score")
    meta["primary_blocker_score"] = round(primary_blocker_score, 4)

    flags: list[str] = []
    if any(row["tier"] == TIER_BLOCKED for row in rows):
        flags.append("blocked_setup_clusters")
    if completion_avg < FLAG_COMPLETION_MIN:
        flags.append("setup_critical_market")
    if ttfmu_avg >= FLAG_TTFMU_MAX_MIN:
        flags.append("time_to_value_slow")
    if abandonment_avg >= FLAG_ABANDONMENT_MAX:
        flags.append("account_abandonment_market")
    if firmware_avg < FLAG_FIRMWARE_TOLERANCE_MIN_MIN:
        flags.append("firmware_update_friction")
    if any(
        "tier3_setup_risk" in row["architect_flags"]
        for row in rows
    ):
        flags.append("tier3_setup_risk")
    if any(
        "guide_printed" in row["architect_flags"]
        for row in rows
    ):
        flags.append("printed_guide_segment")
    if (
        requires_companion_app
        and app_install_avg < FLAG_COMPANION_APP_INSTALL_MIN
    ):
        flags.append("companion_app_gap")

    levers: list[SetupLever] = [
        _lever(
            rows,
            LEVER_GUIDED_SETUP,
            "completion",
            lambda row: (
                row["severities"][BLOCKER_SETUP_COMPLETION]
                >= LEVER_GUIDED_SETUP_SEVERITY_MIN
            ),
            "Add a guided unboxing and setup flow — {share} of the "
            "covered market is at risk of abandoning out-of-box setup.",
        ),
        _lever(
            rows,
            LEVER_ONBOARDING_WIZARD,
            "ttfmu",
            lambda row: (
                row["severities"][BLOCKER_TIME_TO_VALUE]
                >= LEVER_ONBOARDING_SEVERITY_MIN
            ),
            "Ship an in-app first-value onboarding wizard — {share} of "
            "the covered market takes 9+ minutes to first meaningful use.",
        ),
        _lever(
            rows,
            LEVER_COMPANION_APP,
            "app_install",
            lambda row: (
                requires_companion_app
                and row["severities"][BLOCKER_COMPANION_APP]
                >= LEVER_COMPANION_APP_SEVERITY_MIN
            ),
            "Streamline companion-app download and pairing — {share} "
            "of the covered market is unlikely to install the app at all.",
        ),
        _lever(
            rows,
            LEVER_ACCOUNT_OPTIONAL,
            "abandonment",
            lambda row: (
                row["severities"][BLOCKER_ACCOUNT_ABANDONMENT]
                >= LEVER_ACCOUNT_SEVERITY_MIN
            ),
            "Make account creation optional or deferred — {share} of "
            "the covered market abandons during sign-up.",
        ),
        _lever(
            rows,
            LEVER_PREFLASHED_FIRMWARE,
            "firmware_tolerance",
            lambda row: (
                row["severities"][BLOCKER_FIRMWARE_UPDATE]
                >= LEVER_FIRMWARE_SEVERITY_MIN
            ),
            "Pre-flash firmware and make updates optional — {share} of "
            "the covered market cannot tolerate a long first update.",
        ),
        _lever(
            rows,
            LEVER_SIMPLIFIED_ASSEMBLY,
            "assembly_tolerance",
            lambda row: (
                row["severities"][BLOCKER_PHYSICAL_ASSEMBLY]
                >= LEVER_ASSEMBLY_SEVERITY_MIN
            ),
            "Cut physical assembly steps — {share} of the covered "
            "market has low tolerance for multi-step assembly.",
        ),
        _lever(
            rows,
            LEVER_ONE_TAP_PAIRING,
            "pairing_tolerance",
            lambda row: (
                row["severities"][BLOCKER_PAIRING]
                >= LEVER_PAIRING_SEVERITY_MIN
            ),
            "Offer one-tap / QR-code pairing — {share} of the covered "
            "market is likely to give up during device pairing.",
        ),
        _lever(
            rows,
            LEVER_PRINTED_GUIDE,
            "completion",
            lambda row: (
                "guide_printed" in row["architect_flags"]
                or row["severities"][BLOCKER_SETUP_COMPLETION]
                >= LEVER_PRINTED_COMPLETION_SEVERITY_MIN
            ),
            "Include a printed quick-start guide — {share} of the "
            "covered market needs offline, non-app setup help.",
        ),
    ]
    levers.sort(key=lambda lever: (-lever.opportunity_share, lever.key))

    recommendations: list[str] = []
    if verdict == VERDICT_FAST:
        recommendations.append(
            f"Setup is fast (weighted setup-experience index = "
            f"{index_avg:.2f}) — most of the covered market completes "
            "out-of-box setup and reaches first value quickly."
        )
    elif verdict == VERDICT_ACCEPTABLE:
        recommendations.append(
            f"Setup is workable but not friction-free (experience index "
            f"= {index_avg:.2f}, {_fmt_pct(blocked_share)} already "
            "BLOCKED) — pull the strongest lever below before scaling."
        )
    elif verdict == VERDICT_SLOW:
        recommendations.append(
            f"Setup is slow (experience index = {index_avg:.2f}) — "
            "expect meaningful post-purchase returns unless time to "
            "value improves."
        )
    else:
        recommendations.append(
            f"Setup is a launch blocker (experience index = "
            f"{index_avg:.2f}, {_fmt_pct(blocked_share)} of the covered "
            "market BLOCKED) — treat unboxing-to-value as part of the "
            "core product."
        )
    recommendations.append(
        f"Primary setup blocker: {BLOCKER_LABELS[primary_blocker]} "
        f"(severity {primary_blocker_score:.2f}, affects "
        f"{_fmt_pct(primary_blocker_share)} of the covered market)."
    )
    recommendations.append(
        f"Average time to first meaningful use is ~{ttfmu_avg:.1f} "
        f"min, with {_fmt_pct(completion_avg)} out-of-box setup "
        "completion — each minute saved before first value directly "
        "reduces return pressure."
    )
    if requires_companion_app and app_install_avg < FLAG_COMPANION_APP_INSTALL_MIN:
        recommendations.append(
            f"Companion-app install averages only "
            f"{_fmt_pct(app_install_avg)} — make setup work without "
            "the app, or streamline the download/onboarding itself."
        )
    if abandonment_avg >= FLAG_ABANDONMENT_MAX:
        recommendations.append(
            f"Account-creation abandonment is {_fmt_pct(abandonment_avg)} "
            "— defer or remove mandatory sign-up until after first value."
        )
    if firmware_avg < FLAG_FIRMWARE_TOLERANCE_MIN_MIN:
        recommendations.append(
            f"Average firmware-update tolerance is only "
            f"{firmware_avg:.1f} min — pre-flash units and make updates "
            "non-blocking."
        )
    if any(
        "tier3_setup_risk" in row["architect_flags"]
        for row in rows
    ):
        recommendations.append(
            "Tier-3 geography clusters are setup-risk flagged — provide "
            "offline guides and reduce app/firmware dependencies there."
        )
    if any(
        "guide_printed" in row["architect_flags"]
        for row in rows
    ):
        recommendations.append(
            "Older and lower-literacy segments need a printed "
            "quick-start guide — do not rely on in-app onboarding alone."
        )

    return SetupFrictionOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type_name,
        verdict=verdict,
        setup_experience_index=round(index_avg, 4),
        weighted_oob_setup_completion_rate=round(completion_avg, 4),
        weighted_companion_app_install_rate=round(app_install_avg, 4),
        weighted_account_creation_abandonment=round(abandonment_avg, 4),
        weighted_time_to_first_meaningful_use_min=round(ttfmu_avg, 2),
        weighted_firmware_update_tolerance_min=round(firmware_avg, 2),
        weighted_physical_assembly_tolerance=round(assembly_avg, 2),
        weighted_pairing_friction_tolerance=round(pairing_avg, 2),
        seamless_share=round(seamless_share, 4),
        rough_share=round(rough_share, 4),
        slow_share=round(slow_share, 4),
        blocked_share=round(blocked_share, 4),
        primary_blocker=primary_blocker,
        primary_blocker_label=BLOCKER_LABELS[primary_blocker],
        primary_blocker_share=round(primary_blocker_share, 4),
        blocker_distribution=blocker_distribution,
        cluster_profiles=[
            ClusterSetupProfile(
                cluster_id=row["cluster_id"],
                cluster_name=row["cluster_name"],
                population_weight=row["population_weight"],
                oob_setup_completion_rate=round(row["completion"], 4),
                companion_app_install_rate=round(row["app_install"], 4),
                account_creation_abandonment=round(
                    row["abandonment"], 4
                ),
                firmware_update_tolerance_min=round(
                    row["firmware_tolerance"], 2
                ),
                physical_assembly_tolerance=round(
                    row["assembly_tolerance"], 2
                ),
                pairing_friction_tolerance=round(
                    row["pairing_tolerance"], 2
                ),
                time_to_first_meaningful_use_min=round(
                    row["ttfmu"], 2
                ),
                initial_customisation_depth=round(
                    row["customisation_depth"], 4
                ),
                setup_experience_index=round(row["setup_index"], 4),
                setup_tier=row["tier"],
                primary_blocker=row["blocker"],
                primary_blocker_score=row["blocker_score"],
                architect_flags=list(row["architect_flags"]),
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
    "build_setup_friction",
]
