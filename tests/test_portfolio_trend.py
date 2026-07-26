"""
Tests for the cross-simulation portfolio trend helper + schema +
route registration.

The trend logic is pure-Python so we can exercise it without
spinning up Postgres. The DB-touching route is smoke-tested via
the route-registration pattern (gated by scipy).
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    """Pin the module's ``__all__`` so a future rename surfaces
    as an import error rather than a silent attribute miss in
    the route."""
    from app.simulation import portfolio_trend

    assert set(portfolio_trend.__all__) == {
        "DIR_IMPROVING",
        "DIR_DEGRADING",
        "DIR_STABLE",
        "DIR_NEW",
        "DIR_RESOLVED",
        "VALID_DIRECTIONS",
        "TREND_IMPROVED",
        "TREND_DEGRADED",
        "TREND_STABLE",
        "TREND_NEW",
        "TREND_RESOLVED",
        "TREND_MIXED",
        "VALID_TRENDS",
        "STABLE_RELATIVE_THRESHOLD",
        "SIGNIFICANT_THRESHOLDS",
        "KEY_SHIFTS_LIMIT",
        "compute_portfolio_trend",
    }


def test_direction_allowlist_pinned() -> None:
    from app.simulation.portfolio_trend import VALID_DIRECTIONS

    assert set(VALID_DIRECTIONS) == {
        "IMPROVING",
        "DEGRADING",
        "STABLE",
        "NEW",
        "RESOLVED",
    }


def test_trend_allowlist_pinned() -> None:
    from app.simulation.portfolio_trend import VALID_TRENDS

    assert set(VALID_TRENDS) == {
        "IMPROVED",
        "DEGRADED",
        "STABLE",
        "NEW",
        "RESOLVED",
        "MIXED",
    }


# ---------------------------------------------------------------------------
# Per-metric direction labelling
# ---------------------------------------------------------------------------


def _earlier_summary(
    *,
    simulation_count: int = 5,
    mae: float = 0.10,
    mape: float = 0.50,
    data_quality_score: float = 0.5,
    overall_health: str = "NEEDS_ATTENTION",
    tighten_count: int = 0,
    loosen_count: int = 0,
    needs_attention_count: int = 0,
    critical_findings: int = 2,
    correlated_bias_count: int = 1,
) -> dict:
    return {
        "simulation_count": simulation_count,
        "findings_summary": {
            "severity_breakdown": {"CRITICAL": critical_findings},
        },
        "outcomes_summary": {
            "mae": mae,
            "mape": mape,
            "data_quality_score": data_quality_score,
        },
        "clusters_summary": {
            "needs_attention_count": needs_attention_count,
        },
        "architect_accuracy_summary": {
            "tighten_count": tighten_count,
            "loosen_count": loosen_count,
            "outcome_attached_sim_count": simulation_count,
        },
        "correlated_bias_count": correlated_bias_count,
        "data_quality_score": data_quality_score,
        "overall_health": overall_health,
    }


def test_trend_mae_decreasing_is_improving() -> None:
    """MAE later < earlier → IMPROVING."""
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(mae=0.12),
        _earlier_summary(mae=0.05),
    )
    mae_row = next(d for d in out["deltas"] if d["metric"] == "mae")
    assert mae_row["earlier"] == pytest.approx(0.12)
    assert mae_row["later"] == pytest.approx(0.05)
    assert mae_row["delta"] == pytest.approx(-0.07)
    assert mae_row["direction"] == "IMPROVING"


def test_trend_mae_increasing_is_degrading() -> None:
    """MAE later > earlier → DEGRADING."""
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(mae=0.05),
        _earlier_summary(mae=0.12),
    )
    mae_row = next(d for d in out["deltas"] if d["metric"] == "mae")
    assert mae_row["direction"] == "DEGRADING"


def test_trend_data_quality_higher_is_improving() -> None:
    """data_quality_score is higher_is_better — increasing
    means IMPROVING (opposite of MAE)."""
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(data_quality_score=0.30),
        _earlier_summary(data_quality_score=0.80),
    )
    dq_row = next(
        d for d in out["deltas"] if d["metric"] == "data_quality_score"
    )
    assert dq_row["direction"] == "IMPROVING"


def test_trend_data_quality_decreasing_is_degrading() -> None:
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(data_quality_score=0.80),
        _earlier_summary(data_quality_score=0.30),
    )
    dq_row = next(
        d for d in out["deltas"] if d["metric"] == "data_quality_score"
    )
    assert dq_row["direction"] == "DEGRADING"


def test_trend_within_threshold_is_stable() -> None:
    """A change smaller than STABLE_RELATIVE_THRESHOLD (5 %) →
    STABLE for both directions of metric."""
    from app.simulation.portfolio_trend import (
        STABLE_RELATIVE_THRESHOLD,
        compute_portfolio_trend,
    )

    # 0.100 → 0.103 → +3 % rel change → STABLE.
    out = compute_portfolio_trend(
        _earlier_summary(mae=0.10),
        _earlier_summary(mae=0.10 * (1 + STABLE_RELATIVE_THRESHOLD * 0.5)),
    )
    mae_row = next(d for d in out["deltas"] if d["metric"] == "mae")
    assert mae_row["direction"] == "STABLE"


def test_trend_zero_to_zero_is_stable() -> None:
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(tighten_count=0, loosen_count=0),
        _earlier_summary(tighten_count=0, loosen_count=0),
    )
    tighten_row = next(
        d for d in out["deltas"] if d["metric"] == "tighten_count"
    )
    assert tighten_row["direction"] == "STABLE"


def test_trend_metric_absent_in_earlier_is_new() -> None:
    """A metric that wasn't there before but is now → NEW."""
    from app.simulation.portfolio_trend import compute_portfolio_trend

    earlier = _earlier_summary(tighten_count=0)
    later = _earlier_summary(tighten_count=3)
    # Build a payload where tighten_count is missing in earlier.
    earlier["architect_accuracy_summary"] = {
        "outcome_attached_sim_count": 5,
        # tighten_count omitted.
    }
    out = compute_portfolio_trend(earlier, later)
    tighten_row = next(
        d for d in out["deltas"] if d["metric"] == "tighten_count"
    )
    assert tighten_row["direction"] == "NEW"


