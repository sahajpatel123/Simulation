"""
Pure scenario sensitivity analysis for completed simulation results.

Systematically varies each assumption's impact score to identify which
assumptions have the highest sensitivity on the projected conversion rate.
Helps founders prioritise which assumptions to validate first.

No DB / I/O — verifiable without FastAPI or PostgreSQL.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np

from app.simulation.markov import (
    BASE_TRANSITIONS,
    KEYWORD_RULES,
    SENSITIVITY_WEIGHTS,
    STATES,
    STATE_INDEX,
    State,
)
from app.schemas.sensitivity import (
    AssumptionSensitivity,
    SensitivityOut,
    SensitivityPoint,
    SensitivitySummary,
)

# Impact score levels to test (0% to 100% of the original impact score).
IMPACT_LEVELS: list[float] = [0.0, 0.25, 0.5, 0.75, 1.0]

# Forward funnel stages whose transition probabilities matter for conversion.
FORWARD_TRANSITIONS: list[tuple[State, State]] = [
    (State.ARRIVE, State.BROWSE),
    (State.BROWSE, State.CONSIDER),
    (State.CONSIDER, State.DECIDE),
    (State.DECIDE, State.PURCHASE),
]

# Sensitivity score thresholds for tier classification.
SENSITIVITY_TIER_THRESHOLDS: dict[str, float] = {
    "CRITICAL": 0.60,
    "HIGH": 0.35,
    "MEDIUM": 0.15,
    "LOW": 0.0,
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_results(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            import json as _json

            parsed = _json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _assumption_dicts(assumptions: list[Any]) -> list[dict[str, Any]]:
    """Normalise assumption objects/dicts into the shape build_transition_matrix expects."""
    out: list[dict[str, Any]] = []
    for a in assumptions or []:
        if isinstance(a, dict):
            out.append(
                {
                    "text": str(a.get("text", a.get("assumption", ""))),
                    "sensitivity": str(a.get("sensitivity", "MEDIUM")),
                    "impact_score": _safe_float(a.get("impact_score", 5.0), 5.0),
                }
            )
        elif hasattr(a, "text"):
            out.append(
                {
                    "text": str(a.text),
                    "sensitivity": str(getattr(a, "sensitivity", "MEDIUM")),
                    "impact_score": _safe_float(getattr(a, "impact_score", 5.0), 5.0),
                }
            )
    return out


def _build_matrix(
    env_params: dict[str, Any],
    assumptions: list[dict[str, Any]],
) -> np.ndarray:
    """Build a row-stochastic transition matrix from env params + assumptions."""
    n = len(STATES)
    matrix = np.zeros((n, n), dtype=np.float64)

    for from_state, transitions in BASE_TRANSITIONS.items():
        fi = STATE_INDEX[from_state]
        for to_state, prob in transitions.items():
            ti = STATE_INDEX[to_state]
            matrix[fi, ti] = prob

    # Apply assumption-based keyword adjustments
    for assumption in assumptions:
        text = assumption.get("text", "").lower()
        sensitivity = str(assumption.get("sensitivity", "MEDIUM")).upper()
        impact = _safe_float(assumption.get("impact_score", 5.0)) / 10.0
        weight = SENSITIVITY_WEIGHTS.get(sensitivity, 0.12)
        magnitude = weight * impact

        for rule in KEYWORD_RULES:
            if any(kw in text for kw in rule["keywords"]):
                for from_s, to_s, direction in rule["transitions"]:
                    fi = STATE_INDEX[from_s]
                    ti = STATE_INDEX[to_s]
                    matrix[fi, ti] = float(
                        np.clip(matrix[fi, ti] + direction * magnitude, 0.0, 1.0)
                    )
                break

    # Apply env-based adjustments
    price_sensitivity = _safe_float(env_params.get("price_sensitivity", 0.5))
    market_maturity = _safe_float(env_params.get("market_maturity", 0.3))

    decide_idx = STATE_INDEX[State.DECIDE]
    purchase_idx = STATE_INDEX[State.PURCHASE]
    abandon_idx = STATE_INDEX[State.ABANDON]
    matrix[decide_idx, purchase_idx] = float(
        np.clip(matrix[decide_idx, purchase_idx] - price_sensitivity * 0.18, 0.05, 1.0)
    )

    browse_idx = STATE_INDEX[State.BROWSE]
    consider_idx = STATE_INDEX[State.CONSIDER]
    matrix[browse_idx, consider_idx] = float(
        np.clip(matrix[browse_idx, consider_idx] - market_maturity * 0.14, 0.10, 1.0)
    )

    matrix = np.clip(matrix, 0.0, 1.0)

    # Row-normalise
    row_sums = matrix.sum(axis=1, keepdims=True)
    zero_rows = row_sums.flatten() == 0.0
    for ri in np.where(zero_rows)[0]:
        matrix[ri, abandon_idx] = 1.0
        row_sums[ri, 0] = 1.0
    matrix = matrix / row_sums

    return matrix


def _forward_conversion(matrix: np.ndarray) -> float:
    """Compute the forward-chain conversion estimate from a transition matrix."""
    product = 1.0
    for from_s, to_s in FORWARD_TRANSITIONS:
        fi = STATE_INDEX[from_s]
        ti = STATE_INDEX[to_s]
        product *= float(matrix[fi, ti])
    return round(product, 6)


def _find_affected_transitions(text: str) -> list[str]:
    """Find which Markov transitions are affected by an assumption's keywords."""
    affected: list[str] = []
    text_lower = text.lower()
    for rule in KEYWORD_RULES:
        if any(kw in text_lower for kw in rule["keywords"]):
            for from_s, to_s, _ in rule["transitions"]:
                affected.append(f"{from_s.value}→{to_s.value}")
            break
    return affected


