"""
Pure retention-churn analysis for completed simulation results.

Answers the founder's "will users stick around, and why do they churn?"
question by turning the ``RetentionArchitect`` per-cluster metrics into a
deterministic, population-weighted read:

* **Survival curve** — weighted day-1 / 7 / 30 / 90 survival over the
  covered market, plus weighted habit-loop days, re-engagement
  probability, notification re-engagement, and pause-vs-cancel
  preference.
* **Cluster tiers** — every covered cluster is classified
  ``STICKY`` (day-90 survival >= 0.25) / ``STEADY`` (day-30 >= 0.25) /
  ``FADING`` (day-30 >= 0.10) / ``HIGH_CHURN`` (below 0.10).
* **Primary churn trigger** — each cluster is attributed to the strongest
  of four modeled churn signals (price sensitivity, onboarding friction,
  habit-loop weakness, feature drop-off between day 7 and day 30). The
  market-level trigger distribution is the population-weighted share of
  those attributions.
* **Churn stage** — the survival-curve interval (day 1, day 7, day 30,
  day 90) with the largest population-weighted drop.
* **Retention levers** — six interventions (onboarding, habit-loop
  design, feature depth, pricing flexibility, support reduction, winback
  engagement) ranked by the share of the covered market where the
  underlying metric is below a healthy threshold.

The verdict is ``STRONG`` when weighted day-90 survival is at least 0.25,
``MODERATE`` when weighted day-30 survival is at least 0.25, ``WEAK`` when
it is at least 0.10, ``CRITICAL`` otherwise, and ``INSUFFICIENT_DATA`` for
product types whose conductor stack does not run ``RetentionArchitect``
(hardware categories) or when no cluster has usable metrics.

No DB / I/O — verifiable without FastAPI or PostgreSQL. The route layer
supplies ``results``, ``conductor_results`` (per-cluster architect
metrics) and ``cluster_registry``; all arithmetic is deterministic.
Metrics missing from a malformed/partial payload use conservative
defaults (day1 0.30, day7 0.15, day30 0.08, day90 0.04, habit 60 days,
re-engagement 0.05) so a missing field never manufactures a healthy
retention read, lever, or flag.
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable

from app.schemas.retention_churn import (
    ClusterRetentionProfile,
    LEVER_FEATURE,
    LEVER_HABIT,
    LEVER_ONBOARDING,
    LEVER_PRICING,
    LEVER_SUPPORT,
    LEVER_WINBACK,
    RetentionChurnOut,
    RetentionLever,
    STAGE_DAY1,
    STAGE_DAY30,
    STAGE_DAY7,
    STAGE_DAY90,
    TIER_FADING,
    TIER_HIGH_CHURN,
    TIER_STEADY,
    TIER_STICKY,
    TRIGGER_FEATURE,
    TRIGGER_HABIT,
    TRIGGER_ONBOARDING,
    TRIGGER_PRICE,
    VERDICT_CRITICAL,
    VERDICT_INSUFFICIENT,
    VERDICT_MODERATE,
    VERDICT_STRONG,
    VERDICT_WEAK,
)

# Product types whose conductor stack runs RetentionArchitect.
RETENTION_PRODUCT_TYPES: frozenset[str] = frozenset(
    {
        "saas",
        "marketplace",
        "mobile_app",
        "developer_tool",
        "enterprise_software",
        "consumer_app",
        "d2c",
        "b2b_marketplace",
        "productivity_tool",
    }
)

# Ordered trigger keys — used for tie-breaking and market aggregation so
# the output is stable regardless of dict ordering.
TRIGGER_ORDER: tuple[str, ...] = (
    TRIGGER_PRICE,
    TRIGGER_ONBOARDING,
    TRIGGER_HABIT,
    TRIGGER_FEATURE,
)

TRIGGER_LABELS: dict[str, str] = {
    TRIGGER_PRICE: "Price sensitivity",
    TRIGGER_ONBOARDING: "Onboarding friction",
    TRIGGER_HABIT: "Weak habit loop",
    TRIGGER_FEATURE: "Feature drop-off",
}

# Survival drop-off stages in chronological order (first interval wins on
# ties so an earlier cliff is never masked by a later one).
STAGE_ORDER: tuple[str, ...] = (
    STAGE_DAY1,
    STAGE_DAY7,
    STAGE_DAY30,
    STAGE_DAY90,
)

STAGE_LABELS: dict[str, str] = {
    STAGE_DAY1: "the first day",
    STAGE_DAY7: "day 1 and day 7",
    STAGE_DAY30: "day 7 and day 30",
    STAGE_DAY90: "day 30 and day 90",
}

# Cluster-tier thresholds (day-90 / day-30 survival).
TIER_STICKY_DAY90: float = 0.25
TIER_STEADY_DAY30: float = 0.25
TIER_FADING_DAY30: float = 0.10

# Verdict thresholds (weighted market aggregates).
VERDICT_STRONG_DAY90: float = 0.25
VERDICT_MODERATE_DAY30: float = 0.25
VERDICT_WEAK_DAY30: float = 0.10

# Lever opportunity thresholds — a lever applies to a cluster when the
# underlying input is below (or above, for habit days) this healthy level.
LEVER_ONBOARDING_THRESHOLD: float = 0.70
LEVER_HABIT_DAYS_THRESHOLD: float = 14.0
LEVER_FEATURE_THRESHOLD: float = 0.50
LEVER_PRICING_THRESHOLD: float = 0.40
LEVER_SUPPORT_THRESHOLD: float = 0.45
LEVER_WINBACK_THRESHOLD: float = 0.15

# Flag thresholds.
FLAG_CRITICAL_DAY7: float = 0.20
FLAG_HABIT_DAYS: float = 45.0
FLAG_PRICING_WILL_PAY: float = 0.40
FLAG_DEEP_WORK_SHARE: float = 0.50

# Conservative defaults for metrics missing from a malformed/partial
# payload. A missing retention field is treated as weak so it never
# manufactures a healthy read, lever, or flag.
DEFAULT_DAY1: float = 0.30
DEFAULT_DAY7: float = 0.15
DEFAULT_DAY30: float = 0.08
DEFAULT_DAY90: float = 0.04
DEFAULT_HABIT_DAYS: float = 60.0
DEFAULT_REENG_30: float = 0.05
DEFAULT_NOTIF: float = 0.10
DEFAULT_PAUSE: float = 0.30
DEFAULT_SESSION_DEPTH: float = 0.30
DEFAULT_ONBOARDING: float = 0.65
DEFAULT_FEATURE_DEPTH: float = 0.40
DEFAULT_WILL_PAY: float = 0.50
DEFAULT_SUPPORT_TICKET: float = 0.30

LEVER_LABELS: dict[str, str] = {
    LEVER_ONBOARDING: "Onboarding improvement",
    LEVER_HABIT: "Habit-loop design",
    LEVER_FEATURE: "Feature depth",
    LEVER_PRICING: "Pricing flexibility",
    LEVER_SUPPORT: "Support friction reduction",
    LEVER_WINBACK: "Winback engagement",
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


def _architect_metrics(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
    architect: str,
) -> dict[str, Any]:
    """Extract one architect's metrics block for a cluster."""
    if not conductor_results:
        return {}
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return {}
    architect_block = cluster_block.get(architect)
    if not isinstance(architect_block, dict):
        return {}
    metrics = architect_block.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _retention_metrics(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> dict[str, Any]:
    return _architect_metrics(
        conductor_results, cluster_id, "RetentionArchitect"
    )


def _trigger_scores(
    retention_m: dict[str, Any],
    pricing_m: dict[str, Any],
    onboarding_m: dict[str, Any],
) -> dict[str, float]:
    """Normalized churn-signal scores for one cluster (0..1, higher = worse)."""
    will_pay = _clamp(
        _safe_float(pricing_m.get("will_pay_probability"), DEFAULT_WILL_PAY)
    )
    onboard = _clamp(
        _safe_float(onboarding_m.get("onboarding_completion_rate"), DEFAULT_ONBOARDING)
    )
    habit_days = max(
        0.0,
        _safe_float(
            retention_m.get("habit_loop_formation_days"),
            DEFAULT_HABIT_DAYS,
        ),
    )
    d7 = _clamp(_safe_float(retention_m.get("day7_survival"), DEFAULT_DAY7))
    d30 = _clamp(_safe_float(retention_m.get("day30_survival"), DEFAULT_DAY30))
    feature_drop = min(1.0, (d7 - d30) / max(d7, 0.01)) if d7 > 0.0 else 0.0
    return {
        TRIGGER_PRICE: round(1.0 - will_pay, 4),
        TRIGGER_ONBOARDING: round(1.0 - onboard, 4),
        TRIGGER_HABIT: round(min(1.0, habit_days / 60.0), 4),
        TRIGGER_FEATURE: round(max(0.0, feature_drop), 4),
    }


def _primary_trigger(scores: dict[str, float]) -> tuple[str, float]:
    """Highest churn signal; ties resolve to the earlier key in TRIGGER_ORDER."""
    best_key = TRIGGER_ORDER[0]
    best_value = scores.get(best_key, 0.0)
    for key in TRIGGER_ORDER[1:]:
        value = scores.get(key, 0.0)
        if value > best_value:
            best_key = key
            best_value = value
    return best_key, round(best_value, 4)


def _retention_tier(d30: float, d90: float) -> str:
    if d90 >= TIER_STICKY_DAY90:
        return TIER_STICKY
    if d30 >= TIER_STEADY_DAY30:
        return TIER_STEADY
    if d30 >= TIER_FADING_DAY30:
        return TIER_FADING
    return TIER_HIGH_CHURN


def _weighted_average(rows: list[dict[str, Any]], key: str) -> float:
    total_weight = sum(max(0.0, row["population_weight"]) for row in rows)
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
) -> RetentionLever:
    share = _opportunity_share(rows, predicate)
    return RetentionLever(
        key=key,
        label=LEVER_LABELS[key],
        market_value=round(_weighted_average(rows, metric_key), 4),
        opportunity_share=round(share, 4),
        action=action.format(share=_fmt_pct(share)),
    )


