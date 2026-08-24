"""Tests for count_by_sensitivity helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import count_by_sensitivity


def _scenario(sim_id: int, sensitivity: str | None) -> WhatIfOut:
    meta = {"sensitivity_label": sensitivity} if sensitivity else {}
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, meta=meta)


def test_count_by_sensitivity_zero_when_empty() -> None:
    assert count_by_sensitivity([], "HIGH") == 0


def test_count_by_sensitivity_counts_matches() -> None:
    scenarios = [
        _scenario(1, "HIGH"),
        _scenario(2, "HIGH"),
        _scenario(3, "LOW"),
    ]

    assert count_by_sensitivity(scenarios, "HIGH") == 2
    assert count_by_sensitivity(scenarios, "LOW") == 1
    assert count_by_sensitivity(scenarios, "CRITICAL") == 0
