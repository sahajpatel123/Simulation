"""
Tests for the cross-simulation outcomes digest helper + schema +
route registration.

The aggregating logic is pure-Python so we can exercise it without
spinning up Postgres. The DB-touching route is smoke-tested via
the route-registration pattern (gated by scipy).
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# normalise_outlier_threshold
# ---------------------------------------------------------------------------


def test_normalise_outlier_threshold_default() -> None:
    from app.simulation.outcomes_digest import (
        DEFAULT_OUTLIER_THRESHOLD,
        normalise_outlier_threshold,
    )

    assert normalise_outlier_threshold(None) == DEFAULT_OUTLIER_THRESHOLD


def test_normalise_outlier_threshold_passthrough() -> None:
    from app.simulation.outcomes_digest import normalise_outlier_threshold

    assert normalise_outlier_threshold(0.05) == 0.05
    assert normalise_outlier_threshold(0.5) == 0.5


def test_normalise_outlier_threshold_clamps_low_and_high() -> None:
    from app.simulation.outcomes_digest import (
        MAX_OUTLIER_THRESHOLD,
        MIN_OUTLIER_THRESHOLD,
        normalise_outlier_threshold,
    )

    assert normalise_outlier_threshold(-0.5) == MIN_OUTLIER_THRESHOLD
    assert normalise_outlier_threshold(2.0) == MAX_OUTLIER_THRESHOLD


# ---------------------------------------------------------------------------
# aggregate_outcomes — empty / one-sided input
# ---------------------------------------------------------------------------


def test_aggregate_empty_input_returns_zero_summary() -> None:
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes([])
    assert out["mae"] == 0.0
    assert out["mape"] == 0.0
    assert out["rmse"] == 0.0
    assert out["mae_count"] == 0
    assert out["mape_count"] == 0
    assert out["outlier_count"] == 0
    assert out["direction_breakdown"] == {"over": 0, "under": 0, "exact": 0}
    assert out["per_pair"] == []
    assert out["simulation_count"] == 0
    assert out["with_predictions"] == 0


def test_aggregate_only_missing_predicted_excluded_from_metrics() -> None:
    """Pairs with a None predicted side are still counted in
    ``simulation_count`` so the UI can show "X of Y actionable", but
    must not bias MAE / MAPE / RMSE."""
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes([(None, 0.05)])
    assert out["with_predictions"] == 0
    assert out["mae_count"] == 0
    assert out["mae"] == 0.0
    assert out["simulation_count"] == 1
    assert out["per_pair"][0]["variance"] is None


def test_aggregate_only_missing_actual_excluded_from_metrics() -> None:
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes([(0.10, None)])
    assert out["with_predictions"] == 0
    assert out["simulation_count"] == 1


def test_aggregate_keeps_missing_pairs_in_per_pair_list() -> None:
    """The scatter plot still needs to render the empty rows so the
    UI shows "this sim has no prediction yet"."""
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes([
        (0.10, 0.08),
        (None, 0.05),
        (0.20, None),
    ])
    assert out["simulation_count"] == 3
    assert out["with_predictions"] == 1
    assert len(out["per_pair"]) == 3


# ---------------------------------------------------------------------------
# aggregate_outcomes — direction breakdown
# ---------------------------------------------------------------------------


def test_aggregate_perfect_prediction_is_exact() -> None:
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes([(0.10, 0.10), (0.05, 0.05)])
    assert out["direction_breakdown"]["exact"] == 2
    assert out["direction_breakdown"]["over"] == 0
    assert out["direction_breakdown"]["under"] == 0
    assert out["mae"] == 0.0
    assert out["rmse"] == 0.0


def test_aggregate_over_predicted_increments_over() -> None:
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes([
        (0.20, 0.10),  # over by 0.10
        (0.15, 0.10),  # over by 0.05
    ])
    assert out["direction_breakdown"]["over"] == 2
    assert out["direction_breakdown"]["under"] == 0
    assert out["direction_breakdown"]["exact"] == 0


def test_aggregate_under_predicted_increments_under() -> None:
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes([
        (0.05, 0.15),  # under by 0.10
    ])
    assert out["direction_breakdown"]["under"] == 1
    assert out["direction_breakdown"]["over"] == 0


def test_aggregate_mixed_directions_split_correctly() -> None:
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes([
        (0.20, 0.10),  # over
        (0.05, 0.10),  # under
        (0.10, 0.10),  # exact
    ])
    assert out["direction_breakdown"]["over"] == 1
    assert out["direction_breakdown"]["under"] == 1
    assert out["direction_breakdown"]["exact"] == 1


# ---------------------------------------------------------------------------
# aggregate_outcomes — error metrics
# ---------------------------------------------------------------------------


def test_aggregate_mae_averages_absolute_variance() -> None:
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes([
        (0.20, 0.10),  # variance 0.10
        (0.05, 0.10),  # variance -0.05
    ])
    # |0.10| + |-0.05| = 0.15 → MAE = 0.075
    assert out["mae"] == pytest.approx(0.075)
    assert out["mae_count"] == 2


def test_aggregate_rmse_penalises_outliers() -> None:
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes([
        (0.10, 0.10),  # 0
        (0.20, 0.10),  # 0.10
    ])
    # sqrt((0 + 0.01)/2) = sqrt(0.005) ≈ 0.0707
    assert out["rmse"] == pytest.approx((0.005) ** 0.5)


def test_aggregate_mape_excludes_zero_actual() -> None:
    """If actual == 0, MAPE would be infinite. We must skip those
    pairs so the aggregate stays meaningful."""
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes([
        (0.10, 0.00),  # actual=0 → skip from MAPE
        (0.10, 0.05),  # |0.05/0.05| = 1.0 → contribute
    ])
    assert out["mape"] == pytest.approx(1.0)
    assert out["mape_count"] == 1


def test_aggregate_mape_matches_expected() -> None:
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes([
        (0.12, 0.10),  # 0.02/0.10 = 0.20
        (0.18, 0.20),  # 0.02/0.20 = 0.10
    ])
    assert out["mape"] == pytest.approx(0.15)


# ---------------------------------------------------------------------------
# aggregate_outcomes — outlier threshold
# ---------------------------------------------------------------------------


def test_aggregate_outlier_threshold_default_is_10pp() -> None:
    from app.simulation.outcomes_digest import (
        DEFAULT_OUTLIER_THRESHOLD,
        aggregate_outcomes,
    )

    out = aggregate_outcomes([
        (0.15, 0.10),  # 0.05 — NOT outlier at default 0.10
        (0.30, 0.10),  # 0.20 — IS outlier at default 0.10
    ])
    assert out["outlier_count"] == 1
    assert out["per_pair"][0]["is_outlier"] is False
    assert out["per_pair"][1]["is_outlier"] is True
    # Pin the default so a silent change of the constant breaks the test.
    assert DEFAULT_OUTLIER_THRESHOLD == pytest.approx(0.10)


def test_aggregate_outlier_threshold_custom() -> None:
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes(
        [(0.15, 0.10), (0.30, 0.10)],
        outlier_threshold=0.01,
    )
    # At 0.01, both pairs are outliers.
    assert out["outlier_count"] == 2


def test_aggregate_outlier_threshold_helper_clamps() -> None:
    """``aggregate_outcomes`` itself clamps the threshold so the
    caller-supplied value can never widen the outlier definition
    to the entire data range (or flip the sign)."""
    from app.simulation.outcomes_digest import (
        MAX_OUTLIER_THRESHOLD,
        MIN_OUTLIER_THRESHOLD,
        aggregate_outcomes,
    )

    # Above-range gets capped — outlier_count stays 0 (no |variance|
    # exceeds the max of 1.0 in our test data).
    out = aggregate_outcomes([(0.15, 0.10)], outlier_threshold=10.0)
    assert out["outlier_count"] == 0
    # Below-range gets floored to 0 — |0.05| > 0 is True → outlier.
    out2 = aggregate_outcomes(
        [(0.15, 0.10)], outlier_threshold=-10.0
    )
    assert out2["outlier_count"] == 1
    # Sanity: constants match the [0.0, 1.0] contract.
    assert MIN_OUTLIER_THRESHOLD == 0.0
    assert MAX_OUTLIER_THRESHOLD == 1.0


# ---------------------------------------------------------------------------
# aggregate_outcomes — defensive coercion
# ---------------------------------------------------------------------------


def test_aggregate_coerces_string_numbers() -> None:
    from app.simulation.outcomes_digest import aggregate_outcomes

    # Predicted is stored as a string by some legacy paths — must
    # still count as a prediction.
    out = aggregate_outcomes([("0.12", 0.10)])
    assert out["with_predictions"] == 1
    assert out["mae_count"] == 1


def test_aggregate_skips_non_numeric_strings() -> None:
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes([("NaN", 0.10), (0.10, "abc")])
    # Neither pair has both sides numeric → both excluded.
    assert out["with_predictions"] == 0
    assert out["simulation_count"] == 2


def test_aggregate_rejects_nan_and_inf() -> None:
    """``float('NaN')`` and ``float('inf')`` parse as numbers but
    corrupt every aggregate (NaN propagates, inf → outliers always).
    Both must be rejected so a single bad row can't poison the
    cross-simulation rollup."""
    import math

    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes([
        (math.nan, 0.10),
        (math.inf, 0.10),
        (0.10, -math.inf),
        (0.10, math.nan),
        (0.10, 0.10),  # one good row for sanity
    ])
    assert out["with_predictions"] == 1
    assert out["mae"] == pytest.approx(0.0)
    assert out["simulation_count"] == 5


def test_aggregate_rejects_booleans() -> None:
    """``True`` would coerce to 1.0 and silently make a misconfigured
    submit look like a 100% predicted conversion."""
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes([(True, 0.10), (False, 0.10)])
    assert out["with_predictions"] == 0
    assert out["simulation_count"] == 2


def test_aggregate_skips_none_pairs_silently() -> None:
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes([(None, None), (0.10, 0.10)])
    assert out["with_predictions"] == 1
    assert out["simulation_count"] == 2


def test_aggregate_per_pair_carries_all_fields() -> None:
    """The scatter plot needs every field per row, including the
    is_outlier flag."""
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes([(0.20, 0.10)], outlier_threshold=0.05)
    row = out["per_pair"][0]
    assert row["predicted"] == pytest.approx(0.20)
    assert row["actual"] == pytest.approx(0.10)
    assert row["variance"] == pytest.approx(0.10)
    assert row["is_outlier"] is True


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    """Pin the module's ``__all__`` so a future rename surfaces as an
    import error rather than a silent attribute miss in the route."""
    from app.simulation import outcomes_digest

    assert set(outcomes_digest.__all__) == {
        "DEFAULT_OUTLIER_THRESHOLD",
        "MIN_OUTLIER_THRESHOLD",
        "MAX_OUTLIER_THRESHOLD",
        "WELL_CALIBRATED_MAX_MAE",
        "NEEDS_ATTENTION_MAX_MAE",
        "LABEL_INSUFFICIENT_DATA",
        "LABEL_WELL_CALIBRATED",
        "LABEL_NEEDS_ATTENTION",
        "LABEL_POORLY_CALIBRATED",
        "VALID_CONFIDENCE_LABELS",
        "aggregate_outcomes",
        "normalise_outlier_threshold",
    }


# ---------------------------------------------------------------------------
# sim_ids linkage
# ---------------------------------------------------------------------------


def test_aggregate_per_pair_carries_sim_id_when_provided() -> None:
    """When the route supplies sim_ids, every per_pair row must
    carry the matching sim_id so the UI can drill from a scatter
    point back to the source simulation."""
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes(
        [(0.20, 0.10), (0.05, 0.10)],
        sim_ids=[101, 202],
    )
    assert out["per_pair"][0]["sim_id"] == 101
    assert out["per_pair"][1]["sim_id"] == 202


def test_aggregate_per_pair_sim_id_is_none_when_not_provided() -> None:
    """Back-compat: callers that don't supply sim_ids still get a
    valid payload, with ``sim_id`` echoed as ``None``."""
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes([(0.10, 0.10)])
    assert out["per_pair"][0]["sim_id"] is None
    assert out["worst_offender_sim_id"] is None


def test_aggregate_per_pair_sim_id_none_slot_is_preserved() -> None:
    """A ``None`` in the sim_ids list maps to ``None`` on the row —
    it does NOT pick up the adjacent row's id."""
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes(
        [(0.20, 0.10), (0.05, 0.10)],
        sim_ids=[101, None],
    )
    assert out["per_pair"][0]["sim_id"] == 101
    assert out["per_pair"][1]["sim_id"] is None


