"""
Tests for the journey-analytics module and its Pydantic schema contract.

Covers matrix reconstruction, absorbing-chain metrics, most-probable-path
search, transition leverage, serialisation round-trips, aggregation edge
cases, and the endpoint response model.
"""
from __future__ import annotations

import math

import pytest

from app.schemas.journey_analytics import JourneyAnalyticsOut
from app.simulation.journey_analytics import (
    TOP_LEVERAGE,
    TOP_PATHS,
    build_cluster_matrix,
    build_journey_analytics,
    cluster_metrics,
    deserialise_per_cluster_matrices,
    serialise_per_cluster_matrices,
)
from app.simulation.markov import BASE_TRANSITIONS, State

OVERRIDES: dict[tuple[str, str], float] = {
    ("ARRIVE", "BROWSE"): 0.95,
    ("BROWSE", "CONSIDER"): 0.80,
    ("CONSIDER", "DECIDE"): 0.70,
    ("DECIDE", "PURCHASE"): 0.50,
}


def _state_index(state: str) -> int:
    from app.simulation.markov import STATE_INDEX

    return STATE_INDEX[state]


# ---------------------------------------------------------------------------
# Matrix reconstruction
# ---------------------------------------------------------------------------


def test_build_cluster_matrix_is_row_stochastic_and_preserves_base() -> None:
    matrix = build_cluster_matrix({})

    assert matrix.shape == (7, 7)
    assert matrix.sum(axis=1) == pytest.approx([1.0] * 7)
    assert matrix[_state_index("ARRIVE"), _state_index("BROWSE")] == pytest.approx(
        float(BASE_TRANSITIONS[State.ARRIVE][State.BROWSE])
    )
    assert matrix[_state_index("DECIDE"), _state_index("PURCHASE")] == pytest.approx(
        float(BASE_TRANSITIONS[State.DECIDE][State.PURCHASE])
    )


def test_build_cluster_matrix_marks_purchase_and_abandon_absorbing() -> None:
    matrix = build_cluster_matrix({})

    purchase = matrix[_state_index("PURCHASE")]
    abandon = matrix[_state_index("ABANDON")]
    assert purchase[_state_index("PURCHASE")] == pytest.approx(1.0)
    assert abandon[_state_index("ABANDON")] == pytest.approx(1.0)
    assert purchase.sum() == pytest.approx(1.0)
    assert abandon.sum() == pytest.approx(1.0)


def test_build_cluster_matrix_applies_multipliers_then_normalises() -> None:
    matrix = build_cluster_matrix({("ARRIVE", "BROWSE"): 0.95})

    # 0.87 * 0.95 = 0.8265, with 0.13 staying; row normalised.
    assert matrix[_state_index("ARRIVE"), _state_index("BROWSE")] == pytest.approx(
        0.8265 / 0.9565
    )
    assert matrix[_state_index("ARRIVE"), _state_index("ABANDON")] == pytest.approx(
        0.13 / 0.9565
    )
    assert matrix[_state_index("ARRIVE")].sum() == pytest.approx(1.0)


def test_build_cluster_matrix_ignores_invalid_and_absorbing_overrides() -> None:
    matrix = build_cluster_matrix(
        {
            ("UNKNOWN", "BROWSE"): 5.0,
            ("ARRIVE", "UNKNOWN"): 5.0,
            ("PURCHASE", "RETURN"): 5.0,
            ("ABANDON", "ARRIVE"): 5.0,
            ("ARRIVE", "BROWSE"): "not-a-number",
        }
    )
    assert matrix[_state_index("PURCHASE"), _state_index("PURCHASE")] == pytest.approx(1.0)
    assert matrix[_state_index("ABANDON"), _state_index("ABANDON")] == pytest.approx(1.0)
    assert matrix[_state_index("ARRIVE"), _state_index("BROWSE")] == pytest.approx(0.87)
    assert matrix.sum(axis=1) == pytest.approx([1.0] * 7)


# ---------------------------------------------------------------------------
# Absorbing-chain metrics
# ---------------------------------------------------------------------------


