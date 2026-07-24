"""Tests for the multi-scenario what-if summariser."""
from __future__ import annotations

from typing import Any

from app.schemas.what_if import WhatIfSummary
from app.simulation.what_if import (
    build_what_if_scenario,
    summarise_what_if_scenarios,
)


def _base() -> dict[str, Any]:
    return {
        "population_weighted_conversion": 0.05,
        "conversion_rate": 0.05,
        "mean_revenue": 999.0,
        "product_type_detected": "saas",
    }


def _env() -> dict[str, Any]:
    return {
        "average_order_value": 999.0,
        "price_sensitivity": 0.5,
        "market_maturity": 0.3,
    }


def _scenario(
    *,
    sim_id: int,
    assumptions: list[dict[str, Any]],
    overrides: dict[str, float] | None = None,
) -> Any:
    return build_what_if_scenario(
        simulation_id=sim_id,
        project_id=sim_id,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=assumptions,
        **(overrides or {}),
    )


def test_empty_input_returns_zero_summary() -> None:
    summary = summarise_what_if_scenarios([])

    assert isinstance(summary, WhatIfSummary)
    assert summary.scenario_count == 0
    assert summary.avg_delta == 0.0
    assert summary.direction_breakdown == {}
    assert summary.top_categories == []


def test_summary_aggregates_delta_stats() -> None:
    scenarios = [
        _scenario(
            sim_id=1,
            assumptions=[{
                "text": "Pricing is too expensive",
                "sensitivity": "CRITICAL",
                "impact_score": 9,
            }],
        ),
        _scenario(
            sim_id=2,
            assumptions=[{
                "text": "Reviews and testimonials are missing",
                "sensitivity": "HIGH",
                "impact_score": 7,
            }],
            overrides={"override_price_sensitivity": 0.2},
        ),
    ]

    summary = summarise_what_if_scenarios(scenarios)

    assert summary.scenario_count == 2
    assert summary.best_delta >= summary.worst_delta
    assert summary.avg_delta == round(
        (scenarios[0].conversion_delta + scenarios[1].conversion_delta) / 2, 6
    )


def test_summary_counts_directions_and_categories() -> None:
    scenarios = [
        _scenario(
            sim_id=1,
            assumptions=[{
                "text": "Pricing too expensive",
                "sensitivity": "CRITICAL",
                "impact_score": 9,
            }],
        ),
        _scenario(
            sim_id=2,
            assumptions=[{
                "text": "Pricing again",
                "sensitivity": "HIGH",
                "impact_score": 7,
            }],
        ),
        _scenario(
            sim_id=3,
            assumptions=[{
                "text": "UX is confusing",
                "sensitivity": "MEDIUM",
                "impact_score": 5,
            }],
        ),
    ]

    summary = summarise_what_if_scenarios(scenarios)

    total_directions = sum(summary.direction_breakdown.values())
    assert total_directions == 3
    categories = {entry.category for entry in summary.top_categories}
    assert "pricing" in categories


def test_summary_round_trip_serialises_to_dict() -> None:
    scenarios = [
        _scenario(
            sim_id=1,
            assumptions=[{
                "text": "Pricing too expensive",
                "sensitivity": "CRITICAL",
                "impact_score": 9,
            }],
        ),
    ]

    summary = summarise_what_if_scenarios(scenarios)
    dumped = summary.model_dump()

    assert dumped["scenario_count"] == 1
    assert isinstance(dumped["top_categories"], list)
    assert dumped["top_categories"][0]["category"] == "pricing"