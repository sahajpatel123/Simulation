"""Tests for count_by_category helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import count_by_category


def _scenario(sim_id: int, categories: list[str]) -> WhatIfOut:
    return WhatIfOut(
        simulation_id=sim_id,
        project_id=sim_id,
        meta={"matched_keyword_categories": categories},
    )


def test_count_by_category_zero_when_empty_input() -> None:
    assert count_by_category([], "pricing") == 0


def test_count_by_category_counts_matching_scenarios() -> None:
    scenarios = [
        _scenario(1, ["pricing"]),
        _scenario(2, ["pricing", "trust"]),
        _scenario(3, ["ux"]),
    ]

    assert count_by_category(scenarios, "pricing") == 2
    assert count_by_category(scenarios, "trust") == 1
    assert count_by_category(scenarios, "ux") == 1


def test_count_by_category_returns_zero_for_missing_category() -> None:
    scenarios = [_scenario(1, ["pricing"]), _scenario(2, ["trust"])]

    assert count_by_category(scenarios, "ux") == 0