def _highest_churn_stage(weighted: dict[str, float]) -> str:
    """Stage interval with the largest survival drop; ties go to the earlier stage."""
    d1 = weighted["day1"]
    d7 = weighted["day7"]
    d30 = weighted["day30"]
    d90 = weighted["day90"]
    drops: dict[str, float] = {
        STAGE_DAY1: max(0.0, 1.0 - d1),
        STAGE_DAY7: max(0.0, d1 - d7),
        STAGE_DAY30: max(0.0, d7 - d30),
        STAGE_DAY90: max(0.0, d30 - d90),
    }
    best_stage = STAGE_ORDER[0]
    best_drop = drops[best_stage]
    for stage in STAGE_ORDER[1:]:
        drop = drops[stage]
        if drop > best_drop:
            best_stage = stage
            best_drop = drop
    return best_stage


def build_retention_churn(
    results: dict[str, Any] | None,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    conductor_results: dict[str, Any] | None = None,
    cluster_registry: list[dict[str, Any]] | None = None,
    product_type: str = "saas",
) -> RetentionChurnOut:
    """Compose the retention-churn read from completed results.

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
    supported = product_type_name in RETENTION_PRODUCT_TYPES

    rows: list[dict[str, Any]] = []
    covered_weight = 0.0
    for entry in registry:
        cid = str(entry.get("cluster_id", ""))
        if not cid:
            continue
        weight = max(0.0, _safe_float(entry.get("population_weight")))
        metrics = _retention_metrics(conductor_results, cid)
        if not metrics:
            continue

        day1 = _clamp(_safe_float(metrics.get("day1_survival"), DEFAULT_DAY1))
        day7 = _clamp(_safe_float(metrics.get("day7_survival"), DEFAULT_DAY7))
        day30 = _clamp(
            _safe_float(metrics.get("day30_survival"), DEFAULT_DAY30)
        )
        day90 = _clamp(
            _safe_float(metrics.get("day90_survival"), DEFAULT_DAY90)
        )
        habit_days = max(
            0.0,
            _safe_float(
                metrics.get("habit_loop_formation_days"),
                DEFAULT_HABIT_DAYS,
            ),
        )
        reeng_30 = _clamp(
            _safe_float(
                metrics.get("reengagement_probability_30d"),
                DEFAULT_REENG_30,
            )
        )
        notif = _clamp(
            _safe_float(
                metrics.get("notification_reengagement_rate"),
                DEFAULT_NOTIF,
            )
        )
        pause = _clamp(
            _safe_float(
                metrics.get("pause_vs_cancel_preference"),
                DEFAULT_PAUSE,
            )
        )
        session_depth = _clamp(
            _safe_float(
                metrics.get("session_depth_score"),
                DEFAULT_SESSION_DEPTH,
            )
        )
        # Context metrics from sibling architects shape lever opportunities.
        onboarding_metrics = _architect_metrics(
            conductor_results, cid, "OnboardingArchitect"
        )
        feature_metrics = _architect_metrics(
            conductor_results, cid, "FeatureAdoptionArchitect"
        )
        pricing_metrics = _architect_metrics(
            conductor_results, cid, "PricingArchitect"
        )
        support_metrics = _architect_metrics(
            conductor_results, cid, "SupportFrictionArchitect"
        )
        onboarding_rate = _clamp(
            _safe_float(
                onboarding_metrics.get("onboarding_completion_rate"),
                DEFAULT_ONBOARDING,
            )
        )
        feature_depth = _clamp(
            _safe_float(
                feature_metrics.get("feature_depth_score"),
                DEFAULT_FEATURE_DEPTH,
            )
        )
        will_pay = _clamp(
            _safe_float(
                pricing_metrics.get("will_pay_probability"),
                DEFAULT_WILL_PAY,
            )
        )
        support_ticket = _clamp(
            _safe_float(
                support_metrics.get("support_ticket_likelihood"),
                DEFAULT_SUPPORT_TICKET,
            )
        )

        trigger_scores = _trigger_scores(metrics, pricing_metrics, onboarding_metrics)
        trigger, trigger_score = _primary_trigger(trigger_scores)
        session_pattern = (
            "deep_work" if session_depth >= 0.7 else "quick_check"
        )
        covered_weight += weight
        rows.append(
            {
                "cluster_id": cid,
                "cluster_name": str(entry.get("name", "") or cid),
                "population_weight": weight,
                "day1": day1,
                "day7": day7,
                "day30": day30,
                "day90": day90,
                "habit_days": habit_days,
                "reeng_30": reeng_30,
                "notif": notif,
                "pause": pause,
                "session_depth": session_depth,
                "session_pattern": session_pattern,
                "onboarding_rate": onboarding_rate,
                "feature_depth": feature_depth,
                "will_pay": will_pay,
                "support_ticket": support_ticket,
                "tier": _retention_tier(day30, day90),
                "trigger": trigger,
                "trigger_score": trigger_score,
            }
        )

    meta: dict[str, Any] = {
        "signal_quality": signal_quality,
        "total_clusters": len(registry),
        "covered_clusters": len(rows),
        "covered_weight": round(covered_weight, 4),
        "product_type_supported": supported,
        "thresholds": {
            "tier_sticky_day90": TIER_STICKY_DAY90,
            "tier_steady_day30": TIER_STEADY_DAY30,
            "tier_fading_day30": TIER_FADING_DAY30,
            "verdict_strong_day90": VERDICT_STRONG_DAY90,
            "verdict_moderate_day30": VERDICT_MODERATE_DAY30,
            "verdict_weak_day30": VERDICT_WEAK_DAY30,
        },
    }

    if not supported:
        return RetentionChurnOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                (
                    f"Retention is not modeled for {product_type_name} — "
                    "this read supports saas, marketplace, mobile_app, "
                    "developer_tool, enterprise_software, consumer_app, "
                    "d2c, b2b_marketplace and productivity_tool runs."
                )
            ],
            meta=meta,
        )
    if not rows or covered_weight <= 0.0:
        return RetentionChurnOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            verdict=VERDICT_INSUFFICIENT,
            recommendations=[
                "No per-cluster RetentionArchitect metrics were available "
                "for this run."
            ],
            meta=meta,
        )

    day1_avg = _weighted_average(rows, "day1")
    day7_avg = _weighted_average(rows, "day7")
    day30_avg = _weighted_average(rows, "day30")
    day90_avg = _weighted_average(rows, "day90")
    habit_avg = _weighted_average(rows, "habit_days")
    reeng_avg = _weighted_average(rows, "reeng_30")
    notif_avg = _weighted_average(rows, "notif")
    pause_avg = _weighted_average(rows, "pause")
    onboarding_avg = _weighted_average(rows, "onboarding_rate")
    feature_avg = _weighted_average(rows, "feature_depth")
    will_pay_avg = _weighted_average(rows, "will_pay")
    support_avg = _weighted_average(rows, "support_ticket")
    deep_work_weight = sum(
        row["population_weight"]
        for row in rows
        if row["session_pattern"] == "deep_work"
    )
    deep_work_share = deep_work_weight / covered_weight

    weighted: dict[str, float] = {
        "day1": day1_avg,
        "day7": day7_avg,
        "day30": day30_avg,
        "day90": day90_avg,
    }
    highest_churn_stage = _highest_churn_stage(weighted)

    sticky_weight = sum(
        row["population_weight"] for row in rows if row["tier"] == TIER_STICKY
    )
    steady_weight = sum(
        row["population_weight"] for row in rows if row["tier"] == TIER_STEADY
    )
    fading_weight = sum(
        row["population_weight"] for row in rows if row["tier"] == TIER_FADING
    )
    high_churn_weight = sum(
        row["population_weight"]
        for row in rows
        if row["tier"] == TIER_HIGH_CHURN
    )

    if day90_avg >= VERDICT_STRONG_DAY90:
        verdict = VERDICT_STRONG
    elif day30_avg >= VERDICT_MODERATE_DAY30:
        verdict = VERDICT_MODERATE
    elif day30_avg >= VERDICT_WEAK_DAY30:
        verdict = VERDICT_WEAK
    else:
        verdict = VERDICT_CRITICAL

    # Market trigger distribution = population-weighted share of per-cluster
    # primary-trigger attributions.
    trigger_weights: dict[str, float] = {key: 0.0 for key in TRIGGER_ORDER}
    for row in rows:
        trigger_weights[row["trigger"]] += row["population_weight"]
    trigger_distribution = {
        key: round(weight / covered_weight, 4)
        for key, weight in trigger_weights.items()
    }
    primary_trigger = TRIGGER_ORDER[0]
    primary_trigger_share = trigger_distribution[primary_trigger]
    for key in TRIGGER_ORDER[1:]:
        if trigger_distribution[key] > primary_trigger_share:
            primary_trigger = key
            primary_trigger_share = trigger_distribution[key]

    flags: list[str] = []
    if day7_avg < FLAG_CRITICAL_DAY7:
        flags.append("critical_retention_risk")
    if habit_avg > FLAG_HABIT_DAYS:
        flags.append("habit_loop_unlikely")
    if will_pay_avg < FLAG_PRICING_WILL_PAY:
        flags.append("price_sensitivity_risk")
    if deep_work_share > FLAG_DEEP_WORK_SHARE:
        flags.append("deep_work_dominant")
    if any(row["reeng_30"] > LEVER_WINBACK_THRESHOLD for row in rows):
        flags.append("reengagement_possible")
    flags.append(f"churn_cliff_{highest_churn_stage}")

    levers: list[RetentionLever] = [
        _lever(
            rows,
            LEVER_ONBOARDING,
            "onboarding_rate",
            lambda row: row["onboarding_rate"] < LEVER_ONBOARDING_THRESHOLD,
            "Rework onboarding for {share} of the covered market — first-run "
            "time-to-value is the fastest retention win.",
        ),
        _lever(
            rows,
            LEVER_HABIT,
            "habit_days",
            lambda row: row["habit_days"] > LEVER_HABIT_DAYS_THRESHOLD,
            "Design habit triggers, streaks and reminders for {share} — "
            "habit formation currently takes too long.",
        ),
        _lever(
            rows,
            LEVER_FEATURE,
            "feature_depth",
            lambda row: row["feature_depth"] < LEVER_FEATURE_THRESHOLD,
            "Deepen core features for {share} to move users past the "
            "day-30 cliff.",
        ),
        _lever(
            rows,
            LEVER_PRICING,
            "will_pay",
            lambda row: row["will_pay"] < LEVER_PRICING_THRESHOLD,
            "Add flexible plans, annual discounts or EMI options for {share}.",
        ),
        _lever(
            rows,
            LEVER_SUPPORT,
            "support_ticket",
            lambda row: row["support_ticket"] > LEVER_SUPPORT_THRESHOLD,
            "Reduce support friction for {share} — high ticket likelihood "
            "accelerates churn.",
        ),
        _lever(
            rows,
            LEVER_WINBACK,
            "reeng_30",
            lambda row: row["reeng_30"] < LEVER_WINBACK_THRESHOLD,
            "Build winback campaigns for {share} — re-engagement probability "
            "is low.",
        ),
    ]
    levers.sort(key=lambda lever: (-lever.opportunity_share, lever.key))

    recommendations: list[str] = []
    if verdict == VERDICT_STRONG:
        recommendations.append(
            f"Retention is strong (weighted day-90 survival "
            f"{_fmt_pct(day90_avg)}) — shift focus to expansion and "
            "referral loops."
        )
    elif verdict == VERDICT_MODERATE:
        recommendations.append(
            f"Retention is workable (weighted day-30 survival "
            f"{_fmt_pct(day30_avg)}) — pull the strongest lever below to "
            "push day-90 survival past 25%."
        )
    elif verdict == VERDICT_WEAK:
        recommendations.append(
            f"Retention is weak (weighted day-30 survival "
            f"{_fmt_pct(day30_avg)}) — fix the churn trigger before "
            "spending on acquisition."
        )
    else:
        recommendations.append(
            f"Retention is critical (weighted day-30 survival "
            f"{_fmt_pct(day30_avg)}) — the product does not hold its market "
            "today; treat retention as the launch blocker."
        )
    recommendations.append(
        f"The biggest survival drop happens between "
        f"{STAGE_LABELS[highest_churn_stage]} — target that interval first."
    )
    recommendations.append(
        f"Primary churn trigger: {TRIGGER_LABELS[primary_trigger]} "
        f"(affects {_fmt_pct(primary_trigger_share)} of the covered market)."
    )
    if day7_avg < FLAG_CRITICAL_DAY7:
        recommendations.append(
            f"Day-7 survival is only {_fmt_pct(day7_avg)} — focus on "
            "first-week activation before anything else."
        )
    if habit_avg > FLAG_HABIT_DAYS:
        recommendations.append(
            f"Habit formation takes {habit_avg:.0f} days on average — "
            "shorten time-to-habit with scheduled triggers."
        )
    if levers and levers[0].opportunity_share > 0.0:
        recommendations.append(
            f"Highest-impact lever: {levers[0].label} touches "
            f"{_fmt_pct(levers[0].opportunity_share)} of the covered market."
        )
    if any(row["reeng_30"] > LEVER_WINBACK_THRESHOLD for row in rows):
        recommendations.append(
            "Winback is viable — some clusters already re-engage above 15%; "
            "run targeted re-engagement for lapsed users."
        )

    return RetentionChurnOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type_name,
        verdict=verdict,
        weighted_day1_survival=round(day1_avg, 4),
        weighted_day7_survival=round(day7_avg, 4),
        weighted_day30_survival=round(day30_avg, 4),
        weighted_day90_survival=round(day90_avg, 4),
        weighted_habit_loop_days=round(habit_avg, 1),
        weighted_reengagement_30d=round(reeng_avg, 4),
        weighted_notification_reengagement=round(notif_avg, 4),
        weighted_pause_vs_cancel=round(pause_avg, 4),
        deep_work_share=round(deep_work_share, 4),
        highest_churn_stage=highest_churn_stage,
        sticky_share=round(sticky_weight / covered_weight, 4),
        steady_share=round(steady_weight / covered_weight, 4),
        fading_share=round(fading_weight / covered_weight, 4),
        high_churn_share=round(high_churn_weight / covered_weight, 4),
        primary_churn_trigger=primary_trigger,
        primary_churn_trigger_label=TRIGGER_LABELS[primary_trigger],
        primary_churn_trigger_share=round(primary_trigger_share, 4),
        churn_trigger_distribution=trigger_distribution,
        cluster_profiles=[
            ClusterRetentionProfile(
                cluster_id=row["cluster_id"],
                cluster_name=row["cluster_name"],
                population_weight=row["population_weight"],
                day1_survival=round(row["day1"], 4),
                day7_survival=round(row["day7"], 4),
                day30_survival=round(row["day30"], 4),
                day90_survival=round(row["day90"], 4),
                habit_loop_formation_days=round(row["habit_days"], 1),
                reengagement_probability_30d=round(row["reeng_30"], 4),
                notification_reengagement_rate=round(row["notif"], 4),
                pause_vs_cancel_preference=round(row["pause"], 4),
                session_pattern=row["session_pattern"],
                onboarding_completion_rate=round(row["onboarding_rate"], 4),
                feature_depth_score=round(row["feature_depth"], 4),
                will_pay_probability=round(row["will_pay"], 4),
                support_ticket_likelihood=round(row["support_ticket"], 4),
                retention_tier=row["tier"],
                primary_churn_trigger=row["trigger"],
                primary_churn_trigger_score=row["trigger_score"],
            )
            for row in rows
        ],
        levers=levers,
        flags=flags,
        recommendations=recommendations,
        meta=meta,
    )


__all__ = [
    "RETENTION_PRODUCT_TYPES",
    "TRIGGER_ORDER",
    "build_retention_churn",
]
