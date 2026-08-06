"""
Tests for the validation experiment planner.

The planner converts validation-ROI rankings (sensitivity x uncertainty) into
concrete experiments: method, cost tier, duration, sample target, success
threshold and go/no-go rule per assumption worth testing.
"""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.validation_experiment import (
    ValidationExperiment,
    ValidationExperimentPlanOut,
)
from app.schemas.validation_roi import (
    AssumptionValidationRoi,
    ValidationRoiOut,
    ValidationRoiSummary,
)
from app.simulation.validation_experiment_planner import (
    MAX_EXPERIMENTS,
    METHOD_SPECS,
    _match_method,
    build_validation_experiment_plan,
)


def _row(
    text: str,
    *,
    category: str,
    roi_tier: str = "VALIDATE_FIRST",
    roi: float = 0.40,
    confidence: str = "ASPIRATIONAL",
    swing: float = 0.30,
) -> AssumptionValidationRoi:
    return AssumptionValidationRoi(
        assumption_text=text,
        category=category,
        roi_tier=roi_tier,
        validation_roi=roi,
        confidence_tier=confidence,
        expected_conversion_swing=swing,
    )


def _roi(rows: list[AssumptionValidationRoi]) -> ValidationRoiOut:
    return ValidationRoiOut(
        simulation_id=1,
        project_id=2,
        status="COMPLETED",
        baseline_conversion=0.05,
        signal_quality=0.62,
        summary=ValidationRoiSummary(total_assumptions=len(rows)),
        assumptions=rows,
    )


def _plan(
    rows: list[AssumptionValidationRoi],
    *,
    max_experiments: int = MAX_EXPERIMENTS,
) -> ValidationExperimentPlanOut:
    return build_validation_experiment_plan(
        _roi(rows),
        max_experiments=max_experiments,
    )


# ---------------------------------------------------------------------------
# Method selection
# ---------------------------------------------------------------------------


class TestMethodSelection:
    def test_pricing_category_maps_to_wtp_survey(self) -> None:
        assert (
            _match_method("PricingArchitect", "VALIDATE_FIRST")
            == "WILLINGNESS_TO_PAY_SURVEY"
        )

    def test_market_category_maps_to_landing_page(self) -> None:
        assert (
            _match_method("MarketSizeArchitect", "VALIDATE_FIRST")
            == "LANDING_PAGE_SMOKE_TEST"
        )

    def test_competitive_category_maps_to_desk_research(self) -> None:
        assert (
            _match_method("CompetitiveDynamicsArchitect", "HIGH_VALUE")
            == "COMPETITIVE_DESK_RESEARCH"
        )

    def test_acquisition_category_maps_to_paid_test(self) -> None:
        assert (
            _match_method("CustomerAcquisitionArchitect", "VALIDATE_FIRST")
            == "PAID_ACQUISITION_TEST"
        )

    def test_preorder_category_maps_to_preorder_waitlist(self) -> None:
        assert (
            _match_method("PreOrderArchitect", "VALIDATE_FIRST")
            == "PRE_ORDER_WAITLIST"
        )
        assert (
            _match_method("WaitlistConversionArchitect", "HIGH_VALUE")
            == "PRE_ORDER_WAITLIST"
        )

    def test_retention_category_maps_to_concierge(self) -> None:
        assert (
            _match_method("RetentionArchitect", "VALIDATE_FIRST")
            == "CONCIERGE_MVP"
        )

    def test_trust_category_maps_to_interviews(self) -> None:
        assert _match_method("TrustArchitect", "HIGH_VALUE") == "USER_INTERVIEWS"

    def test_unknown_category_validate_first_uses_landing_page(self) -> None:
        assert _match_method("SomeNewDomain", "VALIDATE_FIRST") == "LANDING_PAGE_SMOKE_TEST"

    def test_unknown_category_high_value_uses_interviews(self) -> None:
        assert _match_method("SomeNewDomain", "HIGH_VALUE") == "USER_INTERVIEWS"


