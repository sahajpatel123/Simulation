"""Contract test: WhatIfOut.meta always exposes the documented keys."""
from __future__ import annotations

from typing import Any

from app.simulation.what_if import build_what_if_scenario

_REQUIRED_META_KEYS = {
    "generated_at",
    "base_matrix_conversion",
    "projected_matrix_conversion",
    "existing_assumptions_count",
    "new_assumptions_count",
    "stage_regression_count",
    "stage_improvement_count",
    "net_stage_change",
    "dominant_direction",
    "matched_keyword_categories",
    "sensitivity_score",
    "sensitivity_label",
    "scale_factor_applied",
}


def _base() -> dict[str, Any]:
    return {
        "population_weighted_conversion": 0.05,
        "conversion_rate": 0.05,
        "mean_revenue": 1500.0,
        "product_type_detected": "saas",
    }


def _env() -> dict[str, Any]:
    return {
        "average_order_value": 1500.0,
        "price_sensitivity": 0.5,
        "market_maturity": 0.3,
    }


def test_meta_contract_for_neutral_scenario() -> None:
    out = build_what_if_scenario(
        simulation_id=1,
        project_id=1,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[],
    )

    missing = _REQUIRED_META_KEYS - set(out.meta)
    assert not missing, f"Missing meta keys: {sorted(missing)}"


def test_meta_contract_for_loaded_scenario() -> None:
    out = build_what_if_scenario(
        simulation_id=2,
        project_id=2,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[
            {"text": "Existing trust from prior runs", "sensitivity": "HIGH", "impact_score": 7},
        ],
        new_assumptions=[
            {
                "text": "Pricing is too expensive for tier-3 users",
                "sensitivity": "CRITICAL",
                "impact_score": 9.0,
            },
            {
                "text": "Reviews and testimonials are missing",
                "sensitivity": "HIGH",
                "impact_score": 7.0,
            },
        ],
        override_price_sensitivity=0.8,
    )

    missing = _REQUIRED_META_KEYS - set(out.meta)
    assert not missing, f"Missing meta keys: {sorted(missing)}"
    assert out.meta["sensitivity_label"] == "CRITICAL"
    assert out.meta["dominant_direction"] in {"NEGATIVE", "MIXED"}
    assert len(out.recommendations) <= 6
