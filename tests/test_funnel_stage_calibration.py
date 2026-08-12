"""Tests for the pure stage-level funnel calibration helpers.

Layer 6 turns per-stage predicted-vs-actual drop-off evidence into
pass-through correction scalars that the Conductor multiplies into future
Markov transitions. These tests pin the direction of learning (actual beat
the model → scalar > 1), the sample/effective-sample gates, the clamp
bounds, and the malformed-input guards so a single bad outcome can never
distort the funnel.
"""

from __future__ import annotations

import math

from app.simulation.funnel_stage_calibration import (
    MAX_CORRECTION_SCALAR,
    MIN_CORRECTION_SCALAR,
    MIN_SAMPLE_COUNT,
    STAGE_TRANSITIONS,
    compute_stage_corrections,
    corrected_forward_probability,
    stage_corrections_to_scalar_map,
    stage_to_transition,
    transition_corrections,
)


def _pair(
    predicted: dict[str, float | None],
    actual: dict[str, float | None],
    weight: float = 2.0,
) -> dict:
    return {
        "predicted_drop_rates": predicted,
        "actual_drops": actual,
        "learning_weight": weight,
    }


def _default_predicted() -> dict[str, float]:
    return {"BROWSE": 0.30, "CONSIDER": 0.40, "DECIDE": 0.50}


def _default_actual() -> dict[str, float]:
    return {"BROWSE": 0.20, "CONSIDER": 0.40, "DECIDE": 0.50}


def test_stage_mapping_covers_all_reported_stages() -> None:
    assert tuple(STAGE_TRANSITIONS) == ("BROWSE", "CONSIDER", "DECIDE")
    assert stage_to_transition("browse") == ("BROWSE", "CONSIDER")
    assert stage_to_transition("CONSIDER") == ("CONSIDER", "DECIDE")
    assert stage_to_transition("DECIDE") == ("DECIDE", "PURCHASE")
    assert stage_to_transition("ARRIVE") is None
    assert stage_to_transition(None) is None


def test_below_sample_gate_produces_no_corrections() -> None:
    pairs = [
        _pair(_default_predicted(), _default_actual()),
        _pair(_default_predicted(), _default_actual()),
    ]
    corrections = compute_stage_corrections(pairs, product_type="saas")
    assert corrections == []


def test_below_effective_sample_gate_produces_no_corrections() -> None:
    pairs = [
        _pair(_default_predicted(), _default_actual(), weight=1.0),
        _pair(_default_predicted(), _default_actual(), weight=1.0),
        _pair(_default_predicted(), _default_actual(), weight=0.1),
    ]
    corrections = compute_stage_corrections(pairs, product_type="saas")
    assert corrections == []


def test_actual_beat_model_learns_scalar_above_one() -> None:
    # Model predicted 30% browse drop; founders only saw 10% → pass-through
    # is 0.90 vs 0.70 → scalar ≈ 1.286.
    pairs = [
        _pair(
            {"BROWSE": 0.30, "CONSIDER": 0.40, "DECIDE": 0.50},
            {"BROWSE": 0.10, "CONSIDER": 0.40, "DECIDE": 0.50},
        )
        for _ in range(MIN_SAMPLE_COUNT)
    ]
    corrections = compute_stage_corrections(pairs, product_type="saas")
    browse = next(c for c in corrections if c["stage"] == "BROWSE")
    assert browse["correction_scalar"] > 1.0
    assert browse["correction_scalar"] == round(0.90 / 0.70, 6)
    assert browse["product_type"] == "saas"
    assert browse["from_state"] == "BROWSE"
    assert browse["to_state"] == "CONSIDER"
    assert browse["sample_count"] == MIN_SAMPLE_COUNT
    assert browse["effective_sample_count"] == MIN_SAMPLE_COUNT * 2.0
    assert browse["mean_bias"] == _rounded(-0.20)


def test_model_under_predicted_drop_learns_scalar_below_one() -> None:
    pairs = [
        _pair(
            {"BROWSE": 0.30, "CONSIDER": 0.40, "DECIDE": 0.50},
            {"BROWSE": 0.60, "CONSIDER": 0.40, "DECIDE": 0.50},
        )
        for _ in range(MIN_SAMPLE_COUNT)
    ]
    corrections = compute_stage_corrections(pairs, product_type="saas")
    browse = next(c for c in corrections if c["stage"] == "BROWSE")
    assert browse["correction_scalar"] < 1.0
    assert browse["mean_bias"] == _rounded(0.30)


def test_scalars_clamped_to_safe_bounds() -> None:
    extreme_actual = _default_actual()
    extreme_actual["BROWSE"] = 1.0  # pass-through 0.0 → scalar would be 0
    extreme_predicted = _default_predicted()
    extreme_predicted["BROWSE"] = 0.99  # tiny pass-through → huge ratio
    pairs = [
        _pair(extreme_predicted, extreme_actual),
        _pair(extreme_predicted, extreme_actual),
        _pair(extreme_predicted, extreme_actual),
    ]
    corrections = compute_stage_corrections(pairs, product_type="saas")
    browse = next(c for c in corrections if c["stage"] == "BROWSE")
    assert browse["correction_scalar"] == MIN_CORRECTION_SCALAR

    pairs_under = [
        _pair(
            {"BROWSE": 0.60, "CONSIDER": 0.40, "DECIDE": 0.50},
            {"BROWSE": 0.0, "CONSIDER": 0.40, "DECIDE": 0.50},
        )
        for _ in range(MIN_SAMPLE_COUNT)
    ]
    corrections_under = compute_stage_corrections(
        pairs_under, product_type="saas"
    )
    browse_under = next(
        c for c in corrections_under if c["stage"] == "BROWSE"
    )
    assert browse_under["correction_scalar"] == MAX_CORRECTION_SCALAR