def _sensitivity_tier(score: float) -> str:
    """Map a normalised sensitivity score to a tier label."""
    if score >= SENSITIVITY_TIER_THRESHOLDS["CRITICAL"]:
        return "CRITICAL"
    if score >= SENSITIVITY_TIER_THRESHOLDS["HIGH"]:
        return "HIGH"
    if score >= SENSITIVITY_TIER_THRESHOLDS["MEDIUM"]:
        return "MEDIUM"
    return "LOW"


def _build_recommendation(
    text: str,
    tier: str,
    max_delta: float,
    affected: list[str],
) -> str:
    """Generate a recommendation for an assumption based on its sensitivity."""
    if tier == "CRITICAL":
        return (
            f"CRITICAL: '{text[:80]}' drives up to {abs(max_delta):.1%} conversion change. "
            "Validate this assumption with real user research before launch."
        )
    if tier == "HIGH":
        return (
            f"HIGH: '{text[:80]}' causes up to {abs(max_delta):.1%} conversion swing. "
            "Test this assumption with a landing page experiment."
        )
    if tier == "MEDIUM":
        return (
            f"MEDIUM: '{text[:80]}' has moderate impact ({abs(max_delta):.1%} swing). "
            "Monitor during early user feedback."
        )
    return (
        f"LOW: '{text[:80]}' has minimal conversion impact. "
        "Safe to leave as-is."
    )


