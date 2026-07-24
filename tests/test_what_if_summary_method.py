"""Tests for the WhatIfOut.summary() helper."""
from __future__ import annotations

from typing import Any

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import build_what_if_scenario


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


def test_summary_contains_required_keys() -> None:
    out = build_what_if_scenario(
        simulation_id=1,
        project_id=2,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[],
    )

    summary = out.summary()

    assert summary["simulation_id"] == 1
    assert summary["project_id"] == 2
    assert summary["base_conversion_rate"] == out.base_conversion_rate
    assert summary["projected_conversion_rate"] == out.projected_conversion_rate
    assert summary["conversion_delta"] == out.conversion_delta
    assert "dominant_direction" in summary
    assert "sensitivity_label" in summary
    assert "matched_keyword_categories" in summary


def test_summary_lists_keyword_categories_in_order() -> None:
    out = build_what_if_scenario(
        simulation_id=1,
        project_id=1,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[
            {"text": "Pricing too expensive", "sensitivity": "CRITICAL", "impact_score": 9},
            {"text": "UX is confusing", "sensitivity": "HIGH", "impact_score": 7},
        ],
    )

    categories = out.summary()["matched_keyword_categories"]
    assert categories == ["pricing", "ux"]


def test_summary_is_pure_no_mutation() -> None:
    out = WhatIfOut(
        simulation_id=1,
        project_id=1,
        meta={"dominant_direction": "NEUTRAL", "sensitivity_label": "NONE"},
    )

    first = out.summary()
    second = out.summary()

    assert first == second
    assert first["matched_keyword_categories"] == []
    assert second["matched_keyword_categories"] == []