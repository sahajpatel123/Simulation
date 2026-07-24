"""Tests for the diff_what_if_scenarios helper."""
from __future__ import annotations

from typing import Any

from app.schemas.what_if import WhatIfDiff
from app.simulation.what_if import (
    build_what_if_scenario,
    diff_what_if_scenarios,
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


def test_diff_returns_typed_model() -> None:
    base = _scenario(sim_id=1, assumptions=[])
    other = _scenario(sim_id=2, assumptions=[])

    diff = diff_what_if_scenarios(base, other)

    assert isinstance(diff, WhatIfDiff)
    assert diff.base_simulation_id == 1
    assert diff.other_simulation_id == 2


def test_diff_includes_delta_difference() -> None:
    base = _scenario(sim_id=1, assumptions=[{
        "text": "Pricing too expensive",
        "sensitivity": "CRITICAL",
        "impact_score": 9,
    }])
    other = _scenario(sim_id=2, assumptions=[{
        "text": "Reviews missing",
        "sensitivity": "HIGH",
        "impact_score": 7,
    }])

    diff = diff_what_if_scenarios(base, other)

    assert diff.delta_difference == round(
        other.conversion_delta - base.conversion_delta, 6
    )


def test_diff_separates_shared_and_unique_categories() -> None:
    base = _scenario(sim_id=1, assumptions=[
        {"text": "Pricing too expensive", "sensitivity": "CRITICAL", "impact_score": 9},
        {"text": "UX is confusing", "sensitivity": "HIGH", "impact_score": 7},
    ])
    other = _scenario(sim_id=2, assumptions=[
        {"text": "Pricing again", "sensitivity": "HIGH", "impact_score": 7},
        {"text": "Trust missing", "sensitivity": "HIGH", "impact_score": 7},
    ])

    diff = diff_what_if_scenarios(base, other)

    assert "pricing" in diff.shared_keyword_categories
    assert "ux" in diff.base_only_categories
    assert "trust" in diff.other_only_categories


def test_diff_for_two_empty_scenarios() -> None:
    base = _scenario(sim_id=1, assumptions=[])
    other = _scenario(sim_id=2, assumptions=[])

    diff = diff_what_if_scenarios(base, other)

    assert diff.shared_keyword_categories == []
    assert diff.base_only_categories == []
    assert diff.other_only_categories == []
    assert diff.delta_difference == 0.0