def test_trend_metric_disappearing_is_resolved() -> None:
    """A metric that was there but is gone → RESOLVED."""
    from app.simulation.portfolio_trend import compute_portfolio_trend

    earlier = _earlier_summary(tighten_count=3)
    later = _earlier_summary(tighten_count=0)
    later["architect_accuracy_summary"] = {
        "outcome_attached_sim_count": 5,
        # tighten_count omitted.
    }
    out = compute_portfolio_trend(earlier, later)
    tighten_row = next(
        d for d in out["deltas"] if d["metric"] == "tighten_count"
    )
    assert tighten_row["direction"] == "RESOLVED"


# ---------------------------------------------------------------------------
# Health transition matrix
# ---------------------------------------------------------------------------


def test_trend_health_improved_from_needs_attention_to_healthy() -> None:
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(overall_health="NEEDS_ATTENTION"),
        _earlier_summary(overall_health="HEALTHY"),
    )
    assert out["health_transition"] == "IMPROVED"


def test_trend_health_improved_from_critical_to_needs_attention() -> None:
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(overall_health="CRITICAL"),
        _earlier_summary(overall_health="NEEDS_ATTENTION"),
    )
    assert out["health_transition"] == "IMPROVED"


def test_trend_health_degraded_from_healthy_to_needs_attention() -> None:
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(overall_health="HEALTHY"),
        _earlier_summary(overall_health="NEEDS_ATTENTION"),
    )
    assert out["health_transition"] == "DEGRADED"


def test_trend_health_stable_when_unchanged() -> None:
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(overall_health="HEALTHY"),
        _earlier_summary(overall_health="HEALTHY"),
    )
    assert out["health_transition"] == "STABLE"


