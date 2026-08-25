"""Tests for all_assumption_texts helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfAssumption, WhatIfOut
from app.simulation.what_if import all_assumption_texts


def _scenario(sim_id: int, texts: list[str]) -> WhatIfOut:
    return WhatIfOut(
        simulation_id=sim_id,
        project_id=sim_id,
        assumptions_applied=[
            WhatIfAssumption(text=text, sensitivity="HIGH", impact_score=5)
            for text in texts
        ],
    )


def test_all_assumption_texts_empty_when_empty_input() -> None:
    assert all_assumption_texts([]) == []


def test_all_assumption_texts_empty_when_no_assumptions() -> None:
    scenarios = [_scenario(1, []), _scenario(2, [])]

    assert all_assumption_texts(scenarios) == []


def test_all_assumption_texts_returns_all_in_input_order() -> None:
    scenarios = [
        _scenario(1, ["first", "second"]),
        _scenario(2, ["third"]),
        _scenario(3, []),
        _scenario(4, ["fourth"]),
    ]

    assert all_assumption_texts(scenarios) == ["first", "second", "third", "fourth"]
