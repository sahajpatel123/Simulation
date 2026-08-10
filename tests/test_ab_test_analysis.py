"""Pure-engine tests for the A/B experiment analysis module."""
from __future__ import annotations

import math

import pytest

from app.simulation.ab_test_analysis import (
    MIN_TOTAL_VISITORS,
    MIN_VISITORS_PER_VARIANT,
    VALID_VERDICTS,
    VERDICT_INCONCLUSIVE,
    VERDICT_INSUFFICIENT_DATA,
    VERDICT_SIGNIFICANT,
    VERDICT_TRENDING,
    analyze_ab_test,
)


def _strong_arms() -> tuple[dict, dict]:
    return (
        {"label": "Control", "visitors": 1000, "conversions": 100},
        {"label": "New", "visitors": 1000, "conversions": 160},
    )


def test_strong_winner_is_significant() -> None:
    a, b = _strong_arms()
    out = analyze_ab_test(a, b)
    assert out["verdict"] == VERDICT_SIGNIFICANT
    assert out["significant"] is True
    assert out["winner"] == "New"
    assert out["p_value"] is not None and out["p_value"] < 0.05
    assert out["absolute_uplift"] == pytest.approx(0.06, abs=1e-6)
    assert out["relative_uplift_pct"] == pytest.approx(60.0, abs=1e-4)
    assert out["confidence_level"] == pytest.approx(0.95)


def test_equal_rates_are_inconclusive() -> None:
    out = analyze_ab_test(
        {"label": "A", "visitors": 500, "conversions": 50},
        {"label": "B", "visitors": 500, "conversions": 50},
    )
    assert out["verdict"] == VERDICT_INCONCLUSIVE
    assert out["significant"] is False
    assert out["winner"] is None
    assert out["absolute_uplift"] == 0.0
    assert out["p_value"] == pytest.approx(1.0, abs=1e-6)


def test_moderate_gap_is_trending() -> None:
    out = analyze_ab_test(
        {"label": "Old", "visitors": 200, "conversions": 20},
        {"label": "New", "visitors": 200, "conversions": 30},
    )
    assert out["verdict"] == VERDICT_TRENDING
    assert out["significant"] is False
    assert out["winner"] == "New"
    assert out["p_value"] is not None
    assert 0.05 <= out["p_value"] < 0.20


def test_tiny_samples_are_insufficient() -> None:
    out = analyze_ab_test(
        {"label": "A", "visitors": 5, "conversions": 1},
        {"label": "B", "visitors": 6, "conversions": 2},
    )
    assert out["verdict"] == VERDICT_INSUFFICIENT_DATA
    assert out["significant"] is False
    assert out["p_value"] is None
    assert out["z_score"] is None
    assert out["confidence_interval"]["low"] is None
    assert out["confidence_interval"]["high"] is None
    assert str(MIN_TOTAL_VISITORS) in out["narrative"]


def test_zero_conversions_on_both_arms_are_not_significant() -> None:
    out = analyze_ab_test(
        {"label": "A", "visitors": 300, "conversions": 0},
        {"label": "B", "visitors": 300, "conversions": 0},
    )
    assert out["verdict"] == VERDICT_INCONCLUSIVE
    assert out["significant"] is False
    assert out["absolute_uplift"] == 0.0
    assert out["recommendations"]


def test_conversions_above_visitors_are_insufficient() -> None:
    out = analyze_ab_test(
        {"label": "A", "visitors": 10, "conversions": 20},
        {"label": "B", "visitors": 10, "conversions": 2},
    )
    assert out["verdict"] == VERDICT_INSUFFICIENT_DATA
    assert out["meta"]["malformed_input"] is True
    assert "unusable" in out["narrative"]


def test_non_finite_counts_are_insufficient() -> None:
    out = analyze_ab_test(
        {"label": "A", "visitors": float("nan"), "conversions": 1},
        {"label": "B", "visitors": 10, "conversions": 2},
    )
    assert out["verdict"] == VERDICT_INSUFFICIENT_DATA
    assert out["meta"]["malformed_input"] is True

    out_inf = analyze_ab_test(
        {"label": "A", "visitors": 10, "conversions": 1},
        {"label": "B", "visitors": float("inf"), "conversions": 2},
    )
    assert out_inf["verdict"] == VERDICT_INSUFFICIENT_DATA


def test_bool_and_string_counts_are_rejected() -> None:
    out = analyze_ab_test(
        {"label": "A", "visitors": True, "conversions": 1},
        {"label": "B", "visitors": 10, "conversions": 2},
    )
    assert out["verdict"] == VERDICT_INSUFFICIENT_DATA

    out_str = analyze_ab_test(
        {"label": "A", "visitors": "10.5", "conversions": 1},
        {"label": "B", "visitors": 10, "conversions": 2},
    )
    assert out_str["verdict"] == VERDICT_INSUFFICIENT_DATA


