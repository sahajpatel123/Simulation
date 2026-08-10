"""Route-level tests for ``POST /api/v1/experiments/ab-analysis``."""
from __future__ import annotations

import sys
import types

import pytest
from pydantic import ValidationError

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.api.v1.experiments import analyze_ab_test
from app.schemas.ab_test import (
    AbTestAnalysisIn,
    AbTestAnalysisOut,
    AbTestVariantIn,
)


def _default_payload(**overrides) -> AbTestAnalysisIn:
    data = {
        "variant_a": {
            "label": "Control",
            "visitors": 1000,
            "conversions": 100,
        },
        "variant_b": {
            "label": "New",
            "visitors": 1000,
            "conversions": 160,
        },
    }
    data.update(overrides)
    return AbTestAnalysisIn(**data)


def _call_route(
    payload: AbTestAnalysisIn | None = None,
    *,
    current_user_id: int = 42,
) -> AbTestAnalysisOut:
    return analyze_ab_test(
        payload=payload or _default_payload(),
        current_user=type("U", (), {"id": current_user_id})(),
    )


def test_route_returns_significant_analysis_payload() -> None:
    out = _call_route()
    assert isinstance(out, AbTestAnalysisOut)
    assert out.verdict == "SIGNIFICANT"
    assert out.significant is True
    assert out.winner == "New"
    assert out.variant_a.conversion_rate == pytest.approx(0.10, abs=1e-6)
    assert out.variant_b.conversion_rate == pytest.approx(0.16, abs=1e-6)
    assert out.recommendations
    assert out.key_signals


def test_route_honours_custom_statistical_parameters() -> None:
    payload = _default_payload(
        alpha=0.01,
        power=0.9,
        minimum_detectable_effect=0.03,
    )
    out = _call_route(payload)
    assert out.meta["alpha"] == pytest.approx(0.01)
    assert out.meta["power"] == pytest.approx(0.9)
    assert out.meta["mde"] == pytest.approx(0.03)
    assert out.confidence_level == pytest.approx(0.99)


def test_route_returns_insufficient_data_for_small_sample() -> None:
    payload = _default_payload(
        variant_a={"label": "A", "visitors": 5, "conversions": 1},
        variant_b={"label": "B", "visitors": 6, "conversions": 2},
    )
    out = _call_route(payload)
    assert out.verdict == "INSUFFICIENT_DATA"
    assert out.significant is False
    assert out.p_value is None
    assert out.z_score is None


def test_route_returns_inconclusive_for_equal_arms() -> None:
    payload = _default_payload(
        variant_a={"label": "A", "visitors": 500, "conversions": 50},
        variant_b={"label": "B", "visitors": 500, "conversions": 50},
    )
    out = _call_route(payload)
    assert out.verdict == "INCONCLUSIVE"
    assert out.winner is None
    assert out.absolute_uplift == 0.0


def test_route_returns_trending_for_moderate_gap() -> None:
    payload = _default_payload(
        variant_a={"label": "A", "visitors": 200, "conversions": 20},
        variant_b={"label": "B", "visitors": 200, "conversions": 30},
    )
    out = _call_route(payload)
    assert out.verdict == "TRENDING"
    assert out.winner == "B"
    assert out.p_value is not None
    assert 0.05 <= out.p_value < 0.20


def test_schema_rejects_conversions_above_visitors() -> None:
    with pytest.raises(ValidationError):
        AbTestVariantIn(label="A", visitors=10, conversions=20)

    with pytest.raises(ValidationError):
        _default_payload(
            variant_a={"label": "A", "visitors": 10, "conversions": 20},
            variant_b={"label": "B", "visitors": 10, "conversions": 2},
        )


def test_schema_rejects_negative_and_zero_visitors() -> None:
    with pytest.raises(ValidationError):
        AbTestVariantIn(label="A", visitors=-1, conversions=0)
    with pytest.raises(ValidationError):
        AbTestVariantIn(label="A", visitors=0, conversions=0)


def test_schema_rejects_non_finite_statistical_parameters() -> None:
    with pytest.raises(ValidationError):
        _default_payload(alpha=float("nan"))
    with pytest.raises(ValidationError):
        _default_payload(power=float("inf"))
    with pytest.raises(ValidationError):
        _default_payload(minimum_detectable_effect=float("-inf"))


def test_schema_rejects_out_of_range_statistical_parameters() -> None:
    with pytest.raises(ValidationError):
        _default_payload(alpha=0.0)
    with pytest.raises(ValidationError):
        _default_payload(alpha=1.0)
    with pytest.raises(ValidationError):
        _default_payload(power=0.0)
    with pytest.raises(ValidationError):
        _default_payload(minimum_detectable_effect=0.0)
    with pytest.raises(ValidationError):
        _default_payload(minimum_detectable_effect=0.6)


def test_schema_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AbTestVariantIn(
            label="A",
            visitors=10,
            conversions=1,
            unexpected=True,
        )
    with pytest.raises(ValidationError):
        _default_payload(unexpected="nope")


def test_route_output_round_trips_through_response_model() -> None:
    raw = {
        "variant_a": {
            "label": "Control",
            "visitors": 1000,
            "conversions": 100,
            "conversion_rate": 0.10,
        },
        "variant_b": {
            "label": "New",
            "visitors": 1000,
            "conversions": 160,
            "conversion_rate": 0.16,
        },
        "winner": "New",
        "pooled_conversion_rate": 0.13,
        "absolute_uplift": 0.06,
        "relative_uplift_pct": 60.0,
        "z_score": 3.9894,
        "p_value": 0.000066,
        "confidence_interval": {"low": 0.0306, "high": 0.0894},
        "verdict": "SIGNIFICANT",
        "significant": True,
        "confidence_level": 0.95,
        "visitors_needed_for_observed_uplift": 3841,
        "visitors_needed_for_mde": 3841,
        "narrative": "winner",
        "recommendations": ["Adopt New"],
        "key_signals": [{"label": "verdict", "value": "SIGNIFICANT", "severity": "ok"}],
        "meta": {"alpha": 0.05},
    }
    out = AbTestAnalysisOut(**raw)
    assert out.verdict == "SIGNIFICANT"
    assert out.meta["alpha"] == pytest.approx(0.05)
    assert out.model_dump()["winner"] == "New"


def test_route_accepts_object_like_variants() -> None:
    payload = _default_payload(
        variant_a=AbTestVariantIn(
            label="Control",
            visitors=1000,
            conversions=100,
        ),
        variant_b=AbTestVariantIn(
            label="New",
            visitors=1000,
            conversions=160,
        ),
    )
    out = _call_route(payload)
    assert out.verdict == "SIGNIFICANT"