def test_cluster_metrics_matches_analytic_funnel() -> None:
    metrics = cluster_metrics(build_cluster_matrix(OVERRIDES))
    assert metrics is not None

    assert metrics["purchase_probability"] == pytest.approx(0.040245, abs=1e-5)
    assert metrics["abandon_probability"] == pytest.approx(0.959755, abs=1e-5)
    assert metrics["purchase_probability"] + metrics["abandon_probability"] == pytest.approx(
        1.0, abs=1e-5
    )
    assert metrics["expected_steps_to_absorb"] == pytest.approx(2.7798, abs=1e-3)
    assert metrics["expected_steps_to_absorb"] >= 1.0


def test_cluster_metrics_exit_distribution_sums_to_abandon_probability() -> None:
    metrics = cluster_metrics(build_cluster_matrix(OVERRIDES))
    assert metrics is not None

    distribution = metrics["exit_stage_distribution"]
    assert set(distribution) == {"ARRIVE", "BROWSE", "CONSIDER", "DECIDE"}
    assert sum(distribution.values()) == pytest.approx(
        metrics["abandon_probability"], abs=1e-5
    )
    assert distribution["BROWSE"] > distribution["ARRIVE"]


def test_stronger_purchase_override_raises_conversion() -> None:
    weak = cluster_metrics(build_cluster_matrix(OVERRIDES))
    strong = cluster_metrics(
        build_cluster_matrix({**OVERRIDES, ("DECIDE", "PURCHASE"): 0.90})
    )
    assert weak is not None and strong is not None
    assert strong["purchase_probability"] > weak["purchase_probability"]
    assert strong["expected_steps_to_absorb"] < weak["expected_steps_to_absorb"]


# ---------------------------------------------------------------------------
# Top paths + leverage
# ---------------------------------------------------------------------------


def test_most_probable_path_is_browse_then_abandon() -> None:
    payload = build_journey_analytics({"c0": OVERRIDES})

    assert payload["top_paths"][0]["path"] == ["ARRIVE", "BROWSE", "ABANDON"]
    assert payload["top_paths"][0]["probability"] == pytest.approx(0.374833, abs=1e-5)
    assert payload["top_paths"][0]["converted"] is False
    assert len(payload["top_paths"]) <= TOP_PATHS
    assert any(path["converted"] for path in payload["top_paths"])


def test_leverage_ranks_purchase_transition_first() -> None:
    payload = build_journey_analytics({"c0": OVERRIDES})

    best = payload["leverage_rankings"][0]
    assert best["from_state"] == "DECIDE"
    assert best["to_state"] == "PURCHASE"
    assert best["gain_per_5pp"] > 0.0
    assert best["relative_gain_pct"] > 0.0
    assert "Improving DECIDE" in best["description"]
    assert len(payload["leverage_rankings"]) <= TOP_LEVERAGE

    by_key = {
        (item["from_state"], item["to_state"]): item
        for item in payload["leverage_rankings"]
    }
    assert by_key[("DECIDE", "ABANDON")]["gain_per_5pp"] < 0.0
    # RETURN is unreachable before absorption, so it must not rank.
    assert not any(from_state == "RETURN" for from_state, _ in by_key)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def test_serialise_round_trip_preserves_all_clusters() -> None:
    raw = {"c0": OVERRIDES, "c1": {}, "c2": {("DECIDE", "PURCHASE"): 0.7}}
    serialised = serialise_per_cluster_matrices(raw)

    assert serialised["c0"]["ARRIVE->BROWSE"] == pytest.approx(0.95)
    assert serialised["c1"] == {}
    assert serialised["c2"] == {"DECIDE->PURCHASE": 0.7}

    restored = deserialise_per_cluster_matrices(serialised)
    assert set(restored) == {"c0", "c1", "c2"}
    assert restored["c0"] == OVERRIDES
    assert restored["c1"] == {}


def test_deserialise_skips_garbage() -> None:
    assert deserialise_per_cluster_matrices(None) == {}
    assert deserialise_per_cluster_matrices("nope") == {}
    assert deserialise_per_cluster_matrices({"c0": "junk"}) == {}
    restored = deserialise_per_cluster_matrices(
        {
            "c0": {
                "ARRIVE->BROWSE": 0.9,
                "NOPE->BROWSE": 1.0,
                "ARRIVE->NOPE": 1.0,
                "BROWSE->CONSIDER": "bad",
            }
        }
    )
    assert restored == {"c0": {("ARRIVE", "BROWSE"): 0.9}}


