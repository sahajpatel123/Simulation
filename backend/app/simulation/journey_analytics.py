"""
Journey analytics — Markov-chain customer-journey insights for a simulation.

A founder gets one headline conversion number, but not *how* consumers get
there: which stages they pass through, how long the journey takes, which
exit is the biggest leak, and which single transition improvement would move
the needle most. This module answers those questions analytically from the
per-cluster transition matrices the conductor already produces, without
re-running agents.

Model semantics
---------------
The Markov funnel treats ``PURCHASE`` and ``ABANDON`` as absorbing states —
this matches :meth:`MarkovBehaviourModel.run_chain`, which stops an agent as
soon as it reaches either. ``RETURN`` is still a transient state in the math
(reachable in the raw matrix), but is unreachable before absorption, so it
contributes zero to every aggregate. All metrics are derived with standard
absorbing-chain mathematics:

* ``N = (I - Q)^-1`` is the fundamental matrix; ``N[i, j]`` is the expected
  number of visits to transient state ``j`` starting from transient state
  ``i`` before absorption.
* ``B = N @ R`` gives absorption probabilities; ``B[ARRIVE, PURCHASE]`` is
  the analytic conversion probability of the chain.
* Expected exits via ``i -> ABANDON`` are ``N[ARRIVE, i] * P(i -> ABANDON)``
  (each visit to ``i`` has probability ``P(i -> ABANDON)`` of ending the
  journey).
* Transition leverage is a finite-difference experiment: add +5pp to one
  transition, renormalise the row (the other options shrink proportionally),
  and measure the change in purchase probability. This is the founder-facing
  question *"if I fix this leak, what happens to conversion?"*.

The module is pure (no DB, no I/O). The route layer supplies the persisted
per-cluster override matrices and cluster weights.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from app.simulation.markov import BASE_TRANSITIONS, STATE_INDEX, State

# Funnel stages that can appear mid-journey. PURCHASE/ABANDON are absorbing.
TRANSIENT_STATES: tuple[State, ...] = (
    State.ARRIVE,
    State.BROWSE,
    State.CONSIDER,
    State.DECIDE,
    State.RETURN,
)
ABSORBING_STATES: tuple[State, ...] = (
    State.PURCHASE,
    State.ABANDON,
)

# Journey budget for the most-probable-path search.
MAX_PATH_LENGTH: int = 8
MIN_PATH_PROBABILITY: float = 1e-4
PER_CLUSTER_PATH_CAP: int = 25
TOP_PATHS: int = 10

# Leverage experiment parameters.
LEVERAGE_DELTA: float = 0.05
TOP_LEVERAGE: int = 10

# Ignore clusters with negligible weight when aggregating.
MIN_CLUSTER_WEIGHT: float = 1e-6

_STATE_NAMES: list[str] = [s.value for s in STATE_INDEX]
_TRANSIENT_INDICES: list[int] = [STATE_INDEX[s] for s in TRANSIENT_STATES]
_ABSORBING_INDICES: list[int] = [STATE_INDEX[s] for s in ABSORBING_STATES]
_ABSORBING_PURCHASE: int = STATE_INDEX[State.PURCHASE]
_ABSORBING_ABANDON: int = STATE_INDEX[State.ABANDON]


def _base_matrix() -> np.ndarray:
    """Return the canonical 7x7 base transition matrix (journey semantics)."""
    n = len(_STATE_NAMES)
    matrix = np.zeros((n, n), dtype=np.float64)
    for from_state, to_dict in BASE_TRANSITIONS.items():
        fi = STATE_INDEX[from_state]
        for to_state, prob in to_dict.items():
            matrix[fi, STATE_INDEX[to_state]] = float(prob)
    # PURCHASE and ABANDON are absorbing in the journey model.
    for idx in _ABSORBING_INDICES:
        matrix[idx, :] = 0.0
        matrix[idx, idx] = 1.0
    return matrix


def _normalise_overrides(
    overrides: dict[tuple[str, str], float] | dict[str, float],
) -> dict[tuple[str, str], float]:
    """Accept tuple keys or persisted ``"FROM->TO"`` string keys."""
    normalised: dict[tuple[str, str], float] = {}
    for key, value in overrides.items():
        if isinstance(key, tuple) and len(key) == 2:
            from_state, to_state = str(key[0]), str(key[1])
        elif isinstance(key, str) and "->" in key:
            from_state, to_state = key.split("->", 1)
        else:
            continue
        if from_state not in STATE_INDEX or to_state not in STATE_INDEX:
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(parsed):
            continue
        normalised[(from_state, to_state)] = parsed
    return normalised


def build_cluster_matrix(
    overrides: dict[tuple[str, str], float] | dict[str, float],
) -> np.ndarray:
    """Reconstruct a cluster's full transition matrix from architect overrides.

    Overrides are applied multiplicatively to the base transitions (the same
    semantics as :meth:`MarkovBehaviourModel.build_for_cluster`), clamped,
    then row-normalised so every row is stochastic.
    """
    matrix = _base_matrix()
    for (from_state, to_state), multiplier in _normalise_overrides(overrides).items():
        fi = STATE_INDEX[from_state]
        ti = STATE_INDEX[to_state]
        if fi in _ABSORBING_INDICES:
            continue
        current = matrix[fi, ti]
        matrix[fi, ti] = max(0.001, min(0.999, current * float(multiplier)))

    matrix = np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0)
    for i in range(matrix.shape[0]):
        row_sum = float(matrix[i].sum())
        if row_sum > 0.0:
            matrix[i] /= row_sum
        else:
            matrix[i] = np.zeros(matrix.shape[1], dtype=np.float64)
            matrix[i, _ABSORBING_ABANDON] = 1.0
    return matrix


def _fundamental_matrix(matrix: np.ndarray) -> np.ndarray | None:
    """Fundamental matrix ``N = (I - Q)^-1`` over transient states."""
    q = matrix[np.ix_(_TRANSIENT_INDICES, _TRANSIENT_INDICES)]
    identity = np.eye(len(_TRANSIENT_INDICES), dtype=np.float64)
    try:
        return np.linalg.inv(identity - q)
    except np.linalg.LinAlgError:
        try:
            return np.linalg.pinv(identity - q)
        except np.linalg.LinAlgError:
            return None


def cluster_metrics(matrix: np.ndarray) -> dict[str, Any] | None:
    """Compute absorbing-chain metrics for one cluster matrix."""
    fundamental = _fundamental_matrix(matrix)
    if fundamental is None:
        return None

    r = matrix[np.ix_(_TRANSIENT_INDICES, _ABSORBING_INDICES)]
    absorption = fundamental @ r
    purchase_col = _ABSORBING_INDICES.index(_ABSORBING_PURCHASE)
    abandon_col = _ABSORBING_INDICES.index(_ABSORBING_ABANDON)
    start = _TRANSIENT_INDICES.index(STATE_INDEX[State.ARRIVE])

    purchase_probability = float(absorption[start, purchase_col])
    abandon_probability = float(absorption[start, abandon_col])
    expected_steps = float((fundamental @ np.ones(len(_TRANSIENT_INDICES)))[start])

    exit_stage_distribution: dict[str, float] = {}
    for i, state_idx in enumerate(_TRANSIENT_INDICES):
        state_name = _STATE_NAMES[state_idx]
        if state_idx == STATE_INDEX[State.RETURN]:
            continue
        expected_exits = float(fundamental[start, i]) * float(matrix[state_idx, _ABSORBING_ABANDON])
        exit_stage_distribution[state_name] = round(expected_exits, 6)

    expected_revisits = 0.0
    visits_by_stage: dict[str, float] = {}
    for i, state_idx in enumerate(_TRANSIENT_INDICES):
        state_name = _STATE_NAMES[state_idx]
        visits = float(fundamental[start, i])
        visits_by_stage[state_name] = round(visits, 6)
        self_visits = float(fundamental[i, i])
        if self_visits > 1.0:
            expected_revisits += visits * (1.0 - 1.0 / self_visits)

    return {
        "purchase_probability": round(purchase_probability, 6),
        "abandon_probability": round(abandon_probability, 6),
        "expected_steps_to_absorb": round(expected_steps, 4),
        "expected_revisits": round(expected_revisits, 4),
        "exit_stage_distribution": exit_stage_distribution,
        "visits_by_stage": visits_by_stage,
    }


def _top_paths_for_matrix(
    matrix: np.ndarray,
    *,
    max_paths: int = PER_CLUSTER_PATH_CAP,
    max_length: int = MAX_PATH_LENGTH,
    min_probability: float = MIN_PATH_PROBABILITY,
) -> list[tuple[tuple[str, ...], float]]:
    """Depth-first search for the most probable terminating journeys."""
    start = STATE_INDEX[State.ARRIVE]
    paths: list[tuple[tuple[str, ...], float]] = []

    def visit(
        current: int,
        probability: float,
        path: list[int],
    ) -> None:
        if current in _ABSORBING_INDICES:
            paths.append(
                (
                    tuple(_STATE_NAMES[idx] for idx in path),
                    probability,
                )
            )
            return
        if len(path) >= max_length:
            return
        for to_idx, prob in enumerate(matrix[current]):
            child_prob = probability * float(prob)
            if child_prob < min_probability:
                continue
            visit(to_idx, child_prob, path + [to_idx])

    visit(start, 1.0, [start])
    paths.sort(key=lambda item: item[1], reverse=True)
    return paths[:max_paths]


def _transition_leverage(
    matrix: np.ndarray,
    baseline_purchase: float,
) -> list[dict[str, Any]]:
    """Rank row-normalised +5pp transition improvements by conversion gain."""
    base_metrics = cluster_metrics(matrix)
    if base_metrics is None:
        return []
    fundamental = _fundamental_matrix(matrix)
    if fundamental is None:
        return []

    gains: list[dict[str, Any]] = []
    for from_idx in _TRANSIENT_INDICES:
        if from_idx == STATE_INDEX[State.RETURN]:
            # RETURN is unreachable before absorption; changing it cannot
            # move conversion, so it would only add zero-value noise.
            continue
        row = matrix[from_idx].copy()
        for to_idx, prob in enumerate(row):
            if float(prob) <= 0.0:
                continue
            trial = row.copy()
            trial[to_idx] = max(0.0, float(trial[to_idx]) + LEVERAGE_DELTA)
            row_sum = float(trial.sum())
            if row_sum <= 0.0:
                continue
            trial = trial / row_sum
            trial_matrix = matrix.copy()
            trial_matrix[from_idx] = trial
            trial_metrics = cluster_metrics(trial_matrix)
            if trial_metrics is None:
                continue
            gain = float(trial_metrics["purchase_probability"]) - baseline_purchase
            gains.append(
                {
                    "from_state": _STATE_NAMES[from_idx],
                    "to_state": _STATE_NAMES[to_idx],
                    "gain_per_5pp": round(gain, 6),
                }
            )
    gains.sort(key=lambda item: item["gain_per_5pp"], reverse=True)
    return gains[:TOP_LEVERAGE]


def _describe_leverage(
    from_state: str,
    to_state: str,
    gain: float,
    baseline_purchase: float,
) -> str:
    relative = (gain / baseline_purchase * 100.0) if baseline_purchase > 1e-6 else 0.0
    if gain >= 0.0:
        return (
            f"Improving {from_state}→{to_state} by 5pp lifts conversion by "
            f"+{gain * 100:.2f}pp ({relative:+.1f}% relative)."
        )
    return (
        f"Improving {from_state}→{to_state} by 5pp costs "
        f"{gain * 100:.2f}pp conversion — deprioritise."
    )


def serialise_per_cluster_matrices(
    per_cluster_matrices: dict[str, dict[tuple[str, str], float]],
) -> dict[str, dict[str, float]]:
    """Convert tuple-keyed override maps to JSON-safe ``"FROM->TO"`` keys."""
    return {
        cluster_id: {
            f"{from_state}->{to_state}": round(float(value), 6)
            for (from_state, to_state), value in overrides.items()
        }
        for cluster_id, overrides in per_cluster_matrices.items()
    }


def deserialise_per_cluster_matrices(
    raw: Any,
) -> dict[str, dict[tuple[str, str], float]]:
    """Parse persisted per-cluster override maps back into tuple keys."""
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[tuple[str, str], float]] = {}
    for cluster_id, overrides in raw.items():
        if not isinstance(overrides, dict):
            continue
        result[str(cluster_id)] = _normalise_overrides(overrides)
    return result


def _weighted_cluster_metrics(
    per_cluster_matrices: dict[str, dict[tuple[str, str], float]],
    cluster_weights: dict[str, float] | None,
) -> tuple[
    list[tuple[str, np.ndarray, float]],
    float,
    list[dict[str, Any]] | None,
]:
    """Return ``(cluster_id, matrix, weight)`` triples and a weighted baseline."""
    weights = cluster_weights or {}
    total_weight = sum(
        max(0.0, float(weights.get(cid, 0.0)))
        for cid in per_cluster_matrices
    )
    uniform = total_weight <= 0.0
    if uniform:
        total_weight = float(max(len(per_cluster_matrices), 1))

    weighted_metrics: list[dict[str, Any]] = []
    triples: list[tuple[str, np.ndarray, float]] = []
    for cluster_id, overrides in per_cluster_matrices.items():
        matrix = build_cluster_matrix(overrides)
        raw_weight = float(weights.get(cluster_id, 0.0))
        if uniform:
            weight = 1.0 / total_weight if total_weight > 0 else 0.0
        else:
            weight = raw_weight / total_weight if total_weight > 0 else 0.0
        metrics = cluster_metrics(matrix)
        if metrics is not None:
            weighted_metrics.append(metrics)
            triples.append((cluster_id, matrix, weight))

    if not weighted_metrics:
        return triples, 0.0, None

    total = sum(float(m["purchase_probability"]) * w for m, (_, _, w) in zip(weighted_metrics, triples))
    weight_sum = sum(w for _, _, w in triples)
    baseline = total / weight_sum if weight_sum > 0 else 0.0
    return triples, baseline, weighted_metrics


def build_journey_analytics(
    per_cluster_matrices: Any,
    cluster_weights: dict[str, float] | None = None,
    *,
    max_paths: int = TOP_PATHS,
    max_length: int = MAX_PATH_LENGTH,
) -> dict[str, Any]:
    """Compose the full journey-analytics payload for a simulation."""
    matrices = deserialise_per_cluster_matrices(per_cluster_matrices)
    triples, baseline_purchase, weighted_metrics = _weighted_cluster_metrics(
        matrices,
        cluster_weights,
    )

    if not triples or weighted_metrics is None:
        return {
            "purchase_probability": 0.0,
            "abandon_probability": 0.0,
            "expected_steps_to_absorb": 0.0,
            "expected_revisits": 0.0,
            "exit_stage_distribution": {},
            "top_paths": [],
            "leverage_rankings": [],
            "per_cluster": [],
            "key_insights": [],
            "meta": {"matrix_count": 0, "weighted": False},
        }

    weight_sum = sum(w for _, _, w in triples)
    if weight_sum <= 0.0:
        weight_sum = 1.0

    # Aggregate absorption/step metrics.
    def _weighted_avg(key: str) -> float:
        total = sum(
            float(m[key]) * w
            for m, (_, _, w) in zip(weighted_metrics, triples)
        )
        return total / weight_sum

    purchase_probability = _weighted_avg("purchase_probability")
    abandon_probability = _weighted_avg("abandon_probability")
    expected_steps = _weighted_avg("expected_steps_to_absorb")
    expected_revisits = _weighted_avg("expected_revisits")

    exit_stage_distribution: dict[str, float] = {}
    for stage in (s.value for s in TRANSIENT_STATES if s is not State.RETURN):
        total = sum(
            float(m["exit_stage_distribution"].get(stage, 0.0)) * w
            for m, (_, _, w) in zip(weighted_metrics, triples)
        )
        exit_stage_distribution[stage] = round(total / weight_sum, 6)

    # Merge the most probable paths across clusters (weighted by cluster).
    merged_paths: dict[tuple[str, ...], float] = {}
    for cluster_id, matrix, weight in triples:
        if weight <= MIN_CLUSTER_WEIGHT:
            continue
        for path, probability in _top_paths_for_matrix(matrix, max_length=max_length):
            merged_paths[path] = merged_paths.get(path, 0.0) + weight * probability
    top_paths = [
        {
            "path": list(path),
            "probability": round(probability, 6),
            "converted": path[-1] == State.PURCHASE.value,
        }
        for path, probability in sorted(
            merged_paths.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:max_paths]
    ]

    # Aggregate leverage rankings (weighted across clusters).
    leverage = {}
    for cluster_id, matrix, weight in triples:
        if weight <= MIN_CLUSTER_WEIGHT:
            continue
        cluster_base = next(
            float(m["purchase_probability"])
            for m, (cid, _, _) in zip(weighted_metrics, triples)
            if cid == cluster_id
        )
        for item in _transition_leverage(matrix, cluster_base):
            key = (item["from_state"], item["to_state"])
            leverage[key] = leverage.get(key, 0.0) + weight * float(item["gain_per_5pp"])

    ranked = sorted(leverage.items(), key=lambda item: item[1], reverse=True)
    leverage_rankings = [
        {
            "from_state": from_state,
            "to_state": to_state,
            "gain_per_5pp": round(gain, 6),
            "relative_gain_pct": round(
                (gain / baseline_purchase * 100.0) if baseline_purchase > 1e-6 else 0.0,
                2,
            ),
            "description": _describe_leverage(
                from_state,
                to_state,
                gain,
                baseline_purchase,
            ),
        }
        for (from_state, to_state), gain in ranked[:TOP_LEVERAGE]
    ]

    per_cluster = []
    for (cluster_id, _matrix, weight), metrics in zip(triples, weighted_metrics):
        if cluster_weights and weight <= MIN_CLUSTER_WEIGHT:
            continue
        per_cluster.append(
            {
                "cluster_id": cluster_id,
                "purchase_probability": float(metrics["purchase_probability"]),
                "expected_steps_to_absorb": float(
                    metrics["expected_steps_to_absorb"]
                ),
                "primary_exit_stage": max(
                    metrics["exit_stage_distribution"],
                    key=lambda stage: metrics["exit_stage_distribution"][stage],
                )
                if max(
                    metrics["exit_stage_distribution"].values(),
                    default=0.0,
                )
                > 0.0
                else None,
            }
        )
    per_cluster.sort(key=lambda item: item["purchase_probability"], reverse=True)

    key_insights = _key_insights(
        purchase_probability=purchase_probability,
        expected_steps=expected_steps,
        expected_revisits=expected_revisits,
        exit_stage_distribution=exit_stage_distribution,
        top_paths=top_paths,
        leverage_rankings=leverage_rankings,
    )

    return {
        "purchase_probability": round(purchase_probability, 6),
        "abandon_probability": round(abandon_probability, 6),
        "expected_steps_to_absorb": round(expected_steps, 4),
        "expected_revisits": round(expected_revisits, 4),
        "exit_stage_distribution": exit_stage_distribution,
        "top_paths": top_paths,
        "leverage_rankings": leverage_rankings,
        "per_cluster": per_cluster,
        "key_insights": key_insights,
        "meta": {
            "matrix_count": len(triples),
            "weighted": bool(cluster_weights),
            "path_budget": {
                "max_paths": max_paths,
                "max_length": max_length,
                "min_probability": MIN_PATH_PROBABILITY,
            },
        },
    }


def _key_insights(
    *,
    purchase_probability: float,
    expected_steps: float,
    expected_revisits: float,
    exit_stage_distribution: dict[str, float],
    top_paths: list[dict[str, Any]],
    leverage_rankings: list[dict[str, Any]],
) -> list[str]:
    insights: list[str] = []

    if exit_stage_distribution:
        worst_stage = max(
            exit_stage_distribution,
            key=lambda stage: exit_stage_distribution[stage],
        )
        worst_share = float(exit_stage_distribution[worst_stage])
        insights.append(
            f"{worst_share:.1%} of simulated consumers exit at {worst_stage} "
            f"— the largest single leak in the journey."
        )

    if top_paths:
        top = top_paths[0]
        outcome = "purchase" if top["converted"] else "abandon"
        insights.append(
            f"The most common journey is {' → '.join(top['path'])} "
            f"({top['probability']:.1%} of consumers, ending in {outcome})."
        )

    if leverage_rankings:
        best = leverage_rankings[0]
        insights.append(
            f"Highest-leverage fix: {best['description']}"
        )

    insights.append(
        f"Consumers average {expected_steps:.1f} funnel steps "
        f"({expected_revisits:.1f} revisits) before purchasing or abandoning "
        f"— a {purchase_probability:.1%} overall purchase probability."
    )
    return insights


__all__ = [
    "ABSORBING_STATES",
    "LEVERAGE_DELTA",
    "MAX_PATH_LENGTH",
    "MIN_CLUSTER_WEIGHT",
    "MIN_PATH_PROBABILITY",
    "PER_CLUSTER_PATH_CAP",
    "TOP_LEVERAGE",
    "TOP_PATHS",
    "TRANSIENT_STATES",
    "build_cluster_matrix",
    "build_journey_analytics",
    "cluster_metrics",
    "deserialise_per_cluster_matrices",
    "serialise_per_cluster_matrices",
]