def build_sensitivity_analysis(
    simulation_id: int,
    project_id: int,
    base_results: dict[str, Any],
    env_params: dict[str, Any],
    existing_assumptions: list[Any],
    override_price_sensitivity: float | None = None,
    override_market_maturity: float | None = None,
) -> SensitivityOut:
    """
    Build a scenario sensitivity analysis from a completed simulation.

    For each assumption, varies its impact score across IMPACT_LEVELS and
    measures the resulting conversion rate delta from baseline.

    ``base_results`` — the simulation's ``results_json`` dict.
    ``env_params`` — the environment parameters.
    ``existing_assumptions`` — the project's existing assumptions (dicts or objects).
    """
    data = _coerce_results(base_results)

    # Extract base conversion rate
    base_cr = _safe_float(
        data.get("population_weighted_conversion", data.get("mean_conversion_rate", 0.0))
    )
    base_cr = max(0.0, min(1.0, base_cr))

    # Get AOV for revenue projection
    aov = _safe_float(data.get("mean_revenue", 0.0))
    if aov <= 0:
        aov = _safe_float(env_params.get("average_order_value", 999.0), 999.0)

    # Build env params for the Markov matrix
    base_env = {
        "price_sensitivity": _safe_float(env_params.get("price_sensitivity", 0.5)),
        "market_maturity": _safe_float(env_params.get("market_maturity", 0.3)),
    }
    if override_price_sensitivity is not None:
        base_env["price_sensitivity"] = float(max(0.0, min(1.0, override_price_sensitivity)))
    if override_market_maturity is not None:
        base_env["market_maturity"] = float(max(0.0, min(1.0, override_market_maturity)))

    # Normalise assumptions
    assumptions = _assumption_dicts(existing_assumptions)

    if not assumptions:
        # No assumptions to analyse — return a zero-state result
        return SensitivityOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status="COMPLETED",
            baseline_conversion=base_cr,
            baseline_revenue_per_1000=round(base_cr * 1000 * aov, 2),
            summary=SensitivitySummary(
                total_assumptions=0,
                baseline_conversion=base_cr,
                most_sensitive_assumption="",
                most_sensitive_score=0.0,
                critical_assumptions=0,
                high_assumptions=0,
                medium_assumptions=0,
                low_assumptions=0,
                avg_sensitivity_score=0.0,
            ),
            assumptions=[],
            recommendations=[
                "No assumptions found for this project. Add assumptions to enable sensitivity analysis."
            ],
            product_type_detected=str(data.get("product_type_detected") or ""),
            signal_quality=_safe_float(data.get("signal_quality")),
            meta={
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "impact_levels": IMPACT_LEVELS,
                "assumption_count": 0,
            },
        )

    # Build baseline matrix (all assumptions at their original impact scores)
    baseline_matrix = _build_matrix(base_env, assumptions)
    baseline_matrix_cr = _forward_conversion(baseline_matrix)

    # Use the simulation's actual conversion rate as the authoritative baseline
    if base_cr > 0:
        scale_factor = base_cr / baseline_matrix_cr if baseline_matrix_cr > 0 else 1.0
    else:
        base_cr = baseline_matrix_cr
        scale_factor = 1.0

    # Analyse each assumption
    results: list[AssumptionSensitivity] = []
    max_sensitivity_score = 0.0
    most_sensitive_text = ""

    for i, assumption in enumerate(assumptions):
        text = assumption.get("text", "")
        sensitivity = str(assumption.get("sensitivity", "MEDIUM"))
        baseline_impact = _safe_float(assumption.get("impact_score", 5.0))

        # Build the curve by varying this assumption's impact score
        curve: list[SensitivityPoint] = []
        max_delta = 0.0

        for level in IMPACT_LEVELS:
            # Create a copy of assumptions with this one's impact score varied
            varied_assumptions = list(assumptions)
            varied_assumptions[i] = {
                **assumption,
                "impact_score": baseline_impact * level,
            }

            matrix = _build_matrix(base_env, varied_assumptions)
            matrix_cr = _forward_conversion(matrix)

            # Scale to match the baseline conversion rate
            scaled_cr = round(min(0.99, max(0.0, matrix_cr * scale_factor)), 6)
            delta = round(scaled_cr - base_cr, 6)

            curve.append(
                SensitivityPoint(
                    impact_score=round(baseline_impact * level, 2),
                    conversion_rate=scaled_cr,
                    delta_from_baseline=delta,
                )
            )

            abs_delta = abs(delta)
            if abs_delta > abs(max_delta):
                max_delta = delta

        # Compute sensitivity score: normalised max delta / baseline conversion
        if base_cr > 0:
            sensitivity_score = round(abs(max_delta) / base_cr, 4)
        else:
            sensitivity_score = round(abs(max_delta), 4)

        # Clamp to [0, 1]
        sensitivity_score = max(0.0, min(1.0, sensitivity_score))

        tier = _sensitivity_tier(sensitivity_score)
        affected = _find_affected_transitions(text)
        triggers_rules = len(affected) > 0

        recommendation = _build_recommendation(text, tier, max_delta, affected)

        results.append(
            AssumptionSensitivity(
                assumption_text=text,
                sensitivity=sensitivity,
                baseline_impact_score=baseline_impact,
                baseline_conversion=base_cr,
                max_delta=max_delta,
                sensitivity_score=sensitivity_score,
                sensitivity_tier=tier,
                curve=curve,
                triggers_markov_rules=triggers_rules,
                affected_transitions=affected,
                recommendation=recommendation,
            )
        )

        if sensitivity_score > max_sensitivity_score:
            max_sensitivity_score = sensitivity_score
            most_sensitive_text = text

    # Sort by sensitivity score descending
    results.sort(key=lambda r: (-r.sensitivity_score, -abs(r.max_delta)))

    # Build summary
    critical_count = sum(1 for r in results if r.sensitivity_tier == "CRITICAL")
    high_count = sum(1 for r in results if r.sensitivity_tier == "HIGH")
    medium_count = sum(1 for r in results if r.sensitivity_tier == "MEDIUM")
    low_count = sum(1 for r in results if r.sensitivity_tier == "LOW")
    avg_score = round(sum(r.sensitivity_score for r in results) / len(results), 4)

    summary = SensitivitySummary(
        total_assumptions=len(results),
        baseline_conversion=base_cr,
        most_sensitive_assumption=most_sensitive_text[:200],
        most_sensitive_score=max_sensitivity_score,
        critical_assumptions=critical_count,
        high_assumptions=high_count,
        medium_assumptions=medium_count,
        low_assumptions=low_count,
        avg_sensitivity_score=avg_score,
    )

    # Build recommendations
    recommendations: list[str] = []

    if critical_count > 0:
        critical = [r for r in results if r.sensitivity_tier == "CRITICAL"]
        recommendations.append(
            f"{critical_count} assumption(s) have CRITICAL sensitivity — "
            f"validate '{critical[0].assumption_text[:60]}...' first."
        )

    if high_count > 0:
        recommendations.append(
            f"{high_count} assumption(s) have HIGH sensitivity — "
            "test with landing page experiments before full launch."
        )

    # Top 3 most sensitive
    for r in results[:3]:
        recommendations.append(
            f"'{r.assumption_text[:60]}...' → {r.sensitivity_tier} sensitivity "
            f"(max delta: {abs(r.max_delta):.1%})"
        )

    # Non-triggering assumptions
    non_triggering = [r for r in results if not r.triggers_markov_rules]
    if non_triggering:
        recommendations.append(
            f"{len(non_triggering)} assumption(s) don't trigger Markov keyword rules. "
            "Rewrite with pricing, trust, UX, or market keywords for richer projections."
        )

    if not recommendations:
        recommendations.append(
            "All assumptions have low sensitivity — the simulation is robust "
            "to assumption variations."
        )

    return SensitivityOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status="COMPLETED",
        baseline_conversion=round(base_cr, 6),
        baseline_revenue_per_1000=round(base_cr * 1000 * aov, 2),
        summary=summary,
        assumptions=results,
        recommendations=recommendations[:8],
        product_type_detected=str(data.get("product_type_detected") or ""),
        signal_quality=_safe_float(data.get("signal_quality")) if data.get("signal_quality") else None,
        meta={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "impact_levels": IMPACT_LEVELS,
            "assumption_count": len(results),
            "baseline_matrix_conversion": round(baseline_matrix_cr, 6),
            "scale_factor": round(scale_factor, 4),
        },
    )


__all__ = [
    "IMPACT_LEVELS",
    "SENSITIVITY_TIER_THRESHOLDS",
    "build_sensitivity_analysis",
]
