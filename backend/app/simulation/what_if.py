"""
Pure what-if scenario simulator for completed simulation results.

Takes a simulation's env_params + existing assumptions, optionally applies
user-supplied override assumptions, and re-computes the Markov transition
matrix to project a new conversion rate.

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
from app.schemas.what_if import (
    StageImpact,
    WhatIfAssumption,
    WhatIfOut,
    WhatIfRecommendation,
)

# Forward funnel stages whose transition probabilities matter for conversion.
FORWARD_TRANSITIONS: list[tuple[State, State]] = [
    (State.ARRIVE, State.BROWSE),
    (State.BROWSE, State.CONSIDER),
    (State.CONSIDER, State.DECIDE),
    (State.DECIDE, State.PURCHASE),
]

# Human-readable stage labels for the impact report.
_STAGE_LABELS: dict[State, str] = {
    State.ARRIVE: "ARRIVE",
    State.BROWSE: "BROWSE",
    State.CONSIDER: "CONSIDER",
    State.DECIDE: "DECIDE",
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


def _stage_impacts(
    base_matrix: np.ndarray,
    projected_matrix: np.ndarray,
    new_assumptions: list[dict[str, Any]],
) -> list[StageImpact]:
    """Compute per-stage transition impacts from the what-if assumptions."""
    impacts: list[StageImpact] = []

    # Pre-compute which assumptions affect which transitions
    assumption_effects: dict[tuple[State, State], list[str]] = {}
    for a in new_assumptions:
        text = a.get("text", "").lower()
        for rule in KEYWORD_RULES:
            if any(kw in text for kw in rule["keywords"]):
                for from_s, to_s, _ in rule["transitions"]:
                    key = (from_s, to_s)
                    assumption_effects.setdefault(key, []).append(text[:60])
                break

    for from_s, to_s in FORWARD_TRANSITIONS:
        fi = STATE_INDEX[from_s]
        ti = STATE_INDEX[to_s]
        base_rate = float(base_matrix[fi, ti])
        projected_rate = float(projected_matrix[fi, ti])
        delta = round(projected_rate - base_rate, 6)

        affected = assumption_effects.get((from_s, to_s), [])

        impacts.append(
            StageImpact(
                stage=_STAGE_LABELS.get(from_s, from_s.value),
                transition=f"{from_s.value}→{to_s.value}",
                base_rate=round(base_rate, 4),
                projected_rate=round(projected_rate, 4),
                delta=delta,
                affected_by=affected,
            )
        )

    return impacts


def _build_recommendations(
    base_cr: float,
    projected_cr: float,
    delta: float,
    stage_impacts: list[StageImpact],
    assumptions: list[dict[str, Any]],
    env_overrides: dict[str, Any] | None = None,
) -> list[WhatIfRecommendation]:
    """Generate actionable recommendations from the what-if analysis."""
    recs: list[WhatIfRecommendation] = []
    priority = 1
    env_overrides = env_overrides or {}
    change_count = len(assumptions) + len(env_overrides)

    if delta > 0:
        recs.append(
            WhatIfRecommendation(
                priority=priority,
                title=f"Positive impact: +{delta:.1%} conversion projected",
                rationale=(
                    f"Applying {len(assumptions)} new assumption(s)"
                    f"{' and env overrides' if env_overrides else ''} "
                    f"lifts conversion from {base_cr:.1%} to {projected_cr:.1%}."
                ),
                estimated_lift=delta,
                affected_stages=[s.stage for s in stage_impacts if s.delta > 0],
            )
        )
    elif delta < 0:
        recs.append(
            WhatIfRecommendation(
                priority=priority,
                title=f"Negative impact: −{abs(delta):.1%} conversion projected",
                rationale=(
                    f"Applying {len(assumptions)} new assumption(s)"
                    f"{' and env overrides' if env_overrides else ''} "
                    f"reduces conversion from {base_cr:.1%} to {projected_cr:.1%}. "
                    "Review whether these changes reflect real constraints."
                ),
                estimated_lift=delta,
                affected_stages=[s.stage for s in stage_impacts if s.delta < 0],
            )
        )
    else:
        if change_count == 0:
            rationale = (
                "No assumptions or env overrides were supplied. "
                "Add pricing, trust, UX, or market keywords — or override "
                "price_sensitivity / market_maturity — to project an impact."
            )
        else:
            rationale = (
                "The supplied changes do not move the forward conversion chain. "
                "Try stronger sensitivity, higher impact_score, or keywords that "
                "match pricing, trust, UX, or retention rules."
            )
        recs.append(
            WhatIfRecommendation(
                priority=priority,
                title="Neutral impact — no conversion change projected",
                rationale=rationale,
                estimated_lift=0.0,
                affected_stages=[],
            )
        )
    priority += 1

    if stage_impacts:
        worst_stage = min(stage_impacts, key=lambda s: s.delta)
        if worst_stage.delta < 0:
            to_label = worst_stage.transition.split("→")[-1]
            recs.append(
                WhatIfRecommendation(
                    priority=priority,
                    title=f"Mitigate {worst_stage.stage} stage regression",
                    rationale=(
                        f"The {worst_stage.stage}→{to_label} "
                        f"transition dropped by {abs(worst_stage.delta):.1%} "
                        f"(from {worst_stage.base_rate:.1%} to "
                        f"{worst_stage.projected_rate:.1%})."
                    ),
                    estimated_lift=abs(worst_stage.delta),
                    affected_stages=[worst_stage.stage],
                )
            )
            priority += 1

        best_stage = max(stage_impacts, key=lambda s: s.delta)
        if best_stage.delta > 0:
            to_label = best_stage.transition.split("→")[-1]
            recs.append(
                WhatIfRecommendation(
                    priority=priority,
                    title=f"Leverage {best_stage.stage} stage improvement",
                    rationale=(
                        f"The {best_stage.stage}→{to_label} "
                        f"transition improved by {best_stage.delta:.1%} "
                        f"(from {best_stage.base_rate:.1%} to "
                        f"{best_stage.projected_rate:.1%})."
                    ),
                    estimated_lift=best_stage.delta,
                    affected_stages=[best_stage.stage],
                )
            )
            priority += 1

    has_pricing = any(
        any(
            kw in a.get("text", "").lower()
            for kw in ["pric", "cost", "fee", "₹", "afford"]
        )
        for a in assumptions
    )
    has_trust = any(
        any(
            kw in a.get("text", "").lower()
            for kw in ["trust", "credib", "review", "testimonial", "brand"]
        )
        for a in assumptions
    )
    if assumptions and not has_pricing and not has_trust:
        recs.append(
            WhatIfRecommendation(
                priority=priority,
                title="Add pricing or trust assumptions for richer projections",
                rationale=(
                    "Assumptions containing pricing (₹, cost, fee) or trust "
                    "(review, testimonial, brand) keywords trigger Markov "
                    "transition adjustments. Including these will produce more "
                    "targeted conversion estimates."
                ),
                estimated_lift=0.0,
                affected_stages=[],
            )
        )

    recs.sort(key=lambda r: r.priority)
    return recs


def build_what_if_scenario(
    simulation_id: int,
    project_id: int,
    base_results: dict[str, Any],
    env_params: dict[str, Any],
    existing_assumptions: list[Any],
    new_assumptions: list[dict[str, Any]],
    override_price_sensitivity: float | None = None,
    override_market_maturity: float | None = None,
) -> WhatIfOut:
    """
    Build a what-if scenario projection from a completed simulation.

    ``base_results`` — the simulation's ``results_json`` dict.
    ``env_params`` — the environment parameters (price_sensitivity, market_maturity, etc.).
    ``existing_assumptions`` — the project's existing assumptions (dicts or objects).
    ``new_assumptions`` — user-supplied what-if assumptions (dicts).
    """
    data = _coerce_results(base_results)

    # Extract base conversion rate from results
    base_cr = _safe_float(
        data.get("population_weighted_conversion", data.get("mean_conversion_rate", 0.0))
    )
    base_cr = max(0.0, min(1.0, base_cr))

    # Get AOV for revenue projection
    aov = _safe_float(data.get("mean_revenue", 0.0))
    if aov <= 0:
        aov = _safe_float(env_params.get("average_order_value", 999.0), 999.0)

    # Build env params for the Markov matrix — keep an unmodified baseline
    # so env overrides actually move the projected conversion rate.
    base_env = {
        "price_sensitivity": _safe_float(env_params.get("price_sensitivity", 0.5)),
        "market_maturity": _safe_float(env_params.get("market_maturity", 0.3)),
    }
    projected_env = dict(base_env)
    env_overrides: dict[str, Any] = {}
    if override_price_sensitivity is not None:
        projected_env["price_sensitivity"] = float(
            max(0.0, min(1.0, override_price_sensitivity))
        )
        env_overrides["price_sensitivity"] = projected_env["price_sensitivity"]
    if override_market_maturity is not None:
        projected_env["market_maturity"] = float(
            max(0.0, min(1.0, override_market_maturity))
        )
        env_overrides["market_maturity"] = projected_env["market_maturity"]

    # Normalise assumptions
    base_assumptions = _assumption_dicts(existing_assumptions)
    new_assump_dicts = _assumption_dicts(new_assumptions)

    # Build base matrix (existing assumptions + original env)
    base_matrix = _build_matrix(base_env, base_assumptions)
    base_matrix_cr = _forward_conversion(base_matrix)

    # Use the simulation's actual conversion rate as the authoritative base,
    # but fall back to the matrix-derived rate if the stored rate is missing.
    if base_cr > 0:
        pass
    else:
        base_cr = base_matrix_cr

    # Build projected matrix (existing + new assumptions + overridden env)
    combined_assumptions = base_assumptions + new_assump_dicts
    projected_matrix = _build_matrix(projected_env, combined_assumptions)
    projected_matrix_cr = _forward_conversion(projected_matrix)

    # Scale projected rate to match the base rate's scale
    # (the matrix conversion is a raw product; the simulation's actual
    #  rate incorporates cluster reweighting, architect overrides, etc.)
    if base_matrix_cr > 0 and base_cr > 0:
        scale_factor = base_cr / base_matrix_cr
        projected_cr = round(min(0.99, max(0.0, projected_matrix_cr * scale_factor)), 6)
    else:
        projected_cr = round(max(0.0, min(0.99, projected_matrix_cr)), 6)

    delta = round(projected_cr - base_cr, 6)
    delta_pct = round((delta / base_cr) * 100, 2) if base_cr > 0 else 0.0

    # Revenue projections (per 1000 visitors)
    base_revenue = round(base_cr * 1000 * aov, 2)
    projected_revenue = round(projected_cr * 1000 * aov, 2)

    # Stage-by-stage impacts
    impacts = _stage_impacts(base_matrix, projected_matrix, new_assump_dicts)

    # Recommendations
    recommendations = _build_recommendations(
        base_cr=base_cr,
        projected_cr=projected_cr,
        delta=delta,
        stage_impacts=impacts,
        assumptions=new_assump_dicts,
        env_overrides=env_overrides,
    )

    # Serialise assumptions for the response
    assumptions_applied = [
        WhatIfAssumption(
            text=a.get("text", ""),
            sensitivity=a.get("sensitivity", "MEDIUM"),
            impact_score=_safe_float(a.get("impact_score", 5.0)),
        )
        for a in new_assump_dicts
    ]

    return WhatIfOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status="COMPLETED",
        base_conversion_rate=round(base_cr, 6),
        projected_conversion_rate=projected_cr,
        conversion_delta=delta,
        conversion_delta_pct=delta_pct,
        base_revenue_per_1000=base_revenue,
        projected_revenue_per_1000=projected_revenue,
        stage_impacts=impacts,
        recommendations=recommendations,
        assumptions_applied=assumptions_applied,
        env_overrides=env_overrides,
        meta={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "base_matrix_conversion": round(base_matrix_cr, 6),
            "projected_matrix_conversion": round(projected_matrix_cr, 6),
            "existing_assumptions_count": len(base_assumptions),
            "new_assumptions_count": len(new_assump_dicts),
            "scale_factor_applied": (
                round(base_cr / base_matrix_cr, 4) if base_matrix_cr > 0 else 1.0
            ),
        },
    )


__all__ = ["build_what_if_scenario"]
