"""
Pure fix-leverage conversion projection for completed simulations.

The domain-finding list tells a founder *what* is weak and the founder
action-plan tells them *what to do first*. Neither answers: **if I fix the
top findings, what would my conversion become?** This module fills that
gap deterministically from the persisted payload (no DB, no LLM, no
Celery).

How the projection works
------------------------

* ``raw_funnel`` stage counts are converted into the four forward Markov
  transition rates used by the funnel chain (ARRIVE→BROWSE,
  BROWSE→CONSIDER, CONSIDER→DECIDE, DECIDE→PURCHASE). When counts are
  missing or malformed we fall back to the base Markov rates so a legacy
  row still gets a projection.
* Each domain finding's ``metric_affected`` is mapped to the forward
  transition it would most plausibly improve. The finding's persisted
  ``conversion_impact`` is the lever that drives the improvement, so a
  finding with negligible conversion impact cannot produce a large lift.
* For every transition, the projected rate is the current rate plus the
  best improvement contributed by any finding mapped to that transition,
  capped by ``MAX_UPLIFT_PER_TRANSITION`` and bounded by the remaining room
  to a healthy ``MAX_HEALTHY_RATE``. The projected conversion is the
  product of the four updated rates.

The projection is deliberately conservative and exploratory: it is a
deterministic upper-bound sketch of upside, not a re-simulation.
"""
from __future__ import annotations

import json
import math
from typing import Any

from app.schemas.fix_leverage import (
    FixLeverageFinding,
    FixLeverageOut,
    FixLeverageSummary,
)
from app.simulation.markov import BASE_TRANSITIONS, State

# Forward funnel transitions used by the Markov chain. Keys are the
# transition labels used in responses and the API surface.
FORWARD_TRANSITIONS: tuple[tuple[str, str, str], ...] = (
    ("ARRIVE", "BROWSE", "ARRIVE→BROWSE"),
    ("BROWSE", "CONSIDER", "BROWSE→CONSIDER"),
    ("CONSIDER", "DECIDE", "CONSIDER→DECIDE"),
    ("DECIDE", "PURCHASE", "DECIDE→PURCHASE"),
)

# Healthy (upper-bound) transition rates. These are deliberately
# conservative values close to the base Markov chain so fixing a finding
# cannot produce an implausible near-100% conversion.
MAX_HEALTHY_RATE: dict[str, float] = {
    "ARRIVE→BROWSE": 0.90,
    "BROWSE→CONSIDER": 0.75,
    "CONSIDER→DECIDE": 0.70,
    "DECIDE→PURCHASE": 0.55,
}

# Hard cap on the improvement attributed to one finding for one transition.
MAX_UPLIFT_PER_TRANSITION: float = 0.15

# Domain-finding metric -> forward transition mapping. Metrics that do not
# appear here are kept in the response but marked ``affected_transition=None``
# because the funnel projection cannot plausibly attribute them.
METRIC_TO_TRANSITION: dict[str, str] = {
    "onboarding_completion_rate": "BROWSE→CONSIDER",
    "category_awareness_score": "ARRIVE→BROWSE",
    "problem_urgency_intensity": "ARRIVE→BROWSE",
    "distribution_accessibility_multiplier": "ARRIVE→BROWSE",
    "feature_depth_score": "BROWSE→CONSIDER",
    "core_feature_dau_rate": "BROWSE→CONSIDER",
    "feature_parity_met": "BROWSE→CONSIDER",
    "oob_setup_completion_rate": "BROWSE→CONSIDER",
    "social_proof_met_fraction": "CONSIDER→DECIDE",
    "free_trial_as_trust_substitute": "CONSIDER→DECIDE",
    "brand_deficit_multiplier": "CONSIDER→DECIDE",
    "incumbent_switching_friction": "DECIDE→PURCHASE",
    "will_pay_probability": "DECIDE→PURCHASE",
    "freemium_conversion_ceiling": "DECIDE→PURCHASE",
    "annual_payment_probability": "DECIDE→PURCHASE",
    "viral_coefficient": "ARRIVE→BROWSE",
    "organic_referral_trigger_score": "ARRIVE→BROWSE",
}


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


def _safe_float(value: Any, default: float = 0.0) -> float:
    parsed = _optional_float(value)
    return default if parsed is None else parsed


