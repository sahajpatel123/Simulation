"""Tests for scenarios_with_category helper."""
from __future__ import annotations

from typing import Any

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import (
    build_what_if_scenario,
    scenarios_with_category,
)


def _meta(category: str) -> dict[str, Any]:
    return {
        "dominant_direction": "POSITIVE",
        "sensitivity_label": "HIGH",
        "matched_keyword_categories": [category],
    }


def test_filter_returns_only_scenarios_with_category() -> None:
    a = WhatIfOut(simulation_id=1, project_id=1, meta=_meta("pricing"))
    b = WhatIfOut(simulation_id=2, project_id=2, meta=_meta("trust"))
    c = WhatIfOut(simulation_id=3, project_id=3, meta=_meta("pricing"))

    filtered = scenarios_with_category([a, b, c], "pricing")

    assert [s.simulation_id for s in filtered] == [1, 3]


def test_filter_returns_empty_when_no_matches() -> None:
    a = WhatIfOut(simulation_id=1, project_id=1, meta=_meta("ux"))
    b = WhatIfOut(simulation_id=2, project_id=2, meta=_meta("trust"))

    filtered = scenarios_with_category([a, b], "pricing")

    assert filtered == []


def test_filter_on_real_scenarios() -> None:
    base = {
        "population_weighted_conversion": 0.05,
        "conversion_rate": 0.05,
        "mean_revenue": 999.0,
        "product_type_detected": "saas",
    }
    env = {
        "average_order_value": 999.0,
        "price_sensitivity": 0.5,
        "market_maturity": 0.3,
    }
    pricing = build_what_if_scenario(
        simulation_id=1, project_id=1, base_results=base, env_params=env,
        existing_assumptions=[],
        new_assumptions=[{"text": "Pricing too expensive", "sensitivity": "CRITICAL", "impact_score": 9}],
    )
    neutral = build_what_if_scenario(
        simulation_id=2, project_id=2, base_results=base, env_params=env,
        existing_assumptions=[], new_assumptions=[],
    )

    filtered = scenarios_with_category([pricing, neutral], "pricing")

    assert [s.simulation_id for s in filtered] == [1]
