"""Funnel transition elasticity — which Markov edge is worth improving most.

The engine's headline conversion estimate
(:attr:`ClusterTransitionMatrix.conversion_estimate`) is the *product* of the
four forward-stage probabilities:

    ARRIVE→BROWSE × BROWSE→CONSIDER × CONSIDER→DECIDE × DECIDE→PURCHASE

That product silently ignores the consideration loops in the real matrix
(``CONSIDER→BROWSE`` and ``DECIDE→CONSIDER``): a shopper who circles back to
research re-rolls every downstream die. Those re-rolls are *second chances*
the stage-product writes off, so the headline number understates true
conversion whenever loops exist (the direct funnel path is one term of the
absorbing-chain sum; every loop path adds non-negative probability on top).
This module computes the **loop-adjusted conversion** analytically
(absorbing-chain linear solve, no Monte-Carlo noise — PURCHASE and ABANDON
absorb, everything else is transient, so the figure means "purchased before
abandoning this visit"), reports the gap as ``loop_uplift_pp``, and answers
the founder question neither number can answer alone:

    *if I could improve ONE behavioural transition, which one buys me the
    most conversion?*

For each forward edge we report:

* ``elasticity`` — % change in loop-adjusted conversion per 1% relative
  change in the edge probability (central finite difference);
* ``lift_per_10pct_gain_pp`` — absolute percentage-point conversion gained if
  the edge improves by a realistic +10% relative step;
* ``headroom_lift_pp`` — conversion gained if the edge were lifted all the way
  to a healthy target probability (default 0.90);
* ``related_keywords`` — assumption themes (pricing, trust, UX, …) whose
  keyword rules touch this edge, so the recommendation names a lever, not
  just a matrix cell.

Pure module (no DB, no I/O, fully deterministic): callers pass any 7×7
transition matrix in :data:`app.simulation.markov.STATES` order — typically
``ClusterTransitionMatrix.matrix`` — and get a JSON-ready dict back.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.simulation.markov import KEYWORD_RULES, STATE_INDEX, STATES, State

MODEL: str = "funnel_elasticity_v1"

# The four controllable forward edges, in funnel order. Side exits
# (e.g. CONSIDER→ABANDON) are their complements, so improving one forward
# edge IS reducing its siblings — we only ever quote the forward direction.
FUNNEL_EDGES: tuple[tuple[str, str], ...] = (
    (State.ARRIVE.value, State.BROWSE.value),
    (State.BROWSE.value, State.CONSIDER.value),
    (State.CONSIDER.value, State.DECIDE.value),
    (State.DECIDE.value, State.PURCHASE.value),
)

# Central-difference half-step applied to an edge's probability when
# estimating elasticity (absolute, in probability points).
DEFAULT_STEP: float = 0.05

# Realistic relative improvement quoted per edge in ``lift_per_10pct_gain_pp``.
RELATIVE_IMPROVEMENT: float = 0.10

# "Healthy" stage-conversion target used for headroom lift.
DEFAULT_TARGET_PROBABILITY: float = 0.90

# Leverage labels: rank 1 is always the bottleneck; the rest are graded by
# the absolute pp lift of a +10% relative improvement.
HIGH_LIFT_PP: float = 0.50
MODERATE_LIFT_PP: float = 0.15

_LABEL_PRIMARY = "PRIMARY_BOTTLENECK"
_LABEL_HIGH = "HIGH"
_LABEL_MODERATE = "MODERATE"
_LABEL_LOW = "LOW"

_ABSORPTION_EPS: float = 1e-12


# ---------------------------------------------------------------------------
# Matrix helpers
# ---------------------------------------------------------------------------


def _validate_and_normalise(matrix: np.ndarray) -> np.ndarray:
    """Validate shape/dtype and row-normalise, mirroring the engine."""
    arr = np.asarray(matrix, dtype=np.float64)
    if arr.shape != (len(STATES), len(STATES)):
        raise ValueError(
            f"matrix must have shape ({len(STATES)}, {len(STATES)}), got {arr.shape}"
        )
    if not np.all(np.isfinite(arr)):
        raise ValueError("matrix contains NaN or infinite values")
    if np.any(arr < 0.0):
        raise ValueError("matrix contains negative probabilities")
    out = arr.copy()
    row_sums = out.sum(axis=1)
    for i in range(out.shape[0]):
        if row_sums[i] > 0.0:
            out[i] /= row_sums[i]
    return out


def naive_conversion(matrix: np.ndarray) -> float:
    """Engine-consistent product of the four forward-stage probabilities.

    Matches how ``build_for_cluster`` derives
    ``ClusterTransitionMatrix.conversion_estimate``.
    """
    prod = 1.0
    for from_state, to_state in FUNNEL_EDGES:
        prod *= float(matrix[STATE_INDEX[State(from_state)], STATE_INDEX[State(to_state)]])
    return prod


def _perturb(matrix: np.ndarray, from_idx: int, to_idx: int, delta: float) -> np.ndarray:
    """Return a copy with edge ``from→to`` moved by ``delta``, row kept stochastic.

    The compensating mass is taken from / given to sibling outgoing edges
    proportionally, so relative sibling weights are preserved.
    """
    out = matrix.copy()
    row = out[from_idx]
    current = float(row[to_idx])
    target = float(np.clip(current + delta, 0.0, 1.0))
    diff = target - current
    siblings = [k for k in range(len(STATES)) if k != to_idx and row[k] > 0.0]
    sib_mass = float(sum(row[k] for k in siblings))
    row[to_idx] = target
    if siblings and abs(diff) > 0.0:
        for k in siblings:
            row[k] = max(0.0, row[k] - diff * (row[k] / sib_mass))
    new_sum = float(row.sum())
    if new_sum > 0.0:
        row[:] = row / new_sum
    return out


def loop_adjusted_conversion(matrix: np.ndarray) -> float:
    """P(Purchase before Abandon) from ARRIVE under the full matrix.

    Solves the absorbing chain analytically: pre-purchase states are
    transient, PURCHASE and ABANDON absorb, and consideration loops
    (``CONSIDER→BROWSE``, ``DECIDE→CONSIDER``) re-roll downstream stages.
    Always ≥ :func:`naive_conversion`: the direct funnel path is one term
    of the absorbing sum and every loop path adds non-negative second-chance
    probability on top. The gap is the loop uplift the engine's stage-product
    headline misses.
    """
    transient = [s for s in STATES if s not in (State.PURCHASE, State.ABANDON)]
    t_idx = [STATE_INDEX[s] for s in transient]
    q = matrix[np.ix_(t_idx, t_idx)]
    r_purchase = matrix[t_idx, STATE_INDEX[State.PURCHASE]]
    n = len(t_idx)
    try:
        u = np.linalg.solve(np.eye(n) - q, r_purchase)
    except np.linalg.LinAlgError:
        return 0.0
    arrive_pos = transient.index(State.ARRIVE)
    conv = float(u[arrive_pos])
    # A degenerate matrix whose transient block cannot reach PURCHASE can
    # make the solve diverge; treat non-probabilistic results as zero.
    if not np.isfinite(conv) or conv < -_ABSORPTION_EPS or conv > 1.0 + _ABSORPTION_EPS:
        return 0.0
    return float(np.clip(conv, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Edge-level analysis
# ---------------------------------------------------------------------------


def _edge_elasticity(
    base_conv: float,
    matrix: np.ndarray,
    from_idx: int,
    to_idx: int,
    base_prob: float,
    step: float,
) -> float | None:
    """Central-difference dlog(conversion)/dlog(edge probability)."""
    if base_prob <= 0.0 or base_conv <= _ABSORPTION_EPS:
        return None
    up_delta = min(step, 1.0 - base_prob)
    down_delta = min(step, base_prob)
    if up_delta <= 0.0 or down_delta <= 0.0:
        return None
    conv_up = loop_adjusted_conversion(_perturb(matrix, from_idx, to_idx, up_delta))
    conv_down = loop_adjusted_conversion(_perturb(matrix, from_idx, to_idx, -down_delta))
    denom_rel = (up_delta + down_delta) / base_prob
    if denom_rel <= 0.0:
        return None
    return ((conv_up - conv_down) / max(base_conv, _ABSORPTION_EPS)) / denom_rel


def _edge_lift_pp(
    base_conv: float,
    matrix: np.ndarray,
    from_idx: int,
    to_idx: int,
    base_prob: float,
    relative: float,
) -> float:
    """Absolute pp conversion gain from a +``relative`` improvement of one edge."""
    if base_prob >= 1.0 or base_conv <= _ABSORPTION_EPS:
        return 0.0
    improved = loop_adjusted_conversion(
        _perturb(matrix, from_idx, to_idx, base_prob * relative)
    )
    return max(0.0, (improved - base_conv) * 100.0)


def _edge_headroom_pp(
    base_conv: float,
    matrix: np.ndarray,
    from_idx: int,
    to_idx: int,
    base_prob: float,
    target_probability: float,
) -> float:
    """Absolute pp conversion gain from lifting one edge to the target."""
    target = min(target_probability, 1.0)
    if base_prob >= target or base_conv <= _ABSORPTION_EPS:
        return 0.0
    lifted = loop_adjusted_conversion(
        _perturb(matrix, from_idx, to_idx, target - base_prob)
    )
    return max(0.0, (lifted - base_conv) * 100.0)


def _related_keywords(from_state: str, to_state: str) -> list[str]:
    """Assumption themes whose keyword rules reference this edge."""
    themes: set[str] = set()
    for rule in KEYWORD_RULES:
        for rule_from, rule_to, _direction in rule.get("transitions", []):
            if rule_from.value == from_state and rule_to.value == to_state:
                themes.update(str(kw) for kw in rule.get("keywords", []))
                break
    return sorted(themes)


def _leverage_label(rank: int, lift_pp: float) -> str:
    if rank == 1:
        return _LABEL_PRIMARY
    if lift_pp >= HIGH_LIFT_PP:
        return _LABEL_HIGH
    if lift_pp >= MODERATE_LIFT_PP:
        return _LABEL_MODERATE
    return _LABEL_LOW


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_funnel_elasticity(
    matrix: np.ndarray,
    *,
    step: float = DEFAULT_STEP,
    target_probability: float = DEFAULT_TARGET_PROBABILITY,
    relative_improvement: float = RELATIVE_IMPROVEMENT,
) -> dict[str, Any]:
    """Rank the forward funnel edges by how much conversion each can buy.

    Args:
        matrix: 7×7 transition matrix in ``markov.STATES`` order (rows are
            normalised internally, so raw or corrected matrices both work).
        step: central-difference half-step for elasticity estimation.
        target_probability: "healthy" edge probability used for headroom lift.
        relative_improvement: relative step quoted per-edge as pp gain.

    Returns:
        JSON-ready dict with naive vs loop-adjusted conversion, the
        consideration-loop drag, per-edge elasticity/lift/headroom rows,
        a leverage ranking, and a one-line founder recommendation.
    """
    m = _validate_and_normalise(matrix)
    naive = naive_conversion(m)
    adjusted = loop_adjusted_conversion(m)

    rows: list[dict[str, Any]] = []
    for order, (from_state, to_state) in enumerate(FUNNEL_EDGES):
        fi = STATE_INDEX[State(from_state)]
        ti = STATE_INDEX[State(to_state)]
        base_prob = float(m[fi, ti])
        lift_pp = _edge_lift_pp(adjusted, m, fi, ti, base_prob, relative_improvement)
        headroom_pp = _edge_headroom_pp(
            adjusted, m, fi, ti, base_prob, target_probability
        )
        rows.append(
            {
                "order": order,
                "from_state": from_state,
                "to_state": to_state,
                "base_probability": round(base_prob, 4),
                "dropoff": round(1.0 - base_prob, 4),
                "elasticity": _edge_elasticity(adjusted, m, fi, ti, base_prob, step),
                "lift_per_gain_pp": round(lift_pp, 4),
                "headroom_lift_pp": round(headroom_pp, 4),
                "target_probability": round(min(target_probability, 1.0), 4),
                "leverage": _LABEL_LOW,
                "related_keywords": _related_keywords(from_state, to_state),
            }
        )

    ranked = sorted(
        rows,
        key=lambda r: (-r["lift_per_gain_pp"], -r["headroom_lift_pp"], r["order"]),
    )
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank
        row["leverage"] = _leverage_label(rank, float(row["lift_per_gain_pp"]))

    top = ranked[0]
    # Loop uplift: how much second-chance re-roll probability the engine's
    # stage-product headline writes off. Non-negative by construction.
    loop_uplift_pp = max(0.0, (adjusted - naive) * 100.0)
    recommendation = (
        f"Highest-leverage fix: improve {top['from_state']}->{top['to_state']} "
        f"(currently {top['base_probability']:.2f}); a 10% relative gain is worth "
        f"+{float(top['lift_per_gain_pp']):.2f}pp conversion."
    )
    if loop_uplift_pp >= 0.5:
        recommendation += (
            f" Consideration loops already add {loop_uplift_pp:.1f}pp that the "
            "naive stage-product estimate misses (second-chance re-rolls)."
        )

    return {
        "model": MODEL,
        "conversion": {
            "naive_product": round(naive, 4),
            "loop_adjusted": round(adjusted, 4),
            "loop_uplift_pp": round(loop_uplift_pp, 4),
        },
        "edges": [
            {k: v for k, v in row.items() if k != "order"} for row in rows
        ],
        "ranking": [
            f"{row['from_state']}->{row['to_state']}" for row in ranked
        ],
        "top_recommendation": recommendation,
    }