def test_relative_uplift_is_none_when_control_rate_is_zero() -> None:
    out = analyze_ab_test(
        {"label": "A", "visitors": 500, "conversions": 0},
        {"label": "B", "visitors": 500, "conversions": 10},
    )
    assert out["absolute_uplift"] == pytest.approx(0.02, abs=1e-6)
    assert out["relative_uplift_pct"] is None


def test_confidence_interval_bounds_are_sane() -> None:
    a, b = _strong_arms()
    out = analyze_ab_test(a, b)
    low = out["confidence_interval"]["low"]
    high = out["confidence_interval"]["high"]
    assert low is not None and high is not None
    assert math.isfinite(low) and math.isfinite(high)
    assert low <= high
    assert low <= out["absolute_uplift"] <= high


def test_sample_size_for_observed_uplift_is_positive() -> None:
    a, b = _strong_arms()
    out = analyze_ab_test(a, b)
    assert out["visitors_needed_for_observed_uplift"] is not None
    assert out["visitors_needed_for_observed_uplift"] > 0


def test_sample_size_for_mde_is_reported_when_no_uplift() -> None:
    out = analyze_ab_test(
        {"label": "A", "visitors": 500, "conversions": 50},
        {"label": "B", "visitors": 500, "conversions": 50},
    )
    assert out["visitors_needed_for_observed_uplift"] is None
    assert out["visitors_needed_for_mde"] is not None
    assert out["visitors_needed_for_mde"] > 0


def test_custom_mde_flows_into_meta_and_recommendation() -> None:
    out = analyze_ab_test(
        {"label": "A", "visitors": 500, "conversions": 50},
        {"label": "B", "visitors": 500, "conversions": 50},
        mde=0.05,
    )
    assert out["meta"]["mde"] == pytest.approx(0.05)
    assert any("5.0%" in r for r in out["recommendations"])


@pytest.mark.parametrize(
    ("alpha", "power", "mde"),
    [
        (0.0, 0.8, 0.02),
        (1.0, 0.8, 0.02),
        (0.05, 0.0, 0.02),
        (0.05, 1.0, 0.02),
        (0.05, 0.8, 0.0),
        (0.05, 0.8, 0.6),
        (float("nan"), 0.8, 0.02),
        (0.05, 0.8, float("inf")),
    ],
)
def test_invalid_statistical_parameters_raise(
    alpha: float,
    power: float,
    mde: float,
) -> None:
    with pytest.raises(ValueError):
        analyze_ab_test(
            {"label": "A", "visitors": 100, "conversions": 10},
            {"label": "B", "visitors": 100, "conversions": 12},
            alpha=alpha,
            power=power,
            mde=mde,
        )


def test_labels_are_bounded_and_defaulted() -> None:
    long_label = "x" * 500
    out = analyze_ab_test(
        {"visitors": 1000, "conversions": 100},
        {"label": long_label, "visitors": 1000, "conversions": 160},
    )
    assert out["variant_a"]["label"] == "Control"
    assert out["variant_b"]["label"] == "x" * 80
    assert len(out["variant_b"]["label"]) <= 80


def test_output_is_deterministic() -> None:
    a, b = _strong_arms()
    first = analyze_ab_test(a, b)
    second = analyze_ab_test(a, b)
    assert first == second


def test_key_signals_use_valid_severities() -> None:
    a, b = _strong_arms()
    out = analyze_ab_test(a, b)
    severities = {s["severity"] for s in out["key_signals"]}
    assert severities <= {"ok", "watch", "critical"}


def test_pooled_rate_matches_hand_calculation() -> None:
    a, b = _strong_arms()
    out = analyze_ab_test(a, b)
    assert out["pooled_conversion_rate"] == pytest.approx(
        (100 + 160) / 2000, abs=1e-6
    )


def test_verdict_is_always_from_the_contract() -> None:
    cases = [
        (
            {"label": "A", "visitors": 1000, "conversions": 100},
            {"label": "B", "visitors": 1000, "conversions": 160},
        ),
        (
            {"label": "A", "visitors": 200, "conversions": 20},
            {"label": "B", "visitors": 200, "conversions": 30},
        ),
        (
            {"label": "A", "visitors": 500, "conversions": 50},
            {"label": "B", "visitors": 500, "conversions": 50},
        ),
        (
            {"label": "A", "visitors": 5, "conversions": 1},
            {"label": "B", "visitors": 6, "conversions": 2},
        ),
    ]
    for a, b in cases:
        out = analyze_ab_test(a, b)
        assert out["verdict"] in VALID_VERDICTS


def test_min_visitor_thresholds_are_documented_in_meta() -> None:
    out = analyze_ab_test(
        {"label": "A", "visitors": 100, "conversions": 10},
        {"label": "B", "visitors": 100, "conversions": 12},
    )
    assert out["meta"]["min_total_visitors"] == MIN_TOTAL_VISITORS
    assert out["meta"]["min_visitors_per_variant"] == MIN_VISITORS_PER_VARIANT


