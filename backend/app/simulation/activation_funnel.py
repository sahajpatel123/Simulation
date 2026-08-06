"""
Pure activation-funnel analysis for completed simulation results.

Answers the founder's "why do first-time users drop before first value,
and what should I fix?" question by turning the ``OnboardingArchitect``
per-cluster metrics into a deterministic, population-weighted activation
read:

* **Activation rate** — population-weighted onboarding completion over the
  covered market, alongside weighted time-to-first-value tolerance,
  empty-state bounce, disclosure limit, and friction aggregates.
* **Cluster tiers** — every covered cluster is classified ``STRONG`` /
  ``MODERATE`` / ``WEAK`` / ``CRITICAL`` from completion, empty-state
  bounce, and the mobile completion penalty.
* **Primary blocker** — each cluster is attributed to the strongest of the
  seven modeled failure modes (completion, empty state, identity
  verification, mandatory profile, mobile gap, permission timing,
  time-to-value impatience). The market-level blocker distribution is the
  population-weighted share of those attributions.
* **Activation levers** — seven interventions (simplify onboarding,
  templates, social proof, permission timing, mobile experience, identity
  reduction, progressive disclosure) ranked by the share of the covered
  market they touch.

The verdict is ``BLOCKED`` when weighted completion is below 45% or at
least 25% of the covered market is in the CRITICAL tier, ``AT_RISK`` when
completion is below 65%, more than 35% is WEAK/CRITICAL, empty-state
bounce is above 40%, or the mobile gap touches more than 15%,
``READY`` when activation is healthy, and ``INSUFFICIENT_DATA`` for
product types whose conductor stack does not run ``OnboardingArchitect``
(hardware, d2c, ...) or when no cluster has usable metrics.

No DB / I/O — verifiable without FastAPI or PostgreSQL. The route layer
supplies ``results``, ``conductor_results`` (per-cluster architect
metrics) and ``cluster_registry``; all arithmetic is deterministic.
Metrics missing from a malformed/partial payload use conservative
defaults (6-minute time-to-value tolerance, 18-step disclosure limit) so
a missing field never manufactures a blocker, lever, or flag.
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable

from app.schemas.activation_funnel import (
    ActivationFunnelOut,
    ActivationLever,
    BLOCKER_COMPLETION,
    BLOCKER_EMPTY_STATE,
    BLOCKER_IDENTITY,
    BLOCKER_MANDATORY_PROFILE,
    BLOCKER_MOBILE_GAP,
    BLOCKER_PERMISSION_TIMING,
    BLOCKER_TIME_TO_VALUE,
    ClusterActivationProfile,
    LEVER_DISCLOSURE,
    LEVER_IDENTITY,
    LEVER_MOBILE,
    LEVER_PERMISSION_TIMING,
    LEVER_SIMPLIFY,
    LEVER_SOCIAL_PROOF,
    LEVER_TEMPLATES,
    TIER_CRITICAL,
    TIER_MODERATE,
    TIER_STRONG,
    TIER_WEAK,
    VERDICT_AT_RISK,
    VERDICT_BLOCKED,
    VERDICT_INSUFFICIENT,
    VERDICT_READY,
)

# Product types whose conductor stack runs OnboardingArchitect.
ACTIVATION_PRODUCT_TYPES: frozenset[str] = frozenset(
    {"saas", "marketplace", "mobile_app", "developer_tool", "enterprise_software"}
)

# Ordered blocker keys — used for tie-breaking and market aggregation so
# the output is stable regardless of dict ordering.
BLOCKER_ORDER: tuple[str, ...] = (
    BLOCKER_COMPLETION,
    BLOCKER_EMPTY_STATE,
    BLOCKER_IDENTITY,
    BLOCKER_MANDATORY_PROFILE,
    BLOCKER_MOBILE_GAP,
    BLOCKER_PERMISSION_TIMING,
    BLOCKER_TIME_TO_VALUE,
)

BLOCKER_LABELS: dict[str, str] = {
    BLOCKER_COMPLETION: "Onboarding completion",
    BLOCKER_EMPTY_STATE: "Empty-state bounce",
    BLOCKER_IDENTITY: "Identity verification friction",
    BLOCKER_MANDATORY_PROFILE: "Mandatory profile churn",
    BLOCKER_MOBILE_GAP: "Mobile completion gap",
    BLOCKER_PERMISSION_TIMING: "Permission timing sensitivity",
    BLOCKER_TIME_TO_VALUE: "Time-to-first-value impatience",
}

# Cluster-tier thresholds.
COMPLETION_CRITICAL_THRESHOLD: float = 0.40
COMPLETION_WEAK_THRESHOLD: float = 0.65
COMPLETION_MODERATE_THRESHOLD: float = 0.80
EMPTY_BOUNCE_WEAK_THRESHOLD: float = 0.45
MOBILE_PENALTY_WEAK_THRESHOLD: float = 0.15

# Verdict thresholds (weighted market aggregates).
VERDICT_BLOCKED_COMPLETION: float = 0.45
VERDICT_BLOCKED_CRITICAL_SHARE: float = 0.25
VERDICT_RISK_COMPLETION: float = 0.65
VERDICT_RISK_WEAK_SHARE: float = 0.35
VERDICT_RISK_EMPTY_BOUNCE: float = 0.40
VERDICT_RISK_MOBILE_GAP_SHARE: float = 0.15

# Conservative defaults for metrics missing from a malformed/partial
# payload. An unknown time-to-value tolerance is treated as the modeled
# midpoint; an unknown disclosure limit as the maximum modeled value, so
# neither field invents an impatience flag or a lever opportunity.
TTFV_NEUTRAL_DEFAULT: float = 6.0
DISCLOSURE_NEUTRAL_DEFAULT: float = 18.0

# Lever opportunity predicates and labels.
LEVER_COMPLETION_OPPORTUNITY: float = 0.65
LEVER_TEMPLATE_PREFERENCE: float = 0.50
LEVER_SOCIAL_LIFT: float = 0.25
LEVER_PERMISSION_SENSITIVITY: float = 0.25
LEVER_MOBILE_PENALTY: float = 0.05
LEVER_IDENTITY_FRICTION: float = 0.20
LEVER_DISCLOSURE_LIMIT: float = 5.0

LEVER_LABELS: dict[str, str] = {
    LEVER_SIMPLIFY: "Simplify onboarding",
    LEVER_TEMPLATES: "Templates for first run",
    LEVER_SOCIAL_PROOF: "Social proof in onboarding",
    LEVER_PERMISSION_TIMING: "Delay permission requests",
    LEVER_MOBILE: "Fix mobile onboarding",
    LEVER_IDENTITY: "Reduce identity verification",
    LEVER_DISCLOSURE: "Progressive disclosure",
}

# Tier sort order: most urgent first.
_TIER_RANK: dict[str, int] = {
    TIER_CRITICAL: 0,
    TIER_WEAK: 1,
    TIER_MODERATE: 2,
    TIER_STRONG: 3,
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


def _onboarding_metrics(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> dict[str, Any]:
    """Extract the OnboardingArchitect metrics block for one cluster."""
    if not conductor_results:
        return {}
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return {}
    architect = cluster_block.get("OnboardingArchitect")
    if not isinstance(architect, dict):
        return {}
    metrics = architect.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _blocker_scores(metrics: dict[str, Any]) -> dict[str, float]:
    """Normalized failure-mode scores for one cluster (0..1, higher = worse)."""
    completion = _clamp(_safe_float(metrics.get("onboarding_completion_rate")))
    empty_bounce = _clamp(
        _safe_float(metrics.get("empty_state_bounce_probability"))
    )
    id_friction = _clamp(
        _safe_float(metrics.get("identity_verification_friction"))
    )
    mandatory = _clamp(_safe_float(metrics.get("mandatory_profile_churn_risk")))
    mobile = _clamp(_safe_float(metrics.get("mobile_completion_penalty")))
    permission = _clamp(
        _safe_float(metrics.get("permission_timing_sensitivity"))
    )
    ttfv = max(
        0.0,
        _safe_float(
            metrics.get("time_to_first_value_tolerance"),
            TTFV_NEUTRAL_DEFAULT,
        ),
    )
    time_value = _clamp(max(0.0, 1.0 - ttfv / 10.0))
    return {
        BLOCKER_COMPLETION: round(1.0 - completion, 4),
        BLOCKER_EMPTY_STATE: round(empty_bounce, 4),
        BLOCKER_IDENTITY: round(id_friction, 4),
        BLOCKER_MANDATORY_PROFILE: round(mandatory, 4),
        BLOCKER_MOBILE_GAP: round(mobile, 4),
        BLOCKER_PERMISSION_TIMING: round(permission, 4),
        BLOCKER_TIME_TO_VALUE: round(time_value, 4),
    }


def _primary_blocker(scores: dict[str, float]) -> tuple[str, float]:
    """Highest-score blocker; ties resolve to the earlier key in BLOCKER_ORDER."""
    best_key = BLOCKER_ORDER[0]
    best_value = scores.get(best_key, 0.0)
    for key in BLOCKER_ORDER[1:]:
        value = scores.get(key, 0.0)
        if value > best_value:
            best_key = key
            best_value = value
    return best_key, round(best_value, 4)


def _activation_tier(
    completion: float,
    empty_bounce: float,
    mobile_penalty: float,
) -> str:
    if completion < COMPLETION_CRITICAL_THRESHOLD:
        return TIER_CRITICAL
    if (
        completion < COMPLETION_WEAK_THRESHOLD
        or empty_bounce > EMPTY_BOUNCE_WEAK_THRESHOLD
        or mobile_penalty > MOBILE_PENALTY_WEAK_THRESHOLD
    ):
        return TIER_WEAK
    if completion < COMPLETION_MODERATE_THRESHOLD:
        return TIER_MODERATE
    return TIER_STRONG


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
) -> ActivationLever:
    share = _opportunity_share(rows, predicate)
    return ActivationLever(
        key=key,
        label=LEVER_LABELS[key],
        market_value=round(_weighted_average(rows, metric_key), 4),
        opportunity_share=round(share, 4),
        action=action.format(share=_fmt_pct(share)),
    )


def build_activation_funnel(
    results: dict[str, Any] | None,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    conductor_results: dict[str, Any] | None = None,
    cluster_registry: list[dict[str, Any]] | None = None,
    product_type: str = "saas",
) -> ActivationFunnelOut:
    """Compose the activation-funnel read from completed results.

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
    supported = product_type_name in ACTIVATION_PRODUCT_TYPES

    rows: list[dict[str, Any]] = []
    covered_weight = 0.0
    for entry in registry:
        cid = str(entry.get("cluster_id", ""))
        if not cid:
            continue
        weight = max(0.0, _safe_float(entry.get("population_weight")))
        metrics = _onboarding_metrics(conductor_results, cid)
        if not metrics:
            continue

        completion = _clamp(_safe_float(metrics.get("onboarding_completion_rate")))
        empty_bounce = _clamp(
            _safe_float(metrics.get("empty_state_bounce_probability"))
        )
        disclosure = max(
            0.0,
            _safe_float(
                metrics.get("progressive_disclosure_limit"),
                DISCLOSURE_NEUTRAL_DEFAULT,
            ),
        )
        mobile = _clamp(_safe_float(metrics.get("mobile_completion_penalty")))
        permission = _clamp(
            _safe_float(metrics.get("permission_timing_sensitivity"))
        )
        mandatory = _clamp(
            _safe_float(metrics.get("mandatory_profile_churn_risk"))
        )
        video_skip = _clamp(
            _safe_float(metrics.get("video_walkthrough_skip_rate"))
        )
        social_lift = _clamp(
            _safe_float(metrics.get("social_onboarding_lift"))
        )
        template_pref = _clamp(
            _safe_float(metrics.get("template_vs_blank_preference"))
        )
        id_friction = _clamp(
            _safe_float(metrics.get("identity_verification_friction"))
        )
        ttfv = max(
            0.0,
            _safe_float(
                metrics.get("time_to_first_value_tolerance"),
                TTFV_NEUTRAL_DEFAULT,
            ),
        )

        blocker, blocker_score = _primary_blocker(_blocker_scores(metrics))
        covered_weight += weight
        rows.append(
            {
                "cluster_id": cid,
                "cluster_name": str(entry.get("name", "") or cid),
                "population_weight": weight,
                "completion": completion,
                "ttfv": ttfv,
                "empty_bounce": empty_bounce,
                "disclosure": disclosure,
                "mobile": mobile,
                "permission": permission,
                "mandatory": mandatory,
                "video_skip": video_skip,
                "social_lift": social_lift,
                "template_pref": template_pref,
                "id_friction": id_friction,
                "tier": _activation_tier(completion, empty_bounce, mobile),
                "blocker": blocker,
                "blocker_score": blocker_score,
            }
        )

    meta: dict[str, Any] = {
        "signal_quality": signal_quality,
        "total_clusters": len(registry),
        "covered_clusters": len(rows),
        "covered_weight": round(covered_weight, 4),
        "product_type_supported": supported,
        "thresholds": {
            "completion_critical": COMPLETION_CRITICAL_THRESHOLD,
            "completion_weak": COMPLETION_WEAK_THRESHOLD,
            "completion_moderate": COMPLETION_MODERATE_THRESHOLD,
            "empty_bounce_weak": EMPTY_BOUNCE_WEAK_THRESHOLD,
            "mobile_penalty_weak": MOBILE_PENALTY_WEAK_THRESHOLD,
        },
    }

    if not supported:
        return ActivationFunnelOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                (
                    f"Activation is not modeled for {product_type_name} — "
                    "this read supports saas, marketplace, mobile_app, "
                    "developer_tool and enterprise_software runs."
                )
            ],
            meta=meta,
        )
    if not rows or covered_weight <= 0.0:
        return ActivationFunnelOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                "No per-cluster OnboardingArchitect metrics were available "
                "for this run."
            ],
            meta=meta,
        )

    completion_avg = _weighted_average(rows, "completion")
    empty_bounce_avg = _weighted_average(rows, "empty_bounce")
    id_friction_avg = _weighted_average(rows, "id_friction")
    mandatory_avg = _weighted_average(rows, "mandatory")
    permission_avg = _weighted_average(rows, "permission")
    social_lift_avg = _weighted_average(rows, "social_lift")
    template_pref_avg = _weighted_average(rows, "template_pref")
    ttfv_avg = _weighted_average(rows, "ttfv")
    disclosure_avg = _weighted_average(rows, "disclosure")

    critical_weight = sum(
        row["population_weight"] for row in rows if row["tier"] == TIER_CRITICAL
    )
    weak_plus_critical_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] in (TIER_WEAK, TIER_CRITICAL)
    )
    critical_share = critical_weight / covered_weight
    weak_share = weak_plus_critical_weight / covered_weight
    mobile_gap_share = _opportunity_share(
        rows, lambda row: row["mobile"] > LEVER_MOBILE_PENALTY
    )

    if completion_avg < VERDICT_BLOCKED_COMPLETION or critical_share >= VERDICT_BLOCKED_CRITICAL_SHARE:
        verdict = VERDICT_BLOCKED
    elif (
        completion_avg < VERDICT_RISK_COMPLETION
        or weak_share >= VERDICT_RISK_WEAK_SHARE
        or empty_bounce_avg > VERDICT_RISK_EMPTY_BOUNCE
        or mobile_gap_share > VERDICT_RISK_MOBILE_GAP_SHARE
    ):
        verdict = VERDICT_AT_RISK
    else:
        verdict = VERDICT_READY

    # Market blocker distribution = population-weighted share of per-cluster
    # primary-blocker attributions.
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

    flags: list[str] = []
    if completion_avg < VERDICT_BLOCKED_COMPLETION:
        flags.append("completion_critical")
    if critical_share >= VERDICT_BLOCKED_CRITICAL_SHARE:
        flags.append("critical_activation_share")
    if empty_bounce_avg > VERDICT_RISK_EMPTY_BOUNCE:
        flags.append("empty_state_risk")
    if mobile_gap_share >= 0.10:
        flags.append("mobile_gap")
    if id_friction_avg > 0.20:
        flags.append("identity_friction")
    if mandatory_avg > 0.20:
        flags.append("mandatory_profile_risk")
    if permission_avg > 0.25:
        flags.append("permission_timing")
    if ttfv_avg < 6.0:
        flags.append("time_to_value_impatience")

    levers: list[ActivationLever] = [
        _lever(
            rows,
            LEVER_SIMPLIFY,
            "completion",
            lambda row: row["completion"] < LEVER_COMPLETION_OPPORTUNITY,
            "Reduce setup steps and time-to-value for {share} of the covered market.",
        ),
        _lever(
            rows,
            LEVER_TEMPLATES,
            "template_pref",
            lambda row: row["template_pref"] >= LEVER_TEMPLATE_PREFERENCE,
            "Offer templates or starter content — {share} prefer that over a blank start.",
        ),
        _lever(
            rows,
            LEVER_SOCIAL_PROOF,
            "social_lift",
            lambda row: row["social_lift"] >= LEVER_SOCIAL_LIFT,
            "Show social proof during onboarding — it lifts completion for {share}.",
        ),
        _lever(
            rows,
            LEVER_PERMISSION_TIMING,
            "permission",
            lambda row: row["permission"] >= LEVER_PERMISSION_SENSITIVITY,
            "Delay permission requests until after first value for {share}.",
        ),
        _lever(
            rows,
            LEVER_MOBILE,
            "mobile",
            lambda row: row["mobile"] > LEVER_MOBILE_PENALTY,
            "Fix mobile onboarding — {share} carry a completion penalty.",
        ),
        _lever(
            rows,
            LEVER_IDENTITY,
            "id_friction",
            lambda row: row["id_friction"] >= LEVER_IDENTITY_FRICTION,
            "Reduce identity-verification steps for {share}.",
        ),
        _lever(
            rows,
            LEVER_DISCLOSURE,
            "disclosure",
            lambda row: row["disclosure"] <= LEVER_DISCLOSURE_LIMIT,
            "Keep first-run steps within the disclosure limit for {share}.",
        ),
    ]
    levers.sort(key=lambda lever: (-lever.opportunity_share, lever.key))

    recommendations: list[str] = []
    if verdict == VERDICT_BLOCKED:
        recommendations.append(
            f"Activation is blocked: {_fmt_pct(completion_avg)} completion and "
            f"{_fmt_pct(critical_share)} of the covered market in CRITICAL tier — "
            "fix first-run completion before scaling acquisition."
        )
    elif verdict == VERDICT_AT_RISK:
        recommendations.append(
            f"Activation is at risk ({_fmt_pct(completion_avg)} completion) — "
            "run an onboarding experiment before scaling spend."
        )
    recommendations.append(
        f"Primary activation blocker: {BLOCKER_LABELS[primary_blocker]} "
        f"(affects {_fmt_pct(primary_blocker_share)} of the covered market)."
    )
    if empty_bounce_avg > 0.35:
        recommendations.append(
            f"Empty-state bounce is {_fmt_pct(empty_bounce_avg)} — guide first "
            "users into populated templates or sample data."
        )
    if id_friction_avg >= 0.20:
        recommendations.append(
            f"Identity verification friction is {_fmt_pct(id_friction_avg)} — "
            "defer verification or offer social login."
        )
    if mandatory_avg >= 0.20:
        recommendations.append(
            f"Mandatory profile setup churns {_fmt_pct(mandatory_avg)} — let "
            "users skip fields and complete them later."
        )
    if permission_avg >= 0.25:
        recommendations.append(
            f"Permission sensitivity is {_fmt_pct(permission_avg)} — ask for "
            "permissions at the moment of need, not signup."
        )
    if ttfv_avg < 6.0:
        recommendations.append(
            f"Time-to-first-value tolerance is only {ttfv_avg:.0f} minutes — "
            "cut setup steps and surface the core action immediately."
        )
    if mobile_gap_share > 0.0:
        recommendations.append(
            f"Mobile onboarding penalizes {_fmt_pct(mobile_gap_share)} of the "
            "covered market — prioritize the mobile first-run experience."
        )
    top_lever = levers[0]
    if top_lever.opportunity_share > 0.0:
        recommendations.append(
            f"Highest-impact activation lever: {top_lever.label} — touches "
            f"{_fmt_pct(top_lever.opportunity_share)} of the covered market."
        )

    # Deduplicate while preserving order, then cap at six readable actions.
    seen: set[str] = set()
    recommendations = [
        rec for rec in recommendations if not (rec in seen or seen.add(rec))
    ][:6]

    cluster_profiles = [
        ClusterActivationProfile(
            cluster_id=row["cluster_id"],
            cluster_name=row["cluster_name"],
            population_weight=row["population_weight"],
            onboarding_completion_rate=round(row["completion"], 4),
            time_to_first_value_tolerance=round(row["ttfv"], 2),
            empty_state_bounce_probability=round(row["empty_bounce"], 4),
            progressive_disclosure_limit=round(row["disclosure"], 1),
            mobile_completion_penalty=round(row["mobile"], 4),
            permission_timing_sensitivity=round(row["permission"], 4),
            mandatory_profile_churn_risk=round(row["mandatory"], 4),
            video_walkthrough_skip_rate=round(row["video_skip"], 4),
            social_onboarding_lift=round(row["social_lift"], 4),
            template_vs_blank_preference=round(row["template_pref"], 4),
            identity_verification_friction=round(row["id_friction"], 4),
            activation_tier=row["tier"],
            primary_blocker=row["blocker"],
            primary_blocker_score=row["blocker_score"],
        )
        for row in rows
    ]
    cluster_profiles.sort(
        key=lambda profile: (
            _TIER_RANK[profile.activation_tier],
            profile.onboarding_completion_rate,
        )
    )

    return ActivationFunnelOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type_name,
        verdict=verdict,
        activation_rate=round(completion_avg, 4),
        time_to_first_value_minutes=round(ttfv_avg, 2),
        empty_state_bounce_probability=round(empty_bounce_avg, 4),
        progressive_disclosure_limit=round(disclosure_avg, 1),
        mobile_gap_share=round(mobile_gap_share, 4),
        identity_friction_weighted=round(id_friction_avg, 4),
        mandatory_profile_churn_weighted=round(mandatory_avg, 4),
        permission_timing_weighted=round(permission_avg, 4),
        social_onboarding_lift_weighted=round(social_lift_avg, 4),
        template_preference_weighted=round(template_pref_avg, 4),
        primary_blocker=primary_blocker,
        primary_blocker_label=BLOCKER_LABELS[primary_blocker],
        primary_blocker_share=round(primary_blocker_share, 4),
        blocker_distribution=blocker_distribution,
        cluster_profiles=cluster_profiles,
        levers=levers,
        flags=flags,
        recommendations=recommendations,
        meta=meta,
    )


__all__ = [
    "ACTIVATION_PRODUCT_TYPES",
    "BLOCKER_LABELS",
    "BLOCKER_ORDER",
    "LEVER_LABELS",
    "build_activation_funnel",
]
