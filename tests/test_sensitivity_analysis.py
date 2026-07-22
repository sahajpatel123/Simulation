"""
Tests for the scenario sensitivity analysis engine
(cycle 30 sensitivity-analysis).
"""
from __future__ import annotations

from typing import Any

import pytest

from app.simulation.sensitivity_analysis import (
    IMPACT_LEVELS,
    SENSITIVITY_TIER_THRESHOLDS,
    _forward_conversion,
    _sensitivity_tier,
    build_sensitivity_analysis,
)
from app.schemas.sensitivity import (
    AssumptionSensitivity,
    SensitivityOut,
    SensitivityPoint,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

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

ASSUMPTIONS: list[dict[str, Any]] = [
    {"text": "Users will pay ₹999 without a free trial — expensive for tier-2", "sensitivity": "CRITICAL", "impact_score": 9.0},
    {"text": "Strong market demand for this solution", "sensitivity": "HIGH", "impact_score": 7.0},
    {"text": "No credible reviews or testimonials", "sensitivity": "MEDIUM", "impact_score": 6.0},
    {"text": "The sky is blue", "sensitivity": "LOW", "impact_score": 3.0},  # non-matching keyword
]


# ---------------------------------------------------------------------------
# Sensitivity tier
# ---------------------------------------------------------------------------

class TestSensitivityTier:
    def test_critical(self) -> None:
        assert _sensitivity_tier(0.70) == "CRITICAL"
        assert _sensitivity_tier(0.60) == "CRITICAL"

    def test_high(self) -> None:
        assert _sensitivity_tier(0.40) == "HIGH"
        assert _sensitivity_tier(0.35) == "HIGH"

    def test_medium(self) -> None:
        assert _sensitivity_tier(0.20) == "MEDIUM"
        assert _sensitivity_tier(0.15) == "MEDIUM"

    def test_low(self) -> None:
        assert _sensitivity_tier(0.10) == "LOW"
        assert _sensitivity_tier(0.0) == "LOW"


# ---------------------------------------------------------------------------
# build_sensitivity_analysis
# ---------------------------------------------------------------------------

class TestBuildSensitivityAnalysis:
    def test_basic_analysis(self) -> None:
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
        )
        assert isinstance(result, SensitivityOut)
        assert result.simulation_id == 1
        assert result.project_id == 2
        assert result.status == "COMPLETED"
        assert result.baseline_conversion == 0.05
        assert len(result.assumptions) == 4
        assert result.summary.total_assumptions == 4

    def test_curve_has_all_levels(self) -> None:
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
        )
        for a in result.assumptions:
            assert len(a.curve) == len(IMPACT_LEVELS)
            assert IMPACT_LEVELS == [0.0, 0.25, 0.5, 0.75, 1.0]

    def test_curve_points_structure(self) -> None:
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
        )
        for a in result.assumptions:
            for point in a.curve:
                assert isinstance(point, SensitivityPoint)
                assert 0.0 <= point.impact_score <= 10.0
                assert 0.0 <= point.conversion_rate <= 1.0

    def test_curve_first_point_is_zero_impact(self) -> None:
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
        )
        for a in result.assumptions:
            # First point should have impact_score = 0 (baseline_impact * 0.0)
            assert a.curve[0].impact_score == 0.0

    def test_curve_last_point_is_full_impact(self) -> None:
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
        )
        for a in result.assumptions:
            # Last point should have impact_score = baseline_impact * 1.0
            assert a.curve[-1].impact_score == pytest.approx(a.baseline_impact_score)

    def test_pricing_assumption_has_sensitivity(self) -> None:
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
        )
        pricing = next(a for a in result.assumptions if "₹999" in a.assumption_text)
        assert pricing.sensitivity_score > 0
        assert pricing.sensitivity_tier in ("CRITICAL", "HIGH", "MEDIUM")
        assert pricing.triggers_markov_rules is True
        assert len(pricing.affected_transitions) > 0
        # Pricing affects DECIDE→PURCHASE and CONSIDER→DECIDE
        assert any("DECIDE" in t for t in pricing.affected_transitions)

    def test_non_matching_assumption_low_sensitivity(self) -> None:
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
        )
        sky = next(a for a in result.assumptions if "sky is blue" in a.assumption_text)
        assert sky.triggers_markov_rules is False
        assert len(sky.affected_transitions) == 0
        assert sky.sensitivity_score == 0.0
        assert sky.sensitivity_tier == "LOW"

    def test_sorted_by_sensitivity(self) -> None:
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
        )
        scores = [a.sensitivity_score for a in result.assumptions]
        assert scores == sorted(scores, reverse=True)

    def test_summary_structure(self) -> None:
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
        )
        s = result.summary
        assert s.total_assumptions == 4
        assert s.baseline_conversion == 0.05
        assert s.most_sensitive_assumption != ""
        assert s.most_sensitive_score > 0
        assert s.critical_assumptions + s.high_assumptions + s.medium_assumptions + s.low_assumptions == 4
        assert 0.0 <= s.avg_sensitivity_score <= 1.0

    def test_recommendations_generated(self) -> None:
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
        )
        assert len(result.recommendations) >= 1
        for rec in result.recommendations:
            assert isinstance(rec, str)
            assert len(rec) > 10

    def test_empty_assumptions(self) -> None:
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=[],
        )
        assert result.summary.total_assumptions == 0
        assert len(result.assumptions) == 0
        assert len(result.recommendations) >= 1

    def test_json_string_results(self) -> None:
        import json
        raw = json.dumps(BASE_RESULTS)
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=raw,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
        )
        assert result.baseline_conversion == 0.05

    def test_assumption_objects(self) -> None:
        class _A:
            def __init__(self) -> None:
                self.text = "pay ₹999/month"
                self.sensitivity = "HIGH"
                self.impact_score = 8.0

        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=[_A()],
        )
        assert len(result.assumptions) == 1
        assert result.assumptions[0].assumption_text == "pay ₹999/month"

    def test_env_overrides(self) -> None:
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
            override_price_sensitivity=0.9,
        )
        # Higher price sensitivity should make pricing assumptions more impactful
        pricing = next(a for a in result.assumptions if "₹999" in a.assumption_text)
        assert pricing.sensitivity_score > 0

    def test_meta_fields(self) -> None:
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
        )
        assert "generated_at" in result.meta
        assert "impact_levels" in result.meta
        assert "assumption_count" in result.meta
        assert "baseline_matrix_conversion" in result.meta
        assert "scale_factor" in result.meta

    def test_schema_round_trip(self) -> None:
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
        )
        dumped = result.model_dump()
        assert dumped["simulation_id"] == 1
        assert isinstance(dumped["assumptions"], list)
        assert isinstance(dumped["summary"], dict)
        assert isinstance(dumped["recommendations"], list)

    def test_revenue_projection(self) -> None:
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
        )
        assert result.baseline_revenue_per_1000 == round(0.05 * 1000 * 999.0, 2)

    def test_market_assumption_positive_impact(self) -> None:
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
        )
        market = next(a for a in result.assumptions if "market demand" in a.assumption_text)
        assert market.triggers_markov_rules is True
        assert market.sensitivity_score > 0

    def test_trust_assumption(self) -> None:
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
        )
        trust = next(a for a in result.assumptions if "reviews" in a.assumption_text)
        assert trust.triggers_markov_rules is True
        assert any("BROWSE" in t or "CONSIDER" in t for t in trust.affected_transitions)

    def test_multiple_assumptions_independent(self) -> None:
        """Each assumption should be varied independently."""
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
        )
        # Each assumption should have a curve with 5 points
        for a in result.assumptions:
            assert len(a.curve) == 5
            # The curve should show variation (not all zeros) for matching assumptions
            if a.triggers_markov_rules:
                deltas = [abs(p.delta_from_baseline) for p in a.curve]
                assert max(deltas) > 0, f"Assumption '{a.assumption_text[:40]}' should have non-zero deltas"

    def test_product_type_detected(self) -> None:
        result = build_sensitivity_analysis(
            simulation_id=1,
            project_id=2,
            base_results=BASE_RESULTS,
            env_params=ENV,
            existing_assumptions=ASSUMPTIONS,
        )
        assert result.product_type_detected == "saas"