def test_aggregate_worst_offender_is_highest_abs_variance() -> None:
    from app.simulation.outcomes_digest import aggregate_outcomes

    # Sim 202 has the largest |variance| (0.15).
    out = aggregate_outcomes(
        [(0.10, 0.05), (0.20, 0.05), (0.10, 0.15)],
        sim_ids=[101, 202, 303],
    )
    assert out["worst_offender_sim_id"] == 202


def test_aggregate_worst_offender_ignores_missing_pairs() -> None:
    """A pair without actionable data must not become the worst
    offender — only actionable rows compete."""
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes(
        [(None, None), (0.10, 0.05), (0.20, 0.10)],
        sim_ids=[101, 202, 303],
    )
    # Sim 303 has |variance|=0.10, sim 202 has |variance|=0.05.
    assert out["worst_offender_sim_id"] == 303


def test_aggregate_worst_offender_none_when_all_missing() -> None:
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes(
        [(None, None), (None, None)],
        sim_ids=[101, 202],
    )
    assert out["worst_offender_sim_id"] is None
    assert out["confidence_label"] == "INSUFFICIENT_DATA"


def test_aggregate_worst_offender_none_when_sim_id_missing() -> None:
    """Even when pairs have actionable data, a ``None`` sim_id
    disqualifies the row from worst-offender — we can't link the
    error back to a sim, so we don't claim to."""
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes(
        [(0.20, 0.10)],
        sim_ids=[None],
    )
    assert out["worst_offender_sim_id"] is None


