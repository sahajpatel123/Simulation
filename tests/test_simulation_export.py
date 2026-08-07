"""Tests for the pure per-simulation export helpers."""
from __future__ import annotations

from typing import Any

import pytest
from app.simulation.simulation_export import (
    build_simulation_export,
    simulation_to_csv,
)


def _results() -> dict[str, Any]:
    return {
        "population_weighted_conversion": 0.042,
        "product_type_detected": "saas",
        "cluster_breakdown": {
            "metro_power_professional": 0.061,
            "tier3_first_time_app_user": {
                "conversion_rate": 0.03,
                "population_weight": 0.012,
            },
        },
    }


def test_build_simulation_export_returns_rows() -> None:
    export = build_simulation_export(
        _results(),
        simulation_id=7,
        project_id=10,
        product_type="saas",
        signal_quality=0.62,
        cluster_names={"metro_power_professional": "Metro Pro"},
        cluster_weights={
            "metro_power_professional": 0.5,
            "tier3_first_time_app_user": 0.01,
        },
    )

    assert export["simulation_id"] == 7
    assert export["project_id"] == 10
    assert export["product_type"] == "saas"
    assert export["signal_quality"] == 0.62
    assert export["population_weighted_conversion"] == pytest.approx(0.042)
    assert export["total_clusters"] == 2
    assert export["rows"][0]["cluster_id"] == "metro_power_professional"
    assert export["rows"][0]["cluster_name"] == "Metro Pro"
    assert export["rows"][0]["conversion_rate"] == pytest.approx(0.061)
    assert export["rows"][1]["cluster_name"] == "tier3_first_time_app_user"


def test_missing_cluster_breakdown_returns_empty_rows() -> None:
    export = build_simulation_export(
        {"population_weighted_conversion": 0.04},
        simulation_id=1,
        project_id=2,
    )

    assert export["total_clusters"] == 0
    assert export["rows"] == []
    assert export["population_weighted_conversion"] == 0.04


def test_malformed_values_are_sanitized() -> None:
    export = build_simulation_export(
        {
            "population_weighted_conversion": float("nan"),
            "cluster_breakdown": {
                "a": {"conversion_rate": float("inf"), "population_weight": -1.0}
            },
        },
        simulation_id=1,
        project_id=2,
        signal_quality="not-a-number",
    )

    assert export["signal_quality"] is None
    assert export["population_weighted_conversion"] == 0.0
    assert export["rows"][0]["conversion_rate"] == 0.0
    assert export["rows"][0]["population_weight"] == 0.0


def test_csv_contains_header_and_rows() -> None:
    export = build_simulation_export(
        _results(),
        simulation_id=7,
        project_id=10,
        product_type="saas",
        signal_quality=0.62,
    )
    csv_text = simulation_to_csv(export, metadata={"generated_at": "now", "user_id": 42})

    assert "simulation_id,project_id,status,product_type" in csv_text
    assert "metro_power_professional" in csv_text
    assert "tier3_first_time_app_user" in csv_text
    assert "generated_at,now" in csv_text