# ---------------------------------------------------------------------------
# Plan construction
# ---------------------------------------------------------------------------


class TestBuildPlan:
    def test_selects_only_validate_first_and_high_value(self) -> None:
        rows = [
            _row("pricing claim", category="PricingArchitect", roi_tier="VALIDATE_FIRST"),
            _row("demand claim", category="MarketSizeArchitect", roi_tier="HIGH_VALUE"),
            _row("monitor claim", category="TrustArchitect", roi_tier="MONITOR"),
            _row("low claim", category="TrustArchitect", roi_tier="LOW_VALUE"),
        ]
        plan = _plan(rows)
        assert len(plan.experiments) == 2
        assert {e.roi_tier for e in plan.experiments} == {"VALIDATE_FIRST", "HIGH_VALUE"}

    def test_keeps_roi_ranking_order(self) -> None:
        rows = [
            _row("second", category="MarketSizeArchitect", roi=0.30),
            _row("first", category="PricingArchitect", roi=0.60),
        ]
        plan = _plan(rows)
        assert plan.experiments[0].assumption_text == "first"
        assert plan.experiments[1].assumption_text == "second"

    def test_caps_at_max_experiments(self) -> None:
        rows = [
            _row(f"claim {i}", category="PricingArchitect", roi=0.50 - i * 0.01)
            for i in range(10)
        ]
        plan = _plan(rows, max_experiments=3)
        assert len(plan.experiments) == 3
        assert plan.meta["max_experiments"] == 3

    def test_every_experiment_has_full_spec(self) -> None:
        plan = _plan(
            [
                _row("pricing claim", category="PricingArchitect"),
                _row("demand claim", category="MarketSizeArchitect"),
                _row("competitor claim", category="CompetitiveDynamicsArchitect"),
            ]
        )
        for exp in plan.experiments:
            assert exp.method in METHOD_SPECS
            assert exp.method_label
            assert exp.method_description
            assert exp.sample_target
            assert exp.success_metric
            assert exp.success_threshold
            assert exp.go_no_go_rule
            assert exp.rationale
            assert exp.estimated_duration_days >= 1

    def test_summary_counts_and_sprint_days(self) -> None:
        plan = _plan(
            [
                _row("pricing claim", category="PricingArchitect"),  # FREE, 7d
                _row("demand claim", category="MarketSizeArchitect"),  # LOW, 14d
                _row("acq claim", category="CustomerAcquisitionArchitect"),  # MEDIUM, 14d
            ]
        )
        s = plan.summary
        assert s.experiment_count == 3
        assert s.free_count == 1
        assert s.low_cost_count == 1
        assert s.medium_cost_count == 1
        assert s.budget_ceiling == "MEDIUM"
        assert s.sprint_days == 14
        assert s.sequential_days == 35
        assert s.top_experiment == plan.experiments[0].method_label

    def test_empty_roi_returns_zero_state(self) -> None:
        plan = _plan([])
        assert plan.experiments == []
        assert plan.summary.experiment_count == 0
        assert "No assumptions" in plan.narrative

    def test_all_low_value_returns_zero_state(self) -> None:
        plan = _plan(
            [
                _row("low", category="PricingArchitect", roi_tier="LOW_VALUE", roi=0.01),
                _row("monitor", category="TrustArchitect", roi_tier="MONITOR", roi=0.08),
            ]
        )
        assert plan.experiments == []
        assert "already validated" in plan.narrative or "No assumptions" in plan.narrative

    def test_deduplicates_identical_assumption_text(self) -> None:
        rows = [
            _row("same claim", category="PricingArchitect", roi=0.60),
            _row("same claim", category="MarketSizeArchitect", roi=0.40),
        ]
        plan = _plan(rows)
        assert len(plan.experiments) == 1
        assert plan.experiments[0].assumption_text == "same claim"
        # The strongest-ROI row wins, so the method follows its category.
        assert plan.experiments[0].method == "WILLINGNESS_TO_PAY_SURVEY"
        assert plan.experiments[0].validation_roi == 0.60

    def test_skips_blank_assumption_text(self) -> None:
        plan = _plan(
            [
                _row("   ", category="PricingArchitect"),
                _row("real claim", category="MarketSizeArchitect", roi=0.50),
            ]
        )
        assert len(plan.experiments) == 1
        assert plan.experiments[0].assumption_text == "real claim"

    def test_max_experiments_below_one_returns_zero_state(self) -> None:
        plan = _plan(
            [_row("pricing claim", category="PricingArchitect")],
            max_experiments=0,
        )
        assert plan.experiments == []
        assert plan.summary.experiment_count == 0
        assert plan.meta["max_experiments"] == 0
        assert "No assumptions" in plan.narrative

    def test_rationale_cost_phrasing_is_honest_per_tier(self) -> None:
        free_plan = _plan(
            [_row("pricing claim", category="PricingArchitect")]  # FREE
        )
        assert "cheapest direct evidence" in free_plan.experiments[0].rationale

        low_plan = _plan(
            [_row("retention claim", category="RetentionArchitect")]  # LOW
        )
        assert "low-cost, direct piece of evidence" in low_plan.experiments[0].rationale

        medium_plan = _plan(
            [_row("acq claim", category="CustomerAcquisitionArchitect")]  # MEDIUM
        )
        assert "most direct evidence" in medium_plan.experiments[0].rationale
        assert "cheapest" not in medium_plan.experiments[0].rationale

    def test_narrative_window_label_matches_sprint_duration(self) -> None:
        short_plan = _plan(
            [_row("pricing claim", category="PricingArchitect")]  # 7 days
        )
        assert short_plan.narrative.startswith("Week-1 validation sprint")

        long_plan = _plan(
            [_row("preorder claim", category="RetentionArchitect"),
             _row("preorder claim 2", category="CustomerAcquisitionArchitect")]
        )
        # Both map to 14-day experiments; no experiment is longer, so the
        # window stays "two-week" rather than the hardcoded "Week-1".
        assert long_plan.narrative.startswith("two-week validation sprint")

        longest_plan = _plan(
            [
                _row("preorder claim", category="PreOrderArchitect"),
            ]
        )
        assert longest_plan.experiments[0].estimated_duration_days == 21
        assert longest_plan.narrative.startswith("three-week validation sprint")