def _optional_float(value: Any) -> float | None:
    """Parse a numeric value, returning ``None`` for missing/invalid input."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _extract_stage_counts(results: dict[str, Any]) -> dict[str, int]:
    """Pull raw funnel stage counts from the persisted payload."""
    raw_funnel = results.get("raw_funnel")
    if isinstance(raw_funnel, dict):
        counts = raw_funnel.get("stage_counts")
        if isinstance(counts, dict):
            return {
                str(k).upper(): max(0, int(_safe_float(v, 0.0)))
                for k, v in counts.items()
            }
    # Fallback: stage_metrics rows carry agent_count.
    rows = results.get("stage_metrics") or results.get("stage_aggregations") or []
    if not isinstance(rows, list):
        return {}
    out: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        stage = str(row.get("state") or row.get("stage") or "").upper().strip()
        if not stage:
            continue
        count_value = row.get("agent_count")
        if count_value is None:
            count_value = row.get("agents")
        count = int(_safe_float(count_value, 0.0))
        if count >= 0:
            out[stage] = count
    return out


def _transition_rate(
    counts: dict[str, int],
    base_rate: float,
    from_stage: str,
    to_stage: str,
) -> float:
    """Compute a forward transition rate from stage counts, or fall back."""
    from_count = counts.get(from_stage, 0)
    to_count = counts.get(to_stage, 0)
    if from_count <= 0:
        return _clamp01(base_rate)
    return _clamp01(to_count / from_count)


def _base_rates() -> dict[str, float]:
    """Return the forward transition rates from the Markov base matrix."""
    rates: dict[str, float] = {}
    for from_stage, to_stage, label in FORWARD_TRANSITIONS:
        from_state = State[from_stage]
        to_state = State[to_stage]
        rates[label] = _clamp01(
            float(BASE_TRANSITIONS.get(from_state, {}).get(to_state, 0.0))
        )
    return rates


def _baseline_conversion(
    results: dict[str, Any],
) -> float | None:
    """Return the persisted headline conversion if present, else ``None``.

    Callers use the base Markov product as the last-resort baseline when this
    returns ``None``.
    """
    for key in (
        "population_weighted_conversion",
        "conversion_rate",
        "mean_conversion_rate",
    ):
        parsed = _optional_float(results.get(key))
        if parsed is not None:
            return _clamp01(parsed)
    raw_funnel = results.get("raw_funnel")
    if isinstance(raw_funnel, dict):
        parsed = _optional_float(raw_funnel.get("conversion_rate"))
        if parsed is not None:
            return _clamp01(parsed)
    return None


def _parse_findings(results: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse persisted domain findings into dicts with safe defaults."""
    raw = results.get("domain_findings") or []
    if not isinstance(raw, list):
        return []
    parsed: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        parsed.append(
            {
                "architect_name": str(item.get("architect_name") or ""),
                "cluster_id": str(item.get("cluster_id") or ""),
                "cluster_name": str(
                    item.get("cluster_name") or item.get("cluster_id") or ""
                ),
                "metric_affected": str(item.get("metric_affected") or ""),
                "finding": str(item.get("finding") or ""),
                "recommended_action": str(item.get("recommended_action") or ""),
                "severity": str(item.get("severity") or "INFO").upper(),
                "conversion_impact": max(
                    0.0,
                    _safe_float(

                            item.get("conversion_impact")
                            if item.get("conversion_impact") is not None
                            else item.get("impact_on_overall_conversion")

                    ),
                ),
            }
        )
    return parsed


def _metric_transition(metric: str) -> str | None:
    key = (metric or "").lower()
    return METRIC_TO_TRANSITION.get(key)


def _verdict(
    findings: list[FixLeverageFinding],
    baseline_conversion: float | None,
    projected_conversion: float | None,
) -> str:
    if baseline_conversion is None or projected_conversion is None:
        return "INSUFFICIENT_DATA"
    if not findings:
        return "INSUFFICIENT_DATA"
    if projected_conversion - baseline_conversion > 1e-9:
        return "ACTIONABLE"
    return "NO_UPLIFT_PROJECTED"