def test_trend_health_new_when_earlier_was_insufficient_data() -> None:
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(overall_health="INSUFFICIENT_DATA"),
        _earlier_summary(overall_health="NEEDS_ATTENTION"),
    )
    assert out["health_transition"] == "NEW"


def test_trend_health_resolved_when_lost_ground_truth() -> None:
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(overall_health="HEALTHY"),
        _earlier_summary(overall_health="INSUFFICIENT_DATA"),
    )
    assert out["health_transition"] == "RESOLVED"


# ---------------------------------------------------------------------------
# Summary counts
# ---------------------------------------------------------------------------


def test_trend_summary_counts_classify_each_metric() -> None:
    """improving / degrading / stable counts must sum to the
    number of tracked metrics (8)."""
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        # Earlier: MAE 0.12 → 0.05 = IMPROVING; data_quality
        # 0.30 → 0.80 = IMPROVING; tighten 2 → 0 = IMPROVING.
        _earlier_summary(
            mae=0.12, data_quality_score=0.30, tighten_count=2,
        ),
        _earlier_summary(
            mae=0.05, data_quality_score=0.80, tighten_count=0,
        ),
    )
    assert (
        out["improving_count"]
        + out["degrading_count"]
        + out["stable_count"]
        == 8
    )
    assert out["improving_count"] >= 3


def test_trend_simulation_count_delta_echoed() -> None:
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(simulation_count=5),
        _earlier_summary(simulation_count=12),
    )
    assert out["earlier_simulation_count"] == 5
    assert out["later_simulation_count"] == 12
    assert out["simulation_count_delta"] == 7


def test_trend_simulation_count_shrinking_is_negative() -> None:
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(simulation_count=10),
        _earlier_summary(simulation_count=3),
    )
    assert out["simulation_count_delta"] == -7


# ---------------------------------------------------------------------------
# Summary line
# ---------------------------------------------------------------------------


def test_trend_summary_improved_format() -> None:
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(
            overall_health="NEEDS_ATTENTION", simulation_count=5,
        ),
        _earlier_summary(
            overall_health="HEALTHY", simulation_count=8,
        ),
    )
    assert "NEEDS_ATTENTION" in out["summary"]
    assert "HEALTHY" in out["summary"]
    assert "+3 sim(s)" in out["summary"]


def test_trend_summary_new_format() -> None:
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(
            overall_health="INSUFFICIENT_DATA", simulation_count=0,
        ),
        _earlier_summary(
            overall_health="HEALTHY", simulation_count=5,
        ),
    )
    assert "unlocked" in out["summary"].lower()


def test_trend_summary_resolved_format() -> None:
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(
            overall_health="HEALTHY", simulation_count=5,
        ),
        _earlier_summary(
            overall_health="INSUFFICIENT_DATA", simulation_count=0,
        ),
    )
    assert "regression" in out["summary"].lower()


def test_trend_summary_stable_includes_up_down_count() -> None:
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(overall_health="HEALTHY"),
        _earlier_summary(overall_health="HEALTHY"),
    )
    # The summary for stable includes "X up / Y down".
    assert "up" in out["summary"] and "down" in out["summary"]


# ---------------------------------------------------------------------------
# Defensive coercion
# ---------------------------------------------------------------------------


def test_trend_skips_non_numeric_metric_values() -> None:
    """A string / bool in the metric dict must not crash the
    delta calc."""
    from app.simulation.portfolio_trend import compute_portfolio_trend

    earlier = _earlier_summary()
    later = _earlier_summary()
    # Poison both sides with a non-numeric mae.
    earlier["outcomes_summary"]["mae"] = "NaN"
    later["outcomes_summary"]["mae"] = "abc"
    out = compute_portfolio_trend(earlier, later)
    mae_row = next(d for d in out["deltas"] if d["metric"] == "mae")
    # Both None → STABLE (the defensive coercion rejected NaN).
    assert mae_row["direction"] == "STABLE"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_portfolio_trend_out_default_shape() -> None:
    from app.schemas.simulation import PortfolioTrendOut

    out = PortfolioTrendOut()
    assert out.earlier_simulation_count == 0
    assert out.later_simulation_count == 0
    assert out.simulation_count_delta == 0
    assert out.earlier_health == "INSUFFICIENT_DATA"
    assert out.later_health == "INSUFFICIENT_DATA"
    assert out.health_transition == "STABLE"
    assert out.deltas == []
    assert out.improving_count == 0
    assert out.degrading_count == 0
    assert out.stable_count == 0
    assert out.significant_change_count == 0
    assert out.key_shifts == []
    assert out.summary == ""


