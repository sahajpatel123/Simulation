"""Tests for ``app.simulation.comparison._determine_verdict``.

Locks down the verdict ordering (CLEAR_WINNER > MIXED_BY_CLUSTER > CLOSE_RACE)
and the INSUFFICIENT_DATA short-circuit for fewer than two simulations.
"""
from __future__ import annotations

from typing import Any

from app.simulation.comparison import _determine_verdict


def _sim(
    sim_id: int,
    rate: float,
    *,
    cluster_breakdown: dict[str, float] | None = None,
) -> dict[str, Any]:
    return {
        "simulation_id": sim_id,
        "conversion_rate": rate,
        "cluster_breakdown": cluster_breakdown or {},
    }


def test_single_simulation_is_insufficient() -> None:
    assert _determine_verdict([_sim(1, 0.05)]) == "INSUFFICIENT_DATA"


def test_empty_completed_is_insufficient() -> None:
    assert _determine_verdict([]) == "INSUFFICIENT_DATA"


def test_relative_gap_over_20_percent_is_clear_winner() -> None:
    completed = [_sim(1, 0.10), _sim(2, 0.05)]
    assert _determine_verdict(completed) == "CLEAR_WINNER"


def test_mixed_by_cluster_with_narrow_gap() -> None:
    completed = [
        _sim(1, 0.05, cluster_breakdown={"c1": 0.10, "c2": 0.02}),
        _sim(2, 0.05, cluster_breakdown={"c1": 0.02, "c2": 0.10}),
    ]
    assert _determine_verdict(completed) == "MIXED_BY_CLUSTER"


def test_close_race_within_10_percent() -> None:
    completed = [
        _sim(1, 0.10, cluster_breakdown={"c1": 0.10}),
        _sim(2, 0.095, cluster_breakdown={"c1": 0.095}),
    ]
    assert _determine_verdict(completed) == "CLOSE_RACE"


def test_zero_rates_do_not_trigger_clear_winner() -> None:
    completed = [_sim(1, 0.0), _sim(2, 0.0)]
    assert _determine_verdict(completed) == "CLOSE_RACE"