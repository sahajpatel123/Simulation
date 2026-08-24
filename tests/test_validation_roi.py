"""
Tests for the validation-ROI (de-risking priority) engine.

The engine composes the sensitivity analysis (conversion swing per
assumption) with claim-confidence scoring (evidence backing per
assumption) into a ranked ``sensitivity x uncertainty`` read.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.validation_roi import (
    VALID_ROI_TIERS,
    AssumptionValidationRoi,
    ValidationRoiOut,
)
from app.simulation.validation_roi import (
    HIGH_VALUE_MIN,
    MONITOR_MIN,
    ROI_TIER_HIGH_VALUE,
    ROI_TIER_LOW_VALUE,
    ROI_TIER_MONITOR,
    ROI_TIER_VALIDATE_FIRST,
    VALIDATE_FIRST_MIN,
    _resolve_confidence,
    _roi_tier,
    build_validation_roi,
)

ENV: dict[str, Any] = {
    "price_sensitivity": 0.5,
    "market_maturity": 0.3,
    "average_order_value": 999.0,
}

BASE_RESULTS: dict[str, Any] = {
    "population_weighted_conversion": 0.05,
    "mean_conversion_rate": 0.05,
    "mean_revenue": 999.0,
    "total_agents": 10000,
    "converted": 500,
    "product_type_detected": "saas",
}

# One assumption per confidence tier, each triggering a Markov keyword rule
# so the sensitivity engine produces a real (non-zero) swing.
ASSUMPTIONS: list[dict[str, Any]] = [
    {
        "text": "We believe pricing will be 999 rupees per month for this",
        "sensitivity": "CRITICAL",
        "impact_score": 9.0,
        "category": "PricingArchitect",
    },
    {
        "text": "Market research shows strong market demand for this solution",
        "sensitivity": "CRITICAL",
        "impact_score": 9.0,
        "category": "MarketSizeArchitect",
    },
    {
        "text": "We ran an A/B test and pricing converts well",
        "sensitivity": "HIGH",
        "impact_score": 7.0,
        "category": "CustomerAcquisitionArchitect",
    },
    {
        "text": "The product has no real competitors",
        "sensitivity": "MEDIUM",
        "impact_score": 6.0,
        "category": "CompetitiveDynamicsArchitect",
    },
]


def _build(
    assumptions: list[Any] | None = None,
    *,
    results: dict[str, Any] | None = None,
    signal_quality: float | None = None,
) -> ValidationRoiOut:
    return build_validation_roi(
        simulation_id=1,
        project_id=2,
        base_results=results if results is not None else BASE_RESULTS,
        env_params=ENV,
        existing_assumptions=assumptions if assumptions is not None else ASSUMPTIONS,
        signal_quality=signal_quality,
    )


def _by_text(out: ValidationRoiOut, text: str) -> AssumptionValidationRoi:
    for row in out.assumptions:
        if row.assumption_text == text:
            return row
    raise AssertionError(f"assumption not found: {text}")


# ---------------------------------------------------------------------------
# Tier mapping
# ---------------------------------------------------------------------------

class TestRoiTier:
    def test_bands(self) -> None:
        assert _roi_tier(VALIDATE_FIRST_MIN) == ROI_TIER_VALIDATE_FIRST
        assert _roi_tier(HIGH_VALUE_MIN) == ROI_TIER_HIGH_VALUE
        assert _roi_tier(MONITOR_MIN) == ROI_TIER_MONITOR
        assert _roi_tier(0.0) == ROI_TIER_LOW_VALUE
        assert _roi_tier(0.99) == ROI_TIER_VALIDATE_FIRST


# ---------------------------------------------------------------------------
# Confidence resolution
# ---------------------------------------------------------------------------

class TestResolveConfidence:
    def test_heuristic_external(self) -> None:
        confidence, score = _resolve_confidence(
            "Market research shows strong demand", None
        )
        assert confidence.value == "VALIDATED_EXTERNAL"
        assert score == 1.0

    def test_heuristic_internal(self) -> None:
        confidence, score = _resolve_confidence("We ran an A/B test", None)
        assert confidence.value == "VALIDATED_INTERNAL"
        assert score == 0.75

    def test_heuristic_aspirational(self) -> None:
        confidence, score = _resolve_confidence(
            "We believe users will pay for this", None
        )
        assert confidence.value == "ASPIRATIONAL"
        assert score == 0.40

    def test_heuristic_design_intent_default(self) -> None:
        confidence, score = _resolve_confidence(
            "The product has no real competitors", None
        )
        assert confidence.value == "DESIGN_INTENT"
        assert score == 0.55

    def test_explicit_override_wins_when_stronger(self) -> None:
        confidence, score = _resolve_confidence(
            "We believe users will pay for this", "VALIDATED_INTERNAL"
        )
        assert confidence.value == "VALIDATED_INTERNAL"
        assert score == 0.75

    def test_weaker_explicit_does_not_downgrade(self) -> None:
        confidence, score = _resolve_confidence(
            "Market research shows strong demand", "ASPIRATIONAL"
        )
        assert confidence.value == "VALIDATED_EXTERNAL"
        assert score == 1.0

    def test_invalid_explicit_ignored(self) -> None:
        confidence, _ = _resolve_confidence(
            "We believe users will pay for this", "NOT_A_TIER"
        )
        assert confidence.value == "ASPIRATIONAL"


# ---------------------------------------------------------------------------
# build_validation_roi
# ---------------------------------------------------------------------------

class TestBuildValidationRoi:
    def test_contract(self) -> None:
        out = _build()
        assert isinstance(out, ValidationRoiOut)
        assert out.simulation_id == 1
        assert out.project_id == 2
        assert out.status == "COMPLETED"
        assert out.baseline_conversion == 0.05
        assert out.summary.total_assumptions == 4
        assert len(out.assumptions) == 4

    def test_ranked_by_roi_descending(self) -> None:
        out = _build()
        rois = [r.validation_roi for r in out.assumptions]
        assert rois == sorted(rois, reverse=True)
        assert out.assumptions[0].roi_tier == ROI_TIER_VALIDATE_FIRST

    def test_unvalidated_high_sensitivity_is_validate_first(self) -> None:
        out = _build()
        row = _by_text(
            out, "We believe pricing will be 999 rupees per month for this"
        )
        assert row.confidence_tier == "ASPIRATIONAL"
        assert row.confidence_score == 0.40
        assert row.roi_tier == ROI_TIER_VALIDATE_FIRST
        # roi = sensitivity x (1 - confidence)
        assert row.validation_roi == round(row.sensitivity_score * 0.6, 4)
        assert row.validation_roi > 0

    def test_validated_assumption_scores_zero_roi(self) -> None:
        out = _build()
        row = _by_text(
            out, "Market research shows strong market demand for this solution"
        )
        assert row.confidence_tier == "VALIDATED_EXTERNAL"
        assert row.confidence_score == 1.0
        assert row.validation_roi == 0.0
        assert row.roi_tier == ROI_TIER_LOW_VALUE
        assert row.expected_conversion_swing == 0.0

    def test_internal_validation_lowers_roi(self) -> None:
        out = _build()
        row = _by_text(out, "We ran an A/B test and pricing converts well")
        assert row.confidence_tier == "VALIDATED_INTERNAL"
        assert row.confidence_score == 0.75
        assert row.validation_roi == round(row.sensitivity_score * 0.25, 4)
        assert row.expected_conversion_swing == round(
            abs(row.max_delta) * 0.25, 6
        )
        assert row.roi_tier in {ROI_TIER_MONITOR, ROI_TIER_HIGH_VALUE}

    def test_expected_swing_uses_uncertainty_scaled_max_delta(self) -> None:
        out = _build()
        for row in out.assumptions:
            uncertainty = 1.0 - row.confidence_score
            assert row.expected_conversion_swing == round(
                abs(row.max_delta) * uncertainty, 6
            )

    def test_all_tiers_valid_and_counts_add_up(self) -> None:
        out = _build()
        assert all(r.roi_tier in VALID_ROI_TIERS for r in out.assumptions)
        summary = out.summary
        counted = (
            summary.validate_first_count
            + summary.high_value_count
            + summary.monitor_count
            + summary.low_value_count
        )
        assert counted == summary.total_assumptions
        assert (
            summary.validated_assumptions + summary.unvalidated_assumptions
            == summary.total_assumptions
        )

    def test_top_summary_points_at_first_row(self) -> None:
        out = _build()
        top = out.assumptions[0]
        assert out.summary.top_de_risking_assumption == top.assumption_text[:200]
        assert out.summary.top_roi_score == top.validation_roi
        assert out.summary.top_expected_swing == top.expected_conversion_swing

    def test_recommendations_capped_and_non_empty(self) -> None:
        out = _build()
        assert 1 <= len(out.recommendations) <= 3
        assert all(rec for rec in out.recommendations)

    def test_narrative_mentions_top_assumption(self) -> None:
        out = _build()
        assert out.summary.total_assumptions > 0
        assert out.assumptions[0].assumption_text[:80] in out.recommendations[0]

    def test_orm_style_objects_supported(self) -> None:
        assumptions = [
            SimpleNamespace(
                text="We believe pricing will be 999 rupees per month",
                sensitivity="CRITICAL",
                impact_score=9.0,
                category="PricingArchitect",
            ),
            SimpleNamespace(
                text="Market research shows strong market demand",
                sensitivity="CRITICAL",
                impact_score=9.0,
                category="MarketSizeArchitect",
            ),
        ]
        out = _build(assumptions)
        assert out.summary.total_assumptions == 2
        assert _by_text(
            out, "We believe pricing will be 999 rupees per month"
        ).category == "PricingArchitect"

    def test_explicit_claim_confidence_is_used(self) -> None:
        assumptions = [
            {
                "text": "We believe users will pay 999 rupees per month",
                "sensitivity": "CRITICAL",
                "impact_score": 9.0,
                "category": "PricingArchitect",
                "claim_confidence": "VALIDATED_INTERNAL",
            }
        ]
        out = _build(assumptions)
        row = out.assumptions[0]
        assert row.confidence_tier == "VALIDATED_INTERNAL"
        assert row.confidence_score == 0.75
        assert row.validation_roi == round(row.sensitivity_score * 0.25, 4)

    def test_empty_assumptions_zero_state(self) -> None:
        out = _build([])
        assert out.summary.total_assumptions == 0
        assert out.assumptions == []
        assert out.summary.top_de_risking_assumption == ""
        assert any("No assumptions" in rec for rec in out.recommendations)

    def test_signal_quality_fallback_from_route(self) -> None:
        out = _build(signal_quality=0.61)
        assert out.signal_quality == 0.61

    def test_signal_quality_from_results_when_present(self) -> None:
        results = {**BASE_RESULTS, "signal_quality": 0.73}
        out = _build(results=results)
        assert out.signal_quality == 0.73

    def test_zero_signal_quality_from_results_is_preserved(self) -> None:
        results = {**BASE_RESULTS, "signal_quality": 0.0}
        out = _build(results=results)
        assert out.signal_quality == 0.0

    def test_zero_signal_quality_not_overridden_by_route_fallback(self) -> None:
        results = {**BASE_RESULTS, "signal_quality": 0.0}
        out = _build(results=results, signal_quality=0.62)
        assert out.signal_quality == 0.0

    def test_zero_assumptions_falls_back_to_route_signal_quality(self) -> None:
        out = _build([], signal_quality=0.62)
        assert out.signal_quality == 0.62


class TestDuplicateAssumptionMeta:
    def test_stronger_explicit_confidence_wins_across_duplicates(self) -> None:
        text = "We believe users will pay 999 rupees per month"
        assumptions = [
            {
                "text": text,
                "sensitivity": "CRITICAL",
                "impact_score": 9.0,
                "category": "PricingArchitect",
            },
            {
                "text": text,
                "sensitivity": "CRITICAL",
                "impact_score": 9.0,
                "category": "",
                "claim_confidence": "VALIDATED_INTERNAL",
            },
        ]
        out = _build(assumptions)
        rows = [r for r in out.assumptions if r.assumption_text == text]
        assert len(rows) == 2
        assert all(r.confidence_tier == "VALIDATED_INTERNAL" for r in rows)
        assert all(r.confidence_score == 0.75 for r in rows)
        assert all(r.validation_roi == round(r.sensitivity_score * 0.25, 4) for r in rows)

    def test_category_kept_from_first_non_empty(self) -> None:
        text = "We believe users will pay 999 rupees per month"
        assumptions = [
            {
                "text": text,
                "sensitivity": "CRITICAL",
                "impact_score": 9.0,
                "category": "PricingArchitect",
            },
            {
                "text": text,
                "sensitivity": "CRITICAL",
                "impact_score": 9.0,
                "category": "MarketSizeArchitect",
            },
        ]
        out = _build(assumptions)
        rows = [r for r in out.assumptions if r.assumption_text == text]
        assert all(r.category == "PricingArchitect" for r in rows)


class TestLowValueWording:
    def test_low_value_validated_mentions_validation(self) -> None:
        out = _build()
        row = _by_text(
            out, "Market research shows strong market demand for this solution"
        )
        assert row.roi_tier == ROI_TIER_LOW_VALUE
        assert row.confidence_tier == "VALIDATED_EXTERNAL"
        assert "already" in row.recommendation

    def test_low_value_unvalidated_does_not_claim_validated(self) -> None:
        assumptions = [
            {
                "text": "We believe users will love the design",
                "sensitivity": "LOW",
                "impact_score": 1.0,
                "category": "ProductValueArchitect",
            }
        ]
        out = _build(assumptions)
        row = out.assumptions[0]
        assert row.roi_tier == ROI_TIER_LOW_VALUE
        assert row.confidence_tier == "ASPIRATIONAL"
        assert "already" not in row.recommendation
        assert "not yet validated" in row.recommendation


class TestSchemaValidation:
    def test_roi_tier_literal_rejects_invalid(self) -> None:
        with pytest.raises(ValidationError):
            AssumptionValidationRoi(roi_tier="NOT_A_TIER")

    def test_confidence_tier_literal_rejects_invalid(self) -> None:
        with pytest.raises(ValidationError):
            AssumptionValidationRoi(confidence_tier="MAYBE")

    def test_score_range_enforced(self) -> None:
        with pytest.raises(ValidationError):
            AssumptionValidationRoi(validation_roi=1.5)
        with pytest.raises(ValidationError):
            AssumptionValidationRoi(sensitivity_score=-0.1)
