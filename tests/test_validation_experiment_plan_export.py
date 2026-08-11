"""Pure-helper tests for the validation-experiment-plan CSV/JSON export."""

from __future__ import annotations

import json

from app.schemas.validation_experiment import ValidationExperimentPlanOut
from app.schemas.validation_roi import (
    AssumptionValidationRoi,
    ValidationRoiOut,
    ValidationRoiSummary,
)
from app.simulation.validation_experiment_plan_export import (
    validation_experiment_plan_to_csv,
    validation_experiment_plan_to_json,
)
from app.simulation.validation_experiment_planner import (
    MAX_EXPERIMENTS,
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


def _metadata() -> dict:
    return {
        "generated_at": "2026-08-11T12:00:00+00:00",
        "user_id": 42,
        "format_version": "1",
        "simulation_id": 1,
        "project_id": 2,
    }


def _sample_plan() -> ValidationExperimentPlanOut:
    return _plan(
        [
            _row("pricing claim", category="PricingArchitect"),
            _row(
                "demand claim",
                category="MarketSizeArchitect",
                roi_tier="HIGH_VALUE",
                roi=0.30,
            ),
            _row(
                "acq claim",
                category="CustomerAcquisitionArchitect",
                roi_tier="HIGH_VALUE",
                roi=0.20,
            ),
        ]
    )


def test_csv_contains_metadata_and_summary() -> None:
    csv_text = validation_experiment_plan_to_csv(
        _sample_plan(),
        metadata=_metadata(),
    )

    assert "generated_at,2026-08-11T12:00:00+00:00" in csv_text
    assert "user_id,42" in csv_text
    assert "format_version,1" in csv_text
    assert "simulation_id,1" in csv_text
    assert "project_id,2" in csv_text
    assert "section,Validation Sprint Summary" in csv_text
    assert "experiment_count,3" in csv_text
    assert "validate_first_count,1" in csv_text
    assert "high_value_count,2" in csv_text
    assert "budget_ceiling,MEDIUM" in csv_text
    assert "sprint_days,14" in csv_text
    assert "narrative," in csv_text


def test_csv_renders_one_row_per_experiment_with_full_spec() -> None:
    csv_text = validation_experiment_plan_to_csv(_sample_plan())

    assert "section,Experiments" in csv_text
    assert (
        "rank,assumption_text,category,roi_tier,validation_roi,"
        "expected_conversion_swing,confidence_tier,method,method_label,"
        "method_description,cost_tier,estimated_duration_days,sample_target,"
        "success_metric,success_threshold,go_no_go_rule,rationale" in csv_text
    )
    assert "1,pricing claim,PricingArchitect,VALIDATE_FIRST,0.4,0.3" in csv_text
    assert "WILLINGNESS_TO_PAY_SURVEY" in csv_text
    assert "2,demand claim,MarketSizeArchitect,HIGH_VALUE,0.3,0.3" in csv_text
    assert "LANDING_PAGE_SMOKE_TEST" in csv_text
    assert "3,acq claim,CustomerAcquisitionArchitect,HIGH_VALUE,0.2,0.3" in csv_text
    assert "PAID_ACQUISITION_TEST" in csv_text
    assert "success_threshold" in csv_text
    assert "go_no_go_rule" in csv_text


def test_csv_empty_plan_keeps_sections_and_headers() -> None:
    csv_text = validation_experiment_plan_to_csv(_plan([]))

    assert "section,Validation Sprint Summary" in csv_text
    assert "experiment_count,0" in csv_text
    assert "section,Experiments" in csv_text
    assert (
        "rank,assumption_text,category,roi_tier,validation_roi,"
        "expected_conversion_swing,confidence_tier,method,method_label,"
        "method_description,cost_tier,estimated_duration_days,sample_target,"
        "success_metric,success_threshold,go_no_go_rule,rationale" in csv_text
    )
    assert "section,Meta" in csv_text


def test_csv_neutralizes_spreadsheet_formula_injection() -> None:
    plan = _plan(
        [
            _row(
                '=HYPERLINK("http://evil")',
                category="PricingArchitect",
            ),
        ]
    )

    csv_text = validation_experiment_plan_to_csv(plan)

    assert "'=HYPERLINK(" in csv_text
    assert "http://evil" in csv_text


def test_csv_guards_whitespace_prefixed_formula() -> None:
    plan = _plan(
        [
            _row(
                "  +SUM(A1:A9)",
                category="PricingArchitect",
            ),
        ]
    )

    csv_text = validation_experiment_plan_to_csv(plan)

    assert "'  +SUM(A1:A9)" in csv_text


def test_csv_metadata_none_values_render_empty() -> None:
    csv_text = validation_experiment_plan_to_csv(
        _sample_plan(),
        metadata={
            "generated_at": None,
            "user_id": None,
            "format_version": None,
            "simulation_id": None,
            "project_id": None,
        },
    )

    assert "generated_at,\n" in csv_text
    assert "user_id,\n" in csv_text
    assert "format_version,\n" in csv_text


def test_json_round_trips_plan() -> None:
    json_text = validation_experiment_plan_to_json(
        _sample_plan(),
        metadata=_metadata(),
    )
    parsed = json.loads(json_text)

    assert parsed["metadata"]["user_id"] == 42
    plan = parsed["validation_experiment_plan"]
    assert plan["simulation_id"] == 1
    assert plan["project_id"] == 2
    assert plan["summary"]["experiment_count"] == 3
    assert len(plan["experiments"]) == 3
    assert plan["experiments"][0]["method"] == "WILLINGNESS_TO_PAY_SURVEY"


def test_json_preserves_unicode_and_ends_with_newline() -> None:
    plan = _plan(
        [
            _row("⚠️ 高风险合规", category="PricingArchitect"),
        ]
    )

    json_text = validation_experiment_plan_to_json(plan)

    assert json_text.endswith("\n")
    assert "⚠️ 高风险合规" in json_text
    parsed = json.loads(json_text)
    assert parsed["validation_experiment_plan"]["experiments"][0][
        "assumption_text"
    ] == "⚠️ 高风险合规"


def test_csv_skips_malformed_experiment_rows() -> None:
    payload = _sample_plan().model_dump()
    payload["experiments"] = [
        None,
        "junk",
        [],
        payload["experiments"][0],
    ]

    csv_text = validation_experiment_plan_to_csv(payload)

    assert "junk" not in csv_text
    assert "4,pricing claim,PricingArchitect" in csv_text


def test_csv_handles_missing_summary_and_meta() -> None:
    csv_text = validation_experiment_plan_to_csv(
        {
            "simulation_id": 1,
            "project_id": 2,
            "status": "COMPLETED",
            "narrative": "No plan yet",
        }
    )

    assert "section,Validation Sprint Summary" in csv_text
    assert "experiment_count," in csv_text
    assert "section,Experiments" in csv_text
    assert "section,Meta" in csv_text


def test_export_module_all_contract() -> None:
    from app.simulation import validation_experiment_plan_export

    assert set(validation_experiment_plan_export.__all__) == {
        "validation_experiment_plan_to_csv",
        "validation_experiment_plan_to_json",
    }