def test_aggregate_worst_offender_stable_on_ties() -> None:
    """On equal |variance|, the first encountered sim wins so the
    UI doesn't bounce between ties on every recompute."""
    from app.simulation.outcomes_digest import aggregate_outcomes

    out = aggregate_outcomes(
        [(0.10, 0.00), (0.20, 0.10)],
        sim_ids=[101, 202],
    )
    # Both |variance| == 0.10 — first wins.
    assert out["worst_offender_sim_id"] == 101


def test_aggregate_sim_ids_length_mismatch_raises() -> None:
    """Programming error — the caller passed a misaligned mapping.
    Raise loud rather than silently dropping pairs."""
    from app.simulation.outcomes_digest import aggregate_outcomes

    with pytest.raises(ValueError, match="sim_ids length"):
        aggregate_outcomes(
            [(0.10, 0.10), (0.20, 0.10)],
            sim_ids=[101],
        )


# ---------------------------------------------------------------------------
# confidence_label
# ---------------------------------------------------------------------------


def test_confidence_label_well_calibrated_for_small_mae() -> None:
    from app.simulation.outcomes_digest import (
        LABEL_WELL_CALIBRATED,
        WELL_CALIBRATED_MAX_MAE,
        aggregate_outcomes,
    )

    # MAE = 0.01 → below the 2pp threshold.
    out = aggregate_outcomes(
        [(0.10, 0.11), (0.10, 0.09)],
    )
    assert out["mae"] < WELL_CALIBRATED_MAX_MAE
    assert out["confidence_label"] == LABEL_WELL_CALIBRATED


