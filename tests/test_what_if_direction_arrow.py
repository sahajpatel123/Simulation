"""Tests for WhatIfOut.direction_arrow()."""
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


def test_arrow_up_for_positive_delta() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=0.1)
    assert out.direction_arrow() == "↑"


def test_arrow_down_for_negative_delta() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=-0.05)
    assert out.direction_arrow() == "↓"


def test_arrow_right_for_zero_delta() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=0.0)
    assert out.direction_arrow() == "→"


def test_arrow_right_for_tiny_delta() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=1e-12)
    assert out.direction_arrow() == "→"


def test_arrow_in_real_scenarios() -> None:
    pricing_out = build_what_if_scenario(
        simulation_id=1, project_id=1, base_results=_base(),
        env_params=_env(), existing_assumptions=[],
        new_assumptions=[{
            "text": "Pricing too expensive",
            "sensitivity": "CRITICAL",
            "impact_score": 9,
        }],
    )
    assert pricing_out.direction_arrow() == "↓"

    neutral_out = build_what_if_scenario(
        simulation_id=1, project_id=1, base_results=_base(),
        env_params=_env(), existing_assumptions=[], new_assumptions=[],
    )
    assert neutral_out.direction_arrow() in {"→", "↓"}
