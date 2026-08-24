"""Tests for scenarios_with_sensitivity batch filter."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import scenarios_with_sensitivity


def _scenario(sim_id: int, sensitivity: str | None) -> WhatIfOut:
    meta = {"sensitivity_label": sensitivity} if sensitivity else {}
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, meta=meta)


def test_filter_keeps_scenarios_with_matching_sensitivity() -> None:
    scenarios = [
        _scenario(1, "HIGH"),
        _scenario(2, "LOW"),
        _scenario(3, "HIGH"),
    ]

    filtered = scenarios_with_sensitivity(scenarios, "HIGH")

    assert [s.simulation_id for s in filtered] == [1, 3]


def test_filter_returns_empty_when_no_match() -> None:
    scenarios = [_scenario(1, "HIGH"), _scenario(2, "CRITICAL")]

    filtered = scenarios_with_sensitivity(scenarios, "LOW")

    assert filtered == []


def test_filter_skips_scenarios_without_sensitivity() -> None:
    scenarios = [
        _scenario(1, None),
        _scenario(2, "HIGH"),
    ]

    filtered = scenarios_with_sensitivity(scenarios, "HIGH")

    assert [s.simulation_id for s in filtered] == [2]
