"""Tests for the WhatIfOut.to_log_line() helper."""
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


def test_log_line_for_default_scenario() -> None:
    out = build_what_if_scenario(
        simulation_id=1,
        project_id=2,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[],
    )

    line = out.to_log_line()

    assert line.startswith("what-if sim=1 ")
    assert "base=" in line
    assert "projected=" in line
    assert "delta_pct=" in line
    assert "direction=" in line
    assert "sensitivity=" in line


def test_log_line_includes_signed_delta_pct() -> None:
    out = build_what_if_scenario(
        simulation_id=1,
        project_id=1,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[{
            "text": "Pricing too expensive",
            "sensitivity": "CRITICAL",
            "impact_score": 9,
        }],
    )

    line = out.to_log_line()

    assert "delta_pct=-" in line
    assert "direction=" in line


def test_log_line_falls_back_when_meta_missing() -> None:
    out = WhatIfOut(simulation_id=42, project_id=42)

    line = out.to_log_line()

    assert "direction=NEUTRAL" in line
    assert "sensitivity=NONE" in line
    assert "sim=42" in line