def test_serialise_drops_non_finite_invalid_and_non_numeric_values() -> None:
    raw = {
        "c0": {
            ("ARRIVE", "BROWSE"): 0.95,
            ("BROWSE", "CONSIDER"): float("nan"),
            ("CONSIDER", "DECIDE"): float("inf"),
            ("DECIDE", "PURCHASE"): "0.31",
            ("DECIDE", "NOPE"): 0.5,
            ("NOPE", "DECIDE"): 0.5,
        },
        "c1": {("ARRIVE", "BROWSE"): "not-a-number"},
        "c2": {("DECIDE", "PURCHASE"): -float("inf")},
    }

    serialised = serialise_per_cluster_matrices(raw)

    assert serialised == {
        "c0": {
            "ARRIVE->BROWSE": 0.95,
            "DECIDE->PURCHASE": 0.31,
        },
        "c1": {},
        "c2": {},
    }
    # The write path must never emit values the reader would reject.
    assert deserialise_per_cluster_matrices(serialised) == {
        "c0": {
            ("ARRIVE", "BROWSE"): 0.95,
            ("DECIDE", "PURCHASE"): 0.31,
        },
        "c1": {},
        "c2": {},
    }


def test_non_finite_overrides_never_poison_payload() -> None:
    payload = build_journey_analytics(
        {
            "c0": {
                ("ARRIVE", "BROWSE"): float("nan"),
                ("BROWSE", "CONSIDER"): float("inf"),
                ("CONSIDER", "DECIDE"): -float("inf"),
                ("DECIDE", "PURCHASE"): 0.50,
            },
            "c1": {},
        },
        {"c0": 0.6, "c1": 0.4},
    )

    assert math.isfinite(payload["purchase_probability"])
    assert math.isfinite(payload["abandon_probability"])
    assert math.isfinite(payload["expected_steps_to_absorb"])
    assert all(math.isfinite(p["probability"]) for p in payload["top_paths"])
    assert all(
        math.isfinite(item["gain_per_5pp"])
        for item in payload["leverage_rankings"]
    )
    assert payload["meta"]["matrix_count"] == 2


# ---------------------------------------------------------------------------
# Aggregation and edge cases
# ---------------------------------------------------------------------------


def test_weighted_aggregation_blends_cluster_metrics() -> None:
    payload = build_journey_analytics(
        {"c0": OVERRIDES, "c1": {}},
        {"c0": 0.6, "c1": 0.4},
    )

    # c0 = 0.040245, c1 (base matrix) = 0.091964 (pytest-computed earlier).
    assert payload["purchase_probability"] == pytest.approx(0.060933, abs=1e-5)
    assert payload["abandon_probability"] == pytest.approx(1.0 - 0.060933, abs=1e-5)
    assert sum(payload["exit_stage_distribution"].values()) == pytest.approx(
        payload["abandon_probability"], abs=1e-4
    )
    assert payload["top_paths"][0]["probability"] == pytest.approx(0.357140, abs=1e-5)
    assert payload["meta"]["matrix_count"] == 2
    assert payload["meta"]["weighted"] is True


def test_aggregation_ignores_zero_weight_clusters() -> None:
    payload = build_journey_analytics(
        {"c0": OVERRIDES, "c1": {}},
        {"c0": 1.0, "c1": 0.0},
    )

    assert payload["purchase_probability"] == pytest.approx(0.040245, abs=1e-5)
    assert [item["cluster_id"] for item in payload["per_cluster"]] == ["c0"]


def test_malformed_weights_fall_back_to_uniform() -> None:
    payload = build_journey_analytics(
        {"c0": OVERRIDES, "c1": {}},
        {"c0": float("inf"), "c1": float("nan")},
    )

    # Both weights sanitise to zero -> uniform aggregation, no NaN leakage.
    assert payload["purchase_probability"] == pytest.approx(
        (0.040245 + 0.091964) / 2.0, abs=1e-5
    )
    assert math.isfinite(payload["purchase_probability"])
    assert math.isfinite(payload["abandon_probability"])
    assert math.isfinite(payload["expected_steps_to_absorb"])
    assert all(math.isfinite(p["probability"]) for p in payload["top_paths"])


