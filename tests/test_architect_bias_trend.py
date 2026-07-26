"""
Tests for the per-architect bias trend helper + schema +
route registration.

The trend logic is pure-Python so we can exercise it without
spinning up Postgres. The DB-touching route is smoke-tested
via the route-registration pattern (gated by scipy).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    """Pin the module's ``__all__`` so a future rename surfaces
    as an import error rather than a silent attribute miss in
    the route."""
    from app.simulation import architect_bias_trend

    assert set(architect_bias_trend.__all__) == {
        "LABEL_IMPROVING",
        "LABEL_DEGRADING",
        "LABEL_STABLE",
        "LABEL_WELL_CALIBRATED",
        "LABEL_BIASED",
        "LABEL_UNKNOWN",
        "VALID_BIAS_LABELS",
        "build_architect_bias_trend",
    }


def test_bias_label_allowlist_pinned() -> None:
    from app.simulation.architect_bias_trend import VALID_BIAS_LABELS

    assert set(VALID_BIAS_LABELS) == {
        "IMPROVING",
        "DEGRADING",
        "STABLE",
        "WELL_CALIBRATED",
        "BIASED",
        "UNKNOWN",
    }


# ---------------------------------------------------------------------------
# build_architect_bias_trend — empty / malformed input
# ---------------------------------------------------------------------------


def test_trend_empty_rows_returns_unknown() -> None:
    from app.simulation.architect_bias_trend import (
        build_architect_bias_trend,
    )

    out = build_architect_bias_trend("PricingArchitect", [])
    assert out["architect_name"] == "PricingArchitect"
    assert out["bin_size"] == "month"
    assert out["bins"] == []
    assert out["overall_direction"] == "UNKNOWN"
    assert out["first_bin_abs_variance"] is None
    assert out["last_bin_abs_variance"] is None
    assert out["mean_abs_delta"] is None
    assert out["current_bias_label"] == "UNKNOWN"


def test_trend_skips_sims_without_outcome() -> None:
    """A sim with None predicted / actual is skipped."""
    from app.simulation.architect_bias_trend import (
        build_architect_bias_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=timezone.utc),
            None,
            0.10,
            [
                {
                    "architect_name": "PricingArchitect",
                    "severity": "CRITICAL",
                },
            ],
        ),
        (
            datetime(2026, 2, 15, tzinfo=timezone.utc),
            0.10,
            None,
            [
                {
                    "architect_name": "PricingArchitect",
                    "severity": "CRITICAL",
                },
            ],
        ),
    ]
    out = build_architect_bias_trend("PricingArchitect", rows)
    assert out["bins"] == []


def test_trend_skips_sims_without_findings_for_target() -> None:
    """A sim where the architect had NO findings is skipped."""
    from app.simulation.architect_bias_trend import (
        build_architect_bias_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=timezone.utc),
            0.10,
            0.05,
            [
                {
                    "architect_name": "TrustArchitect",
                    "severity": "WARNING",
                },
            ],
        ),
    ]
    out = build_architect_bias_trend("PricingArchitect", rows)
    assert out["bins"] == []


def test_trend_case_insensitive_architect_match() -> None:
    """Case-insensitive match: 'PRICINGARCHITECT' on the finding
    matches 'PricingArchitect' on the call (PascalCase
    preserved through casefold)."""
    from app.simulation.architect_bias_trend import (
        build_architect_bias_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=timezone.utc),
            0.10,
            0.05,
            [
                {
                    "architect_name": "PRICINGARCHITECT",
                    "severity": "CRITICAL",
                },
            ],
        ),
    ]
    out = build_architect_bias_trend("PricingArchitect", rows)
    assert len(out["bins"]) == 1


# ---------------------------------------------------------------------------
# Bin grouping
# ---------------------------------------------------------------------------


def test_trend_groups_by_month_by_default() -> None:
    from app.simulation.architect_bias_trend import (
        build_architect_bias_trend,
    )

    rows = [
        (
            datetime(2026, 1, 5, tzinfo=timezone.utc),
            0.10,
            0.05,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 1, 25, tzinfo=timezone.utc),
            0.20,
            0.10,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 10, tzinfo=timezone.utc),
            0.30,
            0.15,
            [{"architect_name": "PricingArchitect"}],
        ),
    ]
    out = build_architect_bias_trend("PricingArchitect", rows)
    bins = out["bins"]
    assert len(bins) == 2
    # January: variances [0.05, 0.10] → abs mean = 0.075.
    assert bins[0]["bin"] == "2026-01"
    assert bins[0]["mean_abs_variance"] == pytest.approx(0.075)
    assert bins[0]["observation_count"] == 2
    # February: variance [0.15] → abs mean = 0.15.
    assert bins[1]["bin"] == "2026-02"
    assert bins[1]["mean_abs_variance"] == pytest.approx(0.15)


def test_trend_groups_by_week_when_requested() -> None:
    from app.simulation.architect_bias_trend import (
        build_architect_bias_trend,
    )

    rows = [
        (
            datetime(2026, 1, 5, tzinfo=timezone.utc),  # Monday
            0.10,
            0.05,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 1, 7, tzinfo=timezone.utc),  # Wed same week
            0.15,
            0.05,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 1, 12, tzinfo=timezone.utc),  # next week
            0.20,
            0.10,
            [{"architect_name": "PricingArchitect"}],
        ),
    ]
    out = build_architect_bias_trend(
        "PricingArchitect", rows, bin_size="week",
    )
    bins = out["bins"]
    assert len(bins) == 2
    # First week: variances [0.05, 0.10] → abs mean = 0.075.
    assert bins[0]["observation_count"] == 2
    assert bins[0]["mean_abs_variance"] == pytest.approx(0.075)


# ---------------------------------------------------------------------------
# signed variance
# ---------------------------------------------------------------------------


def test_trend_signed_variance_carries_direction() -> None:
    """mean_signed_variance distinguishes over- vs under-prediction
    (positive vs negative) for the dashboard's divergence plot."""
    from app.simulation.architect_bias_trend import (
        build_architect_bias_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=timezone.utc),
            0.30,
            0.10,  # variance +0.20 (over)
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 15, tzinfo=timezone.utc),
            0.05,
            0.20,  # variance -0.15 (under)
            [{"architect_name": "PricingArchitect"}],
        ),
    ]
    out = build_architect_bias_trend("PricingArchitect", rows)
    bins = out["bins"]
    assert bins[0]["mean_signed_variance"] == pytest.approx(0.20)
    assert bins[1]["mean_signed_variance"] == pytest.approx(-0.15)


