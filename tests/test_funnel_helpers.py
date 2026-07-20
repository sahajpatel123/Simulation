"""Tests for backend/app/simulation/funnel.py.

Two scopes:
  1. The four pure helper functions on FunnelExecutionEngine:
       _derive_assumption_impact, _derive_product_strength,
       _build_stage_metrics, _build_demographic_breakdown.
     These take dataclasses / dicts and return dataclasses — no I/O,
     no Markov, no DB. They are the cheapest unit-test surface in the
     funnel pipeline and the easiest place for regressions to hide.

  2. The module-level _run_single_agent worker. Each worker takes an
     agent dict + transition matrix + assumption impact + price +
     product strength + seed and returns a per-agent result dict.
     We patch MarkovBehaviourModel and BetaSamplingEngine so the test
     is deterministic and does not touch scipy / numpy randomness.

These tests do NOT exercise FunnelExecutionEngine.run_batch itself —
that path needs the ProcessPoolExecutor and the real Markov chain,
covered by tests/test_phase6_integration.py.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# funnel.py transitively imports app.simulation.profiles, which imports scipy
# at module load. Skip the whole module when running on a slim env so we don't
# break the rest of the suite (matches the pattern in test_phase6_integration.py).
pytest.importorskip("scipy", reason="Full stack: pip install -r requirements.txt (scipy)")
pytest.importorskip("numpy", reason="Full stack: pip install -r requirements.txt (numpy)")

from app.simulation.funnel import (  # noqa: E402  (importorskip must come first)
    DemographicBreakdown,
    FunnelExecutionEngine,
    StageMetrics,
    _run_single_agent,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> FunnelExecutionEngine:
    """Single-worker engine so subprocess forking is never triggered in tests."""
    return FunnelExecutionEngine(num_workers=1, store_paths=False)


@pytest.fixture
def base_agent_dict() -> dict[str, Any]:
    return {
        "income_bracket": "UPPER_MIDDLE",
        "region": "METRO",
        "device_type": "MOBILE",
        "age": 35,
        "motivation": 0.7,
        "price_sensitivity": 0.5,
        "digital_literacy": 0.8,
        "trust_baseline": 0.6,
        "patience_score": 0.5,
        "monthly_income": 90_000,
    }


# ---------------------------------------------------------------------------
# _derive_assumption_impact
# ---------------------------------------------------------------------------


def test_derive_assumption_impact_empty_assumptions(
    engine: FunnelExecutionEngine,
) -> None:
    assert engine._derive_assumption_impact([]) == {}


def test_derive_assumption_impact_uses_sensitivity_weight(
    engine: FunnelExecutionEngine,
) -> None:
    assumptions = [
        {"id": 1, "sensitivity": "CRITICAL", "impact_score": 10.0},
        {"id": 2, "sensitivity": "HIGH", "impact_score": 5.0},
        {"id": 3, "sensitivity": "MEDIUM", "impact_score": 5.0},
        {"id": 4, "sensitivity": "LOW", "impact_score": 5.0},
    ]
    impact = engine._derive_assumption_impact(assumptions)
    # impact_score is divided by 10.0 first, then multiplied by weight.
    assert impact["CRITICAL_1"] == pytest.approx(-0.10)
    assert impact["HIGH_2"] == pytest.approx(-0.03)
    assert impact["MEDIUM_3"] == pytest.approx(-0.015)
    assert impact["LOW_4"] == pytest.approx(-0.005)


def test_derive_assumption_impact_unknown_sensitivity_falls_back_to_medium_weight(
    engine: FunnelExecutionEngine,
) -> None:
    assumptions = [{"id": 7, "sensitivity": "WTF", "impact_score": 4.0}]
    impact = engine._derive_assumption_impact(assumptions)
    # 4.0/10 * -0.03 (the MEDIUM default) = -0.012
    assert impact["WTF_7"] == pytest.approx(-0.012)


def test_derive_assumption_impact_missing_sensitivity_treated_as_medium(
    engine: FunnelExecutionEngine,
) -> None:
    assumptions = [{"id": 9, "impact_score": 8.0}]
    impact = engine._derive_assumption_impact(assumptions)
    assert impact["MEDIUM_9"] == pytest.approx(-0.024)


# ---------------------------------------------------------------------------
# _derive_product_strength
# ---------------------------------------------------------------------------


def test_derive_product_strength_no_assumptions_returns_baseline(
    engine: FunnelExecutionEngine,
) -> None:
    assert engine._derive_product_strength([]) == 0.65


def test_derive_product_strength_no_critical_or_high_returns_baseline(
    engine: FunnelExecutionEngine,
) -> None:
    assumptions = [
        {"id": 1, "sensitivity": "MEDIUM"},
        {"id": 2, "sensitivity": "LOW"},
    ]
    assert engine._derive_product_strength(assumptions) == pytest.approx(0.85)


def test_derive_product_strength_critical_reduces_strength(
    engine: FunnelExecutionEngine,
) -> None:
    assumptions = [
        {"id": 1, "sensitivity": "CRITICAL"},
        {"id": 2, "sensitivity": "CRITICAL"},
        {"id": 3, "sensitivity": "HIGH"},
    ]
    # 0.85 - 2*0.08 - 1*0.04 = 0.65
    assert engine._derive_product_strength(assumptions) == pytest.approx(0.65)


def test_derive_product_strength_clipped_to_floor(
    engine: FunnelExecutionEngine,
) -> None:
    # 10 criticals would give 0.85 - 0.80 = 0.05, but floor is 0.15.
    assumptions = [{"sensitivity": "CRITICAL"} for _ in range(10)]
    assert engine._derive_product_strength(assumptions) == 0.15


def test_derive_product_strength_clipped_to_ceiling(
    engine: FunnelExecutionEngine,
) -> None:
    # No criticals/highs gives 0.85, ceiling is 0.90, so still 0.85 here.
    # Push 0 high penalties — assert the function stays at 0.85 and not higher.
    assumptions = [{"sensitivity": "LOW"} for _ in range(50)]
    assert engine._derive_product_strength(assumptions) == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# _build_stage_metrics
# ---------------------------------------------------------------------------


def test_build_stage_metrics_all_agents_reach_every_stage(
    engine: FunnelExecutionEngine,
) -> None:
    stage_counts = {
        "ARRIVE": 100,
        "BROWSE": 90,
        "CONSIDER": 70,
        "DECIDE": 50,
        "PURCHASE": 30,
        "ABANDON": 10,
        "RETURN": 5,
    }
    stage_times = {s: [1.0, 2.0, 3.0] for s in stage_counts}
    metrics = engine._build_stage_metrics(stage_counts, stage_times, 100)

    # One entry per state in the canonical order from app.simulation.markov.STATES.
    assert len(metrics) == len(stage_counts)
    for sm in metrics:
        assert isinstance(sm, StageMetrics)
        assert sm.entry_rate == sm.agent_count / 100

    arrive, browse = metrics[0], metrics[1]
    # ARRIVE is the first stage — there is no previous stage, so its
    # drop_off_rate is 0 by definition (not 0.10; that's BROWSE's drop).
    assert arrive.drop_off_rate == pytest.approx(0.0)
    # BROWSE drops from ARRIVE's count (100) to 90: (100 - 90) / 100 = 0.10.
    assert browse.drop_off_rate == pytest.approx(0.10)
    assert browse.entry_rate == pytest.approx(0.90)
    assert browse.avg_time_seconds == pytest.approx(2.0)


def test_build_stage_metrics_handles_empty_inputs(
    engine: FunnelExecutionEngine,
) -> None:
    metrics = engine._build_stage_metrics({}, {}, total_agents=0)
    assert all(sm.agent_count == 0 for sm in metrics)
    assert all(sm.entry_rate == 0.0 for sm in metrics)
    assert all(sm.drop_off_rate == 0.0 for sm in metrics)
    assert all(sm.avg_time_seconds == 0.0 for sm in metrics)


def test_build_stage_metrics_dropoff_clamped_to_unit_interval(
    engine: FunnelExecutionEngine,
) -> None:
    # If a later stage has more agents than the previous stage (e.g. data
    # anomaly from a future schema change), drop-off must clamp to 0.0
    # rather than going negative.
    stage_counts = {"ARRIVE": 5, "BROWSE": 50, "CONSIDER": 50}
    stage_times = {"ARRIVE": [1.0], "BROWSE": [2.0], "CONSIDER": [3.0]}
    metrics = engine._build_stage_metrics(stage_counts, stage_times, 50)
    browse = metrics[1]
    assert browse.drop_off_rate >= 0.0
    assert browse.drop_off_rate <= 1.0


# ---------------------------------------------------------------------------
# _build_demographic_breakdown
# ---------------------------------------------------------------------------


def test_build_demographic_breakdown_groups_by_keys(
    engine: FunnelExecutionEngine,
) -> None:
    raw_results = [
        {"income_bracket": "LOW", "region": "RURAL", "device_type": "MOBILE",
         "age": 22, "converted": True},
        {"income_bracket": "LOW", "region": "RURAL", "device_type": "MOBILE",
         "age": 25, "converted": False},
        {"income_bracket": "HIGH", "region": "METRO", "device_type": "DESKTOP",
         "age": 45, "converted": True},
    ]
    breakdown = engine._build_demographic_breakdown(raw_results)

    assert isinstance(breakdown, DemographicBreakdown)
    assert breakdown.by_income_bracket["LOW"]["conversion_rate"] == pytest.approx(0.5)
    assert breakdown.by_income_bracket["LOW"]["count"] == 2
    assert breakdown.by_income_bracket["HIGH"]["conversion_rate"] == 1.0
    assert breakdown.by_income_bracket["HIGH"]["count"] == 1

    assert breakdown.by_region["RURAL"]["conversion_rate"] == pytest.approx(0.5)
    assert breakdown.by_region["METRO"]["conversion_rate"] == 1.0

    assert breakdown.by_device["MOBILE"]["count"] == 2
    assert breakdown.by_device["DESKTOP"]["count"] == 1


def test_build_demographic_breakdown_age_brackets_use_decade_floors(
    engine: FunnelExecutionEngine,
) -> None:
    raw_results = [
        {"income_bracket": "X", "region": "X", "device_type": "X", "age": 22,
         "converted": True},
        {"income_bracket": "X", "region": "X", "device_type": "X", "age": 29,
         "converted": False},
        {"income_bracket": "X", "region": "X", "device_type": "X", "age": 35,
         "converted": True},
    ]
    breakdown = engine._build_demographic_breakdown(raw_results)
    assert "20s" in breakdown.by_age_bracket
    assert "30s" in breakdown.by_age_bracket
    assert breakdown.by_age_bracket["20s"]["count"] == 2
    assert breakdown.by_age_bracket["30s"]["count"] == 1


def test_build_demographic_breakdown_missing_keys_default_to_unknown(
    engine: FunnelExecutionEngine,
) -> None:
    raw_results = [
        {"converted": True},  # everything else missing
    ]
    breakdown = engine._build_demographic_breakdown(raw_results)
    assert breakdown.by_income_bracket["UNKNOWN"]["count"] == 1
    assert breakdown.by_region["UNKNOWN"]["count"] == 1
    assert breakdown.by_device["UNKNOWN"]["count"] == 1


# ---------------------------------------------------------------------------
# _run_single_agent
# ---------------------------------------------------------------------------


def _make_worker_args(
    agent_dict: dict[str, Any], seed: int = 42
) -> tuple[Any, ...]:
    return (
        agent_dict,
        [[0.0] * 7 for _ in range(7)],  # placeholder 7x7 transition matrix
        {"HIGH_a": -0.05},
        999.0,
        999.0,
        0.7,
        seed,
    )


def test_run_single_agent_marks_converted_when_both_paths_agree(
    base_agent_dict: dict[str, Any],
) -> None:
    fake_markov_result = {
        "converted": True,
        "final_state": "PURCHASE",
        "path": ["ARRIVE", "BROWSE", "CONSIDER", "DECIDE", "PURCHASE"],
        "total_time_seconds": 12.5,
    }
    with (
        patch("app.simulation.funnel.MarkovBehaviourModel") as markov_cls,
        patch("app.simulation.funnel.BetaSamplingEngine") as sampling_cls,
    ):
        markov_instance = MagicMock()
        markov_instance.run_chain.return_value = fake_markov_result
        markov_cls.return_value = markov_instance

        sampling_instance = MagicMock()
        sampling_instance.full_conversion_decision.return_value = MagicMock(
            converted=True, retention_days=30, price_accepted=True
        )
        sampling_cls.return_value = sampling_instance

        result = _run_single_agent(_make_worker_args(base_agent_dict))

    assert result["converted"] is True
    assert result["final_state"] == "PURCHASE"
    assert result["markov_converted"] is True
    assert result["price_accepted"] is True
    assert result["retention_days"] == 30
    assert result["income_bracket"] == "UPPER_MIDDLE"
    assert result["region"] == "METRO"
    assert result["device_type"] == "MOBILE"
    assert result["age"] == 35


def test_run_single_agent_overrides_to_abandon_when_price_rejects(
    base_agent_dict: dict[str, Any],
) -> None:
    fake_markov_result = {
        "converted": True,
        "final_state": "PURCHASE",
        "path": ["ARRIVE", "BROWSE", "PURCHASE"],
        "total_time_seconds": 7.0,
    }
    with (
        patch("app.simulation.funnel.MarkovBehaviourModel") as markov_cls,
        patch("app.simulation.funnel.BetaSamplingEngine") as sampling_cls,
    ):
        markov_cls.return_value.run_chain.return_value = fake_markov_result

        sampling_cls.return_value.full_conversion_decision.return_value = MagicMock(
            converted=False, retention_days=0, price_accepted=False
        )

        result = _run_single_agent(_make_worker_args(base_agent_dict))

    # Markov said PURCHASE, sampling said no → final is ABANDON and the
    # trailing PURCHASE in the path is rewritten to ABANDON.
    assert result["converted"] is False
    assert result["final_state"] == "ABANDON"
    assert result["markov_converted"] is True
    assert result["price_accepted"] is False
    assert result["path"][-1] == "ABANDON"
    assert "PURCHASE" not in result["path"]


def test_run_single_agent_preserves_abandon_when_markov_says_no(
    base_agent_dict: dict[str, Any],
) -> None:
    fake_markov_result = {
        "converted": False,
        "final_state": "ABANDON",
        "path": ["ARRIVE", "ABANDON"],
        "total_time_seconds": 1.0,
    }
    with (
        patch("app.simulation.funnel.MarkovBehaviourModel") as markov_cls,
        patch("app.simulation.funnel.BetaSamplingEngine") as sampling_cls,
    ):
        markov_cls.return_value.run_chain.return_value = fake_markov_result

        sampling_cls.return_value.full_conversion_decision.return_value = MagicMock(
            converted=True, retention_days=10, price_accepted=True
        )

        result = _run_single_agent(_make_worker_args(base_agent_dict))

    # If markov already abandoned, sampling's "yes" doesn't promote the agent.
    assert result["converted"] is False
    assert result["final_state"] == "ABANDON"
    assert result["markov_converted"] is False


def test_run_single_agent_missing_optional_fields_default_gracefully() -> None:
    minimal_agent = {"converted_pseudo": True}  # only unrelated key
    fake_markov_result = {
        "converted": False,
        "final_state": "ABANDON",
        "path": ["ARRIVE"],
        "total_time_seconds": 0.5,
    }
    with (
        patch("app.simulation.funnel.MarkovBehaviourModel") as markov_cls,
        patch("app.simulation.funnel.BetaSamplingEngine") as sampling_cls,
    ):
        markov_cls.return_value.run_chain.return_value = fake_markov_result

        sampling_cls.return_value.full_conversion_decision.return_value = MagicMock(
            converted=False, retention_days=0, price_accepted=False
        )

        result = _run_single_agent(_make_worker_args(minimal_agent))

    assert result["income_bracket"] == "UNKNOWN"
    assert result["region"] == "UNKNOWN"
    assert result["device_type"] == "UNKNOWN"
    assert result["age"] == 30