def test_portfolio_trend_out_round_trips_helper_payload() -> None:
    from app.schemas.simulation import PortfolioTrendOut
    from app.simulation.portfolio_trend import compute_portfolio_trend

    payload = compute_portfolio_trend(
        _earlier_summary(
            overall_health="NEEDS_ATTENTION", mae=0.12,
        ),
        _earlier_summary(
            overall_health="HEALTHY", mae=0.05,
        ),
    )
    out = PortfolioTrendOut(**payload)
    assert out.earlier_health == "NEEDS_ATTENTION"
    assert out.later_health == "HEALTHY"
    assert out.health_transition == "IMPROVED"
    assert out.summary != ""


# ---------------------------------------------------------------------------
# significance flag
# ---------------------------------------------------------------------------


def test_trend_significant_threshold_for_mae() -> None:
    """MAE shift of ≥ 0.005 (5% of a percentage point) is
    significant."""
    from app.simulation.portfolio_trend import compute_portfolio_trend

    # 0.10 → 0.11 → delta 0.01 → significant.
    out = compute_portfolio_trend(
        _earlier_summary(mae=0.10),
        _earlier_summary(mae=0.11),
    )
    mae_row = next(d for d in out["deltas"] if d["metric"] == "mae")
    assert mae_row["significant"] is True


def test_trend_insignificant_threshold_for_mae() -> None:
    """MAE shift smaller than the threshold → not significant,
    even when direction says IMPROVING / DEGRADING."""
    from app.simulation.portfolio_trend import compute_portfolio_trend

    # 0.100 → 0.103 → delta 0.003 < threshold 0.005 → not significant.
    out = compute_portfolio_trend(
        _earlier_summary(mae=0.10),
        _earlier_summary(mae=0.103),
    )
    mae_row = next(d for d in out["deltas"] if d["metric"] == "mae")
    assert mae_row["significant"] is False


def test_trend_significant_threshold_for_counts() -> None:
    """Count metrics: any change ≥ 1 is significant."""
    from app.simulation.portfolio_trend import compute_portfolio_trend

    # tighten_count 0 → 1 → significant.
    out = compute_portfolio_trend(
        _earlier_summary(tighten_count=0),
        _earlier_summary(tighten_count=1),
    )
    tighten_row = next(
        d for d in out["deltas"] if d["metric"] == "tighten_count"
    )
    assert tighten_row["significant"] is True


def test_trend_zero_delta_is_not_significant() -> None:
    """Same value on both sides → delta 0 → not significant."""
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(mae=0.05),
        _earlier_summary(mae=0.05),
    )
    mae_row = next(d for d in out["deltas"] if d["metric"] == "mae")
    assert mae_row["delta"] == 0.0
    assert mae_row["significant"] is False


def test_trend_significant_change_count_top_level() -> None:
    """Top-level count of how many metrics shifted meaningfully."""
    from app.simulation.portfolio_trend import compute_portfolio_trend

    # mae 0.10 → 0.12 (+0.02, significant)
    # data_quality 0.30 → 0.80 (+0.50, significant)
    # tighten_count 0 → 0 (no change)
    out = compute_portfolio_trend(
        _earlier_summary(
            mae=0.10, data_quality_score=0.30, tighten_count=0,
        ),
        _earlier_summary(
            mae=0.12, data_quality_score=0.80, tighten_count=0,
        ),
    )
    assert out["significant_change_count"] >= 2


# ---------------------------------------------------------------------------
# key_shifts
# ---------------------------------------------------------------------------


