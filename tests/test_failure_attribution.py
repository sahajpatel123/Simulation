"""Tests for the pure failure-attribution digest builder."""

from __future__ import annotations

import pytest

from app.simulation.failure_attribution import (
    ABS_VARIANCE_CRITICAL_PP,
    ABS_VARIANCE_WATCH_PP,
    MAX_REASONS,
    SIGNAL_CRITICAL,
    SIGNAL_OK,
    SIGNAL_WATCH,
    build_failure_attribution,
)


def _row(**overrides):
    row = {
        "id": 1,
        "simulation_id": 7,
        "project_id": 10,
        "days_since_launch": 30,
        "actual_conversion_rate": 0.03,
        "primary_failure_reason": "PRICING",
        "product_changed_since_sim": False,
        "pricing_changed": True,
        "target_market_changed": False,
        "data_confidence": "ESTIMATED",
        "signal_quality_at_run": 0.6,
        "learning_weight": 0.36,
        "results_json": {"population_weighted_conversion": 0.04},
    }
    row.update(overrides)
    return row


def test_empty_rows_returns_no_data_payload() -> None:
    payload = build_failure_attribution([], project_id=10)

    assert payload["project_id"] == 10
    assert payload["total_outcomes"] == 0
    assert payload["attributed_count"] == 0
    assert payload["unattributed_count"] == 0
    assert payload["top_reason"] is None
    assert payload["reasons"] == []
    assert "No founder outcomes recorded" in payload["narrative"]
    assert payload["key_signals"][0]["severity"] == SIGNAL_WATCH


def test_groups_reasons_case_insensitively_and_computes_shares() -> None:
    rows = [
        _row(primary_failure_reason="pricing", actual_conversion_rate=0.03),
        _row(primary_failure_reason="PRICING ", actual_conversion_rate=0.04),
        _row(primary_failure_reason="Onboarding", actual_conversion_rate=0.05),
    ]

    payload = build_failure_attribution(rows, project_id=10)

    assert payload["total_outcomes"] == 3
    assert payload["attributed_count"] == 3
    assert payload["unattributed_count"] == 0
    assert payload["top_reason"] == "pricing"
    assert [r["reason"] for r in payload["reasons"]] == [
        "pricing",
        "Onboarding",
    ]
    assert payload["reasons"][0]["count"] == 2
    assert payload["reasons"][0]["share_pct"] == pytest.approx(66.67)
    assert payload["reasons"][1]["count"] == 1
    assert payload["reasons"][1]["share_pct"] == pytest.approx(33.33)


def test_computes_prediction_error_per_reason() -> None:
    rows = [
        _row(primary_failure_reason="PRICING", actual_conversion_rate=0.01),
        _row(primary_failure_reason="PRICING", actual_conversion_rate=0.03),
        _row(primary_failure_reason="ONBOARDING", actual_conversion_rate=0.04),
    ]

    payload = build_failure_attribution(rows, project_id=10)
    by_reason = {r["reason"]: r for r in payload["reasons"]}

    pricing = by_reason["PRICING"]
    assert pricing["avg_abs_variance_pp"] == pytest.approx(2.0)
    # signed variance: (-3pp + -1pp) / 2
    assert pricing["avg_signed_variance_pp"] == pytest.approx(-2.0)

    onboarding = by_reason["ONBOARDING"]
    assert onboarding["avg_abs_variance_pp"] == pytest.approx(0.0)
    assert onboarding["avg_signed_variance_pp"] == pytest.approx(0.0)


def test_unattributed_outcomes_are_counted_separately() -> None:
    rows = [
        _row(primary_failure_reason="PRICING"),
        _row(primary_failure_reason=None),
        _row(primary_failure_reason="   "),
        {"id": 4, "project_id": 10},  # malformed-ish but counted
    ]

    payload = build_failure_attribution(rows, project_id=10)

    assert payload["total_outcomes"] == 4
    assert payload["attributed_count"] == 1
    assert payload["unattributed_count"] == 3
    assert payload["top_reason"] == "PRICING"


def test_sorts_by_count_desc_then_reason_ascending() -> None:
    rows = [
        _row(primary_failure_reason="B"),
        _row(primary_failure_reason="A"),
        _row(primary_failure_reason="A"),
        _row(primary_failure_reason="C"),
    ]

    reasons = [r["reason"] for r in build_failure_attribution(
        rows, project_id=10
    )["reasons"]]

    assert reasons == ["A", "B", "C"]