# ---------------------------------------------------------------------------
# Direction label
# ---------------------------------------------------------------------------


def test_trend_overall_direction_improving_when_bias_shrinks() -> None:
    """Bias went from 0.20 to 0.05 → IMPROVING."""
    from app.simulation.architect_bias_trend import (
        LABEL_IMPROVING,
        build_architect_bias_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=timezone.utc),
            0.30,
            0.10,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 15, tzinfo=timezone.utc),
            0.10,
            0.05,
            [{"architect_name": "PricingArchitect"}],
        ),
    ]
    out = build_architect_bias_trend("PricingArchitect", rows)
    assert out["overall_direction"] == LABEL_IMPROVING
    # first=0.20, last=0.05 → delta = -0.15.
    assert out["mean_abs_delta"] == pytest.approx(-0.15)


def test_trend_overall_direction_degrading_when_bias_grows() -> None:
    """Bias went from 0.05 to 0.20 → DEGRADING."""
    from app.simulation.architect_bias_trend import (
        LABEL_DEGRADING,
        build_architect_bias_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=timezone.utc),
            0.10,
            0.05,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 15, tzinfo=timezone.utc),
            0.30,
            0.10,
            [{"architect_name": "PricingArchitect"}],
        ),
    ]
    out = build_architect_bias_trend("PricingArchitect", rows)
    assert out["overall_direction"] == LABEL_DEGRADING


def test_trend_overall_direction_stable_within_threshold() -> None:
    """Delta within 1pp → STABLE so jitter doesn't read as drift."""
    from app.simulation.architect_bias_trend import (
        LABEL_STABLE,
        build_architect_bias_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=timezone.utc),
            0.10,
            0.05,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 15, tzinfo=timezone.utc),
            0.105,
            0.05,
            [{"architect_name": "PricingArchitect"}],
        ),
    ]
    out = build_architect_bias_trend("PricingArchitect", rows)
    # First mean_abs = 0.05, last = 0.055 → delta 0.005 < 0.01.
    assert out["overall_direction"] == LABEL_STABLE