def test_confidence_label_needs_attention_for_moderate_mae() -> None:
    from app.simulation.outcomes_digest import (
        LABEL_NEEDS_ATTENTION,
        NEEDS_ATTENTION_MAX_MAE,
        WELL_CALIBRATED_MAX_MAE,
        aggregate_outcomes,
    )

    # MAE = 0.035 → between 2pp and 5pp.
    out = aggregate_outcomes(
        [(0.135, 0.10), (0.065, 0.10)],
    )
    assert WELL_CALIBRATED_MAX_MAE <= out["mae"] < NEEDS_ATTENTION_MAX_MAE
    assert out["confidence_label"] == LABEL_NEEDS_ATTENTION


def test_confidence_label_poorly_calibrated_for_large_mae() -> None:
    from app.simulation.outcomes_digest import (
        LABEL_POORLY_CALIBRATED,
        NEEDS_ATTENTION_MAX_MAE,
        aggregate_outcomes,
    )

    # MAE = 0.10 → ≥ 5pp.
    out = aggregate_outcomes(
        [(0.20, 0.10), (0.00, 0.10)],
    )
    assert out["mae"] >= NEEDS_ATTENTION_MAX_MAE
    assert out["confidence_label"] == LABEL_POORLY_CALIBRATED


def test_confidence_label_boundary_at_2pp_is_needs_attention() -> None:
    """Inclusive lower bound on the NEEDS_ATTENTION bucket — MAE
    exactly equal to 2pp is not 'well calibrated'."""
    from app.simulation.outcomes_digest import (
        LABEL_NEEDS_ATTENTION,
        WELL_CALIBRATED_MAX_MAE,
        aggregate_outcomes,
    )

    out = aggregate_outcomes([(WELL_CALIBRATED_MAX_MAE, 0.0)])
    assert out["confidence_label"] == LABEL_NEEDS_ATTENTION