def build_fix_leverage(
    results: Any,
    *,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
) -> FixLeverageOut:
    """Build the fix-leverage projection from a completed run's payload.

    Pure function: the route layer supplies the persisted ``results_json``
    and ownership metadata. Returns a :class:`FixLeverageOut` matching the
    schema contract.
    """
    data = _coerce_results(results)
    counts = _extract_stage_counts(data)
    base = _base_rates()

    # Current forward transition rates derived from the persisted funnel.
    current_rates: dict[str, float] = {}
    for from_stage, to_stage, label in FORWARD_TRANSITIONS:
        current_rates[label] = _transition_rate(
            counts,
            base[label],
            from_stage,
            to_stage,
        )

    has_funnel = bool(counts)
    baseline = _baseline_conversion(data)
    if baseline is None:
        # Last-resort: the base Markov chain product is a deterministic
        # renderable default for a legacy/malformed payload.
        baseline = _clamp01(
            math.prod(base[label] for _f, _t, label in FORWARD_TRANSITIONS)
        )
    findings = _parse_findings(data)

    # Map each finding to a transition and collect improvements.
    finding_rows: list[dict[str, Any]] = []
    best_by_transition: dict[str, float] = {}
    for finding in findings:
        metric = finding["metric_affected"]
        transition = _metric_transition(metric)
        uplift = 0.0
        if transition is not None:
            current = current_rates[transition]
            max_rate = MAX_HEALTHY_RATE[transition]
            room = max(0.0, max_rate - current)
            impact = finding["conversion_impact"]
            # Scale the finding's persisted conversion impact into an
            # improvement on the transition's remaining room. The impact is
            # already calibrated to the overall conversion (delta × cluster
            # fraction × relative conversion). Findings with zero impact are
            # kept in the response but do not move the projection.
            uplift = (
                min(MAX_UPLIFT_PER_TRANSITION, impact * room * 1.25)
                if impact > 0.0
                else 0.0
            )
            best_by_transition[transition] = max(
                best_by_transition.get(transition, 0.0),
                uplift,
            )

        finding_rows.append(
            {
                **finding,
                "transition": transition,
                "uplift": round(uplift, 6),
            }
        )

    # Projected transition rates.
    projected_rates: dict[str, float] = {}
    for _from, _to, label in FORWARD_TRANSITIONS:
        projected_rates[label] = _clamp01(
            current_rates[label] + best_by_transition.get(label, 0.0)
        )
    raw_projected = math.prod(
        projected_rates[label] for _f, _t, label in FORWARD_TRANSITIONS
    )
    if has_funnel:
        projected = _clamp01(raw_projected)
    else:
        # No funnel counts: scale the persisted headline by the projected-vs-
        # base transition-chain ratio so the projection stays consistent with
        # the baseline the dashboard already trusts, and never over-promises.
        base_product = math.prod(base[label] for _f, _t, label in FORWARD_TRANSITIONS)
        scale = (raw_projected / base_product) if base_product > 0.0 else 1.0
        projected = _clamp01(min(1.0, baseline * scale))

    # Sort findings by their projected uplift descending, preserving stable
    # ordering for equal uplift.
    finding_rows.sort(
        key=lambda row: (-row["uplift"], row["metric_affected"])
    )

    finding_out: list[FixLeverageFinding] = [
        FixLeverageFinding(
            finding=row["finding"],
            architect_name=row["architect_name"],
            metric_affected=row["metric_affected"],
            recommended_action=row["recommended_action"],
            severity=row["severity"],
            affected_transition=row["transition"],
            conversion_impact=round(row["conversion_impact"], 6),
            projected_uplift=row["uplift"],
            cluster_id=row["cluster_id"],
            cluster_name=row["cluster_name"],
        )
        for row in finding_rows
    ]

    actionable = [
        f for f in finding_out if f.affected_transition is not None
    ]
    unmapped = [f for f in finding_out if f.affected_transition is None]
    transitions_improved = sorted(
        {
            f.affected_transition
            for f in actionable
            if f.projected_uplift > 0.0
        }
    )

    absolute_lift: float | None = None
    relative_lift_pct: float | None = None
    if baseline is not None and projected is not None:
        absolute_lift = round(max(0.0, projected - baseline), 6)
        if baseline > 0.0:
            relative_lift_pct = round(absolute_lift / baseline * 100.0, 2)

    summary = FixLeverageSummary(
        total_findings=len(finding_out),
        actionable_findings=len(actionable),
        unmapped_findings=len(unmapped),
        transitions_improved=transitions_improved,
        verdict=_verdict(finding_out, baseline, projected),
    )

    meta: dict[str, Any] = {}
    parsed_signal = _optional_float(signal_quality)
    if parsed_signal is not None:
        meta["signal_quality"] = round(_clamp01(parsed_signal), 4)

    return FixLeverageOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        baseline_conversion=(
            round(baseline, 6) if baseline is not None else None
        ),
        projected_conversion=(
            round(projected, 6) if projected is not None else None
        ),
        absolute_lift=absolute_lift,
        relative_lift_pct=relative_lift_pct,
        findings=finding_out,
        summary=summary,
        meta=meta,
    )


__all__ = [
    "MAX_UPLIFT_PER_TRANSITION",
    "METRIC_TO_TRANSITION",
    "build_fix_leverage",
]