def test_unusable_pairs_are_skipped() -> None:
    pairs = [
        _pair(
            {"BROWSE": 1.0, "CONSIDER": 0.40, "DECIDE": 0.50},
            {"BROWSE": 0.20, "CONSIDER": 0.40, "DECIDE": 0.50},
        ),
        _pair(
            {"BROWSE": 1.0, "CONSIDER": 0.40, "DECIDE": 0.50},
            {"BROWSE": 0.20, "CONSIDER": 0.40, "DECIDE": 0.50},
        ),
        _pair(
            {"BROWSE": 0.30, "CONSIDER": 0.40, "DECIDE": 0.50},
            {"BROWSE": None, "CONSIDER": 0.40, "DECIDE": 0.50},
        ),
        _pair(
            {"BROWSE": 0.30, "CONSIDER": 0.40, "DECIDE": 0.50},
            {"BROWSE": 0.20, "CONSIDER": 0.40, "DECIDE": 0.50},
        ),
        _pair(
            {"BROWSE": 0.30, "CONSIDER": 0.40, "DECIDE": 0.50},
            {"BROWSE": 0.20, "CONSIDER": 0.40, "DECIDE": 0.50},
        ),
        _pair(
            {"BROWSE": 0.30, "CONSIDER": 0.40, "DECIDE": 0.50},
            {"BROWSE": 0.20, "CONSIDER": 0.40, "DECIDE": 0.50},
        ),
    ]
    corrections = compute_stage_corrections(pairs, product_type="saas")
    browse = next(c for c in corrections if c["stage"] == "BROWSE")
    # Only the three usable BROWSE pairs count (two malformed are skipped).
    assert browse["sample_count"] == 3
    # CONSIDER/DECIDE rows are usable in all six pairs.
    consider = next(c for c in corrections if c["stage"] == "CONSIDER")
    assert consider["sample_count"] == 6


def test_confidence_curve_matches_other_calibration_layers() -> None:
    pairs = [
        _pair(_default_predicted(), _default_actual(), weight=5.0)
        for _ in range(MIN_SAMPLE_COUNT)
    ]
    corrections = compute_stage_corrections(pairs, product_type="saas")
    for correction in corrections:
        eff = correction["effective_sample_count"]
        assert correction["confidence_weight"] == round(eff / (eff + 30.0), 6)
        assert 0.0 <= correction["confidence_weight"] <= 1.0


def test_learning_weight_is_ignored_when_malformed() -> None:
    pairs = [
        _pair(
            _default_predicted(),
            _default_actual(),
            weight=float("nan"),
        )
        for _ in range(MIN_SAMPLE_COUNT)
    ]
    corrections = compute_stage_corrections(pairs, product_type="saas")
    assert corrections == []
    # A negative weight also cannot inflate effective evidence.
    pairs_negative = [
        _pair(_default_predicted(), _default_actual(), weight=-5.0)
        for _ in range(MIN_SAMPLE_COUNT)
    ]
    assert compute_stage_corrections(
        pairs_negative, product_type="saas"
    ) == []


def test_transition_corrections_skips_malformed_entries() -> None:
    assert transition_corrections(
        {
            "CONSIDER": 0.8,
            "DECIDE": 1.0,
            "ARRIVE": 9.9,
            "BROWSE": 10.0,  # out-of-range value is clamped
        }
    ) == {
        ("BROWSE", "CONSIDER"): MAX_CORRECTION_SCALAR,
        ("CONSIDER", "DECIDE"): 0.8,
        ("DECIDE", "PURCHASE"): 1.0,
    }
    assert transition_corrections(None) == {}
    assert transition_corrections(
        {"BROWSE": float("nan"), "CONSIDER": None}
    ) == {}


def test_stage_corrections_to_scalar_map_filters_by_confidence() -> None:
    rows = [
        {"stage": "BROWSE", "correction_scalar": 1.1, "confidence_weight": 0.1},
        {"stage": "BROWSE", "correction_scalar": 1.3, "confidence_weight": 0.9},
        {"stage": "CONSIDER", "correction_scalar": 0.7, "confidence_weight": 0.5},
        {"stage": "NOPE", "correction_scalar": 1.1, "confidence_weight": 0.9},
        {"stage": "DECIDE", "correction_scalar": float("nan"), "confidence_weight": 0.9},
    ]
    result = stage_corrections_to_scalar_map(rows)
    # Highest-confidence BROWSE row wins; low-confidence row is ignored.
    assert result == {"BROWSE": 1.3, "CONSIDER": 0.7}
    assert stage_corrections_to_scalar_map(None) == {}


def test_corrected_forward_probability_guards_and_bounds() -> None:
    assert corrected_forward_probability(0.5, 1.2) == 0.6
    assert corrected_forward_probability(0.999, 2.0) == 0.999
    assert corrected_forward_probability(0.001, 0.1) == 0.001
    assert corrected_forward_probability(0.5, float("nan")) == 0.5
    assert corrected_forward_probability(0.5, None) == 0.5  # type: ignore[arg-type]
    assert math.isfinite(corrected_forward_probability(0.5, 1.0))


def _rounded(value: float) -> float:
    """Tiny helper so the module stays import-light for the main assertion."""
    return round(value, 6)
