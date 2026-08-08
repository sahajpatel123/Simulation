"""
Founder action plan — a deterministic, ranked "what should I fix first?"
digest for completed simulation results.

The simulation pipeline already produces several raw views over the same
run: domain findings, funnel-bottleneck diagnosis, launch readiness and
calibration. This module turns the *persisted* payload (no DB writes, no
LLM calls) into a founder-facing action plan that is sorted by quick-win
score: estimated conversion impact divided by implementation effort.

Actions are sourced from two deterministic signals:

* **Domain findings** — the top accountability findings persisted onto
  ``results_json["domain_findings"]`` by the simulation task.
* **Funnel bottleneck** — the forward Markov stage whose drop-off deviates
  most from the healthy benchmark when stage metrics are present.

Each action carries an effort tier (LOW / MEDIUM / HIGH) assigned from the
affected metric family, so founders can pick "quick wins" first without
digging through ten domain findings.
"""
from __future__ import annotations

import json
from typing import Any

from app.schemas.founder_action_plan import (
    EFFORT_HIGH,
    EFFORT_LOW,
    EFFORT_MEDIUM,
    ActionPlanItem,
    ActionPlanSummary,
    FounderActionPlanOut,
)

MAX_ACTIONS: int = 8

# Healthy drop-off rates derived from the base Markov transition matrix
# (see app.simulation.markov). Used to identify the funnel bottleneck when
# stage metrics are present in the persisted payload.
HEALTHY_DROP_OFF: dict[str, float] = {
    "ARRIVE": 0.13,
    "BROWSE": 0.38,
    "CONSIDER": 0.38,
    "DECIDE": 0.55,
    "PURCHASE": 0.0,
    "ABANDON": 0.0,
    "RETURN": 0.20,
}

FORWARD_STAGES: tuple[str, ...] = ("ARRIVE", "BROWSE", "CONSIDER", "DECIDE")

# Effort tier by metric family. Keys are substring matches against the
# persisted finding's ``metric_affected``; the first match wins.
EFFORT_TIERS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("copy", "messaging", "awareness", "trigger", "referral"), EFFORT_LOW),
    (
        (
            "pricing",
            "onboarding",
            "trial",
            "setup",
            "feature",
            "integration",
            "trust",
            "social_proof",
        ),
        EFFORT_MEDIUM,
    ),
    (
        (
            "distribution",
            "ecosystem",
            "hardware",
            "clinical",
            "regulatory",
            "incumbent",
            "infrastructure",
        ),
        EFFORT_HIGH,
    ),
)

SOURCE_DOMAIN_FINDING: str = "DOMAIN_FINDING"
SOURCE_FUNNEL: str = "FUNNEL_BOTTLENECK"

