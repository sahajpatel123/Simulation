"""Tests for WhatIfOut.has_category()."""
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


def test_has_category_false_when_meta_empty() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1)
    assert out.has_category("pricing") is False


def test_has_category_true_when_present() -> None:
    out = WhatIfOut(
        simulation_id=1,
        project_id=1,
        meta={"matched_keyword_categories": ["pricing", "trust"]},
    )
    assert out.has_category("pricing") is True
    assert out.has_category("trust") is True


def test_has_category_false_when_missing() -> None:
    out = WhatIfOut(
        simulation_id=1,
        project_id=1,
        meta={"matched_keyword_categories": ["pricing"]},
    )
    assert out.has_category("ux") is False


def test_has_category_on_real_pricing_scenario() -> None:
    out = build_what_if_scenario(
        simulation_id=1,
        project_id=1,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[
            {
                "text": "Pricing too expensive",
                "sensitivity": "CRITICAL",
                "impact_score": 9,
            }
        ],
    )

    assert out.has_category("pricing") is True
    assert out.has_category("ux") is False
