"""Tests for scenarios_with_all_categories batch filter."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import scenarios_with_all_categories


def _scenario(sim_id: int, categories: list[str]) -> WhatIfOut:
    return WhatIfOut(
        simulation_id=sim_id,
        project_id=sim_id,
        meta={"matched_keyword_categories": categories},
    )


def test_filter_keeps_only_scenarios_with_all_categories() -> None:
    scenarios = [
        _scenario(1, ["pricing", "trust"]),
        _scenario(2, ["pricing"]),
        _scenario(3, ["trust"]),
    ]

    filtered = scenarios_with_all_categories(scenarios, ["pricing", "trust"])

    assert [s.simulation_id for s in filtered] == [1]


def test_filter_returns_empty_when_target_categories_empty() -> None:
    """Empty target returns all scenarios (vacuous truth)."""
    scenarios = [_scenario(1, ["pricing"]), _scenario(2, [])]

    filtered = scenarios_with_all_categories(scenarios, [])

    assert [s.simulation_id for s in filtered] == [1, 2]


def test_filter_returns_empty_when_no_scenario_matches() -> None:
    scenarios = [_scenario(1, ["pricing"]), _scenario(2, ["trust"])]

    filtered = scenarios_with_all_categories(scenarios, ["pricing", "trust"])

    assert filtered == []
