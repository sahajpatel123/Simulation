"""Tests for scenarios_with_any_category_count helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import scenarios_with_any_category_count


def _scenario(sim_id: int, categories: list[str]) -> WhatIfOut:
    return WhatIfOut(
        simulation_id=sim_id,
        project_id=sim_id,
        meta={"matched_keyword_categories": categories},
    )


def test_count_zero_when_empty_input() -> None:
    assert scenarios_with_any_category_count([], ["pricing"]) == 0


def test_count_zero_when_no_match() -> None:
    scenarios = [_scenario(1, ["ux"]), _scenario(2, ["growth"])]

    assert scenarios_with_any_category_count(scenarios, ["pricing", "trust"]) == 0


def test_count_matches_when_any_category_present() -> None:
    scenarios = [
        _scenario(1, ["pricing"]),
        _scenario(2, ["trust"]),
        _scenario(3, ["ux"]),
        _scenario(4, ["pricing", "ux"]),
    ]

    # scenarios 1, 2, and 4 each have at least one of pricing/trust
    assert scenarios_with_any_category_count(scenarios, ["pricing", "trust"]) == 3