def test_trend_key_shifts_picks_top_by_relative_change() -> None:
    """Top shifts sorted by |delta| / max(|earlier|, |later|)."""
    from app.simulation.portfolio_trend import compute_portfolio_trend

    # mae 0.10 → 0.05 = 50% rel change (biggest).
    # tighten 5 → 0 = 100% rel change (bigger).
    # data_quality 0.80 → 0.83 = ~4% (STABLE, not in shifts).
    out = compute_portfolio_trend(
        _earlier_summary(
            mae=0.10, tighten_count=5, data_quality_score=0.80,
        ),
        _earlier_summary(
            mae=0.05, tighten_count=0, data_quality_score=0.83,
        ),
    )
    keys = [k["metric"] for k in out["key_shifts"]]
    # tighten_count should rank first (100% > 50%).
    assert keys[0] == "tighten_count"
    assert "mae" in keys
    assert "data_quality_score" not in keys  # STABLE excluded


def test_trend_key_shifts_excludes_stable_and_new() -> None:
    """Only IMPROVING / DEGRADING rows surface — STABLE / NEW
    / RESOLVED aren't a 'shift'."""
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(mae=0.05),
        _earlier_summary(mae=0.05),  # identical → STABLE
    )
    assert out["key_shifts"] == []


def test_trend_key_shifts_caps_at_three() -> None:
    """Top-N cap keeps the dashboard headline readable."""
    from app.simulation.portfolio_trend import (
        KEY_SHIFTS_LIMIT,
        compute_portfolio_trend,
    )

    # Trigger 5+ IMPROVING metrics.
    out = compute_portfolio_trend(
        _earlier_summary(
            mae=0.20, mape=0.60, tighten_count=4, loosen_count=3,
            correlated_bias_count=2, critical_findings=5,
            needs_attention_count=4, data_quality_score=0.20,
        ),
        _earlier_summary(
            mae=0.05, mape=0.10, tighten_count=0, loosen_count=0,
            correlated_bias_count=0, critical_findings=0,
            needs_attention_count=0, data_quality_score=0.80,
        ),
    )
    assert len(out["key_shifts"]) <= KEY_SHIFTS_LIMIT
    assert KEY_SHIFTS_LIMIT == 3


def test_trend_key_shifts_carries_relative_change() -> None:
    """Each key_shifts row carries a relative_change field so
    the dashboard can render a percentage badge."""
    from app.simulation.portfolio_trend import compute_portfolio_trend

    out = compute_portfolio_trend(
        _earlier_summary(mae=0.10),
        _earlier_summary(mae=0.05),
    )
    shift = out["key_shifts"][0]
    assert shift["metric"] == "mae"
    assert shift["direction"] == "IMPROVING"
    assert shift["delta"] == pytest.approx(-0.05)
    assert shift["earlier"] == pytest.approx(0.10)
    assert shift["later"] == pytest.approx(0.05)
    # Relative change = 0.05 / 0.10 = 0.50.
    assert shift["relative_change"] == pytest.approx(0.50)


def test_trend_key_shifts_empty_for_identical_windows() -> None:
    """No deltas → no shifts."""
    from app.simulation.portfolio_trend import compute_portfolio_trend

    payload = _earlier_summary(overall_health="HEALTHY")
    out = compute_portfolio_trend(payload, payload)
    assert out["key_shifts"] == []


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_portfolio_trend_route_registered() -> None:
    """GET /simulations/portfolio-trend must appear in the
    router."""
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy"
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import simulations as sim_mod

    paths = {r.path for r in sim_mod.router.routes}
    assert "/simulations/portfolio-trend" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert "GET" in methods_by_path["/simulations/portfolio-trend"]


def test_portfolio_trend_route_query_params() -> None:
    """Pin the query-param surface so the UI contract is
    documented."""
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy"
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import simulations as sim_mod

    for r in sim_mod.router.routes:
        if (
            r.path == "/simulations/portfolio-trend"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "since" in query_param_names
            assert "until" in query_param_names
            return
    raise AssertionError(
        "GET /simulations/portfolio-trend route not found"
    )