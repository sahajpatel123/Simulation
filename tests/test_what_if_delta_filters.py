"""Tests for scenarios_with_positive_delta / scenarios_with_negative_delta."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import (
    scenarios_with_negative_delta,
    scenarios_with_positive_delta,
)


def _scenario(sim_id: int, delta: float) -> WhatIfOut:
    return WhatIfOut(
        simulation_id=sim_id,
        project_id=sim_id,
        conversion_delta=delta,
    )


def test_positive_delta_filter_keeps_only_positive() -> None:
    scenarios = [_scenario(1, 0.05), _scenario(2, -0.05), _scenario(3, 0.0), _scenario(4, 0.10)]

    filtered = scenarios_with_positive_delta(scenarios)

    assert [s.simulation_id for s in filtered] == [1, 4]


def test_negative_delta_filter_keeps_only_negative() -> None:
    scenarios = [_scenario(1, 0.05), _scenario(2, -0.05), _scenario(3, 0.0), _scenario(4, -0.10)]

    filtered = scenarios_with_negative_delta(scenarios)

    assert [s.simulation_id for s in filtered] == [2, 4]


def test_filters_are_mutually_exclusive_with_neutral() -> None:
    scenarios = [_scenario(1, 0.05), _scenario(2, -0.05), _scenario(3, 0.0)]

    pos = scenarios_with_positive_delta(scenarios)
    neg = scenarios_with_negative_delta(scenarios)

    assert sum(len(s) for s in (pos, neg)) == 2