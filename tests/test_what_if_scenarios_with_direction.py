"""Tests for scenarios_with_direction batch filter."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import scenarios_with_direction


def _scenario(sim_id: int, direction: str | None) -> WhatIfOut:
    meta = {"dominant_direction": direction} if direction else {}
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, meta=meta)


def test_filter_keeps_scenarios_with_matching_direction() -> None:
    scenarios = [
        _scenario(1, "POSITIVE"),
        _scenario(2, "NEGATIVE"),
        _scenario(3, "POSITIVE"),
    ]

    filtered = scenarios_with_direction(scenarios, "POSITIVE")

    assert [s.simulation_id for s in filtered] == [1, 3]


def test_filter_returns_empty_when_no_match() -> None:
    scenarios = [
        _scenario(1, "POSITIVE"),
        _scenario(2, "NEGATIVE"),
    ]

    filtered = scenarios_with_direction(scenarios, "NEUTRAL")

    assert filtered == []


def test_filter_skips_scenarios_without_direction() -> None:
    scenarios = [
        _scenario(1, None),
        _scenario(2, "POSITIVE"),
    ]

    filtered = scenarios_with_direction(scenarios, "POSITIVE")

    assert [s.simulation_id for s in filtered] == [2]
