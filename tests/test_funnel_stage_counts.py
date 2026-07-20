"""Regression tests for _funnel_result_from_conductor.

The Celery task previously fabricated stage_counts using hardcoded fractions
(BROWSE=0.88, CONSIDER=0.62, DECIDE=0.42) regardless of the actual Conductor
result. For a 1% conversion scenario, that narrated 42x more agents reaching
DECIDE than really did. These tests pin the derived-from-conductor behavior.
"""
from __future__ import annotations

import pytest

from app.simulation.conductor import ConductorResult
from app.tasks.simulation_tasks import (
    _derive_chain_scalars,
    _funnel_result_from_conductor,
)


def _cr(pwc: float, overrides: dict[tuple[str, str], float] | None = None) -> ConductorResult:
    return ConductorResult(
        product_type=None,
        cluster_results={},
        population_weighted_conversion=pwc,
        domain_reports=[],
        cluster_breakdown={"c0": pwc * 2.0},
        architect_accountability={},
        per_cluster_matrices={"c0": overrides or {}},
        signal_quality=0.0,
    )


def test_high_conversion_chain_is_monotonic_and_purchase_anchored():
    cr = _cr(0.20, {
        ("ARRIVE", "BROWSE"): 0.95,
        ("BROWSE", "CONSIDER"): 0.80,
        ("CONSIDER", "DECIDE"): 0.70,
        ("DECIDE", "PURCHASE"): 0.50,
    })
    fr = _funnel_result_from_conductor(cr, 10000, {"average_order_value": 999.0}, 42, 1.0)
    sc = fr.stage_counts

    assert sc["ARRIVE"] == 10000
    assert sc["BROWSE"] == 9500
    assert sc["CONSIDER"] == 7600
    assert sc["DECIDE"] == 5320
    assert sc["PURCHASE"] == 2000
    assert sc["PURCHASE"] <= sc["DECIDE"]
    assert sc["DECIDE"] <= sc["CONSIDER"]
    assert sc["CONSIDER"] <= sc["BROWSE"]
    assert sc["BROWSE"] <= sc["ARRIVE"]


def test_low_conversion_does_not_inflate_decide_above_purchase():
    """The pre-fix code reported DECIDE = max(100, int(10000*0.42)) = 4200 for
    a 1% conversion project. Verify the new chain reports DECIDE close to the
    conductor-derived PURCHASE."""
    cr = _cr(0.01, {
        ("ARRIVE", "BROWSE"): 0.40,
        ("BROWSE", "CONSIDER"): 0.30,
        ("CONSIDER", "DECIDE"): 0.20,
        ("DECIDE", "PURCHASE"): 0.20,
    })
    fr = _funnel_result_from_conductor(cr, 10000, {"average_order_value": 999.0}, 42, 1.0)
    sc = fr.stage_counts

    assert sc["PURCHASE"] == 100
    assert sc["DECIDE"] <= sc["PURCHASE"] * 10  # must not be 42x inflated
    assert sc["DECIDE"] >= sc["PURCHASE"]


def test_chain_scalars_fall_back_to_base_when_empty():
    cr = ConductorResult(
        product_type=None,
        cluster_results={},
        population_weighted_conversion=0.05,
        domain_reports=[],
        cluster_breakdown={},
        architect_accountability={},
        per_cluster_matrices={},
        signal_quality=0.0,
    )
    a, b, c, d = _derive_chain_scalars(cr)
    assert a == pytest.approx(0.87)
    assert b == pytest.approx(0.62)
    assert c == pytest.approx(0.46)
    assert d == pytest.approx(0.31)


def test_zero_agents_produces_zero_counts():
    cr = _cr(0.05, {("ARRIVE", "BROWSE"): 0.5})
    fr = _funnel_result_from_conductor(cr, 0, {"average_order_value": 999.0}, 42, 1.0)
    for stage, count in fr.stage_counts.items():
        assert count == 0, f"{stage} expected 0, got {count}"


def test_purchase_equals_converted_even_when_chain_underestimates():
    """When per-cluster override sets drive a high cluster_breakdown ratio
    that the chain product under-estimates, PURCHASE must still match the
    conductor-derived converted count (do not silently under-report)."""
    cr = ConductorResult(
        product_type=None,
        cluster_results={},
        population_weighted_conversion=0.50,
        domain_reports=[],
        cluster_breakdown={"A": 0.10, "B": 0.90},
        architect_accountability={},
        per_cluster_matrices={
            "A": {
                ("ARRIVE", "BROWSE"): 0.90,
                ("BROWSE", "CONSIDER"): 0.80,
                ("CONSIDER", "DECIDE"): 0.70,
                ("DECIDE", "PURCHASE"): 0.30,
            },
            "B": {
                ("ARRIVE", "BROWSE"): 0.40,
                ("BROWSE", "CONSIDER"): 0.30,
                ("CONSIDER", "DECIDE"): 0.20,
                ("DECIDE", "PURCHASE"): 0.95,
            },
        },
        signal_quality=0.0,
    )
    fr = _funnel_result_from_conductor(cr, 10000, {"average_order_value": 999.0}, 42, 1.0)
    assert fr.stage_counts["PURCHASE"] == 5000
    assert fr.converted == 5000
    assert fr.stage_counts["ABANDON"] == 5000
