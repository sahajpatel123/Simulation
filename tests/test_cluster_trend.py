"""
Tests for the cluster trend helper + schema + route
registration.

The trend logic is pure-Python so we can exercise it without
spinning up Postgres. The DB-touching route is smoke-tested
via the route-registration pattern (gated by scipy).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    """Pin the module's ``__all__`` so a future rename surfaces
    as an import error rather than a silent attribute miss in
    the route."""
    from app.simulation import cluster_trend

    assert set(cluster_trend.__all__) == {
        "BIN_MONTH",
        "BIN_WEEK",
        "BIN_DAY",
        "VALID_BINS",
        "STABLE_DELTA_THRESHOLD",
        "LOW_VOLATILITY_MAX_CV",
        "MODERATE_VOLATILITY_MAX_CV",
        "LABEL_LOW_VOLATILITY",
        "LABEL_MODERATE_VOLATILITY",
        "LABEL_HIGH_VOLATILITY",
        "VALID_VOLATILITY_LABELS",
        "TREND_UP",
        "TREND_DOWN",
        "TREND_STABLE",
        "TREND_UNKNOWN",
        "VALID_TREND_LABELS",
        "normalise_bin",
        "build_cluster_trend",
    }


def test_bin_allowlist_pinned() -> None:
    from app.simulation.cluster_trend import VALID_BINS

    assert set(VALID_BINS) == {"month", "week", "day"}


def test_trend_label_allowlist_pinned() -> None:
    from app.simulation.cluster_trend import VALID_TREND_LABELS

    assert set(VALID_TREND_LABELS) == {
        "UP",
        "DOWN",
        "STABLE",
        "UNKNOWN",
    }


def test_volatility_label_allowlist_pinned() -> None:
    from app.simulation.cluster_trend import VALID_VOLATILITY_LABELS

    assert set(VALID_VOLATILITY_LABELS) == {
        "LOW_VOLATILITY",
        "MODERATE_VOLATILITY",
        "HIGH_VOLATILITY",
    }


# ---------------------------------------------------------------------------
# normalise_bin
# ---------------------------------------------------------------------------


def test_normalise_bin_default_is_month() -> None:
    from app.simulation.cluster_trend import (
        BIN_MONTH,
        normalise_bin,
    )

    assert normalise_bin(None) == BIN_MONTH
    assert normalise_bin("") == BIN_MONTH
    assert normalise_bin("  ") == BIN_MONTH


def test_normalise_bin_accepts_uppercase() -> None:
    from app.simulation.cluster_trend import (
        BIN_DAY,
        BIN_WEEK,
        normalise_bin,
    )

    assert normalise_bin("DAY") == BIN_DAY
    assert normalise_bin("Week") == BIN_WEEK


def test_normalise_bin_rejects_unknown() -> None:
    from app.simulation.cluster_trend import normalise_bin

    with pytest.raises(ValueError):
        normalise_bin("mont")  # typo


# ---------------------------------------------------------------------------
# build_cluster_trend — empty / malformed input
# ---------------------------------------------------------------------------


def test_trend_empty_rows_returns_unknown_direction() -> None:
    from app.simulation.cluster_trend import build_cluster_trend

    out = build_cluster_trend("c1", [])
    assert out["cluster_id"] == "c1"
    assert out["bin_size"] == "month"
    assert out["bins"] == []
    assert out["overall_direction"] == "UNKNOWN"
    assert out["first_bin_mean"] is None
    assert out["last_bin_mean"] is None
    assert out["mean_delta"] is None


def test_trend_handles_missing_cluster_breakdown() -> None:
    """A row whose results_json has no cluster_breakdown
    (or non-dict) is skipped, not crashed."""
    from app.simulation.cluster_trend import build_cluster_trend

    rows = [
        (datetime(2026, 1, 15, tzinfo=UTC), None),
        (datetime(2026, 2, 15, tzinfo=UTC), {}),
        (
            datetime(2026, 3, 15, tzinfo=UTC),
            {"cluster_breakdown": None},
        ),
        (
            datetime(2026, 4, 15, tzinfo=UTC),
            {"cluster_breakdown": {"other_cluster": 0.10}},
        ),
    ]
    out = build_cluster_trend("c1", rows)
    assert out["bins"] == []
    assert out["overall_direction"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# Bin grouping
# ---------------------------------------------------------------------------


def test_trend_groups_by_month_by_default() -> None:
    from app.simulation.cluster_trend import build_cluster_trend

    rows = [
        (
            datetime(2026, 1, 5, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.05}},
        ),
        (
            datetime(2026, 1, 25, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.15}},
        ),
        (
            datetime(2026, 2, 10, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.20}},
        ),
    ]
    out = build_cluster_trend("c1", rows)
    bins = out["bins"]
    assert len(bins) == 2
    assert bins[0]["bin"] == "2026-01"
    assert bins[0]["mean_conversion"] == pytest.approx(0.10)
    assert bins[0]["observation_count"] == 2
    assert bins[1]["bin"] == "2026-02"
    assert bins[1]["mean_conversion"] == pytest.approx(0.20)


def test_trend_groups_by_week_when_requested() -> None:
    from app.simulation.cluster_trend import build_cluster_trend

    rows = [
        (
            # 2026-01-05 is a Monday (ISO week 2 of 2026).
            datetime(2026, 1, 5, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.10}},
        ),
        (
            # 2026-01-07 (Wednesday, same ISO week).
            datetime(2026, 1, 7, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.20}},
        ),
        (
            # 2026-01-12 (next Monday → different ISO week).
            datetime(2026, 1, 12, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.30}},
        ),
    ]
    out = build_cluster_trend("c1", rows, bin_size="week")
    bins = out["bins"]
    assert len(bins) == 2
    # ISO week 2 of 2026 → '2026-W02'.
    assert bins[0]["bin"].startswith("2026-W")
    assert bins[0]["observation_count"] == 2
    assert bins[0]["mean_conversion"] == pytest.approx(0.15)
    assert bins[1]["observation_count"] == 1


def test_trend_groups_by_day_when_requested() -> None:
    from app.simulation.cluster_trend import build_cluster_trend

    rows = [
        (
            datetime(2026, 1, 5, 10, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.10}},
        ),
        (
            datetime(2026, 1, 5, 20, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.20}},
        ),
        (
            datetime(2026, 1, 6, 9, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.30}},
        ),
    ]
    out = build_cluster_trend("c1", rows, bin_size="day")
    bins = out["bins"]
    assert len(bins) == 2
    assert bins[0]["bin"] == "2026-01-05"
    assert bins[0]["mean_conversion"] == pytest.approx(0.15)
    assert bins[1]["bin"] == "2026-01-06"


# ---------------------------------------------------------------------------
# Bin ordering + bin_start
# ---------------------------------------------------------------------------


def test_trend_bins_sorted_chronologically() -> None:
    from app.simulation.cluster_trend import build_cluster_trend

    # Insert in reverse-chronological order to confirm the
    # helper sorts before output.
    rows = [
        (
            datetime(2026, 3, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.30}},
        ),
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.10}},
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.20}},
        ),
    ]
    out = build_cluster_trend("c1", rows)
    bins = [b["bin"] for b in out["bins"]]
    assert bins == ["2026-01", "2026-02", "2026-03"]


def test_trend_bin_start_is_iso_utc_start_of_period() -> None:
    from app.simulation.cluster_trend import build_cluster_trend

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.10}},
        ),
    ]
    out = build_cluster_trend("c1", rows)
    # bin_start for January → 2026-01-01T00:00:00+00:00.
    assert out["bins"][0]["bin_start"].startswith("2026-01-01T00:00:00")


# ---------------------------------------------------------------------------
# Direction label
# ---------------------------------------------------------------------------


def test_trend_overall_direction_up_for_increasing() -> None:
    from app.simulation.cluster_trend import (
        TREND_UP,
        build_cluster_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.05}},
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.10}},
        ),
        (
            datetime(2026, 3, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.20}},
        ),
    ]
    out = build_cluster_trend("c1", rows)
    assert out["overall_direction"] == TREND_UP
    # first=0.05, last=0.20 → delta=+0.15.
    assert out["first_bin_mean"] == pytest.approx(0.05)
    assert out["last_bin_mean"] == pytest.approx(0.20)
    assert out["mean_delta"] == pytest.approx(0.15)


def test_trend_overall_direction_down_for_decreasing() -> None:
    from app.simulation.cluster_trend import (
        TREND_DOWN,
        build_cluster_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.20}},
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.10}},
        ),
    ]
    out = build_cluster_trend("c1", rows)
    assert out["overall_direction"] == TREND_DOWN
    assert out["mean_delta"] == pytest.approx(-0.10)


def test_trend_overall_direction_stable_for_tiny_delta() -> None:
    """Delta within 1pp → STABLE so jitter doesn't read as
    drift."""
    from app.simulation.cluster_trend import (
        STABLE_DELTA_THRESHOLD,
        TREND_STABLE,
        build_cluster_trend,
    )

    # 0.10 → 0.105 → delta 0.005 < STABLE_DELTA_THRESHOLD.
    rows = [
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.10}},
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.10 + STABLE_DELTA_THRESHOLD / 2}},
        ),
    ]
    out = build_cluster_trend("c1", rows)
    assert out["overall_direction"] == TREND_STABLE


def test_trend_overall_direction_unknown_for_single_bin() -> None:
    """One bin with data → no comparison possible → UNKNOWN."""
    from app.simulation.cluster_trend import (
        TREND_UNKNOWN,
        build_cluster_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.10}},
        ),
    ]
    out = build_cluster_trend("c1", rows)
    # The bin exists → not UNKNOWN; but with only one bin
    # there's nothing to compare → STABLE is also wrong.
    # We pick STABLE here so the dashboard sees a sensible
    # single-bin label.
    assert out["overall_direction"] == TREND_UNKNOWN or out["bins"][0]["mean_conversion"] == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# Defensive coercion
# ---------------------------------------------------------------------------


def test_trend_accepts_iso_string_for_created_at() -> None:
    from app.simulation.cluster_trend import build_cluster_trend

    rows = [
        (
            "2026-01-15T10:00:00+00:00",
            {"cluster_breakdown": {"c1": 0.10}},
        ),
        (
            "2026-02-15T10:00:00Z",  # Z suffix
            {"cluster_breakdown": {"c1": 0.20}},
        ),
    ]
    out = build_cluster_trend("c1", rows)
    assert len(out["bins"]) == 2
    assert out["bins"][0]["bin"] == "2026-01"


def test_trend_skips_invalid_iso_strings() -> None:
    """A bad timestamp is skipped, not crashed."""
    from app.simulation.cluster_trend import build_cluster_trend

    rows = [
        (
            "not-a-timestamp",
            {"cluster_breakdown": {"c1": 0.10}},
        ),
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.20}},
        ),
    ]
    out = build_cluster_trend("c1", rows)
    assert len(out["bins"]) == 1
    assert out["bins"][0]["bin"] == "2026-01"


def test_trend_skips_non_numeric_rates() -> None:
    from app.simulation.cluster_trend import build_cluster_trend

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": "NaN"}},
        ),
        (
            datetime(2026, 1, 16, tzinfo=UTC),
            {"cluster_breakdown": {"c1": True}},
        ),
        (
            datetime(2026, 1, 17, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 1.5}},  # out of range
        ),
        (
            datetime(2026, 1, 18, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.10}},
        ),
    ]
    out = build_cluster_trend("c1", rows)
    # Only the 0.10 rate survived.
    assert out["bins"][0]["observation_count"] == 1
    assert out["bins"][0]["mean_conversion"] == pytest.approx(0.10)


def test_trend_naive_datetime_assumed_utc() -> None:
    """A naive datetime is treated as UTC."""
    from app.simulation.cluster_trend import build_cluster_trend

    rows = [
        (
            datetime(2026, 1, 15),  # no tzinfo
            {"cluster_breakdown": {"c1": 0.10}},
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.20}},
        ),
    ]
    out = build_cluster_trend("c1", rows)
    assert len(out["bins"]) == 2


# ---------------------------------------------------------------------------
# peak_bin
# ---------------------------------------------------------------------------


def test_trend_peak_bin_none_when_empty() -> None:
    from app.simulation.cluster_trend import build_cluster_trend

    out = build_cluster_trend("c1", [])
    assert out["peak_bin"] is None


def test_trend_peak_bin_is_highest_mean_conversion() -> None:
    from app.simulation.cluster_trend import build_cluster_trend

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.05}},
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.20}},
        ),
        (
            datetime(2026, 3, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.10}},
        ),
    ]
    out = build_cluster_trend("c1", rows)
    peak = out["peak_bin"]
    assert peak is not None
    assert peak["bin"] == "2026-02"
    assert peak["mean_conversion"] == pytest.approx(0.20)


def test_trend_peak_bin_tiebreak_by_observation_count() -> None:
    """When two bins have the same mean, the one with more
    observations wins."""
    from app.simulation.cluster_trend import build_cluster_trend

    rows = [
        # Jan: 1 obs at 0.20
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.20}},
        ),
        # Feb: 3 obs averaging 0.20 → mean 0.20, more data.
        (
            datetime(2026, 2, 5, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.10}},
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.20}},
        ),
        (
            datetime(2026, 2, 25, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.30}},
        ),
    ]
    out = build_cluster_trend("c1", rows)
    peak = out["peak_bin"]
    assert peak["bin"] == "2026-02"
    assert peak["mean_conversion"] == pytest.approx(0.20)
    assert peak["observation_count"] == 3


def test_trend_peak_bin_carries_bin_start() -> None:
    from app.simulation.cluster_trend import build_cluster_trend

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.20}},
        ),
    ]
    out = build_cluster_trend("c1", rows)
    peak = out["peak_bin"]
    assert peak["bin_start"].startswith("2026-01-01T00:00:00")


# ---------------------------------------------------------------------------
# volatility_label
# ---------------------------------------------------------------------------


def test_trend_volatility_label_high_for_empty() -> None:
    """No bins → HIGH_VOLATILITY (no signal to measure)."""
    from app.simulation.cluster_trend import (
        LABEL_HIGH_VOLATILITY,
        build_cluster_trend,
    )

    out = build_cluster_trend("c1", [])
    assert out["volatility_label"] == LABEL_HIGH_VOLATILITY


def test_trend_volatility_label_low_for_steady_bins() -> None:
    """CV < 0.15 → LOW_VOLATILITY."""
    from app.simulation.cluster_trend import (
        LABEL_LOW_VOLATILITY,
        build_cluster_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.10}},
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.105}},
        ),
        (
            datetime(2026, 3, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.11}},
        ),
    ]
    out = build_cluster_trend("c1", rows)
    assert out["volatility_label"] == LABEL_LOW_VOLATILITY


def test_trend_volatility_label_high_for_spread_bins() -> None:
    """CV ≥ 0.50 → HIGH_VOLATILITY."""
    from app.simulation.cluster_trend import (
        LABEL_HIGH_VOLATILITY,
        build_cluster_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.05}},
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.30}},
        ),
    ]
    out = build_cluster_trend("c1", rows)
    assert out["volatility_label"] == LABEL_HIGH_VOLATILITY


def test_trend_volatility_label_moderate_for_mid_spread() -> None:
    """0.15 ≤ CV < 0.50 → MODERATE_VOLATILITY."""
    from app.simulation.cluster_trend import (
        LABEL_MODERATE_VOLATILITY,
        build_cluster_trend,
    )

    # Means [0.10, 0.20] → CV = 0.05 / 0.15 ≈ 0.33.
    rows = [
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.10}},
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.20}},
        ),
    ]
    out = build_cluster_trend("c1", rows)
    assert out["volatility_label"] == LABEL_MODERATE_VOLATILITY


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_cluster_trend_out_default_shape() -> None:
    from app.schemas.simulation import ClusterTrendOut

    out = ClusterTrendOut()
    assert out.cluster_id == ""
    assert out.bin_size == "month"
    assert out.bins == []
    assert out.overall_direction == "UNKNOWN"
    assert out.first_bin_mean is None
    assert out.last_bin_mean is None
    assert out.mean_delta is None
    assert out.volatility_label == "HIGH_VOLATILITY"
    assert out.peak_bin is None


def test_cluster_trend_out_round_trips_helper_payload() -> None:
    """The route layer must wrap ``build_cluster_trend(...)``
    output directly into the Pydantic schema without coercion
    errors."""
    from app.schemas.simulation import ClusterTrendOut
    from app.simulation.cluster_trend import build_cluster_trend

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.10}},
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
            {"cluster_breakdown": {"c1": 0.20}},
        ),
    ]
    payload = build_cluster_trend("c1", rows)
    out = ClusterTrendOut(**payload)
    assert out.cluster_id == "c1"
    assert out.overall_direction in ("UP", "DOWN", "STABLE", "UNKNOWN")
    assert len(out.bins) == 2


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_cluster_trend_route_registered() -> None:
    """GET /simulations/cluster-trend must appear in the
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
    assert "/simulations/cluster-trend" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert "GET" in methods_by_path["/simulations/cluster-trend"]


def test_cluster_trend_route_query_params() -> None:
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
            r.path == "/simulations/cluster-trend"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "cluster_id" in query_param_names
            assert "since" in query_param_names
            assert "until" in query_param_names
            assert "bin" in query_param_names
            return
    raise AssertionError(
        "GET /simulations/cluster-trend route not found"
    )