def test_confidence_label_insufficient_data_for_no_pairs() -> None:
    from app.simulation.outcomes_digest import (
        LABEL_INSUFFICIENT_DATA,
        aggregate_outcomes,
    )

    out = aggregate_outcomes(
        [(None, None), (None, 0.10)],
    )
    # No actionable rows → MAE is meaningless → flag it.
    assert out["mae_count"] == 0
    assert out["confidence_label"] == LABEL_INSUFFICIENT_DATA


def test_confidence_label_allowlist_is_stable() -> None:
    """Pin the public label enum so a rename breaks here rather
    than silently at the dashboard."""
    from app.simulation.outcomes_digest import VALID_CONFIDENCE_LABELS

    assert set(VALID_CONFIDENCE_LABELS) == {
        "INSUFFICIENT_DATA",
        "WELL_CALIBRATED",
        "NEEDS_ATTENTION",
        "POORLY_CALIBRATED",
    }


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_outcomes_digest_out_default_shape() -> None:
    from app.schemas.simulation import OutcomesDigestOut

    out = OutcomesDigestOut()
    assert out.mae == 0.0
    assert out.mape == 0.0
    assert out.rmse == 0.0
    assert out.mae_count == 0
    assert out.mape_count == 0
    assert out.outlier_count == 0
    assert out.direction_breakdown == {"over": 0, "under": 0, "exact": 0}
    assert out.per_pair == []
    assert out.simulation_count == 0
    assert out.with_predictions == 0
    assert out.worst_offender_sim_id is None
    assert out.confidence_label == "INSUFFICIENT_DATA"


def test_outcomes_digest_out_round_trips_aggregate_payload() -> None:
    """The route layer must be able to wrap ``aggregate_outcomes(...)``
    output directly into the Pydantic schema without coercion errors."""
    from app.schemas.simulation import OutcomesDigestOut
    from app.simulation.outcomes_digest import aggregate_outcomes

    payload = aggregate_outcomes([
        (0.20, 0.10),
        (0.05, 0.10),
    ])
    out = OutcomesDigestOut(**payload)
    assert out.mae == pytest.approx(0.075)
    assert out.direction_breakdown["over"] == 1
    assert out.direction_breakdown["under"] == 1
    assert out.with_predictions == 2


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_aggregate_outcomes_route_registered() -> None:
    """GET /simulations/aggregate/outcomes must appear in the router."""
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy"
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import simulations as sim_mod

    paths = {r.path for r in sim_mod.router.routes}
    assert "/simulations/aggregate/outcomes" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert "GET" in methods_by_path["/simulations/aggregate/outcomes"]


def test_aggregate_outcomes_route_query_params() -> None:
    """Pin the query-param surface so the UI contract is documented."""
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy"
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import simulations as sim_mod

    for r in sim_mod.router.routes:
        if (
            r.path == "/simulations/aggregate/outcomes"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "ids" in query_param_names
            assert "outlier_threshold" in query_param_names
            return
    raise AssertionError(
        "GET /simulations/aggregate/outcomes route not found"
    )
