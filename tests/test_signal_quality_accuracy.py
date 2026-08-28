"""Accuracy-by-signal-quality digest and route tests."""
from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest

from app.schemas.signal_quality_accuracy import SignalQualityAccuracyOut
from app.simulation.signal_quality_accuracy import (
    VERDICT_ALIGNED,
    VERDICT_FLAT,
    VERDICT_INSUFFICIENT,
    VERDICT_INVERTED,
    build_signal_quality_accuracy,
)

if "razorpay" not in sys.modules:
    razorpay_stub = types.ModuleType("razorpay")
    razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = razorpay_stub


def _row(predicted: Any, actual: Any, quality: Any) -> dict[str, Any]:
    return {
        "predicted_conversion": predicted,
        "actual_conversion": actual,
        "signal_quality_at_run": quality,
    }


def _bucket(payload: dict[str, Any], tier: str) -> dict[str, Any]:
    return next(bucket for bucket in payload["buckets"] if bucket["tier"] == tier)


def test_empty_history_returns_canonical_insufficient_payload() -> None:
    payload = build_signal_quality_accuracy(
        [], user_id=42, generated_at="2026-08-29T00:00:00+00:00"
    )

    assert payload["user_id"] == 42
    assert payload["generated_at"] == "2026-08-29T00:00:00+00:00"
    assert payload["total_outcomes"] == 0
    assert payload["discarded_rows"] == 0
    assert payload["populated_tier_count"] == 0
    assert payload["verdict"] == VERDICT_INSUFFICIENT
    assert payload["comparison_from_tier"] is None
    assert payload["absolute_error_improvement"] is None
    assert [bucket["tier"] for bucket in payload["buckets"]] == [
        "QUARANTINED",
        "PARTIAL",
        "FULL",
    ]
    assert all(bucket["outcome_count"] == 0 for bucket in payload["buckets"])
    assert payload["recommendations"]


def test_aligned_history_reports_error_reduction() -> None:
    payload = build_signal_quality_accuracy(
        [
            _row(0.20, 0.10, 0.10),
            _row(0.18, 0.10, 0.24),
            _row(0.12, 0.10, 0.50),
            _row(0.10, 0.10, 0.90),
        ],
        user_id=1,
    )

    assert payload["verdict"] == VERDICT_ALIGNED
    assert payload["comparison_from_tier"] == "QUARANTINED"
    assert payload["comparison_to_tier"] == "FULL"
    assert payload["absolute_error_improvement"] == pytest.approx(0.08)
    assert payload["relative_error_reduction"] == pytest.approx(0.888889)
    assert payload["total_outcomes"] == 4
    assert payload["populated_tier_count"] == 2

    low = _bucket(payload, "QUARANTINED")
    assert low["mean_absolute_error"] == pytest.approx(0.09)
    assert low["root_mean_square_error"] == pytest.approx(0.090554)
    assert low["mean_signed_error"] == pytest.approx(0.09)
    assert low["overprediction_count"] == 2

    full = _bucket(payload, "FULL")
    assert full["mean_absolute_error"] == pytest.approx(0.01)
    assert full["overprediction_count"] == 1
    assert full["exact_count"] == 1
    assert "fell" in payload["narrative"]


def test_inverted_history_warns_when_high_quality_is_less_accurate() -> None:
    payload = build_signal_quality_accuracy(
        [
            _row(0.11, 0.10, 0.10),
            _row(0.09, 0.10, 0.20),
            _row(0.20, 0.10, 0.70),
            _row(0.18, 0.10, 0.80),
        ],
        user_id=1,
    )

    assert payload["verdict"] == VERDICT_INVERTED
    assert payload["absolute_error_improvement"] == pytest.approx(-0.08)
    assert payload["relative_error_reduction"] == pytest.approx(-8.0)
    assert "rose" in payload["narrative"]
    assert any("product changes" in item for item in payload["recommendations"])


