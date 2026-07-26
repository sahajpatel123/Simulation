"""
Tests for the calibration-health helper + schema + route
registration.

The health logic is pure-Python so we can exercise it
without spinning up Postgres. The DB-touching route is
smoke-tested via the route-registration pattern (gated by
scipy).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    """Pin the module's ``__all__`` so a future rename surfaces
    as an import error rather than a silent attribute miss in
    the route."""
    from app.simulation import calibration_health

    assert set(calibration_health.__all__) == {
        "LABEL_WELL_CALIBRATED",
        "LABEL_NEEDS_ATTENTION",
        "LABEL_POORLY_CALIBRATED",
        "LABEL_INSUFFICIENT_DATA",
        "VALID_HEALTH_LABELS",
        "WELL_CALIBRATED_MAX_MAE",
        "NEEDS_ATTENTION_MAX_MAE",
        "TREND_WINDOWS",
        "build_calibration_health",
    }


def test_health_label_allowlist_pinned() -> None:
    from app.simulation.calibration_health import VALID_HEALTH_LABELS

    assert set(VALID_HEALTH_LABELS) == {
        "WELL_CALIBRATED",
        "NEEDS_ATTENTION",
        "POORLY_CALIBRATED",
        "INSUFFICIENT_DATA",
    }


# ---------------------------------------------------------------------------
# build_calibration_health — empty / malformed input
# ---------------------------------------------------------------------------


def test_health_empty_input_returns_insufficient() -> None:
    from app.simulation.calibration_health import (
        LABEL_INSUFFICIENT_DATA,
        build_calibration_health,
    )

    out = build_calibration_health([])
    assert out["overall_health"] == LABEL_INSUFFICIENT_DATA
    assert out["observation_count"] == 0
    assert out["mean_abs_variance"] is None
    assert out["top_miscalibrated_architect"] is None


def test_health_skips_rows_with_missing_outcome() -> None:
    from app.simulation.calibration_health import build_calibration_health

    out = build_calibration_health([
        (datetime(2026, 1, 1, tzinfo=timezone.utc), 0.10, 0.05, []),
        (datetime(2026, 1, 2, tzinfo=timezone.utc), None, None, []),
        (datetime(2026, 1, 3, tzinfo=timezone.utc), "abc", "def", []),
    ])
    assert out["observation_count"] == 1


# ---------------------------------------------------------------------------
# Overall health label
# ---------------------------------------------------------------------------


def test_health_well_calibrated_below_2pp() -> None:
    from app.simulation.calibration_health import (
        LABEL_WELL_CALIBRATED,
        build_calibration_health,
    )

    out = build_calibration_health([
        (datetime(2026, 1, 1, tzinfo=timezone.utc), 0.10, 0.09, []),
        (datetime(2026, 1, 2, tzinfo=timezone.utc), 0.10, 0.11, []),
    ])
    # |variance| mean = (0.01 + 0.01) / 2 = 0.01 < 0.02
    assert out["overall_health"] == LABEL_WELL_CALIBRATED


def test_health_needs_attention_for_mid_variance() -> None:
    from app.simulation.calibration_health import (
        LABEL_NEEDS_ATTENTION,
        build_calibration_health,
    )

    out = build_calibration_health([
        (datetime(2026, 1, 1, tzinfo=timezone.utc), 0.10, 0.05, []),
        (datetime(2026, 1, 2, tzinfo=timezone.utc), 0.10, 0.10, []),
    ])
    # mean |variance| = 0.025 → NEEDS_ATTENTION.
    assert out["overall_health"] == LABEL_NEEDS_ATTENTION


def test_health_poorly_calibrated_for_high_variance() -> None:
    from app.simulation.calibration_health import (
        LABEL_POORLY_CALIBRATED,
        build_calibration_health,
    )

    out = build_calibration_health([
        (datetime(2026, 1, 1, tzinfo=timezone.utc), 0.20, 0.05, []),
        (datetime(2026, 1, 2, tzinfo=timezone.utc), 0.10, 0.20, []),
    ])
    # mean |variance| = 0.125 → POORLY_CALIBRATED.
    assert out["overall_health"] == LABEL_POORLY_CALIBRATED


# ---------------------------------------------------------------------------
# Top miscalibrated architect
# ---------------------------------------------------------------------------


def _finding(architect: str, severity: str) -> dict:
    return {
        "architect_name": architect,
        "severity": severity,
    }


def test_health_top_miscalibrated_architect() -> None:
    """The architect with the highest |calibration_variance|
    surfaces first."""
    from app.simulation.calibration_health import build_calibration_health

    out = build_calibration_health([
        # Sim 1: |variance| 0.05, only PricingArchitect
        # findings → bridge sees pricing with calibration
        # 0.05.
        (
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            0.10, 0.05,
            [_finding("PricingArchitect", "CRITICAL")],
        ),
        # Sim 2: |variance| 0.10, only TrustArchitect
        # findings → trust with calibration 0.10.
        (
            datetime(2026, 1, 2, tzinfo=timezone.utc),
            0.20, 0.10,
            [_finding("TrustArchitect", "CRITICAL")],
        ),
    ])
    top = out["top_miscalibrated_architect"]
    assert top is not None
    assert top["architect_name"] == "TrustArchitect"
    assert top["abs_calibration_variance"] == pytest.approx(0.10)


def test_health_top_miscalibrated_none_when_no_calibrated_architect() -> None:
    """When no architect had bias data → None (rather than
    crashing on the first row)."""
    from app.simulation.calibration_health import build_calibration_health

    # No findings → every architect is INSUFFICIENT_DATA.
    out = build_calibration_health([
        (
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            0.10, 0.05,
            [],
        ),
    ])
    assert out["top_miscalibrated_architect"] is None


# ---------------------------------------------------------------------------
# Architect accuracy counts
# ---------------------------------------------------------------------------


def test_health_architect_accuracy_counts_zero_when_no_data() -> None:
    """No data → all-zero counts (canonical shape)."""
    from app.simulation.calibration_health import build_calibration_health

    out = build_calibration_health([])
    counts = out["architect_accuracy_counts"]
    assert counts == {
        "TIGHTEN": 0,
        "LOOSEN": 0,
        "TRUSTED": 0,
    }


def test_health_architect_accuracy_counts_increments() -> None:
    from app.simulation.calibration_health import build_calibration_health

    out = build_calibration_health([
        (
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            0.20, 0.05,
            [_finding("PricingArchitect", "CRITICAL")] * 3,
        ),
        # Two distinct sims for trust with high variance →
        # TIGHTEN / LOOSEN depending on direction.
        (
            datetime(2026, 1, 2, tzinfo=timezone.utc),
            0.20, 0.10,
            [_finding("TrustArchitect", "CRITICAL")],
        ),
        (
            datetime(2026, 1, 3, tzinfo=timezone.utc),
            0.30, 0.10,
            [_finding("TrustArchitect", "CRITICAL")],
        ),
    ])
    counts = out["architect_accuracy_counts"]
    # Sum of all counts ≤ observation count.
    total = counts["TIGHTEN"] + counts["LOOSEN"] + counts["TRUSTED"]
    assert total <= 3


# ---------------------------------------------------------------------------
# Trend buckets
# ---------------------------------------------------------------------------


def test_health_trend_buckets_always_present() -> None:
    """The trend_buckets list is always present with the
    three windows (7d / 30d / 90d) even when empty."""
    from app.simulation.calibration_health import build_calibration_health

    out = build_calibration_health([])
    buckets = out["trend_buckets"]
    assert len(buckets) == 3
    windows = [b["window"] for b in buckets]
    assert "7d" in windows
    assert "30d" in windows
    assert "90d" in windows


def test_health_trend_buckets_filter_by_window() -> None:
    """A 60-day-old sim is in the 90d window but NOT in 7d
    or 30d."""
    from app.simulation.calibration_health import build_calibration_health

    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    out = build_calibration_health(
        [
            (
                now - timedelta(days=60),
                0.20, 0.10,
                [_finding("PricingArchitect", "CRITICAL")],
            ),
        ],
        now=now,
    )
    by_window = {b["window"]: b for b in out["trend_buckets"]}
    assert by_window["7d"]["observation_count"] == 0
    assert by_window["30d"]["observation_count"] == 0
    assert by_window["90d"]["observation_count"] == 1
    assert by_window["90d"]["mean_abs_variance"] == pytest.approx(0.10)


def test_health_trend_buckets_mean_uses_window_rows() -> None:
    """mean_abs_variance averages only the rows inside the
    window, not the full batch."""
    from app.simulation.calibration_health import build_calibration_health

    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    out = build_calibration_health(
        [
            # In all windows.
            (
                now - timedelta(days=1),
                0.10, 0.05,  # |variance| 0.05
                [],
            ),
            # In 30d and 90d only (outside 7d).
            (
                now - timedelta(days=20),
                0.10, 0.20,  # |variance| 0.10
                [],
            ),
            # In 90d only.
            (
                now - timedelta(days=60),
                0.10, 0.05,  # |variance| 0.05
                [],
            ),
        ],
        now=now,
    )
    by_window = {b["window"]: b for b in out["trend_buckets"]}
    # 7d: only the 1-day-old row.
    assert by_window["7d"]["observation_count"] == 1
    assert by_window["7d"]["mean_abs_variance"] == pytest.approx(0.05)
    # 30d: 1-day + 20-day rows.
    assert by_window["30d"]["observation_count"] == 2
    assert by_window["30d"]["mean_abs_variance"] == pytest.approx(0.075)
    # 90d: all 3 rows.
    assert by_window["90d"]["observation_count"] == 3
    assert by_window["90d"]["mean_abs_variance"] == pytest.approx(
        (0.05 + 0.10 + 0.05) / 3, abs=1e-6
    )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def test_health_summary_includes_label_and_variance() -> None:
    from app.simulation.calibration_health import build_calibration_health

    out = build_calibration_health([
        (datetime(2026, 1, 1, tzinfo=timezone.utc), 0.10, 0.09, []),
    ])
    # |variance| 0.01 → WELL_CALIBRATED.
    assert "WELL_CALIBRATED" in out["summary"]


def test_health_summary_no_data_message() -> None:
    from app.simulation.calibration_health import build_calibration_health

    out = build_calibration_health([])
    assert "No data" in out["summary"]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_calibration_health_out_default_shape() -> None:
    from app.schemas.simulation import CalibrationHealthOut

    out = CalibrationHealthOut()
    assert out.overall_health == "INSUFFICIENT_DATA"
    assert out.mean_abs_variance is None
    assert out.observation_count == 0
    assert out.top_miscalibrated_architect is None
    assert out.architect_accuracy_counts == {}
    assert out.trend_buckets == []
    assert out.summary == ""


def test_calibration_health_out_round_trips_helper_payload() -> None:
    """The route layer must wrap ``build_calibration_health(...)``
    output directly into the Pydantic schema without coercion
    errors."""
    from app.schemas.simulation import CalibrationHealthOut
    from app.simulation.calibration_health import (
        build_calibration_health,
    )

    payload = build_calibration_health([
        (
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            0.10, 0.05,
            [_finding("PricingArchitect", "CRITICAL")],
        ),
    ])
    out = CalibrationHealthOut(**payload)
    assert out.observation_count == 1
    assert out.overall_health in (
        "WELL_CALIBRATED", "NEEDS_ATTENTION", "POORLY_CALIBRATED",
    )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_calibration_health_route_registered() -> None:
    """GET /simulations/calibration-health must appear in the
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
    assert "/simulations/calibration-health" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET" in methods_by_path["/simulations/calibration-health"]
    )


def test_calibration_health_route_query_params() -> None:
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
            r.path == "/simulations/calibration-health"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "ids" in query_param_names
            return
    raise AssertionError(
        "GET /simulations/calibration-health route not found"
    )