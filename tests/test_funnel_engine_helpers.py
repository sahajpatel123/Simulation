"""
Tests for FunnelExecutionEngine helpers and result dataclasses
(cycle 35 funnel-engine-test-coverage).

The existing ``test_funnel_stage_counts.py`` covers the high-level
``_funnel_result_from_conductor`` used by Celery; this suite focuses on
the engine's pure helpers that don't need a process pool:

  1. ``_derive_assumption_impact`` maps CRITICAL/HIGH/MEDIUM/LOW to weights.
  2. ``_derive_product_strength`` clamps between 0.15 and 0.90 and penalises
     CRITICAL/HIGH counts.
  3. ``_build_stage_metrics`` produces the right entry_rate and drop_off_rate.
  4. ``_build_demographic_breakdown`` groups raw results by demographic key.
  5. Result dataclasses round-trip via Pydantic-style dataclass semantics.
  6. ``run_batch`` raises on empty agent list.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.simulation.funnel import (
    DemographicBreakdown,
    FunnelExecutionEngine,
    StageMetrics,
)


# ---------------------------------------------------------------------------
# _derive_assumption_impact
# ---------------------------------------------------------------------------


def test_derive_assumption_impact_empty_input() -> None:
    engine = FunnelExecutionEngine(num_workers=1)
    assert engine._derive_assumption_impact([]) == {}


def test_derive_assumption_impact_critical_is_most_negative() -> None:
    engine = FunnelExecutionEngine(num_workers=1)
    impact = engine._derive_assumption_impact(
        [
            {"id": 1, "sensitivity": "CRITICAL", "impact_score": 10.0},
            {"id": 2, "sensitivity": "HIGH", "impact_score": 10.0},
            {"id": 3, "sensitivity": "MEDIUM", "impact_score": 10.0},
            {"id": 4, "sensitivity": "LOW", "impact_score": 10.0},
        ]
    )
    keys = {k.split("_", 1)[0]: v for k, v in impact.items()}
    # All values negative (impact weights).
    assert all(v < 0.0 for v in impact.values())
    # CRITICAL < HIGH < MEDIUM < LOW (more critical = more negative).
    assert keys["CRITICAL"] < keys["HIGH"] < keys["MEDIUM"] < keys["LOW"]


def test_derive_assumption_impact_uses_impact_score() -> None:
    engine = FunnelExecutionEngine(num_workers=1)
    low_score = engine._derive_assumption_impact(
        [{"id": 1, "sensitivity": "HIGH", "impact_score": 1.0}]
    )
    high_score = engine._derive_assumption_impact(
        [{"id": 1, "sensitivity": "HIGH", "impact_score": 10.0}]
    )
    low_v = next(iter(low_score.values()))
    high_v = next(iter(high_score.values()))
    assert abs(high_v) > abs(low_v)


def test_derive_assumption_impact_unknown_sensitivity_defaults_to_medium_weight() -> None:
    engine = FunnelExecutionEngine(num_workers=1)
    impact = engine._derive_assumption_impact(
        [{"id": 1, "sensitivity": "UNKNOWN_BUCKET", "impact_score": 5.0}]
    )
    # Defaults to MEDIUM weight (-0.03) × impact_score/10 = -0.015.
    assert next(iter(impact.values())) == pytest.approx(-0.015, abs=1e-9)


def test_derive_assumption_impact_missing_id_falls_back_to_object_id() -> None:
    engine = FunnelExecutionEngine(num_workers=1)
    impact = engine._derive_assumption_impact(
        [{"sensitivity": "HIGH", "impact_score": 5.0}]  # no id key
    )
    assert len(impact) == 1
    # Key begins with HIGH_<something>.
    key = next(iter(impact.keys()))
    assert key.startswith("HIGH_")


# ---------------------------------------------------------------------------
# _derive_product_strength
# ---------------------------------------------------------------------------


def test_derive_product_strength_empty_defaults_to_baseline() -> None:
    engine = FunnelExecutionEngine(num_workers=1)
    assert engine._derive_product_strength([]) == 0.65


def test_derive_product_strength_penalises_many_critical_assumptions() -> None:
    """The formula is 0.85 - critical*0.08 - high*0.04 clamped to [0.15, 0.90].
    Three CRITICAL assumptions yield 0.85 - 0.24 = 0.61, which is below the
    no-assumption baseline of 0.65."""
    engine = FunnelExecutionEngine(num_workers=1)
    baseline = engine._derive_product_strength([])
    many_criticals = engine._derive_product_strength(
        [{"sensitivity": "CRITICAL", "impact_score": 9.0} for _ in range(3)]
    )
    assert many_criticals < baseline
    # Strength of 1 critical is 0.85 - 0.08 = 0.77, still above baseline.
    one_critical = engine._derive_product_strength(
        [{"sensitivity": "CRITICAL", "impact_score": 9.0}]
    )
    assert one_critical > baseline


def test_derive_product_strength_floor_at_0_15() -> None:
    """Many CRITICAL assumptions should floor at 0.15, never go below."""
    engine = FunnelExecutionEngine(num_workers=1)
    many_criticals = [
        {"sensitivity": "CRITICAL", "impact_score": 9.0} for _ in range(20)
    ]
    strength = engine._derive_product_strength(many_criticals)
    assert strength >= 0.15


def test_derive_product_strength_ceiling_at_0_90() -> None:
    """No assumptions → 0.65 baseline; nothing raises it above 0.90."""
    engine = FunnelExecutionEngine(num_workers=1)
    assert engine._derive_product_strength([]) <= 0.90


# ---------------------------------------------------------------------------
# _build_stage_metrics
# ---------------------------------------------------------------------------


def test_build_stage_metrics_returns_one_per_state() -> None:
    engine = FunnelExecutionEngine(num_workers=1)
    from app.simulation.markov import STATES

    counts = {s.value: 100 for s in STATES}
    times = {s.value: [10.0, 20.0, 30.0] for s in STATES}
    metrics = engine._build_stage_metrics(counts, times, total_agents=200)
    assert len(metrics) == len(STATES)
    # State order matches STATES.
    assert [m.state for m in metrics] == [s.value for s in STATES]


def test_build_stage_metrics_entry_rate_is_fraction() -> None:
    engine = FunnelExecutionEngine(num_workers=1)
    counts = {
        "ARRIVE": 1000,
        "BROWSE": 800,
        "CONSIDER": 500,
        "DECIDE": 200,
        "PURCHASE": 50,
        "ABANDON": 0,
        "RETURN": 0,
    }
    times = {k: [] for k in counts}
    metrics = engine._build_stage_metrics(counts, times, total_agents=1000)
    # ARRIVE entry_rate should be 1000/1000 = 1.0.
    assert metrics[0].entry_rate == pytest.approx(1.0, abs=1e-9)
    # BROWSE: 800/1000 = 0.8
    assert metrics[1].entry_rate == pytest.approx(0.8, abs=1e-9)


def test_build_stage_metrics_drop_off_is_clamped() -> None:
    engine = FunnelExecutionEngine(num_workers=1)
    # ARRIVE = 0 makes the drop_off potentially undefined; ensure clamp.
    counts = {
        "ARRIVE": 0,
        "BROWSE": 0,
        "CONSIDER": 0,
        "DECIDE": 0,
        "PURCHASE": 0,
        "ABANDON": 0,
        "RETURN": 0,
    }
    times = {k: [] for k in counts}
    metrics = engine._build_stage_metrics(counts, times, total_agents=0)
    for m in metrics:
        assert 0.0 <= m.drop_off_rate <= 1.0


def test_build_stage_metrics_avg_time_empty_returns_zero() -> None:
    engine = FunnelExecutionEngine(num_workers=1)
    counts = {k: 0 for k in (
        "ARRIVE", "BROWSE", "CONSIDER", "DECIDE",
        "PURCHASE", "ABANDON", "RETURN",
    )}
    times = {k: [] for k in counts}
    metrics = engine._build_stage_metrics(counts, times, total_agents=0)
    for m in metrics:
        assert m.avg_time_seconds == 0.0


def test_build_stage_metrics_rounds_to_4dp() -> None:
    engine = FunnelExecutionEngine(num_workers=1)
    counts = {k: 333 for k in (
        "ARRIVE", "BROWSE", "CONSIDER", "DECIDE",
        "PURCHASE", "ABANDON", "RETURN",
    )}
    times = {k: [] for k in counts}
    metrics = engine._build_stage_metrics(counts, times, total_agents=1000)
    for m in metrics:
        # Entry rates are rounded to 4 dp.
        assert m.entry_rate == round(m.entry_rate, 4)


# ---------------------------------------------------------------------------
# _build_demographic_breakdown
# ---------------------------------------------------------------------------


def test_build_demographic_breakdown_groups_by_income_region_device_age() -> None:
    engine = FunnelExecutionEngine(num_workers=1)
    raw = [
        {
            "income_bracket": "MIDDLE",
            "region": "METRO",
            "device_type": "MOBILE",
            "age": 30,
            "converted": True,
        },
        {
            "income_bracket": "MIDDLE",
            "region": "TIER2",
            "device_type": "DESKTOP",
            "age": 25,
            "converted": False,
        },
        {
            "income_bracket": "HIGH_INCOME",
            "region": "METRO",
            "device_type": "MOBILE",
            "age": 40,
            "converted": True,
        },
    ]
    demo = engine._build_demographic_breakdown(raw)
    # Income bracket counts.
    assert demo.by_income_bracket["MIDDLE"]["count"] == 2
    assert demo.by_income_bracket["HIGH_INCOME"]["count"] == 1
    # Region counts.
    assert demo.by_region["METRO"]["count"] == 2
    assert demo.by_region["TIER2"]["count"] == 1
    # Device counts.
    assert demo.by_device["MOBILE"]["count"] == 2
    assert demo.by_device["DESKTOP"]["count"] == 1


def test_build_demographic_breakdown_age_buckets_are_decade_groups() -> None:
    engine = FunnelExecutionEngine(num_workers=1)
    raw = [
        {"income_bracket": "x", "region": "x", "device_type": "x", "age": 22, "converted": True},
        {"income_bracket": "x", "region": "x", "device_type": "x", "age": 28, "converted": False},
        {"income_bracket": "x", "region": "x", "device_type": "x", "age": 41, "converted": True},
    ]
    demo = engine._build_demographic_breakdown(raw)
    # 22 and 28 → "20s" bucket.
    assert demo.by_age_bracket["20s"]["count"] == 2
    # 41 → "40s" bucket.
    assert demo.by_age_bracket["40s"]["count"] == 1


def test_build_demographic_breakdown_conversion_rates_in_unit_interval() -> None:
    engine = FunnelExecutionEngine(num_workers=1)
    raw = [
        {"income_bracket": "A", "region": "X", "device_type": "P", "age": 30, "converted": v}
        for v in [True, False, False, True]
    ]
    demo = engine._build_demographic_breakdown(raw)
    for group in (
        demo.by_income_bracket,
        demo.by_region,
        demo.by_device,
        demo.by_age_bracket,
    ):
        for bucket in group.values():
            assert 0.0 <= bucket["conversion_rate"] <= 1.0


def test_build_demographic_breakdown_empty_input_yields_empty_groups() -> None:
    engine = FunnelExecutionEngine(num_workers=1)
    demo = engine._build_demographic_breakdown([])
    assert demo.by_income_bracket == {}
    assert demo.by_region == {}
    assert demo.by_device == {}
    assert demo.by_age_bracket == {}


# ---------------------------------------------------------------------------
# Dataclass round-trip semantics
# ---------------------------------------------------------------------------


def test_stage_metrics_round_trip() -> None:
    m = StageMetrics(
        state="BROWSE",
        agent_count=42,
        entry_rate=0.84,
        drop_off_rate=0.16,
        avg_time_seconds=37.4,
    )
    # Equality (dataclass) and field access.
    assert m.state == "BROWSE"
    assert m.agent_count == 42
    assert m == StageMetrics(
        state="BROWSE",
        agent_count=42,
        entry_rate=0.84,
        drop_off_rate=0.16,
        avg_time_seconds=37.4,
    )


def test_demographic_breakdown_round_trip() -> None:
    d = DemographicBreakdown(
        by_income_bracket={"MIDDLE": {"count": 10, "conversion_rate": 0.05}},
        by_region={"METRO": {"count": 5, "conversion_rate": 0.10}},
        by_device={"MOBILE": {"count": 8, "conversion_rate": 0.07}},
        by_age_bracket={"30s": {"count": 6, "conversion_rate": 0.06}},
    )
    assert d.by_income_bracket["MIDDLE"]["count"] == 10
    # Equality by value.
    assert d == DemographicBreakdown(
        by_income_bracket={"MIDDLE": {"count": 10, "conversion_rate": 0.05}},
        by_region={"METRO": {"count": 5, "conversion_rate": 0.10}},
        by_device={"MOBILE": {"count": 8, "conversion_rate": 0.07}},
        by_age_bracket={"30s": {"count": 6, "conversion_rate": 0.06}},
    )


# ---------------------------------------------------------------------------
# run_batch failure paths
# ---------------------------------------------------------------------------


def test_run_batch_rejects_empty_agents() -> None:
    engine = FunnelExecutionEngine(num_workers=1)
    with pytest.raises(ValueError, match="agents list is empty"):
        engine.run_batch(
            agents=[],
            env_params={"average_order_value": 999.0, "price_sensitivity": 0.5},
            assumptions=[],
            seed=42,
        )