def test_missing_variant_objects_are_handled() -> None:
    out = analyze_ab_test(
        None,
        {"label": "B", "visitors": 100, "conversions": 12},
    )
    assert out["verdict"] == VERDICT_INSUFFICIENT_DATA
    assert out["meta"]["malformed_input"] is True


def _sample_size_flag(out: dict) -> dict:
    return next(s for s in out["key_signals"] if s["label"] == "sample_size_sufficient")


def test_sample_size_flag_is_true_for_significant_verdicts() -> None:
    out = analyze_ab_test(
        {"label": "A", "visitors": 1000, "conversions": 100},
        {"label": "B", "visitors": 1000, "conversions": 160},
    )
    assert out["verdict"] == VERDICT_SIGNIFICANT
    assert _sample_size_flag(out)["value"] is True


def test_sample_size_flag_uses_observed_uplift_for_trending_verdicts() -> None:
    out = analyze_ab_test(
        {"label": "A", "visitors": 5000, "conversions": 500},
        {"label": "B", "visitors": 5000, "conversions": 560},
    )
    assert out["verdict"] == VERDICT_TRENDING
    needed_observed = out["visitors_needed_for_observed_uplift"]
    assert needed_observed is not None and needed_observed > 5000
    assert _sample_size_flag(out)["value"] is False


def test_sample_size_flag_uses_mde_for_inconclusive_verdicts() -> None:
    out = analyze_ab_test(
        {"label": "A", "visitors": 10000, "conversions": 1000},
        {"label": "B", "visitors": 10000, "conversions": 1010},
    )
    assert out["verdict"] == VERDICT_INCONCLUSIVE
    assert out["visitors_needed_for_mde"] <= 10000
    assert _sample_size_flag(out)["value"] is True


def test_p_value_signal_severity_honours_configured_alpha() -> None:
    arms = (
        {"label": "A", "visitors": 1000, "conversions": 100},
        {"label": "B", "visitors": 1000, "conversions": 128},
    )

    out_strict = analyze_ab_test(*arms, alpha=0.01)
    assert out_strict["verdict"] == VERDICT_TRENDING
    p_signal = next(
        s for s in out_strict["key_signals"] if s["label"] == "p_value"
    )
    assert p_signal["severity"] == "watch"

    out_lenient = analyze_ab_test(*arms, alpha=0.10)
    assert out_lenient["verdict"] == VERDICT_SIGNIFICANT
    p_signal = next(
        s for s in out_lenient["key_signals"] if s["label"] == "p_value"
    )
    assert p_signal["severity"] == "ok"


def test_duplicate_labels_are_disambiguated() -> None:
    out = analyze_ab_test(
        {"label": "Landing", "visitors": 1000, "conversions": 100},
        {"label": "Landing", "visitors": 1000, "conversions": 160},
    )
    assert out["variant_a"]["label"] == "Landing (arm A)"
    assert out["variant_b"]["label"] == "Landing (arm B)"
    assert out["winner"] == "Landing (arm B)"

    long_label = "x" * 80
    out_long = analyze_ab_test(
        {"label": long_label, "visitors": 1000, "conversions": 100},
        {"label": long_label, "visitors": 1000, "conversions": 160},
    )
    assert out_long["variant_a"]["label"] != out_long["variant_b"]["label"]
    assert len(out_long["variant_a"]["label"]) <= 80
    assert len(out_long["variant_b"]["label"]) <= 80


def test_inconclusive_guidance_reports_observed_uplift_cost() -> None:
    out = analyze_ab_test(
        {"label": "A", "visitors": 10000, "conversions": 1000},
        {"label": "B", "visitors": 10000, "conversions": 1010},
    )
    assert out["verdict"] == VERDICT_INCONCLUSIVE
    needed_observed = out["visitors_needed_for_observed_uplift"]
    assert needed_observed is not None and needed_observed > 10000
    assert any(
        str(needed_observed) in r and "per arm would be needed" in r
        for r in out["recommendations"]
    )


def test_no_sample_size_guidance_from_full_conversion_baseline() -> None:
    out = analyze_ab_test(
        {"label": "A", "visitors": 20, "conversions": 20},
        {"label": "B", "visitors": 20, "conversions": 0},
    )
    assert out["verdict"] == VERDICT_SIGNIFICANT
    assert out["visitors_needed_for_mde"] == 0
    assert not any("plan for roughly" in r for r in out["recommendations"])


def test_malformed_summary_never_shows_impossible_counts() -> None:
    out = analyze_ab_test(
        {"label": "A", "visitors": 10, "conversions": 20},
        {"label": "B", "visitors": 10, "conversions": 2},
    )
    assert out["verdict"] == VERDICT_INSUFFICIENT_DATA
    assert out["variant_a"]["conversions"] <= out["variant_a"]["visitors"]
    assert out["variant_b"]["conversions"] <= out["variant_b"]["visitors"]
