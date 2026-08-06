"""
Pure ecosystem-compatibility analysis for completed simulation results.

Answers the founder's "is my hardware too dependent on someone else's
ecosystem, and which compatibility lever should I pull first?"
question by turning the ``EcosystemCompatibilityArchitect``
per-cluster metrics into a deterministic, population-weighted read:

* **Compatibility index** — a 0..1 market-weighted composite
  (higher = more open / compatible) of platform lock-in resistance
  (25%), smart-home compatibility requirement (20%), hardware
  subscription resentment (20%), cloud-privacy concern (20%) and
  voice-assistant expectation (15%). Every component is normalized so
  all five blockers are comparable and higher scores always mean
  better compatibility.
* **Cluster tiers** — every covered cluster is classified ``OPEN``
  (index >= 0.75) / ``PARTIAL`` (>= 0.55) / ``TETHERED`` (>= 0.40) /
  ``LOCKED`` (< 0.40).
* **Primary compatibility blocker** — each cluster is attributed to the
  worst of the five modeled inputs (platform lock-in, smart-home gate,
  subscription resentment, cloud privacy, voice expectation). The
  market-level blocker distribution is the population-weighted share of
  those attributions.
* **Ecosystem levers** — six interventions (Matter / smart-home
  support, open API/SDK, optional subscription, local/private cloud
  mode, voice-assistant integration, household multi-user design)
  ranked by the share of the covered market where the underlying
  friction is present.

The verdict is ``SEAMLESS`` when the weighted compatibility index is at
least 0.75, ``WORKABLE`` at 0.55, ``FRAGILE`` at 0.40, ``BLOCKED``
below that, and ``INSUFFICIENT_DATA`` when no cluster has usable
metrics. ``EcosystemCompatibilityArchitect`` activates for
consumer_hardware, health_hardware, iot_hardware, smart_home and
wearable stacks, so the read is supported for exactly those product
types and reports ``product_type_supported: false`` otherwise.

The covered market is the population weight of clusters with usable
metrics and a positive population share; zero-weight clusters are
excluded from profiles, flags and lever shares. ``meta`` also carries a
``primary_blocker_score`` (0..1, population-weighted severity of each
cluster's worst compatibility blocker) so a ``SEAMLESS`` verdict with a
residual tie-break blocker is not mistaken for a real integration risk.

No DB / I/O — verifiable without FastAPI or PostgreSQL. The route layer
supplies ``results``, ``conductor_results`` (per-cluster architect
metrics) and ``cluster_registry``; all arithmetic is deterministic.
Metrics missing from a malformed/partial payload use neutral defaults
(lock-in acceptance 0.60, smart-home requirement 0.30, subscription
resentment 0.25, cloud tolerance 0.55, API interest 0.20, cross-device
0.50, household sharing 0.40, voice expectation 0.25, gate 0.50) so a
missing field never manufactures a LOCKED tier or an extreme blocker.
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable

from app.schemas.ecosystem_compatibility import (
    BLOCKER_CLOUD,
    BLOCKER_LOCKIN,
    BLOCKER_SMART_HOME,
    BLOCKER_SUBSCRIPTION,
    BLOCKER_VOICE,
    ClusterEcosystemProfile,
    EcosystemCompatibilityOut,
    EcosystemLever,
    LEVER_API,
    LEVER_HOUSEHOLD,
    LEVER_MATTER,
    LEVER_PRIVACY,
    LEVER_SUBSCRIPTION,
    LEVER_VOICE,
    TIER_LOCKED,
    TIER_OPEN,
    TIER_PARTIAL,
    TIER_TETHERED,
    VERDICT_BLOCKED,
    VERDICT_FRAGILE,
    VERDICT_INSUFFICIENT,
    VERDICT_SEAMLESS,
    VERDICT_WORKABLE,
)

# Ordered blocker keys — used for tie-breaking and market aggregation so
# the output is stable regardless of dict ordering.
BLOCKER_ORDER: tuple[str, ...] = (
    BLOCKER_LOCKIN,
    BLOCKER_SMART_HOME,
    BLOCKER_SUBSCRIPTION,
    BLOCKER_CLOUD,
    BLOCKER_VOICE,
)

BLOCKER_LABELS: dict[str, str] = {
    BLOCKER_LOCKIN: "Platform lock-in resistance",
    BLOCKER_SMART_HOME: "Smart-home compatibility requirement",
    BLOCKER_SUBSCRIPTION: "Hardware subscription resentment",
    BLOCKER_CLOUD: "Cloud privacy concern",
    BLOCKER_VOICE: "Voice-assistant expectation",
}

LEVER_LABELS: dict[str, str] = {
    LEVER_MATTER: "Matter + Alexa/Google/Apple Home support",
    LEVER_API: "Open API / SDK / webhooks",
    LEVER_SUBSCRIPTION: "Optional subscription or one-time price",
    LEVER_PRIVACY: "Local-first & private cloud mode",
    LEVER_VOICE: "Voice-assistant integration",
    LEVER_HOUSEHOLD: "Multi-user household & accessory design",
}

# Cluster-tier thresholds (compatibility index; higher = better).
TIER_OPEN_INDEX: float = 0.75
TIER_PARTIAL_INDEX: float = 0.55
TIER_TETHERED_INDEX: float = 0.40

# Verdict thresholds (weighted market compatibility index).
VERDICT_SEAMLESS_INDEX: float = 0.75
VERDICT_WORKABLE_INDEX: float = 0.55
VERDICT_FRAGILE_INDEX: float = 0.40

# Composite weights (sum to 1.0).
WEIGHT_LOCKIN: float = 0.25
WEIGHT_SMART_HOME: float = 0.20
WEIGHT_SUBSCRIPTION: float = 0.20
WEIGHT_CLOUD: float = 0.20
WEIGHT_VOICE: float = 0.15

# Neutral defaults for metrics missing from a malformed/partial payload.
# They lean middle-of-road so a missing field neither manufactures a
# LOCKED tier nor hides a real blocker present in other metrics.
DEFAULT_LOCKIN_ACCEPTANCE: float = 0.60
DEFAULT_SMART_HOME_REQUIREMENT: float = 0.30
DEFAULT_SUBSCRIPTION_RESENTMENT: float = 0.25
DEFAULT_CLOUD_TOLERANCE: float = 0.55
DEFAULT_API_INTEREST: float = 0.20
DEFAULT_CROSS_DEVICE: float = 0.50
DEFAULT_HOUSEHOLD_SHARING: float = 0.40
DEFAULT_VOICE_EXPECTATION: float = 0.25
DEFAULT_GATE: float = 0.50

# Lever opportunity thresholds — a lever applies to a cluster when the
# underlying ecosystem metric crosses the friction line (requirements /
# resentment / expectations above, tolerances below).
LEVER_SMART_HOME_MIN: float = 0.30
LEVER_API_MIN: float = 0.25
LEVER_SUBSCRIPTION_MIN: float = 0.50
LEVER_CLOUD_TOLERANCE_MAX: float = 0.45
LEVER_VOICE_MIN: float = 0.30
LEVER_HOUSEHOLD_MIN: float = 0.40

# Flag thresholds (weighted market aggregates; higher = better except
# smart-home requirement / subscription resentment / voice expectation
# where higher = worse).
FLAG_LOCKIN_ACCEPTANCE_MIN: float = 0.45
FLAG_SMART_HOME_MAX: float = 0.30
FLAG_SUBSCRIPTION_MAX: float = 0.50
FLAG_CLOUD_TOLERANCE_MIN: float = 0.45
FLAG_VOICE_MAX: float = 0.30


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


def _ecosystem_metrics(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> dict[str, Any]:
    """Extract the EcosystemCompatibilityArchitect metrics block for one
    cluster."""
    if not conductor_results:
        return {}
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return {}
    architect = cluster_block.get("EcosystemCompatibilityArchitect")
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
    architect = cluster_block.get("EcosystemCompatibilityArchitect")
    if not isinstance(architect, dict):
        return []
    flags = architect.get("flags")
    if not isinstance(flags, dict):
        return []
    return sorted(
        key for key, value in flags.items() if bool(value)
    )


def _severities(metrics: dict[str, Any]) -> dict[str, float]:
    """Normalized compatibility-blocker severities for one cluster
    (0..1, higher = worse)."""
    lockin_acceptance = _clamp(
        _safe_float(
            metrics.get("platform_lockin_acceptance"),
            DEFAULT_LOCKIN_ACCEPTANCE,
        )
    )
    smart_home_req = _clamp(
        _safe_float(
            metrics.get("smart_home_compatibility_requirement"),
            DEFAULT_SMART_HOME_REQUIREMENT,
        )
    )
    subscription = _clamp(
        _safe_float(
            metrics.get("subscription_hardware_resentment"),
            DEFAULT_SUBSCRIPTION_RESENTMENT,
        )
    )
    cloud_tolerance = _clamp(
        _safe_float(
            metrics.get("cloud_storage_tolerance"),
            DEFAULT_CLOUD_TOLERANCE,
        )
    )
    voice = _clamp(
        _safe_float(
            metrics.get("voice_assistant_expectation"),
            DEFAULT_VOICE_EXPECTATION,
        )
    )
    return {
        BLOCKER_LOCKIN: round(1.0 - lockin_acceptance, 4),
        BLOCKER_SMART_HOME: round(smart_home_req, 4),
        BLOCKER_SUBSCRIPTION: round(subscription, 4),
        BLOCKER_CLOUD: round(1.0 - cloud_tolerance, 4),
        BLOCKER_VOICE: round(voice, 4),
    }


def _primary_blocker(severities: dict[str, float]) -> tuple[str, float]:
    """Worst blocker; ties resolve to the earlier key in BLOCKER_ORDER."""
    best_key = BLOCKER_ORDER[0]
    best_value = severities.get(best_key, 0.0)
    for key in BLOCKER_ORDER[1:]:
        value = severities.get(key, 0.0)
        if value > best_value:
            best_key = key
            best_value = value
    return best_key, round(best_value, 4)


def _compatibility_index(severities: dict[str, float]) -> float:
    """Composite 0..1 compatibility score (higher = more open /
    compatible)."""
    return _clamp(
        1.0
        - WEIGHT_LOCKIN * severities.get(BLOCKER_LOCKIN, 0.0)
        - WEIGHT_SMART_HOME * severities.get(BLOCKER_SMART_HOME, 0.0)
        - WEIGHT_SUBSCRIPTION * severities.get(BLOCKER_SUBSCRIPTION, 0.0)
        - WEIGHT_CLOUD * severities.get(BLOCKER_CLOUD, 0.0)
        - WEIGHT_VOICE * severities.get(BLOCKER_VOICE, 0.0)
    )


def _compatibility_tier(index: float) -> str:
    if index >= TIER_OPEN_INDEX:
        return TIER_OPEN
    if index >= TIER_PARTIAL_INDEX:
        return TIER_PARTIAL
    if index >= TIER_TETHERED_INDEX:
        return TIER_TETHERED
    return TIER_LOCKED


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
) -> EcosystemLever:
    share = _opportunity_share(rows, predicate)
    return EcosystemLever(
        key=key,
        label=LEVER_LABELS[key],
        market_value=round(_weighted_average(rows, metric_key), 4),
        opportunity_share=round(share, 4),
        action=action.format(share=_fmt_pct(share)),
    )


def build_ecosystem_compatibility(
    results: dict[str, Any] | None,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    conductor_results: dict[str, Any] | None = None,
    cluster_registry: list[dict[str, Any]] | None = None,
    product_type: str = "saas",
) -> EcosystemCompatibilityOut:
    """Compose the ecosystem-compatibility read from completed results.

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
        metrics = _ecosystem_metrics(conductor_results, cid)
        if not metrics:
            continue

        lockin_acceptance = _clamp(
            _safe_float(
                metrics.get("platform_lockin_acceptance"),
                DEFAULT_LOCKIN_ACCEPTANCE,
            )
        )
        smart_home_req = _clamp(
            _safe_float(
                metrics.get("smart_home_compatibility_requirement"),
                DEFAULT_SMART_HOME_REQUIREMENT,
            )
        )
        subscription = _clamp(
            _safe_float(
                metrics.get("subscription_hardware_resentment"),
                DEFAULT_SUBSCRIPTION_RESENTMENT,
            )
        )
        cloud_tolerance = _clamp(
            _safe_float(
                metrics.get("cloud_storage_tolerance"),
                DEFAULT_CLOUD_TOLERANCE,
            )
        )
        api_interest = _clamp(
            _safe_float(
                metrics.get("developer_api_interest"),
                DEFAULT_API_INTEREST,
            )
        )
        cross_device = _clamp(
            _safe_float(
                metrics.get("cross_device_interoperability"),
                DEFAULT_CROSS_DEVICE,
            )
        )
        household_sharing = _clamp(
            _safe_float(
                metrics.get("household_sharing_behaviour"),
                DEFAULT_HOUSEHOLD_SHARING,
            )
        )
        voice = _clamp(
            _safe_float(
                metrics.get("voice_assistant_expectation"),
                DEFAULT_VOICE_EXPECTATION,
            )
        )
        gate = _clamp(
            _safe_float(
                metrics.get("ecosystem_compatibility_gate"),
                DEFAULT_GATE,
            )
        )

        severities = _severities(metrics)
        index = _compatibility_index(severities)
        blocker, blocker_score = _primary_blocker(severities)
        covered_weight += weight
        rows.append(
            {
                "cluster_id": cid,
                "cluster_name": str(entry.get("name", "") or cid),
                "population_weight": weight,
                "lockin_acceptance": lockin_acceptance,
                "smart_home_req": smart_home_req,
                "subscription": subscription,
                "cloud_tolerance": cloud_tolerance,
                "api_interest": api_interest,
                "cross_device": cross_device,
                "household_sharing": household_sharing,
                "voice": voice,
                "gate": gate,
                "compatibility_index": round(index, 4),
                "tier": _compatibility_tier(index),
                "blocker": blocker,
                "blocker_score": blocker_score,
                "architect_flags": _architect_flags(
                    conductor_results, cid
                ),
            }
        )

    architect_available = any(
        _ecosystem_metrics(conductor_results, str(entry.get("cluster_id", "")))
        for entry in registry
    )

    meta: dict[str, Any] = {
        "signal_quality": signal_quality,
        "total_clusters": len(registry),
        "covered_clusters": len(rows),
        "covered_weight": round(covered_weight, 4),
        "primary_blocker_score": 0.0,
        "product_type_supported": architect_available,
        "thresholds": {
            "tier_open_index": TIER_OPEN_INDEX,
            "tier_partial_index": TIER_PARTIAL_INDEX,
            "tier_tethered_index": TIER_TETHERED_INDEX,
            "verdict_seamless_index": VERDICT_SEAMLESS_INDEX,
            "verdict_workable_index": VERDICT_WORKABLE_INDEX,
            "verdict_fragile_index": VERDICT_FRAGILE_INDEX,
        },
    }

    if not rows or covered_weight <= 0.0:
        return EcosystemCompatibilityOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                (
                    "EcosystemCompatibilityArchitect only activates for "
                    "consumer_hardware, health_hardware, iot_hardware, "
                    "smart_home and wearable product types — this run "
                    "does not use that stack."
                    if not architect_available
                    else "No per-cluster EcosystemCompatibilityArchitect "
                    "metrics were available for this run."
                ),
            ],
            meta=meta,
        )

    index_avg = _weighted_average(rows, "compatibility_index")
    lockin_avg = _weighted_average(rows, "lockin_acceptance")
    smart_home_avg = _weighted_average(rows, "smart_home_req")
    subscription_avg = _weighted_average(rows, "subscription")
    cloud_avg = _weighted_average(rows, "cloud_tolerance")
    api_avg = _weighted_average(rows, "api_interest")
    cross_device_avg = _weighted_average(rows, "cross_device")
    household_avg = _weighted_average(rows, "household_sharing")
    voice_avg = _weighted_average(rows, "voice")
    gate_avg = _weighted_average(rows, "gate")

    open_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_OPEN
    )
    partial_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_PARTIAL
    )
    tethered_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_TETHERED
    )
    locked_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_LOCKED
    )
    open_share = open_weight / covered_weight
    partial_share = partial_weight / covered_weight
    tethered_share = tethered_weight / covered_weight
    locked_share = locked_weight / covered_weight

    if index_avg >= VERDICT_SEAMLESS_INDEX:
        verdict = VERDICT_SEAMLESS
    elif index_avg >= VERDICT_WORKABLE_INDEX:
        verdict = VERDICT_WORKABLE
    elif index_avg >= VERDICT_FRAGILE_INDEX:
        verdict = VERDICT_FRAGILE
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
    # average of each cluster's worst normalized blocker score.
    primary_blocker_score = _weighted_average(rows, "blocker_score")
    meta["primary_blocker_score"] = round(primary_blocker_score, 4)

    flags: list[str] = []
    if any(row["tier"] == TIER_LOCKED for row in rows):
        flags.append("locked_clusters")
    if lockin_avg < FLAG_LOCKIN_ACCEPTANCE_MIN:
        flags.append("platform_lockin_market")
    if smart_home_avg >= FLAG_SMART_HOME_MAX:
        flags.append("smart_home_gate_market")
    if subscription_avg >= FLAG_SUBSCRIPTION_MAX:
        flags.append("subscription_resentment_market")
    if cloud_avg < FLAG_CLOUD_TOLERANCE_MIN:
        flags.append("cloud_privacy_market")
    if voice_avg >= FLAG_VOICE_MAX:
        flags.append("voice_expectation_market")

    levers: list[EcosystemLever] = [
        _lever(
            rows,
            LEVER_MATTER,
            "smart_home_req",
            lambda row: row["smart_home_req"] >= LEVER_SMART_HOME_MIN,
            "Add Matter plus Alexa/Google/Apple Home support — {share} "
            "of the covered market requires smart-home compatibility.",
        ),
        _lever(
            rows,
            LEVER_API,
            "api_interest",
            lambda row: row["api_interest"] >= LEVER_API_MIN,
            "Publish an open API, SDK and webhooks — {share} of the "
            "covered market wants developer-level integration.",
        ),
        _lever(
            rows,
            LEVER_SUBSCRIPTION,
            "subscription",
            lambda row: row["subscription"] >= LEVER_SUBSCRIPTION_MIN,
            "Make the hardware subscription optional or fold it into the "
            "device price — {share} of the covered market resents a "
            "forced subscription.",
        ),
        _lever(
            rows,
            LEVER_PRIVACY,
            "cloud_tolerance",
            lambda row: row["cloud_tolerance"] < LEVER_CLOUD_TOLERANCE_MAX,
            "Offer local/on-device storage plus a private cloud mode — "
            "{share} of the covered market has cloud privacy concerns.",
        ),
        _lever(
            rows,
            LEVER_VOICE,
            "voice",
            lambda row: row["voice"] >= LEVER_VOICE_MIN,
            "Ship voice-assistant integration — {share} of the covered "
            "market expects voice control.",
        ),
        _lever(
            rows,
            LEVER_HOUSEHOLD,
            "household_sharing",
            lambda row: row["household_sharing"] >= LEVER_HOUSEHOLD_MIN,
            "Design multi-user household profiles and accessory attach — "
            "{share} of the covered market shares devices across the "
            "household.",
        ),
    ]
    levers.sort(key=lambda lever: (-lever.opportunity_share, lever.key))

    recommendations: list[str] = []
    if verdict == VERDICT_SEAMLESS:
        recommendations.append(
            f"Ecosystem compatibility is strong (index = {index_avg:.2f}) "
            "— openness and integrations are a differentiator; keep SDKs "
            "and docs current as the install base grows."
        )
    elif verdict == VERDICT_WORKABLE:
        recommendations.append(
            f"Ecosystem compatibility is workable but not universal "
            f"(index = {index_avg:.2f}, "
            f"{_fmt_pct(tethered_share + locked_share)} already "
            "TETHERED/LOCKED) — close the top integration gaps before "
            "scaling."
        )
    elif verdict == VERDICT_FRAGILE:
        recommendations.append(
            f"Ecosystem compatibility is fragile (index = {index_avg:.2f}) "
            "— expect elevated churn and word-of-mouth friction in "
            "locked segments unless integration gaps close."
        )
    else:
        recommendations.append(
            f"Ecosystem compatibility is a launch blocker (index = "
            f"{index_avg:.2f}, {_fmt_pct(locked_share)} of the covered "
            "market LOCKED) — treat integration support as a go/no-go "
            "requirement."
        )
    recommendations.append(
        f"Primary compatibility blocker: {BLOCKER_LABELS[primary_blocker]} "
        f"(severity {primary_blocker_score:.2f}, affects "
        f"{_fmt_pct(primary_blocker_share)} of the covered market)."
    )
    if levers:
        top = levers[0]
        recommendations.append(
            f"Highest-leverage action: {top.label} — touches "
            f"{_fmt_pct(top.opportunity_share)} of the covered market."
        )
    if lockin_avg < FLAG_LOCKIN_ACCEPTANCE_MIN:
        recommendations.append(
            f"Platform lock-in acceptance averages "
            f"{_fmt_pct(lockin_avg)} — keep the device usable with "
            "competing ecosystems and avoid exclusive tie-ins."
        )
    if smart_home_avg >= FLAG_SMART_HOME_MAX:
        recommendations.append(
            f"Smart-home compatibility is required by "
            f"{_fmt_pct(smart_home_avg)} of the covered market — add "
            "Matter, Alexa, Google Home and Apple Home support."
        )
    if subscription_avg >= FLAG_SUBSCRIPTION_MAX:
        recommendations.append(
            f"Subscription resentment averages "
            f"{_fmt_pct(subscription_avg)} — offer a lifetime / one-time "
            "option alongside the recurring plan."
        )
    if cloud_avg < FLAG_CLOUD_TOLERANCE_MIN:
        recommendations.append(
            f"Cloud tolerance averages {_fmt_pct(cloud_avg)} — ship a "
            "local-first mode with on-device processing and opt-in "
            "cloud sync."
        )
    if voice_avg >= FLAG_VOICE_MAX:
        recommendations.append(
            f"Voice-assistant expectation averages {_fmt_pct(voice_avg)} "
            "— integrate the assistants your target households already "
            "use."
        )

    return EcosystemCompatibilityOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type_name,
        verdict=verdict,
        compatibility_index=round(index_avg, 4),
        weighted_platform_lockin_acceptance=round(lockin_avg, 4),
        weighted_smart_home_requirement=round(smart_home_avg, 4),
        weighted_subscription_resentment=round(subscription_avg, 4),
        weighted_cloud_tolerance=round(cloud_avg, 4),
        weighted_developer_api_interest=round(api_avg, 4),
        weighted_cross_device_interoperability=round(cross_device_avg, 4),
        weighted_household_sharing=round(household_avg, 4),
        weighted_voice_expectation=round(voice_avg, 4),
        weighted_compatibility_gate=round(gate_avg, 4),
        open_share=round(open_share, 4),
        partial_share=round(partial_share, 4),
        tethered_share=round(tethered_share, 4),
        locked_share=round(locked_share, 4),
        primary_blocker=primary_blocker,
        primary_blocker_label=BLOCKER_LABELS[primary_blocker],
        primary_blocker_share=round(primary_blocker_share, 4),
        blocker_distribution=blocker_distribution,
        cluster_profiles=[
            ClusterEcosystemProfile(
                cluster_id=row["cluster_id"],
                cluster_name=row["cluster_name"],
                population_weight=row["population_weight"],
                platform_lockin_acceptance=row["lockin_acceptance"],
                smart_home_compatibility_requirement=row["smart_home_req"],
                subscription_hardware_resentment=row["subscription"],
                cloud_storage_tolerance=row["cloud_tolerance"],
                developer_api_interest=row["api_interest"],
                cross_device_interoperability=row["cross_device"],
                household_sharing_behaviour=row["household_sharing"],
                voice_assistant_expectation=row["voice"],
                ecosystem_compatibility_gate=row["gate"],
                compatibility_index=row["compatibility_index"],
                compatibility_tier=row["tier"],
                primary_blocker=row["blocker"],
                primary_blocker_score=row["blocker_score"],
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
    "BLOCKER_LABELS",
    "BLOCKER_ORDER",
    "LEVER_LABELS",
    "build_ecosystem_compatibility",
]
