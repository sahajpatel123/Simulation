"""Tests for aggregate sensitivity score/label in WhatIfOut.meta."""
from __future__ import annotations

from typing import Any

from app.simulation.markov import SENSITIVITY_WEIGHTS
from app.simulation.what_if import _aggregate_sensitivity, build_what_if_scenario


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


def test_empty_assumptions_yields_none() -> None:
    score, label = _aggregate_sensitivity([])
    assert score == 0.0
    assert label == "NONE"


def test_aggregate_picks_heaviest_label() -> None:
    score, label = _aggregate_sensitivity([
        {"text": "Pricing matters", "sensitivity": "LOW", "impact_score": 2},
        {"text": "Trust matters", "sensitivity": "CRITICAL", "impact_score": 9},
    ])

    assert label == "CRITICAL"
    assert score == SENSITIVITY_WEIGHTS["CRITICAL"]


def test_aggregate_falls_back_to_none_for_unknown_label() -> None:
    score, label = _aggregate_sensitivity([
        {"text": "Anything", "sensitivity": "UNKNOWN", "impact_score": 5},
    ])

    assert score == 0.0
    assert label == "NONE"


def test_what_if_response_includes_sensitivity_meta() -> None:
    out = build_what_if_scenario(
        simulation_id=1,
        project_id=1,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[
            {"text": "Pricing is too expensive", "sensitivity": "HIGH", "impact_score": 7},
        ],
    )

    assert out.meta["sensitivity_label"] == "HIGH"
    assert out.meta["sensitivity_score"] == SENSITIVITY_WEIGHTS["HIGH"]


def test_what_if_response_with_no_assumptions() -> None:
    out = build_what_if_scenario(
        simulation_id=2,
        project_id=2,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[],
    )

    assert out.meta["sensitivity_label"] == "NONE"
    assert out.meta["sensitivity_score"] == 0.0