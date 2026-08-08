"""
Pure support-friction analysis for completed simulation results.

Answers the founder's "how much support burden will this customer base
create, and which levers remove it?" question by turning the
``SupportFrictionArchitect`` per-cluster metrics into a deterministic,
population-weighted support read:

* **Friction index** — a 0..1 market-weighted composite (higher =
  worse) of ticket likelihood (30%), the self-serve resolution gap
  (20%), response-time tolerance (15%), bug tolerance (10%), downtime
  sensitivity (15%) and documentation perception (10%). The component
  severities are normalized against the architect's modeled ranges so
  the six drivers are comparable.
* **Cluster tiers** — every covered cluster is classified ``LOW``
  (index < 0.30) / ``MODERATE`` (< 0.40) / ``HIGH`` (< 0.50) /
  ``CRITICAL`` (>= 0.50).
* **Primary friction driver** — each cluster is attributed to the
  worst of the six modeled drivers (ticket volume, self-serve gap,
  response tolerance, bug tolerance, downtime sensitivity,
  documentation gap). The market-level driver distribution is the
  population-weighted share of those attributions.
* **Support levers** — six interventions (documentation & onboarding,
  self-service build, live chat, ticket prevention, reliability SLA,
  quality gate) ranked by the share of the covered market where the
  underlying driver is present.
* **Burden estimate** — expected monthly support contacts and the
  equivalent support-staff headcount per 10k users, derived from the
  weighted ticket likelihood and self-serve resolution rate (500
  contacts per agent per month heuristic).

The verdict is ``LOW_BURDEN`` when the weighted friction index is below
0.30, ``MODERATE`` below 0.40, ``HIGH`` below 0.50, ``CRITICAL`` above
that, and ``INSUFFICIENT_DATA`` when no cluster has usable metrics.
``SupportFrictionArchitect`` runs in every conductor stack, so all 15
product types are supported.

The covered market is the population weight of clusters with usable
metrics and a positive population share; zero-weight clusters are
excluded from profiles, flags and lever shares.

No DB / I/O — verifiable without FastAPI or PostgreSQL. The route layer
supplies ``results``, ``conductor_results`` (per-cluster architect
metrics) and ``cluster_registry``; all arithmetic is deterministic.
Metrics missing from a malformed/partial payload use neutral defaults
(ticket 0.25, self-serve 0.50, tolerance 12h, bug tolerance 2.0,
downtime 0.30, documentation effect 0.0) so a missing field never
manufactures a CRITICAL tier or an extreme driver.
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable

from app.schemas.support_friction import (
    DRIVER_BUG,
    DRIVER_DOCS,
    DRIVER_DOWNTIME,
    DRIVER_RESPONSE,
    DRIVER_SELF_SERVE,
    DRIVER_TICKET,
    LEVER_CHAT,
    LEVER_DOCS,
    LEVER_ONBOARDING,
    LEVER_QUALITY,
    LEVER_RELIABILITY,
    LEVER_SELF_SERVE,
    TIER_CRITICAL,
    TIER_HIGH,
    TIER_LOW,
    TIER_MODERATE,
    VERDICT_CRITICAL,
    VERDICT_HIGH,
    VERDICT_INSUFFICIENT,
    VERDICT_LOW_BURDEN,
    VERDICT_MODERATE,
    ClusterFrictionProfile,
    SupportFrictionOut,
    SupportLever,
)

# Ordered driver keys — used for tie-breaking and market aggregation so
# the output is stable regardless of dict ordering.
DRIVER_ORDER: tuple[str, ...] = (
    DRIVER_TICKET,
    DRIVER_SELF_SERVE,
    DRIVER_RESPONSE,
    DRIVER_BUG,
    DRIVER_DOWNTIME,
    DRIVER_DOCS,
)

DRIVER_LABELS: dict[str, str] = {
    DRIVER_TICKET: "High ticket volume",
    DRIVER_SELF_SERVE: "Low self-service resolution",
    DRIVER_RESPONSE: "Tight response-time tolerance",
    DRIVER_BUG: "Low bug tolerance",
    DRIVER_DOWNTIME: "High downtime sensitivity",
    DRIVER_DOCS: "Documentation gap",
}

LEVER_LABELS: dict[str, str] = {
    LEVER_DOCS: "Documentation & onboarding",
    LEVER_SELF_SERVE: "Self-service build",
    LEVER_CHAT: "Live chat",
    LEVER_ONBOARDING: "Ticket prevention",
    LEVER_RELIABILITY: "Reliability SLA",
    LEVER_QUALITY: "Quality gate",
}

# Cluster-tier thresholds (friction index; higher = worse).
TIER_LOW_INDEX: float = 0.30
TIER_MODERATE_INDEX: float = 0.40
TIER_HIGH_INDEX: float = 0.50

# Verdict thresholds (weighted market friction index).
VERDICT_LOW_INDEX: float = 0.30
VERDICT_MODERATE_INDEX: float = 0.40
VERDICT_HIGH_INDEX: float = 0.50

# Normalization anchors for driver severities (all 0..1, higher = worse).
RESPONSE_SCALE_HOURS: float = 8.0
BUG_TOLERANCE_SCALE: float = 5.0
SELF_SERVE_SEVERITY_SCALE: float = 0.45
DOCUMENTATION_SCALE: float = 0.30

# Composite weights (sum to 1.0).
WEIGHT_TICKET: float = 0.30
WEIGHT_SELF_SERVE: float = 0.20
WEIGHT_RESPONSE: float = 0.15
WEIGHT_BUG: float = 0.10
WEIGHT_DOWNTIME: float = 0.15
WEIGHT_DOCS: float = 0.10

# Support-staff heuristic: one agent resolves ~500 contacts/month.
CONTACTS_PER_AGENT_MONTH: float = 500.0

# Neutral defaults for metrics missing from a malformed/partial payload.
DEFAULT_TICKET: float = 0.25
DEFAULT_SELF_SERVE: float = 0.50
DEFAULT_TOLERANCE_HOURS: float = 12.0
DEFAULT_BUG_TOLERANCE: float = 2.0
DEFAULT_DOWNTIME: float = 0.30
DEFAULT_DOC_EFFECT: float = 0.0

# Lever opportunity thresholds — a lever applies to a cluster when the
# underlying driver is present.
LEVER_DOCS_SEVERITY_THRESHOLD: float = 0.50
LEVER_DOCS_EFFECT_THRESHOLD: float = 0.10
LEVER_SELF_SERVE_THRESHOLD: float = 0.20
LEVER_CHAT_TICKET_THRESHOLD: float = 0.30
LEVER_CHAT_TOLERANCE_HOURS: float = 8.0
LEVER_ONBOARDING_TICKET_THRESHOLD: float = 0.35
LEVER_RELIABILITY_THRESHOLD: float = 0.50

# Flag thresholds.
FLAG_TICKET_THRESHOLD: float = 0.30
FLAG_SELF_SERVE_THRESHOLD: float = 0.30
FLAG_TOLERANCE_HOURS: float = 8.0
FLAG_DOWNTIME_THRESHOLD: float = 0.50
FLAG_BUG_THRESHOLD: float = 2.0
FLAG_DOC_EFFECT_THRESHOLD: float = 0.10


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


def _friction_metrics(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> dict[str, Any]:
    """Extract the SupportFrictionArchitect metrics block for one cluster."""
    if not conductor_results:
        return {}
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return {}
    architect = cluster_block.get("SupportFrictionArchitect")
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
    architect = cluster_block.get("SupportFrictionArchitect")
    if not isinstance(architect, dict):
        return []
    flags = architect.get("flags")
    if not isinstance(flags, dict):
        return []
    return sorted(
        key for key, value in flags.items() if bool(value)
    )


def _severities(metrics: dict[str, Any]) -> dict[str, float]:
    """Normalized support-friction driver severities for one cluster
    (0..1, higher = worse)."""
    ticket = _clamp(
        _safe_float(
            metrics.get("support_ticket_likelihood"),
            DEFAULT_TICKET,
        )
    )
    self_serve = _clamp(
        _safe_float(
            metrics.get("self_serve_resolution_rate"),
            DEFAULT_SELF_SERVE,
        )
    )
    tolerance_hours = max(
        0.0,
        _safe_float(
            metrics.get("response_time_tolerance_hours"),
            DEFAULT_TOLERANCE_HOURS,
        ),
    )
    bug_tolerance = max(
        0.0,
        _safe_float(
            metrics.get("bug_tolerance_threshold"),
            DEFAULT_BUG_TOLERANCE,
        ),
    )
    downtime = _clamp(
        _safe_float(
            metrics.get("downtime_sensitivity"),
            DEFAULT_DOWNTIME,
        )
    )
    doc_effect = _safe_float(
        metrics.get("documentation_quality_perception_effect"),
        DEFAULT_DOC_EFFECT,
    )
    return {
        DRIVER_TICKET: round(ticket, 4),
        DRIVER_SELF_SERVE: round(
            _clamp(
                (SELF_SERVE_SEVERITY_SCALE - self_serve)
                / SELF_SERVE_SEVERITY_SCALE
            ),
            4,
        ),
        DRIVER_RESPONSE: round(
            _clamp(
                (RESPONSE_SCALE_HOURS - tolerance_hours)
                / RESPONSE_SCALE_HOURS
            ),
            4,
        ),
        DRIVER_BUG: round(
            _clamp(
                (3.0 - bug_tolerance) / BUG_TOLERANCE_SCALE
            ),
            4,
        ),
        DRIVER_DOWNTIME: round(downtime, 4),
        DRIVER_DOCS: round(
            _clamp(
                1.0 - max(0.0, doc_effect) / DOCUMENTATION_SCALE
            ),
            4,
        ),
    }


def _primary_driver(severities: dict[str, float]) -> tuple[str, float]:
    """Worst driver; ties resolve to the earlier key in DRIVER_ORDER."""
    best_key = DRIVER_ORDER[0]
    best_value = severities.get(best_key, 0.0)
    for key in DRIVER_ORDER[1:]:
        value = severities.get(key, 0.0)
        if value > best_value:
            best_key = key
            best_value = value
    return best_key, round(best_value, 4)


def _friction_index(severities: dict[str, float]) -> float:
    """Composite 0..1 support-friction score (higher = worse)."""
    return _clamp(
        WEIGHT_TICKET * severities.get(DRIVER_TICKET, 0.0)
        + WEIGHT_SELF_SERVE * severities.get(DRIVER_SELF_SERVE, 0.0)
        + WEIGHT_RESPONSE * severities.get(DRIVER_RESPONSE, 0.0)
        + WEIGHT_BUG * severities.get(DRIVER_BUG, 0.0)
        + WEIGHT_DOWNTIME * severities.get(DRIVER_DOWNTIME, 0.0)
        + WEIGHT_DOCS * severities.get(DRIVER_DOCS, 0.0)
    )


def _friction_tier(friction_index: float) -> str:
    if friction_index < TIER_LOW_INDEX:
        return TIER_LOW
    if friction_index < TIER_MODERATE_INDEX:
        return TIER_MODERATE
    if friction_index < TIER_HIGH_INDEX:
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
) -> SupportLever:
    share = _opportunity_share(rows, predicate)
    return SupportLever(
        key=key,
        label=LEVER_LABELS[key],
        market_value=round(_weighted_average(rows, metric_key), 4),
        opportunity_share=round(share, 4),
        action=action.format(share=_fmt_pct(share)),
    )


def build_support_friction(
    results: dict[str, Any] | None,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    conductor_results: dict[str, Any] | None = None,
    cluster_registry: list[dict[str, Any]] | None = None,
    product_type: str = "saas",
) -> SupportFrictionOut:
    """Compose the support-friction read from completed results.

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
        metrics = _friction_metrics(conductor_results, cid)
        if not metrics:
            continue

        ticket = _clamp(
            _safe_float(
                metrics.get("support_ticket_likelihood"),
                DEFAULT_TICKET,
            )
        )
        self_serve = _clamp(
            _safe_float(
                metrics.get("self_serve_resolution_rate"),
                DEFAULT_SELF_SERVE,
            )
        )
        tolerance_hours = max(
            0.0,
            _safe_float(
                metrics.get("response_time_tolerance_hours"),
                DEFAULT_TOLERANCE_HOURS,
            ),
        )
        bug_tolerance = max(
            0.0,
            _safe_float(
                metrics.get("bug_tolerance_threshold"),
                DEFAULT_BUG_TOLERANCE,
            ),
        )
        downtime = _clamp(
            _safe_float(
                metrics.get("downtime_sensitivity"),
                DEFAULT_DOWNTIME,
            )
        )
        doc_effect = _safe_float(
            metrics.get("documentation_quality_perception_effect"),
            DEFAULT_DOC_EFFECT,
        )

        severities = _severities(metrics)
        friction_index = _friction_index(severities)
        driver, driver_score = _primary_driver(severities)
        covered_weight += weight
        rows.append(
            {
                "cluster_id": cid,
                "cluster_name": str(entry.get("name", "") or cid),
                "population_weight": weight,
                "ticket": ticket,
                "self_serve": self_serve,
                "tolerance_hours": tolerance_hours,
                "bug_tolerance": bug_tolerance,
                "downtime": downtime,
                "doc_effect": doc_effect,
                "friction_index": friction_index,
                "tier": _friction_tier(friction_index),
                "driver": driver,
                "driver_score": driver_score,
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
        "primary_driver_score": 0.0,
        "product_type_supported": True,
        "contacts_per_agent_month": CONTACTS_PER_AGENT_MONTH,
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
        return SupportFrictionOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                "No per-cluster SupportFrictionArchitect metrics were "
                "available for this run."
            ],
            meta=meta,
        )

    friction_index_avg = _weighted_average(rows, "friction_index")
    ticket_avg = _weighted_average(rows, "ticket")
    self_serve_avg = _weighted_average(rows, "self_serve")
    tolerance_avg = _weighted_average(rows, "tolerance_hours")
    bug_avg = _weighted_average(rows, "bug_tolerance")
    downtime_avg = _weighted_average(rows, "downtime")
    doc_avg = _weighted_average(rows, "doc_effect")

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

    if friction_index_avg < VERDICT_LOW_INDEX:
        verdict = VERDICT_LOW_BURDEN
    elif friction_index_avg < VERDICT_MODERATE_INDEX:
        verdict = VERDICT_MODERATE
    elif friction_index_avg < VERDICT_HIGH_INDEX:
        verdict = VERDICT_HIGH
    else:
        verdict = VERDICT_CRITICAL

    # Market driver distribution = population-weighted share of
    # per-cluster primary-driver attributions.
    driver_weights: dict[str, float] = {key: 0.0 for key in DRIVER_ORDER}
    for row in rows:
        driver_weights[row["driver"]] += row["population_weight"]
    driver_distribution = {
        key: round(weight / covered_weight, 4)
        for key, weight in driver_weights.items()
    }
    primary_driver = DRIVER_ORDER[0]
    primary_driver_share = driver_distribution[primary_driver]
    for key in DRIVER_ORDER[1:]:
        if driver_distribution[key] > primary_driver_share:
            primary_driver = key
            primary_driver_share = driver_distribution[key]
    # Market-level severity of the attributed driver: population-weighted
    # average of each cluster's worst normalized driver score.
    primary_driver_score = _weighted_average(rows, "driver_score")
    meta["primary_driver_score"] = round(primary_driver_score, 4)

    flags: list[str] = []
    if any(row["tier"] == TIER_CRITICAL for row in rows):
        flags.append("critical_friction_clusters")
    if ticket_avg > FLAG_TICKET_THRESHOLD:
        flags.append("ticket_volume_high")
    if self_serve_avg < FLAG_SELF_SERVE_THRESHOLD:
        flags.append("self_serve_low")
    if any(
        "phone_support_required" in row["architect_flags"]
        for row in rows
    ):
        flags.append("phone_support_required")
    if tolerance_avg < FLAG_TOLERANCE_HOURS:
        flags.append("response_tolerance_tight")
    if downtime_avg > FLAG_DOWNTIME_THRESHOLD:
        flags.append("downtime_sensitive_market")
    if bug_avg <= FLAG_BUG_THRESHOLD:
        flags.append("low_bug_tolerance")
    if doc_avg < FLAG_DOC_EFFECT_THRESHOLD:
        flags.append("documentation_gap")

    levers: list[SupportLever] = [
        _lever(
            rows,
            LEVER_DOCS,
            "doc_effect",
            lambda row: (
                (
                    row["driver"] == DRIVER_DOCS
                    and row["driver_score"] > LEVER_DOCS_SEVERITY_THRESHOLD
                )
                or row["doc_effect"] < LEVER_DOCS_EFFECT_THRESHOLD
            ),
            "Expand the knowledge base and in-app guides — {share} of "
            "the covered market lacks effective documentation.",
        ),
        _lever(
            rows,
            LEVER_SELF_SERVE,
            "self_serve",
            lambda row: (
                row["driver"] == DRIVER_SELF_SERVE
                or row["self_serve"] < LEVER_SELF_SERVE_THRESHOLD
            ),
            "Build self-service support (FAQs, chat-bot, video guides) "
            "for {share} of the covered market.",
        ),
        _lever(
            rows,
            LEVER_CHAT,
            "tolerance_hours",
            lambda row: (
                row["ticket"] > LEVER_CHAT_TICKET_THRESHOLD
                or row["tolerance_hours"] < LEVER_CHAT_TOLERANCE_HOURS
            ),
            "Offer live chat with a fast first response — {share} of "
            "the covered market needs help within hours.",
        ),
        _lever(
            rows,
            LEVER_ONBOARDING,
            "ticket",
            lambda row: (
                row["ticket"] > LEVER_ONBOARDING_TICKET_THRESHOLD
            ),
            "Improve onboarding and error messages to prevent tickets "
            "for {share} of the covered market.",
        ),
        _lever(
            rows,
            LEVER_RELIABILITY,
            "downtime",
            lambda row: row["downtime"] > LEVER_RELIABILITY_THRESHOLD,
            "Publish an uptime SLA and incident comms — {share} of the "
            "covered market is highly downtime-sensitive.",
        ),
        _lever(
            rows,
            LEVER_QUALITY,
            "bug_tolerance",
            lambda row: (
                row["driver"] == DRIVER_BUG
                and row["driver_score"] > 0.0
            ),
            "Run release quality gates — {share} of the covered market "
            "abandons after very few errors.",
        ),
    ]
    levers.sort(key=lambda lever: (-lever.opportunity_share, lever.key))

    contacts_per_10k = int(
        round(10000.0 * ticket_avg * (1.0 - self_serve_avg))
    )
    agents_per_10k = round(
        contacts_per_10k / CONTACTS_PER_AGENT_MONTH,
        1,
    )

    recommendations: list[str] = []
    if verdict == VERDICT_LOW_BURDEN:
        recommendations.append(
            f"Support burden is low (weighted friction index = "
            f"{friction_index_avg:.2f}) — keep documentation and "
            "self-service current as the user base grows."
        )
    elif verdict == VERDICT_MODERATE:
        recommendations.append(
            f"Support burden is workable but not free (friction index = "
            f"{friction_index_avg:.2f}, {_fmt_pct(critical_share)} "
            "already CRITICAL) — pull the strongest lever below to "
            "reduce ticket load before scaling."
        )
    elif verdict == VERDICT_HIGH:
        recommendations.append(
            f"Support burden is high (friction index = "
            f"{friction_index_avg:.2f}) — expect meaningful post-purchase "
            "churn unless self-service and response speed improve."
        )
    else:
        recommendations.append(
            f"Support burden is critical (friction index = "
            f"{friction_index_avg:.2f}, {_fmt_pct(critical_share)} of the "
            "covered market CRITICAL) — treat support capacity as a "
            "launch blocker."
        )
    recommendations.append(
        f"Primary friction driver: {DRIVER_LABELS[primary_driver]} "
        f"(severity {primary_driver_score:.2f}, affects "
        f"{_fmt_pct(primary_driver_share)} of the covered market)."
    )
    recommendations.append(
        f"Estimated support load: ~{contacts_per_10k} contacts per "
        f"10,000 users/month, or ~{agents_per_10k:.1f} full-time "
        "support agents (500 contacts/agent/month heuristic)."
    )
    if ticket_avg > FLAG_TICKET_THRESHOLD:
        recommendations.append(
            f"Ticket likelihood averages {_fmt_pct(ticket_avg)} — "
            "prioritize root-cause fixes over reactive support."
        )
    if self_serve_avg < FLAG_SELF_SERVE_THRESHOLD:
        recommendations.append(
            f"Only {_fmt_pct(self_serve_avg)} of the covered market can "
            "self-resolve — a knowledge base and guided flows will "
            "directly cut contacts."
        )
    if tolerance_avg < FLAG_TOLERANCE_HOURS:
        recommendations.append(
            f"Average response-time tolerance is ~{tolerance_avg:.1f}h — "
            "premium segments expect near-immediate help."
        )
    if downtime_avg > FLAG_DOWNTIME_THRESHOLD:
        recommendations.append(
            f"Downtime sensitivity is {_fmt_pct(downtime_avg)} — "
            "publish SLAs and status pages before launch."
        )
    if bug_avg <= FLAG_BUG_THRESHOLD:
        recommendations.append(
            f"Average bug tolerance is ~{bug_avg:.1f} errors before "
            "abandonment — invest in release quality gates."
        )
    if doc_avg < FLAG_DOC_EFFECT_THRESHOLD:
        recommendations.append(
            f"Documentation perception effect is only "
            f"{doc_avg:.2f} — docs currently add little support value."
        )

    return SupportFrictionOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type_name,
        verdict=verdict,
        friction_index=round(friction_index_avg, 4),
        weighted_ticket_likelihood=round(ticket_avg, 4),
        weighted_self_serve_resolution_rate=round(self_serve_avg, 4),
        weighted_response_time_tolerance_hours=round(tolerance_avg, 1),
        weighted_bug_tolerance_threshold=round(bug_avg, 1),
        weighted_downtime_sensitivity=round(downtime_avg, 4),
        weighted_documentation_effect=round(doc_avg, 4),
        estimated_monthly_contacts_per_10k_users=contacts_per_10k,
        estimated_support_agents_per_10k_users=agents_per_10k,
        low_share=round(low_share, 4),
        moderate_share=round(moderate_share, 4),
        high_share=round(high_share, 4),
        critical_share=round(critical_share, 4),
        primary_driver=primary_driver,
        primary_driver_label=DRIVER_LABELS[primary_driver],
        primary_driver_share=round(primary_driver_share, 4),
        driver_distribution=driver_distribution,
        cluster_profiles=[
            ClusterFrictionProfile(
                cluster_id=row["cluster_id"],
                cluster_name=row["cluster_name"],
                population_weight=row["population_weight"],
                support_ticket_likelihood=round(row["ticket"], 4),
                self_serve_resolution_rate=round(row["self_serve"], 4),
                response_time_tolerance_hours=round(
                    row["tolerance_hours"], 1
                ),
                bug_tolerance_threshold=round(row["bug_tolerance"], 1),
                downtime_sensitivity=round(row["downtime"], 4),
                documentation_quality_perception_effect=round(
                    row["doc_effect"], 4
                ),
                friction_index=round(row["friction_index"], 4),
                friction_tier=row["tier"],
                primary_driver=row["driver"],
                primary_driver_score=row["driver_score"],
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
    "DRIVER_ORDER",
    "build_support_friction",
]
