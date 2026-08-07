"""Unit tests for app.simulation.funnel_calibration.

Pure-helper tests — no DB, no Redis, no Celery. They verify that the
founder-facing funnel calibration digest correctly maps simulated stage
drop-off against actual founder-reported drop-off.
"""
from __future__ import annotations

from app.simulation.funnel_calibration import (
    STAGES,
    build_funnel_calibration_digest,
    predicted_drop_rates_from_results,
)


def _results(stage_metrics: list[dict]) -> dict:
    return {"stage_metrics": stage_metrics}


def _aggregated_results(stage_aggregations: list[dict]) -> dict:
    return {"stage_aggregations": stage_aggregations}


def test_predicted_drop_rates_from_stage_metrics():
    rates = predicted_drop_rates_from_results(
        _results(
            [
                {"state": "BROWSE", "drop_off_rate": 0.42},
                {"state": "CONSIDER", "drop_off_rate": 0.38},
                {"state": "DECIDE", "drop_off_rate": 0.61},
            ]
        )
    )
    assert rates == {
        "BROWSE": 0.42,
        "CONSIDER": 0.38,
        "DECIDE": 0.61,
    }


def test_predicted_drop_rates_from_aggregated_shape():
    rates = predicted_drop_rates_from_results(
        _aggregated_results(
            [
                {"state": "BROWSE", "mean_drop_off_rate": 0.43},
                {"state": "DECIDE", "mean_drop_off_rate": 0.59},
            ]
        )
    )
    assert rates["BROWSE"] == 0.43
    assert rates["CONSIDER"] is None
    assert rates["DECIDE"] == 0.59


def test_empty_results_yields_none_rates():
    rates = predicted_drop_rates_from_results({})
    assert rates == {stage: None for stage in STAGES}


def test_digest_surfaces_primary_mismatch_and_narrative():
    pairs = [
        (
            _results(
                [
                    {"state": "BROWSE", "drop_off_rate": 0.40},
                    {"state": "CONSIDER", "drop_off_rate": 0.38},
                    {"state": "DECIDE", "drop_off_rate": 0.60},
                ]
            ),
            {"BROWSE": 0.45, "CONSIDER": 0.38, "DECIDE": 0.62},
        ),
        (
            _results(
                [
                    {"state": "BROWSE", "drop_off_rate": 0.41},
                    {"state": "CONSIDER", "drop_off_rate": 0.39},
                    {"state": "DECIDE", "drop_off_rate": 0.61},
                ]
            ),
            {"BROWSE": 0.46, "CONSIDER": 0.39, "DECIDE": 0.61},
        ),
    ]
    payload = build_funnel_calibration_digest(pairs)

    assert payload["outcome_count"] == 2
    assert payload["usable_count"] == 6
    assert payload["primary_mismatch_stage"] == "BROWSE"
    assert payload["primary_mismatch"]["domain"] == "ONBOARDING"
    assert payload["primary_mismatch"]["recommended_architects"]
    assert payload["funnel_bias"]["direction"] == "UNDER_PREDICTING_DROP"
    assert "browse" in payload["narrative"]
    assert any(
        signal["label"] == "primary_mismatch_stage"
        for signal in payload["key_signals"]
    )

    by_stage = {s["stage"]: s for s in payload["stages"]}
    assert by_stage["BROWSE"]["predicted_drop_off_rate"] == 0.405
    assert by_stage["BROWSE"]["actual_drop_off_rate"] == 0.455
    assert by_stage["BROWSE"]["mean_abs_gap"] == 0.05
    assert by_stage["CONSIDER"]["mean_abs_gap"] == 0.0


def test_digest_handles_empty_and_partial_inputs():
    empty = build_funnel_calibration_digest([])
    assert empty["outcome_count"] == 0
    assert empty["usable_count"] == 0
    assert empty["primary_mismatch_stage"] is None
    assert empty["funnel_bias"]["direction"] == "INSUFFICIENT_DATA"
    assert "No founder outcomes" in empty["narrative"]

    partial = build_funnel_calibration_digest(
        [
            (
                _results(
                    [
                        {"state": "BROWSE", "drop_off_rate": 0.40},
                    ]
                ),
                {"BROWSE": 0.44, "CONSIDER": 0.30},
            )
        ]
    )
    assert partial["usable_count"] == 1
    assert partial["primary_mismatch_stage"] == "BROWSE"
    assert partial["stages"][1]["sample_count"] == 0


def test_digest_treats_missing_sim_results_as_unusable():
    payload = build_funnel_calibration_digest(
        [(None, {"BROWSE": 0.5, "CONSIDER": 0.5, "DECIDE": 0.5})]
    )
    assert payload["outcome_count"] == 1
    assert payload["usable_count"] == 0
    assert payload["primary_mismatch_stage"] is None


def test_digest_no_primary_mismatch_when_stages_match():
    payload = build_funnel_calibration_digest(
        [
            (
                _results(
                    [
                        {"state": "BROWSE", "drop_off_rate": 0.40},
                        {"state": "CONSIDER", "drop_off_rate": 0.38},
                        {"state": "DECIDE", "drop_off_rate": 0.60},
                    ]
                ),
                {"BROWSE": 0.40, "CONSIDER": 0.38, "DECIDE": 0.60},
            )
        ]
    )
    assert payload["usable_count"] == 3
    assert payload["primary_mismatch_stage"] is None
    assert payload["primary_mismatch"] is None
    assert "No per-stage prediction gap" in payload["narrative"]
    assert not any(
        signal["label"] == "primary_mismatch_stage"
        for signal in payload["key_signals"]
    )
    by_stage = {s["stage"]: s for s in payload["stages"]}
    assert by_stage["BROWSE"]["severity"] == "ok"


def test_digest_primary_mismatch_signal_severity_tracks_gap():
    payload = build_funnel_calibration_digest(
        [
            (
                _results([{"state": "BROWSE", "drop_off_rate": 0.40}]),
                {"BROWSE": 0.41},
            )
        ]
    )
    signal = next(
        s for s in payload["key_signals"]
        if s["label"] == "primary_mismatch_stage"
    )
    assert signal["severity"] == "ok"