def test_negative_and_non_numeric_weights_are_clamped() -> None:
    payload = build_journey_analytics(
        {"c0": OVERRIDES, "c1": {}},
        {"c0": -5.0, "c1": "0.4", "c2": "not-a-number"},
    )

    # c0 clamps to zero; only c1 contributes.
    assert payload["purchase_probability"] == pytest.approx(0.091964, abs=1e-5)
    assert payload["purchase_probability"] >= 0.0
    assert [item["cluster_id"] for item in payload["per_cluster"]] == ["c1"]


def test_non_dict_cluster_weights_are_ignored() -> None:
    payload = build_journey_analytics({"c0": OVERRIDES, "c1": {}}, [0.6, 0.4])

    assert payload["meta"]["weighted"] is False
    assert payload["meta"]["matrix_count"] == 2
    assert payload["purchase_probability"] == pytest.approx(
        (0.040245 + 0.091964) / 2.0, abs=1e-5
    )


def test_no_weights_uses_uniform_aggregation() -> None:
    payload = build_journey_analytics({"c0": OVERRIDES})

    assert payload["meta"]["weighted"] is False
    assert payload["meta"]["matrix_count"] == 1
    assert payload["purchase_probability"] == pytest.approx(0.040245, abs=1e-5)
    assert payload["per_cluster"][0]["cluster_id"] == "c0"
    assert payload["per_cluster"][0]["primary_exit_stage"] == "BROWSE"


def test_per_cluster_exposes_stage_leaks_and_expected_visits() -> None:
    payload = build_journey_analytics({"c0": OVERRIDES})
    cluster = payload["per_cluster"][0]

    # The per-cluster detail mirrors the analytic per-cluster metrics exactly,
    # so founders can see where each segment leaks rather than one headline.
    metrics = cluster_metrics(build_cluster_matrix(OVERRIDES))
    assert metrics is not None
    assert cluster["exit_stage_distribution"] == metrics["exit_stage_distribution"]
    assert cluster["expected_visits_by_stage"] == metrics["visits_by_stage"]

    # Leak shares across stages sum to that cluster's abandon probability, and
    # every stage visit count is finite and non-negative (ARRIVE starts at 1).
    assert sum(cluster["exit_stage_distribution"].values()) == pytest.approx(
        1.0 - cluster["purchase_probability"],
        abs=1e-5,
    )
    assert cluster["expected_visits_by_stage"]["ARRIVE"] == pytest.approx(1.0)
    assert cluster["expected_visits_by_stage"]["RETURN"] == pytest.approx(0.0)
    assert all(v >= 0.0 for v in cluster["expected_visits_by_stage"].values())
    assert all(
        v >= 0.0 for v in cluster["exit_stage_distribution"].values()
    )


def test_empty_input_returns_safe_payload() -> None:
    payload = build_journey_analytics({})

    assert payload["purchase_probability"] == 0.0
    assert payload["abandon_probability"] == 0.0
    assert payload["top_paths"] == []
    assert payload["leverage_rankings"] == []
    assert payload["per_cluster"] == []
    assert payload["key_insights"] == []
    assert payload["meta"]["matrix_count"] == 0


def test_key_insights_are_actionable() -> None:
    payload = build_journey_analytics({"c0": OVERRIDES})

    joined = " ".join(payload["key_insights"])
    assert "largest single leak" in joined
    assert "most common journey" in joined
    assert "Highest-leverage fix" in joined
    assert "average" in joined


# ---------------------------------------------------------------------------
# Schema contract
# ---------------------------------------------------------------------------


def test_schema_validates_full_payload() -> None:
    payload = build_journey_analytics(
        {"c0": OVERRIDES, "c1": {}},
        {"c0": 0.6, "c1": 0.4},
    )
    out = JourneyAnalyticsOut(
        simulation_id=1,
        project_id=2,
        **payload,
    )

    assert out.simulation_id == 1
    assert out.project_id == 2
    assert out.purchase_probability == pytest.approx(0.060933, abs=1e-5)
    assert out.top_paths
    assert out.leverage_rankings
    assert out.per_cluster
    assert out.key_insights
    assert 0.0 <= out.purchase_probability <= 1.0
    assert all(0.0 <= p.probability <= 1.0 for p in out.top_paths)
    assert out.per_cluster[0].exit_stage_distribution
    assert out.per_cluster[0].expected_visits_by_stage["ARRIVE"] == pytest.approx(1.0)