# Funnel stage -> recommended action copy used when no domain finding
# exists for the bottleneck.
FUNNEL_STAGE_ACTION: dict[str, tuple[str, str, str]] = {
    "ARRIVE": (
        "Tighten acquisition targeting",
        "Improve how you reach the earliest visitors; weak arrival converts "
        "into weak revenue.",
        "Low",
    ),
    "BROWSE": (
        "Cut first-page friction",
        "Visitors reach the page but leave before evaluating your product.",
        "Medium",
    ),
    "CONSIDER": (
        "Build trust at consideration",
        "Prospects stop before deciding; add proof, testimonials or clearer "
        "value framing.",
        "Medium",
    ),
    "DECIDE": (
        "De-risk the final decision",
        "Buyers stall at the decision point; simplify pricing, add guarantees "
        "or make the purchase step obvious.",
        "Medium",
    ),
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_results(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _effort_for_metric(metric: str) -> str:
    key = (metric or "").lower()
    for needles, effort in EFFORT_TIERS:
        if any(n in key for n in needles):
            return effort
    return EFFORT_MEDIUM


def _quick_win_score(
    impact: float,
    effort: str,
    severity_bonus: float,
) -> float:
    """Impact per unit of effort, with a small severity nudge for urgency."""
    effort_value = {"LOW": 1.0, "MEDIUM": 0.55, "HIGH": 0.25}.get(effort, 0.5)
    raw = impact * effort_value + severity_bonus
    return round(min(1.0, max(0.0, raw)), 6)


def _parse_domain_findings(results: dict[str, Any]) -> list[dict[str, Any]]:
    raw = results.get("domain_findings") or []
    if not isinstance(raw, list):
        return []
    parsed: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            parsed.append(
                {
                    "architect_name": str(item.get("architect_name") or ""),
                    "cluster_id": str(item.get("cluster_id") or ""),
                    "cluster_name": str(item.get("cluster_name") or item.get("cluster_id") or ""),
                    "metric_affected": str(item.get("metric_affected") or ""),
                    "finding": str(item.get("finding") or ""),
                    "recommended_action": str(item.get("recommended_action") or ""),
                    "severity": str(item.get("severity") or "INFO").upper(),
                    "actual_value": _safe_float(item.get("actual_value")),
                    "healthy_benchmark": _safe_float(item.get("healthy_benchmark")),
                    "conversion_impact": _safe_float(
                        item.get("conversion_impact") or item.get("impact_on_overall_conversion")
                    ),
                    "affected_agent_count": _safe_int(item.get("affected_agent_count")),
                }
            )
        except Exception:
            continue
    return parsed


def _extract_stage_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    raw = results.get("stage_metrics") or results.get("stage_aggregations") or []
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("state") or item.get("stage") or "").upper().strip()
        if not stage:
            continue
        rows.append(
            {
                "stage": stage,
                "drop_off_rate": max(
                    0.0,
                    min(1.0, _safe_float(item.get("drop_off_rate", item.get("mean_drop_off_rate")))),
                ),
                "agent_count": _safe_int(item.get("agent_count", item.get("agents"))),
            }
        )
    return rows


def _primary_bottleneck(results: dict[str, Any]) -> str | None:
    """Return the forward stage with the largest excess drop-off."""
    rows = _extract_stage_rows(results)
    candidates: list[tuple[str, float]] = []
    for row in rows:
        stage = row["stage"]
        if stage not in FORWARD_STAGES:
            continue
        healthy = HEALTHY_DROP_OFF.get(stage, 0.35)
        excess = float(row["drop_off_rate"]) - healthy
        if excess > 0.0:
            candidates.append((stage, excess))
    if not candidates:
        return None
    return max(candidates, key=lambda pair: pair[1])[0]


def _build_action_items(results: dict[str, Any]) -> list[ActionPlanItem]:
    findings = _parse_domain_findings(results)
    bottleneck = _primary_bottleneck(results)

    items: list[ActionPlanItem] = []
    seen: set[tuple[str, str]] = set()

    # Actions from persisted domain findings. Findings are already ranked
    # by conversion impact by the AccountabilityEngine; we keep that order
    # and cap at MAX_ACTIONS after the funnel action is considered.
    for finding in findings:
        metric = finding["metric_affected"]
        cluster_id = finding["cluster_id"]
        key = (SOURCE_DOMAIN_FINDING, metric + ":" + cluster_id)
        if key in seen:
            continue
        seen.add(key)

        severity = finding["severity"]
        severity_bonus = 0.08 if severity == "CRITICAL" else 0.03 if severity == "WARNING" else 0.0
        effort = _effort_for_metric(metric)
        impact = max(0.0, finding["conversion_impact"])
        score = _quick_win_score(impact, effort, severity_bonus)

        items.append(
            ActionPlanItem(
                priority=0,  # assigned after sort
                title=metric.replace("_", " ").title(),
                summary=finding["finding"],
                domain=finding["architect_name"],
                stage=bottleneck or "",
                metric_affected=metric,
                source=SOURCE_DOMAIN_FINDING,
                severity=severity,
                effort=effort,
                quick_win_score=score,
                estimated_conversion_impact=round(impact, 6),
                recommended_action=finding["recommended_action"],
                related_cluster_ids=[cluster_id],
            )
        )

    # Ensure the funnel bottleneck is represented even when no finding was
    # persisted for it (e.g. legacy payloads / partial results).
    if bottleneck and bottleneck in FUNNEL_STAGE_ACTION:
        key = (SOURCE_FUNNEL, bottleneck)
        if key not in seen:
            seen.add(key)
            title, summary, _effort_text = FUNNEL_STAGE_ACTION[bottleneck]
            effort = (
                _effort_text.upper()
                if _effort_text.upper() in (EFFORT_LOW, EFFORT_MEDIUM, EFFORT_HIGH)
                else EFFORT_MEDIUM
            )
            rows = {r["stage"]: r for r in _extract_stage_rows(results)}
            drop = float(rows[bottleneck]["drop_off_rate"])
            excess = drop - HEALTHY_DROP_OFF.get(bottleneck, 0.35)
            # Convert excess drop-off into an impact estimate: population
            # weight of the stage times the fraction of excess that is
            # realistically recoverable by a focused intervention.
            impact = min(0.15, max(0.0, excess * 0.10))
            score = _quick_win_score(impact, effort, 0.05)
            items.append(
                ActionPlanItem(
                    priority=0,
                    title=title,
                    summary=summary,
                    domain="Funnel",
                    stage=bottleneck,
                    metric_affected="drop_off_" + bottleneck.lower(),
                    source=SOURCE_FUNNEL,
                    severity="WARNING" if excess >= 0.08 else "INFO",
                    effort=effort,
                    quick_win_score=score,
                    estimated_conversion_impact=round(impact, 6),
                    recommended_action=title,
                    related_cluster_ids=[],
                )
            )

    items.sort(
        key=lambda item: (
            -item.quick_win_score,
            -item.estimated_conversion_impact,
            {"CRITICAL": 0, "WARNING": 1, "INFO": 2}.get(item.severity, 3),
        )
    )
    for i, item in enumerate(items[:MAX_ACTIONS], start=1):
        item.priority = i
    return items[:MAX_ACTIONS]


def build_founder_action_plan(
    results: Any,
    *,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    product_type: str = "saas",
    signal_quality: float | None = None,
) -> FounderActionPlanOut:
    """Build a deterministic founder action plan from persisted results."""
    results_dict = _coerce_results(results)
    headline = _safe_float(
        results_dict.get(
            "population_weighted_conversion",
            results_dict.get("conversion_rate"),
        ),
        0.0,
    )
    actions = _build_action_items(results_dict)

    critical = sum(1 for a in actions if a.severity == "CRITICAL")
    warning = sum(1 for a in actions if a.severity == "WARNING")
    quick_wins = sum(1 for a in actions if a.effort == EFFORT_LOW)
    total_impact = round(sum(a.estimated_conversion_impact for a in actions), 6)

    if not actions:
        verdict = "INSUFFICIENT_DATA"
    elif critical > 0:
        verdict = "CRITICAL_ISSUES"
    elif quick_wins > 0:
        verdict = "QUICK_WINS_AVAILABLE"
    else:
        verdict = "MONITOR"

    bottleneck = _primary_bottleneck(results_dict)

    return FounderActionPlanOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type or "saas",
        headline_conversion=round(headline, 6) if headline > 0 else None,
        signal_quality=round(signal_quality, 6)
        if isinstance(signal_quality, (int, float))
        else None,
        primary_bottleneck=bottleneck,
        actions=actions,
        summary=ActionPlanSummary(
            total_actions=len(actions),
            total_critical=critical,
            total_warning=warning,
            quick_win_count=quick_wins,
            estimated_total_conversion_impact=total_impact,
            verdict=verdict,
        ),
        meta={
            "sources": [SOURCE_DOMAIN_FINDING, SOURCE_FUNNEL],
            "max_actions": MAX_ACTIONS,
        },
    )


__all__ = ["build_founder_action_plan"]
