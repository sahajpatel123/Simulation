"""
Tests for what-if scenario simulator helpers
(cycle 30 what-if-scenario).
"""
from __future__ import annotations

from typing import Any

import pytest

from app.schemas.what_if import WhatIfAssumption, WhatIfRequest
from app.simulation.what_if import build_what_if_scenario


def _base(
    *,
    cr: float = 0.05,
    aov: float = 999.0,
) -> dict[str, Any]:
    return {
        "population_weighted_conversion": cr,
        "conversion_rate": cr,
        "mean_revenue": aov,
        "product_type_detected": "saas",
    }


def _env(**overrides: float) -> dict[str, Any]:
    base = {
        "average_order_value": 999.0,
        "price_sensitivity": 0.5,
        "market_maturity": 0.3,
    }
    base.update(overrides)
    return base


def test_empty_changes_are_neutral() -> None:
    out = build_what_if_scenario(
        simulation_id=1,
        project_id=2,
        base_results=_base(cr=0.05),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[],
    )
    assert out.base_conversion_rate == pytest.approx(0.05)
    assert out.conversion_delta == pytest.approx(0.0, abs=1e-6)
    assert out.recommendations[0].estimated_lift == 0.0
    assert "No assumptions" in out.recommendations[0].rationale


def test_pricing_assumption_reduces_projected_conversion() -> None:
    out = build_what_if_scenario(
        simulation_id=1,
        project_id=2,
        base_results=_base(cr=0.06),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[
            {
                "text": "Users will pay ₹999 without a free trial — expensive for tier-2",
                "sensitivity": "CRITICAL",
                "impact_score": 9.0,
            }
        ],
    )
    assert out.conversion_delta < 0
    assert out.projected_conversion_rate < out.base_conversion_rate
    decide = next(s for s in out.stage_impacts if s.stage == "DECIDE")
    assert decide.delta < 0
    assert out.assumptions_applied[0].sensitivity == "CRITICAL"
    assert "Negative impact" in out.recommendations[0].title


def test_env_price_sensitivity_override_moves_conversion() -> None:
    low = build_what_if_scenario(
        simulation_id=1,
        project_id=2,
        base_results=_base(cr=0.05),
        env_params=_env(price_sensitivity=0.3),
        existing_assumptions=[],
        new_assumptions=[],
        override_price_sensitivity=0.9,
    )
    assert low.env_overrides["price_sensitivity"] == 0.9
    assert low.conversion_delta < 0
    assert low.projected_conversion_rate < low.base_conversion_rate


def test_lower_price_sensitivity_improves_conversion() -> None:
    out = build_what_if_scenario(
        simulation_id=1,
        project_id=2,
        base_results=_base(cr=0.04),
        env_params=_env(price_sensitivity=0.8),
        existing_assumptions=[],
        new_assumptions=[],
        override_price_sensitivity=0.1,
    )
    assert out.conversion_delta > 0
    assert "Positive impact" in out.recommendations[0].title


def test_existing_assumptions_counted_in_meta() -> None:
    out = build_what_if_scenario(
        simulation_id=3,
        project_id=4,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[
            {"text": "Trusted brand with 10k reviews", "sensitivity": "HIGH", "impact_score": 7},
            {"text": "Price is competitive at ₹499", "sensitivity": "MEDIUM", "impact_score": 5},
        ],
        new_assumptions=[
            {"text": "UX is confusing on mobile", "sensitivity": "HIGH", "impact_score": 8},
        ],
    )
    assert out.meta["existing_assumptions_count"] == 2
    assert out.meta["new_assumptions_count"] == 1
    assert out.simulation_id == 3
    assert len(out.stage_impacts) == 4


def test_assumption_objects_with_attributes() -> None:
    class _A:
        def __init__(self) -> None:
            self.text = "Users will return monthly due to loyalty rewards"
            self.sensitivity = "medium"
            self.impact_score = 6.0

    out = build_what_if_scenario(
        simulation_id=5,
        project_id=5,
        base_results=_base(cr=0.05),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[_A()],
    )
    assert out.meta["new_assumptions_count"] == 1
    assert out.assumptions_applied[0].text.startswith("Users will return")


def test_json_string_results_and_missing_cr_fallback() -> None:
    import json

    raw = json.dumps({"product_type_detected": "saas"})
    out = build_what_if_scenario(
        simulation_id=6,
        project_id=6,
        base_results=raw,
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[],
    )
    assert out.base_conversion_rate > 0
    assert out.projected_conversion_rate > 0


def test_revenue_projections_scale_with_aov() -> None:
    out = build_what_if_scenario(
        simulation_id=7,
        project_id=7,
        base_results=_base(cr=0.10, aov=2000.0),
        env_params=_env(average_order_value=2000.0),
        existing_assumptions=[],
        new_assumptions=[],
    )
    assert out.base_revenue_per_1000 == pytest.approx(0.10 * 1000 * 2000.0)


def test_request_schema_bounds() -> None:
    req = WhatIfRequest(
        assumptions=[
            WhatIfAssumption(text="Price is too expensive for students", impact_score=8)
        ],
        override_price_sensitivity=0.7,
    )
    assert len(req.assumptions) == 1
    with pytest.raises(Exception):
        WhatIfAssumption(text="ab")  # too short


def test_schema_round_trip() -> None:
    out = build_what_if_scenario(
        simulation_id=8,
        project_id=8,
        base_results=_base(cr=0.05),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[
            {
                "text": "No credible reviews or testimonials on the landing page",
                "sensitivity": "HIGH",
                "impact_score": 7,
            }
        ],
    )
    dumped = out.model_dump()
    assert dumped["simulation_id"] == 8
    assert "generated_at" in dumped["meta"]
    assert isinstance(dumped["stage_impacts"], list)
    assert isinstance(dumped["recommendations"], list)
