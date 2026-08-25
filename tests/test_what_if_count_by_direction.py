"""Tests for count_by_direction helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import count_by_direction


def _scenario(sim_id: int, direction: str | None) -> WhatIfOut:
    meta = {"dominant_direction": direction} if direction else {}
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, meta=meta)


def test_count_by_direction_zero_when_empty() -> None:
    assert count_by_direction([], "POSITIVE") == 0


def test_count_by_direction_counts_matches() -> None:
    scenarios = [
        _scenario(1, "POSITIVE"),
        _scenario(2, "POSITIVE"),
        _scenario(3, "NEGATIVE"),
    ]

    assert count_by_direction(scenarios, "POSITIVE") == 2
    assert count_by_direction(scenarios, "NEGATIVE") == 1
    assert count_by_direction(scenarios, "NEUTRAL") == 0
