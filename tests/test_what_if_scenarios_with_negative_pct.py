"""Tests for scenarios_with_negative_pct batch filter."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import scenarios_with_negative_pct


def _scenario(sim_id: int, delta_pct: float) -> WhatIfOut:
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, conversion_delta_pct=delta_pct)


def test_filter_keeps_only_negative_pct_scenarios() -> None:
    scenarios = [
        _scenario(1, -12.5),
        _scenario(2, 5.0),
        _scenario(3, 0.0),
        _scenario(4, -7.2),
    ]

    filtered = scenarios_with_negative_pct(scenarios)

    assert [s.simulation_id for s in filtered] == [1, 4]


def test_filter_returns_empty_when_no_negative() -> None:
    scenarios = [_scenario(1, 5.0), _scenario(2, 0.0)]

    assert scenarios_with_negative_pct(scenarios) == []


def test_filter_returns_empty_for_empty_input() -> None:
    assert scenarios_with_negative_pct([]) == []