# ---------------------------------------------------------------------------
# Schema guards
# ---------------------------------------------------------------------------


class TestSchema:
    def test_rejects_unknown_cost_tier(self) -> None:
        with pytest.raises(ValidationError):
            ValidationExperiment(
                assumption_text="x",
                category="PricingArchitect",
                roi_tier="VALIDATE_FIRST",
                validation_roi=0.4,
                expected_conversion_swing=0.3,
                confidence_tier="ASPIRATIONAL",
                method="USER_INTERVIEWS",
                cost_tier="HIGH",
            )

    def test_rejects_unknown_method_id(self) -> None:
        with pytest.raises(ValidationError):
            ValidationExperiment(
                assumption_text="x",
                category="PricingArchitect",
                roi_tier="VALIDATE_FIRST",
                validation_roi=0.4,
                expected_conversion_swing=0.3,
                confidence_tier="ASPIRATIONAL",
                method="MAGIC_8_BALL",
                cost_tier="FREE",
            )


def test_meta_exposes_model_version_and_source() -> None:
    plan = _plan([_row("pricing claim", category="PricingArchitect")])
    assert plan.meta["model"] == "validation_experiment_planner_v1"
    assert "validation_roi" in plan.meta["source"]


def test_unknown_category_fallback_spec_is_consistent() -> None:
    """Every method id produced by the matcher must exist in the spec table."""
    categories = ["PricingArchitect", "MarketSizeArchitect", "CompetitiveDynamicsArchitect"]
    tiers = ["VALIDATE_FIRST", "HIGH_VALUE"]
    for cat in categories:
        for tier in tiers:
            method = _match_method(cat, tier)
            assert method in METHOD_SPECS
            assert METHOD_SPECS[method]["label"]
