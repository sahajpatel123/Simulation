"""Tests for scenarios_average_delta_pct helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import scenarios_average_delta_pct


def _scenario(sim_id: int, delta_pct: float) -> WhatIfOut:
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, conversion_delta_pct=delta_pct)


def test_average_delta_pct_returns_zero_for_empty_input() -> None:
    assert scenarios_average_delta_pct([]) == 0.0


def test_average_delta_pct_returns_single_value() -> None:
    assert scenarios_average_delta_pct([_scenario(1, 12.5)]) == 12.5


def test_average_delta_pct_computes_mean() -> None:
    scenarios = [_scenario(1, 10.0), _scenario(2, 20.0), _scenario(3, 30.0)]

    assert scenarios_average_delta_pct(scenarios) == 20.0


def test_average_delta_pct_handles_negative() -> None:
    scenarios = [_scenario(1, -5.0), _scenario(2, 5.0)]

    assert scenarios_average_delta_pct(scenarios) == 0.0
