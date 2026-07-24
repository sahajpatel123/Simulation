"""Tests for WhatIfSummary.direction_breakdown_total()."""
from __future__ import annotations

from app.schemas.what_if import WhatIfSummary


def test_total_zero_when_breakdown_empty() -> None:
    assert WhatIfSummary().direction_breakdown_total() == 0


def test_total_returns_sum_of_counts() -> None:
    summary = WhatIfSummary(
        scenario_count=5,
        direction_breakdown={"POSITIVE": 2, "NEGATIVE": 3},
    )

    assert summary.direction_breakdown_total() == 5


def test_total_matches_scenario_count_for_default_summary() -> None:
    from typing import Any

    from app.simulation.what_if import build_what_if_scenario, summarise_what_if_scenarios

    scenarios = [
        build_what_if_scenario(
            simulation_id=i,
            project_id=i,
            base_results={
                "population_weighted_conversion": 0.05,
                "conversion_rate": 0.05,
                "mean_revenue": 999.0,
                "product_type_detected": "saas",
            },
            env_params={
                "average_order_value": 999.0,
                "price_sensitivity": 0.5,
                "market_maturity": 0.3,
            },
            existing_assumptions=[],
            new_assumptions=[
                {"text": "Pricing too expensive", "sensitivity": "CRITICAL", "impact_score": 9},
            ],
        )
        for i in range(3)
    ]

    summary = summarise_what_if_scenarios(scenarios)

    assert summary.direction_breakdown_total() == summary.scenario_count == len(scenarios)