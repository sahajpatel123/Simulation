"""Tests for count_with_matched_categories helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import count_with_matched_categories


def _scenario(sim_id: int, categories: list[str]) -> WhatIfOut:
    return WhatIfOut(
        simulation_id=sim_id,
        project_id=sim_id,
        meta={"matched_keyword_categories": categories},
    )


def test_count_zero_when_empty_input() -> None:
    assert count_with_matched_categories([], ["pricing"]) == 0


def test_count_zero_when_no_scenario_matches_all() -> None:
    scenarios = [
        _scenario(1, ["pricing"]),
        _scenario(2, ["trust"]),
    ]

    assert count_with_matched_categories(scenarios, ["pricing", "trust"]) == 0


def test_count_scenarios_matching_all_categories() -> None:
    scenarios = [
        _scenario(1, ["pricing", "trust"]),
        _scenario(2, ["pricing"]),
        _scenario(3, ["pricing", "trust", "ux"]),
    ]

    assert count_with_matched_categories(scenarios, ["pricing", "trust"]) == 2
