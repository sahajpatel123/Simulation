"""Tests for scenarios_average_delta helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import scenarios_average_delta


def _scenario(sim_id: int, delta: float) -> WhatIfOut:
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, conversion_delta=delta)


def test_average_returns_zero_for_empty_input() -> None:
    assert scenarios_average_delta([]) == 0.0


def test_average_returns_single_delta() -> None:
    assert scenarios_average_delta([_scenario(1, 0.05)]) == 0.05


def test_average_computes_mean_across_scenarios() -> None:
    scenarios = [_scenario(1, 0.10), _scenario(2, 0.20), _scenario(3, 0.30)]

    assert scenarios_average_delta(scenarios) == 0.20


def test_average_handles_negative_deltas() -> None:
    scenarios = [_scenario(1, -0.05), _scenario(2, 0.05)]

    assert scenarios_average_delta(scenarios) == 0.0
