"""Tests for WhatIfOut CSV export helpers."""
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


def test_csv_header_has_nine_columns() -> None:
    header = WhatIfOut.to_csv_header()
    assert len(header) == 9
    assert header[0] == "simulation_id"
    assert header[-1] == "matched_keyword_categories"


def test_csv_row_matches_header_length() -> None:
    out = WhatIfOut(
        simulation_id=1,
        project_id=2,
        base_conversion_rate=0.05,
        projected_conversion_rate=0.06,
        conversion_delta=0.01,
        conversion_delta_pct=20.0,
        meta={"dominant_direction": "POSITIVE", "sensitivity_label": "HIGH"},
    )

    row = out.to_csv_row()
    assert len(row) == len(WhatIfOut.to_csv_header())


def test_csv_row_values_for_neutral_scenario() -> None:
    out = build_what_if_scenario(
        simulation_id=7,
        project_id=8,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[],
    )

    row = out.to_csv_row()

    assert row[0] == "7"
    assert row[1] == "8"
    assert float(row[2]) == out.base_conversion_rate
    assert float(row[3]) == out.projected_conversion_rate
    assert float(row[4]) == out.conversion_delta
    assert row[6] == "NEUTRAL"
    assert row[7] == "NONE"
    assert row[8] == ""


def test_csv_row_joins_categories_with_pipe() -> None:
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

    row = out.to_csv_row()

    assert "pricing" in row[8]
    assert "ux" in row[8]
    assert "|" in row[8]