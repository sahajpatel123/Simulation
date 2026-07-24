"""Tests for surfacing matched KEYWORD_RULES categories in what-if meta."""
from __future__ import annotations

from typing import Any

from app.simulation.what_if import _matched_keyword_categories, build_what_if_scenario


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


def test_matched_categories_detect_pricing_and_trust() -> None:
    out = build_what_if_scenario(
        simulation_id=1,
        project_id=1,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[
            {"text": "Price is too expensive", "sensitivity": "HIGH", "impact_score": 7},
            {"text": "Reviews and testimonials are missing", "sensitivity": "HIGH", "impact_score": 7},
        ],
    )

    categories = out.meta["matched_keyword_categories"]
    assert "pricing" in categories
    assert "trust" in categories


def test_matched_categories_empty_for_unrelated_text() -> None:
    out = build_what_if_scenario(
        simulation_id=2,
        project_id=2,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[
            {"text": "Random prose about weather", "sensitivity": "LOW", "impact_score": 2},
        ],
    )

    assert out.meta["matched_keyword_categories"] == []


def test_matched_categories_deduped_and_ordered() -> None:
    out = build_what_if_scenario(
        simulation_id=3,
        project_id=3,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[
            {"text": "Pricing is the first concern"},
            {"text": "Pricing again", "sensitivity": "MEDIUM", "impact_score": 5},
            {"text": "Trust is missing"},
        ],
    )

    categories = out.meta["matched_keyword_categories"]
    assert categories.count("pricing") == 1
    assert "trust" in categories
    assert categories.index("pricing") < categories.index("trust")


def test_matched_keyword_categories_helper_directly() -> None:
    assert _matched_keyword_categories("UI is confusing and complex") == ["ux"]
    assert _matched_keyword_categories("Viral word-of-mouth growth") == ["growth"]
    assert _matched_keyword_categories("Nothing relevant here") == []