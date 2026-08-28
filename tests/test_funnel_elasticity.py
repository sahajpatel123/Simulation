"""
Tests for funnel transition elasticity (app/simulation/funnel_elasticity.py).

Contract pinned here:

  1. ``naive_conversion`` reproduces the engine's forward-stage product
     (the same formula behind ``conversion_estimate``).
  2. On the real BASE_TRANSITIONS matrix, loop-adjusted conversion sits
     strictly below the naive product (consideration loops cost conversion).
  3. On an acyclic (loop-free) matrix the two definitions agree exactly —
     validates the absorbing-chain solve analytically.
  4. Raising any forward edge's probability never lowers loop-adjusted
     conversion.
  5. Every forward edge reports a positive lift for a +10% relative gain,
     finite elasticity where computable, and earlier edges are amplified
     through downstream loops at least as much as the last edge.
  6. Degenerate all→ABANDON matrices return zeroes without crashing.
  7. An edge already at/above the healthy target has zero headroom.
  8. Keyword themes map onto the edges their rules touch
     (pricing → DECIDE→PURCHASE, trust → BROWSE→CONSIDER).
  9. Payload shape, ranking consistency, leverage labels, determinism.
 10. Works on matrices produced by ``MarkovBehaviourModel``.
 11. Invalid matrices (wrong shape, NaN, negative) raise ValueError.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from app.simulation.funnel_elasticity import (
    DEFAULT_TARGET_PROBABILITY,
    FUNNEL_EDGES,
    _perturb,
    build_funnel_elasticity,
    build_population_funnel_elasticity,
    loop_adjusted_conversion,
    naive_conversion,
)
from app.simulation.journey_analytics import build_cluster_matrix
from app.simulation.markov import BASE_TRANSITIONS, STATE_INDEX, STATES, State

# ---------------------------------------------------------------------------
# Matrix builders
# ---------------------------------------------------------------------------


def _matrix_from_spec(spec: dict[tuple[str, str], float]) -> np.ndarray:
    """Row-stochastic-free builder: entries given explicitly, rest zero."""
    m = np.zeros((len(STATES), len(STATES)), dtype=np.float64)
    for (from_s, to_s), prob in spec.items():
        m[STATE_INDEX[State(from_s)], STATE_INDEX[State(to_s)]] = prob
    for i in range(m.shape[0]):
        s = m[i].sum()
        if s > 0:
            m[i] /= s
        else:
            m[i, STATE_INDEX[State.ABANDON]] = 1.0
    return m


def _base_matrix() -> np.ndarray:
    spec: dict[tuple[str, str], float] = {}
    for from_s, to_dict in BASE_TRANSITIONS.items():
        for to_s, prob in to_dict.items():
            spec[(from_s.value, to_s.value)] = prob
    return _matrix_from_spec(spec)


def _acyclic_matrix() -> np.ndarray:
    """Loop-free funnel: no backward edges, PURCHASE/ABANDON absorbing."""
    return _matrix_from_spec(
        {
            ("ARRIVE", "BROWSE"): 0.87,
            ("ARRIVE", "ABANDON"): 0.13,
            ("BROWSE", "CONSIDER"): 0.62,
            ("BROWSE", "ABANDON"): 0.38,
            ("CONSIDER", "DECIDE"): 0.46,
            ("CONSIDER", "ABANDON"): 0.54,
            ("DECIDE", "PURCHASE"): 0.31,
            ("DECIDE", "ABANDON"): 0.69,
            ("PURCHASE", "ABANDON"): 1.0,
            ("ABANDON", "ABANDON"): 1.0,
            ("RETURN", "ABANDON"): 1.0,
        }
    )


def _all_abandon_matrix() -> np.ndarray:
    return _matrix_from_spec({})


def _env(**overrides: Any) -> dict[str, Any]:
    env: dict[str, Any] = {
        "consumer_volume": 10_000,
        "growth_rate_per_month": 8.0,
        "average_order_value": 999.0,
        "price_sensitivity": 0.5,
        "market_maturity": 0.3,
    }
    env.update(overrides)
    return env


# ---------------------------------------------------------------------------
# 1–3. Conversion definitions
# ---------------------------------------------------------------------------


def test_naive_conversion_matches_engine_product_formula() -> None:
    m = _base_matrix()
    expected = 1.0
    for from_s, to_s in FUNNEL_EDGES:
        expected *= m[STATE_INDEX[State(from_s)], STATE_INDEX[State(to_s)]]
    assert naive_conversion(m) == pytest.approx(expected, abs=1e-12)
    # Benchmark hand-value for the shipped BASE_TRANSITIONS.
    assert naive_conversion(m) == pytest.approx(0.87 * 0.62 * 0.46 * 0.31, rel=1e-9)


def test_loop_adjusted_on_base_matrix() -> None:
    """Consideration loops give shoppers second chances: adjusted > naive."""
    m = _base_matrix()
    adjusted = loop_adjusted_conversion(m)
    naive = naive_conversion(m)
    assert 0.0 < naive < adjusted <= 1.0


def test_loop_adjusted_never_below_naive_on_random_stochastic_matrices() -> None:
    """Structural invariant, not a benchmark accident: the direct funnel path
    is one term of the absorbing sum and loop paths only add probability.
    Verified over seeded random row-stochastic matrices with loops."""
    rng = np.random.default_rng(1234)
    for _ in range(25):
        m = rng.random((len(STATES), len(STATES)))
        # Keep PURCHASE/ABANDON absorbing so "before abandoning" stays true.
        m[STATE_INDEX[State.PURCHASE]] = [0.0] * len(STATES)
        m[STATE_INDEX[State.PURCHASE], STATE_INDEX[State.PURCHASE]] = 1.0
        m[STATE_INDEX[State.ABANDON]] = [0.0] * len(STATES)
        m[STATE_INDEX[State.ABANDON], STATE_INDEX[State.ABANDON]] = 1.0
        m /= m.sum(axis=1, keepdims=True)
        adjusted = loop_adjusted_conversion(m)
        naive = naive_conversion(m)
        assert adjusted >= naive - 1e-9, (adjusted, naive)


def test_acyclic_chain_reproduces_naive_product_exactly() -> None:
    m = _acyclic_matrix()
    assert loop_adjusted_conversion(m) == pytest.approx(naive_conversion(m), abs=1e-9)


def test_loop_adjusted_is_a_probability() -> None:
    for m in (_base_matrix(), _acyclic_matrix(), _all_abandon_matrix()):
        conv = loop_adjusted_conversion(m)
        assert 0.0 <= conv <= 1.0


# ---------------------------------------------------------------------------
# 4–5. Edge behaviour
# ---------------------------------------------------------------------------


def test_raising_any_forward_edge_never_lowers_conversion() -> None:
    m = _base_matrix()
    baseline = loop_adjusted_conversion(m)
    for from_s, to_s in FUNNEL_EDGES:
        bumped = loop_adjusted_conversion(_perturb(m, STATE_INDEX[State(from_s)], STATE_INDEX[State(to_s)], 0.05))
        assert bumped >= baseline - 1e-12


def test_every_edge_has_positive_lift_and_finite_elasticity() -> None:
    payload = build_funnel_elasticity(_base_matrix())
    lifts = [edge["lift_per_gain_pp"] for edge in payload["edges"]]
    assert all(lift > 0.0 for lift in lifts)
    elasticities = [edge["elasticity"] for edge in payload["edges"]]
    assert all(el is not None and np.isfinite(el) for el in elasticities)


def test_earlier_edge_lift_at_least_last_edge_on_base_matrix() -> None:
    """Improvements upstream re-roll every downstream loop, so they compound."""
    payload = build_funnel_elasticity(_base_matrix())
    by_key = {
        f"{e['from_state']}->{e['to_state']}": e["lift_per_gain_pp"]
        for e in payload["edges"]
    }
    assert by_key["ARRIVE->BROWSE"] >= by_key["DECIDE->PURCHASE"] - 1e-9


# ---------------------------------------------------------------------------
# 6–7. Degenerate and saturated cases
# ---------------------------------------------------------------------------


def test_degenerate_all_abandon_matrix_returns_zeroes_without_crash() -> None:
    payload = build_funnel_elasticity(_all_abandon_matrix())
    conv = payload["conversion"]
    assert conv["naive_product"] == 0.0
    assert conv["loop_adjusted"] == 0.0
    assert all(e["lift_per_gain_pp"] == 0.0 for e in payload["edges"])
    assert len(payload["ranking"]) == len(FUNNEL_EDGES)


def test_edge_at_target_has_zero_headroom() -> None:
    m = _matrix_from_spec(
        {
            ("ARRIVE", "BROWSE"): 0.95,
            ("ARRIVE", "ABANDON"): 0.05,
            ("BROWSE", "CONSIDER"): 0.62,
            ("BROWSE", "ABANDON"): 0.38,
            ("CONSIDER", "DECIDE"): 0.46,
            ("CONSIDER", "ABANDON"): 0.54,
            ("DECIDE", "PURCHASE"): 0.31,
            ("DECIDE", "ABANDON"): 0.69,
            ("PURCHASE", "ABANDON"): 1.0,
            ("ABANDON", "ABANDON"): 1.0,
            ("RETURN", "ABANDON"): 1.0,
        }
    )
    payload = build_funnel_elasticity(m)
    arrive_row = next(
        e for e in payload["edges"] if e["from_state"] == "ARRIVE"
    )
    assert arrive_row["base_probability"] >= DEFAULT_TARGET_PROBABILITY
    assert arrive_row["headroom_lift_pp"] == 0.0


# ---------------------------------------------------------------------------
# 8. Keyword theme mapping
# ---------------------------------------------------------------------------


def test_pricing_keywords_map_to_decide_to_purchase() -> None:
    payload = build_funnel_elasticity(_base_matrix())
    decide_row = next(
        e
        for e in payload["edges"]
        if e["from_state"] == "DECIDE" and e["to_state"] == "PURCHASE"
    )
    assert any("pric" in kw for kw in decide_row["related_keywords"])


def test_trust_keywords_map_to_browse_to_consider() -> None:
    payload = build_funnel_elasticity(_base_matrix())
    browse_row = next(
        e for e in payload["edges"] if e["from_state"] == "BROWSE"
    )
    assert any("trust" in kw for kw in browse_row["related_keywords"])


# ---------------------------------------------------------------------------
# 9. Payload shape, ranking, determinism
# ---------------------------------------------------------------------------


def test_payload_shape_and_ranking_consistency() -> None:
    payload = build_funnel_elasticity(_base_matrix())
    assert set(payload.keys()) == {
        "model",
        "conversion",
        "edges",
        "ranking",
        "top_recommendation",
    }
    assert payload["model"] == "funnel_elasticity_v1"
    assert len(payload["edges"]) == len(FUNNEL_EDGES)
    assert len(payload["ranking"]) == len(FUNNEL_EDGES)

    top_key = payload["ranking"][0]
    top_row = next(
        e
        for e in payload["edges"]
        if f"{e['from_state']}->{e['to_state']}" == top_key
    )
    best_lift = max(e["lift_per_gain_pp"] for e in payload["edges"])
    assert top_row["lift_per_gain_pp"] == pytest.approx(best_lift)
    assert top_row["leverage"] == "PRIMARY_BOTTLENECK"

    labelled = {e["leverage"] for e in payload["edges"]}
    assert labelled <= {"PRIMARY_BOTTLENECK", "HIGH", "MODERATE", "LOW"}

    rec = payload["top_recommendation"]
    assert top_key.split("->")[0] in rec and "->" in rec
    # Signed loop-uplift contract: the payload exposes loop_uplift_pp and the
    # recommendation quantifies it when material.
    effect = payload["conversion"]["loop_uplift_pp"]
    naive_v = payload["conversion"]["naive_product"]
    adjusted_v = payload["conversion"]["loop_adjusted"]
    # Payload values are rounded to 4dp each, so the reconstructed uplift can
    # differ by up to ~0.01pp; exactness is pinned separately on raw floats.
    assert effect == pytest.approx(
        max(0.0, (adjusted_v - naive_v) * 100.0), abs=0.02
    )
    assert adjusted_v >= naive_v
    if effect >= 0.5:
        assert "add" in rec


def test_build_is_deterministic() -> None:
    m = _base_matrix()
    first = build_funnel_elasticity(m)
    second = build_funnel_elasticity(m)
    assert first == second


# ---------------------------------------------------------------------------
# 10. Engine-built matrices
# ---------------------------------------------------------------------------


def test_works_with_engine_built_transition_matrix() -> None:
    from app.simulation.markov import MarkovBehaviourModel

    matrix = MarkovBehaviourModel().build_transition_matrix(_env(), [], seed=42)
    payload = build_funnel_elasticity(matrix)

    expected_naive = 1.0
    for from_s, to_s in FUNNEL_EDGES:
        expected_naive *= matrix[
            STATE_INDEX[State(from_s)], STATE_INDEX[State(to_s)]
        ]
    assert payload["conversion"]["naive_product"] == pytest.approx(
        round(expected_naive, 4), abs=1e-4
    )
    assert payload["conversion"]["loop_adjusted"] > 0.0
    assert all(np.isfinite(e["lift_per_gain_pp"]) for e in payload["edges"])


# ---------------------------------------------------------------------------
# 11. Invalid input
# ---------------------------------------------------------------------------


def test_wrong_shape_raises_value_error() -> None:
    with pytest.raises(ValueError):
        build_funnel_elasticity(np.zeros((3, 3)))


def test_nan_entry_raises_value_error() -> None:
    m = _base_matrix()
    m[0, 1] = np.nan
    with pytest.raises(ValueError):
        build_funnel_elasticity(m)


def test_negative_entry_raises_value_error() -> None:
    m = _base_matrix()
    m[2, 3] = -0.1
    with pytest.raises(ValueError):
        build_funnel_elasticity(m)


# ---------------------------------------------------------------------------
# 12. Population-level aggregation
# ---------------------------------------------------------------------------

def test_population_returns_none_without_usable_matrices() -> None:
    assert build_population_funnel_elasticity(None) is None
    assert build_population_funnel_elasticity({}) is None
    assert build_population_funnel_elasticity({"c1": "not-a-dict"}) is None


def test_population_payload_shape_and_ranking() -> None:
    matrices = {
        "cluster_a": {"DECIDE->PURCHASE": 1.6},
        "cluster_b": {"CONSIDER->DECIDE": 1.4},
        "cluster_c": {},
    }
    weights = {"cluster_a": 0.5, "cluster_b": 0.3, "cluster_c": 0.2}
    payload = build_population_funnel_elasticity(matrices, weights)

    assert payload is not None
    assert set(payload.keys()) == {
        "model",
        "conversion",
        "edges",
        "ranking",
        "cluster_consensus",
        "per_cluster_top_edges",
        "top_recommendation",
    }
    assert len(payload["edges"]) == len(FUNNEL_EDGES)
    assert len(payload["ranking"]) == len(FUNNEL_EDGES)
    # Every cluster contributed exactly one vote.
    assert sum(
        c["weighted_vote_share"] for c in payload["cluster_consensus"]
    ) == pytest.approx(1.0, abs=1e-6)
    top_key = payload["ranking"][0]
    top_row = next(
        e
        for e in payload["edges"]
        if f"{e['from_state']}->{e['to_state']}" == top_key
    )
    best_lift = max(e["lift_per_gain_pp"] for e in payload["edges"])
    assert top_row["lift_per_gain_pp"] == pytest.approx(best_lift)
    assert "Across" in payload["top_recommendation"]


def test_population_weighting_changes_the_verdict_when_it_should() -> None:
    """A heavy cluster's favourite edge must dominate a light cluster's."""
    matrices = {
        "heavy": {"DECIDE->PURCHASE": 1.8},
        "light": {"ARRIVE->BROWSE": 1.8},
    }
    tilted = build_population_funnel_elasticity(
        matrices, {"heavy": 9.0, "light": 1.0}
    )
    assert tilted is not None
    heavy_only = build_funnel_elasticity(
        build_cluster_matrix({"DECIDE->PURCHASE": 1.8})
    )
    assert (
        tilted["ranking"][0] == heavy_only["ranking"][0]
    ), "the 9:1 weighted mix should follow the heavy cluster"


def test_population_conversion_is_weighted_mean_of_cluster_conversions() -> None:
    matrices = {
        "a": {"DECIDE->PURCHASE": 1.5},
        "b": {"DECIDE->PURCHASE": 0.4},
    }
    weights = {"a": 3.0, "b": 1.0}
    payload = build_population_funnel_elasticity(matrices, weights)
    assert payload is not None

    conv_a = build_funnel_elasticity(build_cluster_matrix(matrices["a"]))[
        "conversion"
    ]["loop_adjusted"]
    conv_b = build_funnel_elasticity(build_cluster_matrix(matrices["b"]))[
        "conversion"
    ]["loop_adjusted"]
    expected = (3.0 * conv_a + 1.0 * conv_b) / 4.0
    assert payload["conversion"]["loop_adjusted"] == pytest.approx(
        expected, abs=1e-4
    )


def test_population_loop_uplift_is_normalised_by_total_weight() -> None:
    matrices = {
        "a": {"DECIDE->PURCHASE": 1.5},
        "b": {"CONSIDER->BROWSE": 1.8},
    }
    payload = build_population_funnel_elasticity(
        matrices,
        {"a": 3.0, "b": 1.0},
    )

    assert payload is not None
    conversion = payload["conversion"]
    expected_uplift_pp = (
        conversion["loop_adjusted"] - conversion["naive_product"]
    ) * 100.0
    assert conversion["loop_uplift_pp"] == pytest.approx(
        expected_uplift_pp,
        abs=0.0001,
    )


def test_population_loop_uplift_is_invariant_to_weight_scale() -> None:
    matrices = {
        "a": {"DECIDE->PURCHASE": 1.5},
        "b": {"CONSIDER->BROWSE": 1.8},
    }
    fractional = build_population_funnel_elasticity(
        matrices,
        {"a": 0.75, "b": 0.25},
    )
    whole = build_population_funnel_elasticity(
        matrices,
        {"a": 3.0, "b": 1.0},
    )

    assert fractional is not None
    assert whole is not None
    assert fractional["conversion"] == whole["conversion"]


def test_population_is_deterministic_and_bad_weights_sanitised() -> None:
    matrices = {"x": {"BROWSE->CONSIDER": 1.2}, "y": {}}
    bad_weights = {"x": float("nan"), "y": -3, "z": "junk"}
    first = build_population_funnel_elasticity(matrices, bad_weights)
    second = build_population_funnel_elasticity(matrices, bad_weights)
    assert first == second and first is not None
    # NaN/negative/junk weights were dropped → both clusters fall back to
    # equal weight, so y still appears with its own top edge.
    tops = {c["cluster_id"]: c["top_edge"] for c in first["per_cluster_top_edges"]}
    assert set(tops) == {"x", "y"}


def test_population_does_not_invent_weights_for_missing_clusters() -> None:
    matrices = {
        "kept": {"DECIDE->PURCHASE": 1.5},
        "missing": {"ARRIVE->BROWSE": 1.8},
    }
    payload = build_population_funnel_elasticity(matrices, {"kept": 3.0})

    assert payload is not None
    assert [
        cluster["cluster_id"] for cluster in payload["per_cluster_top_edges"]
    ] == ["kept"]
    expected = build_funnel_elasticity(
        build_cluster_matrix(matrices["kept"])
    )["conversion"]["loop_adjusted"]
    assert payload["conversion"]["loop_adjusted"] == pytest.approx(
        expected, abs=1e-6
    )
    assert payload["cluster_consensus"]
    assert payload["cluster_consensus"][0]["weighted_vote_share"] == 1.0


def test_population_uses_uniform_weights_when_matches_are_unusable() -> None:
    matrices = {"a": {}, "b": {"DECIDE->PURCHASE": 0.4}}
    payload = build_population_funnel_elasticity(matrices, {"unknown": 5.0})

    assert payload is not None
    assert {
        cluster["cluster_id"] for cluster in payload["per_cluster_top_edges"]
    } == {"a", "b"}
    conv_a = build_funnel_elasticity(build_cluster_matrix(matrices["a"]))[
        "conversion"
    ]["loop_adjusted"]
    conv_b = build_funnel_elasticity(build_cluster_matrix(matrices["b"]))[
        "conversion"
    ]["loop_adjusted"]
    assert payload["conversion"]["loop_adjusted"] == pytest.approx(
        (conv_a + conv_b) / 2.0, abs=1e-6
    )