def test_reason_list_is_capped() -> None:
    rows = [
        _row(primary_failure_reason=f"REASON {i}")
        for i in range(MAX_REASONS + 5)
    ]

    payload = build_failure_attribution(rows, project_id=10)

    assert len(payload["reasons"]) == MAX_REASONS
    assert payload["attributed_count"] == MAX_REASONS + 5


def test_severity_buckets_follow_abs_variance_thresholds() -> None:
    rows = [
        _row(
            primary_failure_reason="TIGHT",
            actual_conversion_rate=0.0405,
            results_json={"population_weighted_conversion": 0.04},
        ),
        _row(
            primary_failure_reason="WATCH",
            actual_conversion_rate=0.07,
            results_json={"population_weighted_conversion": 0.04},
        ),
        _row(
            primary_failure_reason="BROKEN",
            actual_conversion_rate=0.10,
            results_json={"population_weighted_conversion": 0.04},
        ),
    ]

    payload = build_failure_attribution(rows, project_id=10)
    by_reason = {r["reason"]: r for r in payload["reasons"]}

    assert by_reason["TIGHT"]["severity"] == SIGNAL_OK
    assert by_reason["WATCH"]["severity"] == SIGNAL_WATCH
    assert by_reason["BROKEN"]["severity"] == SIGNAL_CRITICAL


def test_malformed_rows_do_not_crash_builder() -> None:
    rows = [
        "not-a-dict",
        None,
        123,
        _row(
            primary_failure_reason=None,
            actual_conversion_rate="NaN",
            results_json={"bad": "shape"},
        ),
        _row(
            primary_failure_reason="OK",
            actual_conversion_rate="0.03",
            days_since_launch="n/a",
            learning_weight="bad",
        ),
    ]

    payload = build_failure_attribution(rows, project_id=10)

    assert payload["total_outcomes"] == 5
    assert payload["attributed_count"] == 1
    # The valid-but-string-typed row is usable, so the rollup has data.
    assert payload["reasons"][0]["avg_abs_variance_pp"] == pytest.approx(1.0)
    assert payload["reasons"][0]["avg_days_since_launch"] is None
    assert payload["reasons"][0]["avg_learning_weight"] is None


def test_data_confidence_and_change_flags_rollup() -> None:
    rows = [
        _row(
            primary_failure_reason="PRICING",
            data_confidence="EXACT",
            product_changed_since_sim=True,
            pricing_changed=True,
        ),
        _row(
            primary_failure_reason="PRICING",
            data_confidence="ESTIMATED",
            pricing_changed=False,
            target_market_changed=True,
        ),
    ]

    reason = build_failure_attribution(rows, project_id=10)["reasons"][0]

    assert reason["data_confidence_breakdown"] == {
        "EXACT": 1,
        "ESTIMATED": 1,
    }
    assert reason["product_changed_count"] == 1
    assert reason["pricing_changed_count"] == 1
    assert reason["target_market_changed_count"] == 1


def test_string_change_flags_are_parsed_explicitly() -> None:
    rows = [
        _row(
            primary_failure_reason="PRICING",
            product_changed_since_sim="true",
            pricing_changed="false",
        ),
    ]

    reason = build_failure_attribution(rows, project_id=10)["reasons"][0]

    assert reason["product_changed_count"] == 1
    assert reason["pricing_changed_count"] == 0


def test_narrative_includes_top_reason_and_prediction_error() -> None:
    rows = [
        _row(primary_failure_reason="PRICING", actual_conversion_rate=0.01),
        _row(primary_failure_reason="PRICING", actual_conversion_rate=0.02),
    ]

    narrative = build_failure_attribution(rows, project_id=10)["narrative"]

    assert "2 recorded outcome(s)" in narrative
    assert "2 included a failure reason" in narrative
    assert "Most common: PRICING (100.0% of attributed outcomes)" in narrative
    assert "missed by 2.5pp on average" in narrative


def test_threshold_constants_are_sane() -> None:
    assert ABS_VARIANCE_WATCH_PP < ABS_VARIANCE_CRITICAL_PP
    assert MAX_REASONS > 0
