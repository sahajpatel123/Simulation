"""Tests for scenarios_with_any_category and has_category_any helpers."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import scenarios_with_any_category


def _scenario(sim_id: int, categories: list[str]) -> WhatIfOut:
    return WhatIfOut(
        simulation_id=sim_id,
        project_id=sim_id,
        meta={"matched_keyword_categories": categories},
    )


def test_filter_matches_any_category() -> None:
    scenarios = [
        _scenario(1, ["pricing"]),
        _scenario(2, ["trust"]),
        _scenario(3, ["ux"]),
    ]

    filtered = scenarios_with_any_category(scenarios, ["pricing", "trust"])

    assert [s.simulation_id for s in filtered] == [1, 2]


def test_filter_returns_empty_when_no_categories_match() -> None:
    scenarios = [_scenario(1, ["ux"]), _scenario(2, ["growth"])]

    filtered = scenarios_with_any_category(scenarios, ["pricing", "trust"])

    assert filtered == []


def test_filter_returns_empty_when_target_categories_empty() -> None:
    scenarios = [_scenario(1, ["pricing"])]

    filtered = scenarios_with_any_category(scenarios, [])

    assert filtered == []


def test_filter_matches_scenario_with_multiple_categories() -> None:
    scenarios = [_scenario(1, ["pricing", "trust", "ux"])]

    filtered = scenarios_with_any_category(scenarios, ["trust"])

    assert [s.simulation_id for s in filtered] == [1]
