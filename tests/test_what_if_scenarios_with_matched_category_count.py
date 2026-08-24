"""Tests for scenarios_with_matched_category_count batch filter."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import scenarios_with_matched_category_count


def _scenario(sim_id: int, categories: list[str]) -> WhatIfOut:
    return WhatIfOut(
        simulation_id=sim_id,
        project_id=sim_id,
        meta={"matched_keyword_categories": categories},
    )


def test_filter_keeps_only_scenarios_matching_all_categories() -> None:
    scenarios = [
        _scenario(1, ["pricing", "trust"]),
        _scenario(2, ["pricing"]),
        _scenario(3, ["pricing", "trust", "ux"]),
    ]

    filtered = scenarios_with_matched_category_count(scenarios, ["pricing", "trust"])

    assert [s.simulation_id for s in filtered] == [1, 3]


def test_filter_returns_empty_when_no_match() -> None:
    scenarios = [
        _scenario(1, ["pricing"]),
        _scenario(2, ["trust"]),
    ]

    filtered = scenarios_with_matched_category_count(scenarios, ["pricing", "trust"])

    assert filtered == []


def test_filter_returns_empty_for_empty_input() -> None:
    assert scenarios_with_matched_category_count([], ["pricing"]) == []


def test_filter_skips_scenarios_without_categories() -> None:
    scenarios = [
        _scenario(1, []),
        _scenario(2, ["pricing"]),
    ]

    filtered = scenarios_with_matched_category_count(scenarios, ["pricing"])

    assert [s.simulation_id for s in filtered] == [2]
