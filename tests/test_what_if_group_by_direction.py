"""Tests for group_scenarios_by_direction helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import group_scenarios_by_direction


def _scenario(sim_id: int, direction: str | None) -> WhatIfOut:
    meta = {"dominant_direction": direction} if direction else {}
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, meta=meta)


def test_groups_by_dominant_direction() -> None:
    scenarios = [
        _scenario(1, "POSITIVE"),
        _scenario(2, "NEGATIVE"),
        _scenario(3, "POSITIVE"),
        _scenario(4, "NEUTRAL"),
    ]

    grouped = group_scenarios_by_direction(scenarios)

    assert [s.simulation_id for s in grouped["POSITIVE"]] == [1, 3]
    assert [s.simulation_id for s in grouped["NEGATIVE"]] == [2]
    assert [s.simulation_id for s in grouped["NEUTRAL"]] == [4]


def test_missing_direction_falls_through_to_unknown() -> None:
    scenarios = [
        _scenario(1, "POSITIVE"),
        _scenario(2, None),
    ]

    grouped = group_scenarios_by_direction(scenarios)

    assert "UNKNOWN" in grouped
    assert [s.simulation_id for s in grouped["UNKNOWN"]] == [2]


def test_empty_input_returns_empty_dict() -> None:
    assert group_scenarios_by_direction([]) == {}


def test_group_preserves_input_order() -> None:
    scenarios = [
        _scenario(1, "POSITIVE"),
        _scenario(2, "POSITIVE"),
    ]

    grouped = group_scenarios_by_direction(scenarios)

    assert [s.simulation_id for s in grouped["POSITIVE"]] == [1, 2]