def test_sub_half_point_difference_is_flat() -> None:
    payload = build_signal_quality_accuracy(
        [
            _row(0.120, 0.10, 0.30),
            _row(0.118, 0.10, 0.40),
            _row(0.116, 0.10, 0.60),
            _row(0.114, 0.10, 0.90),
        ],
        user_id=1,
    )

    assert payload["verdict"] == VERDICT_FLAT
    assert payload["comparison_from_tier"] == "PARTIAL"
    assert payload["comparison_to_tier"] == "FULL"
    assert payload["absolute_error_improvement"] == pytest.approx(0.004)


def test_single_observation_tiers_do_not_claim_a_direction() -> None:
    payload = build_signal_quality_accuracy(
        [
            _row(0.30, 0.10, 0.10),
            _row(0.10, 0.10, 0.90),
        ],
        user_id=1,
    )

    assert payload["total_outcomes"] == 2
    assert payload["populated_tier_count"] == 2
    assert payload["verdict"] == VERDICT_INSUFFICIENT
    assert payload["absolute_error_improvement"] is None


@pytest.mark.parametrize(
    "bad_row",
    [
        _row(None, 0.1, 0.5),
        _row(0.1, "nope", 0.5),
        _row(0.1, 0.1, float("nan")),
        _row(True, 0.1, 0.5),
        _row(1.1, 0.1, 0.5),
        _row(0.1, -0.1, 0.5),
    ],
)
def test_malformed_rows_are_discarded(bad_row: dict[str, Any]) -> None:
    payload = build_signal_quality_accuracy([bad_row], user_id=1)
    assert payload["total_outcomes"] == 0
    assert payload["discarded_rows"] == 1
    assert payload["verdict"] == VERDICT_INSUFFICIENT


def test_object_rows_and_quality_boundaries_use_canonical_tiers() -> None:
    payload = build_signal_quality_accuracy(
        [
            SimpleNamespace(
                predicted_conversion=0.1,
                actual_conversion=0.1,
                signal_quality_at_run=0.249999,
            ),
            SimpleNamespace(
                predicted_conversion=0.1,
                actual_conversion=0.1,
                signal_quality_at_run=0.25,
            ),
            SimpleNamespace(
                predicted_conversion=0.1,
                actual_conversion=0.1,
                signal_quality_at_run=0.50,
            ),
        ],
        user_id=1,
    )
    assert _bucket(payload, "QUARANTINED")["outcome_count"] == 1
    assert _bucket(payload, "PARTIAL")["outcome_count"] == 1
    assert _bucket(payload, "FULL")["outcome_count"] == 1


def test_builder_payload_validates_against_response_schema() -> None:
    parsed = SignalQualityAccuracyOut.model_validate(
        build_signal_quality_accuracy(
            [
                _row(0.20, 0.10, 0.10),
                _row(0.18, 0.10, 0.20),
                _row(0.11, 0.10, 0.60),
                _row(0.10, 0.10, 0.80),
            ],
            user_id=9,
        )
    )
    assert parsed.user_id == 9
    assert parsed.verdict == VERDICT_ALIGNED
    assert len(parsed.buckets) == 3


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.params: dict[str, Any] | None = None

    def execute(self, statement: Any, params: dict[str, Any]) -> _FakeResult:
        self.params = params
        return _FakeResult(self.rows)


def test_route_scopes_query_to_current_user() -> None:
    from app.api.v1.calibration import get_my_signal_quality_accuracy

    session = _FakeSession(
        [
            _row(0.20, 0.10, 0.10),
            _row(0.18, 0.10, 0.20),
            _row(0.11, 0.10, 0.60),
            _row(0.10, 0.10, 0.80),
        ]
    )
    output = get_my_signal_quality_accuracy(
        db=session,  # type: ignore[arg-type]
        current_user=SimpleNamespace(id=77),  # type: ignore[arg-type]
    )

    assert session.params == {"uid": 77}
    assert output.user_id == 77
    assert output.verdict == VERDICT_ALIGNED


def test_router_registers_authenticated_signal_quality_endpoint() -> None:
    from app.api.v1.calibration import router

    route = next(
        route
        for route in router.routes
        if getattr(route, "path", "") == "/calibration/my-signal-quality-accuracy"
    )
    assert route.response_model is SignalQualityAccuracyOut
    assert route.methods == {"GET"}