# ---------------------------------------------------------------------------
# current_bias_label
# ---------------------------------------------------------------------------


def test_trend_current_bias_label_well_calibrated_below_threshold() -> None:
    """Last bin |variance| < 0.02 → WELL_CALIBRATED."""
    from app.simulation.architect_bias_trend import (
        LABEL_WELL_CALIBRATED,
        build_architect_bias_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=timezone.utc),
            0.10,
            0.10,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 15, tzinfo=timezone.utc),
            0.10,
            0.09,  # variance 0.01 < 0.02 → WELL
            [{"architect_name": "PricingArchitect"}],
        ),
    ]
    out = build_architect_bias_trend("PricingArchitect", rows)
    assert out["current_bias_label"] == LABEL_WELL_CALIBRATED


def test_trend_current_bias_label_biased_above_threshold() -> None:
    """Last bin |variance| ≥ 0.02 → BIASED."""
    from app.simulation.architect_bias_trend import (
        LABEL_BIASED,
        build_architect_bias_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=timezone.utc),
            0.30,
            0.10,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 15, tzinfo=timezone.utc),
            0.30,
            0.20,  # variance 0.10 ≥ 0.02 → BIASED
            [{"architect_name": "PricingArchitect"}],
        ),
    ]
    out = build_architect_bias_trend("PricingArchitect", rows)
    assert out["current_bias_label"] == LABEL_BIASED


# ---------------------------------------------------------------------------
# Defensive coercion
# ---------------------------------------------------------------------------


def test_trend_skips_invalid_iso_strings() -> None:
    """A bad timestamp is skipped, not crashed."""
    from app.simulation.architect_bias_trend import (
        build_architect_bias_trend,
    )

    rows = [
        (
            "not-a-timestamp",
            0.10,
            0.05,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 1, 15, tzinfo=timezone.utc),
            0.10,
            0.05,
            [{"architect_name": "PricingArchitect"}],
        ),
    ]
    out = build_architect_bias_trend("PricingArchitect", rows)
    assert len(out["bins"]) == 1


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_architect_bias_trend_out_default_shape() -> None:
    from app.schemas.simulation import ArchitectBiasTrendOut

    out = ArchitectBiasTrendOut()
    assert out.architect_name == ""
    assert out.bin_size == "month"
    assert out.bins == []
    assert out.overall_direction == "UNKNOWN"
    assert out.first_bin_abs_variance is None
    assert out.last_bin_abs_variance is None
    assert out.mean_abs_delta is None
    assert out.current_bias_label == "UNKNOWN"


def test_architect_bias_trend_out_round_trips_helper_payload() -> None:
    """The route layer must wrap
    ``build_architect_bias_trend(...)`` output directly into
    the Pydantic schema without coercion errors."""
    from app.schemas.simulation import ArchitectBiasTrendOut
    from app.simulation.architect_bias_trend import (
        build_architect_bias_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=timezone.utc),
            0.30,
            0.10,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 15, tzinfo=timezone.utc),
            0.10,
            0.05,
            [{"architect_name": "PricingArchitect"}],
        ),
    ]
    payload = build_architect_bias_trend(
        "PricingArchitect", rows,
    )
    out = ArchitectBiasTrendOut(**payload)
    assert out.architect_name == "PricingArchitect"
    assert out.overall_direction in (
        "IMPROVING", "DEGRADING", "STABLE", "UNKNOWN",
    )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_architect_bias_trend_route_registered() -> None:
    """GET /simulations/architect-bias-trend must appear in
    the router."""
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
    assert "/simulations/architect-bias-trend" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET" in methods_by_path["/simulations/architect-bias-trend"]
    )


def test_architect_bias_trend_route_query_params() -> None:
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
            r.path == "/simulations/architect-bias-trend"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "architect_name" in query_param_names
            assert "since" in query_param_names
            assert "until" in query_param_names
            assert "bin" in query_param_names
            return
    raise AssertionError(
        "GET /simulations/architect-bias-trend route not found"
    )