"""Pure-helper tests for the batch what-if scenario comparison feature."""
from __future__ import annotations

from typing import Any

from app.schemas.what_if import WhatIfAssumption
from app.schemas.what_if_batch import (
    WhatIfBatchOut,
    WhatIfBatchScenarioInput,
)
from app.simulation.what_if_batch import build_what_if_batch


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


def _scenario(label: str, assumption: str, sensitivity: str = "HIGH") -> dict[str, Any]:
    return {
        "label": label,
        "assumptions": [
            {
                "text": assumption,
                "sensitivity": sensitivity,
                "impact_score": 8.0,
            }
        ],
        "override_price_sensitivity": None,
        "override_market_maturity": None,
    }


def test_batch_ranks_positive_above_negative() -> None:
    out = build_what_if_batch(
        simulation_id=1,
        project_id=2,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        scenarios=[
            _scenario("pricing", "Pricing too expensive"),
            _scenario("demand", "Strong market demand for this product"),
        ],
    )

    assert isinstance(out, WhatIfBatchOut)
    assert out.simulation_id == 1
    assert out.project_id == 2
    assert out.status == "COMPLETED"
    assert out.summary.scenario_count == 2
    assert [s.label for s in out.scenarios] == ["demand", "pricing"]
    assert out.best_scenario is not None
    assert out.best_scenario.label == "demand"
    assert out.worst_scenario is not None
    assert out.worst_scenario.label == "pricing"
    assert out.scenarios[0].scenario.conversion_delta > out.scenarios[1].scenario.conversion_delta


def test_batch_empty_returns_empty_ranked_list() -> None:
    out = build_what_if_batch(
        simulation_id=1,
        project_id=2,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        scenarios=[],
    )

    assert out.summary.scenario_count == 0
    assert out.scenarios == []
    assert out.best_scenario is None
    assert out.worst_scenario is None


def test_batch_auto_labels_when_missing() -> None:
    out = build_what_if_batch(
        simulation_id=1,
        project_id=2,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        scenarios=[
            {
                "label": "",
                "assumptions": [],
                "override_price_sensitivity": 0.9,
                "override_market_maturity": None,
            },
            {
                "label": "   ",
                "assumptions": [],
                "override_price_sensitivity": None,
                "override_market_maturity": 0.8,
            },
        ],
    )

    assert {s.label for s in out.scenarios} == {"Scenario 1", "Scenario 2"}


def test_batch_keeps_full_scenario_payload() -> None:
    out = build_what_if_batch(
        simulation_id=7,
        project_id=9,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        scenarios=[_scenario("demand", "Strong market demand for this product")],
    )

    scenario = out.scenarios[0].scenario
    assert scenario.simulation_id == 7
    assert scenario.project_id == 9
    assert scenario.projected_conversion_rate > 0
    assert scenario.recommendations
    assert scenario.meta["dominant_direction"] in {
        "POSITIVE",
        "NEUTRAL",
        "NEGATIVE",
        "MIXED",
    }


def test_lowercase_sensitivity_matches_uppercase_weight() -> None:
    """Lowercase sensitivity labels must be normalised to the canonical weight."""
    upper = build_what_if_batch(
        simulation_id=1,
        project_id=2,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        scenarios=[
            _scenario("pricing", "Pricing too expensive", sensitivity="HIGH")
        ],
    )
    lower = build_what_if_batch(
        simulation_id=1,
        project_id=2,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        scenarios=[
            _scenario("pricing", "Pricing too expensive", sensitivity="high")
        ],
    )

    assert lower.scenarios[0].scenario.conversion_delta == upper.scenarios[
        0
    ].scenario.conversion_delta
    assert (
        lower.scenarios[0].scenario.meta["sensitivity_label"]
        == upper.scenarios[0].scenario.meta["sensitivity_label"]
        == "HIGH"
    )


def test_batch_accepts_pydantic_scenario_models() -> None:
    """The batch helper should accept schema models directly (route passes raw models)."""
    out = build_what_if_batch(
        simulation_id=1,
        project_id=2,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        scenarios=[
            WhatIfBatchScenarioInput(
                label="demand",
                assumptions=[
                    WhatIfAssumption(
                        text="Strong market demand for this product",
                        sensitivity="HIGH",
                        impact_score=8.0,
                    )
                ],
            ),
            WhatIfBatchScenarioInput(
                label="pricing",
                assumptions=[
                    WhatIfAssumption(
                        text="Pricing too expensive",
                        sensitivity="HIGH",
                        impact_score=8.0,
                    )
                ],
            ),
        ],
    )

    assert [s.label for s in out.scenarios] == ["demand", "pricing"]
    assert out.scenarios[0].scenario.meta["new_assumptions_count"] == 1
