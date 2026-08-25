"""
Tests for the per-architect bias trend helper + schema +
route registration.

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


def test_direction_from_variance_uses_label_improving() -> None:
    """Regression: ``_direction_from_variance`` previously had
    ``TREND_IMPROVING if False else LABEL_IMPROVING`` — a
    dead-code toggle that always returned ``LABEL_IMPROVING``
    but obscured intent and tripped lint. Pin that improving
    direction is LABEL_IMPROVING, not the cluster trend's
    TREND_UP.
    """
    from app.simulation.architect_bias_trend import (
        LABEL_DEGRADING,
        LABEL_IMPROVING,
        LABEL_STABLE,
        _direction_from_variance,
    )
    # Last is smaller (improving): delta < 0 → LABEL_IMPROVING.
    assert _direction_from_variance(0.10, 0.02) == LABEL_IMPROVING
    # Last is larger (degrading): delta > 0 → LABEL_DEGRADING.
    assert _direction_from_variance(0.02, 0.10) == LABEL_DEGRADING
    # Within stable threshold: → LABEL_STABLE.
    assert _direction_from_variance(0.05, 0.06) == LABEL_STABLE
    # Either side missing → UNKNOWN.
    assert _direction_from_variance(None, 0.05) == "UNKNOWN"
    assert _direction_from_variance(0.05, None) == "UNKNOWN"


def test_trend_dedupes_to_latest_outcome_per_sim() -> None:
    """Regression: the route layer's dedup logic kept the
    newest outcome per sim. If a founder submitted 3 outcomes
    for the same sim, the trend used to see 3 rows (one per
    outcome) because the dedup used ``id(r)`` on object
    identity and dead-code ``if r[0] in seen if False else
    False``. After the fix, the route selects ``Simulation.id``
    in the query and dedupes on ``r.id`` so the helper sees
    exactly 1 row per sim. This test pins the helper's input
    contract: pass the post-dedup rows, get 1 bin per sim.
    """
    from app.simulation.architect_bias_trend import (
        build_architect_bias_trend,
    )

    findings = [
        {
            "architect_name": "PricingArchitect",
            "severity": "CRITICAL",
        },
    ]
    # Pre-dedup rows would be 3 (oldest, middle, newest
    # outcome for the same sim). The post-dedup row is the
    # newest (Outcome.created_at DESC → first row per sim).
    post_dedup_rows = [
        (
            datetime(2026, 3, 20, tzinfo=UTC),
            0.30,  # newest outcome: predicted
            0.05,  # actual
            findings,
        ),
    ]
    out = build_architect_bias_trend("PricingArchitect", post_dedup_rows)
    # Exactly 1 bin, observation_count == 1, no double-counting.
    assert len(out["bins"]) == 1
    assert out["bins"][0]["observation_count"] == 1
    assert out["last_bin_abs_variance"] == round(abs(0.30 - 0.05), 6)
    """A sim with None predicted / actual is skipped."""
    from app.simulation.architect_bias_trend import (
        build_architect_bias_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=UTC),
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
            datetime(2026, 2, 15, tzinfo=UTC),
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
            datetime(2026, 1, 15, tzinfo=UTC),
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
            datetime(2026, 1, 15, tzinfo=UTC),
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
            datetime(2026, 1, 5, tzinfo=UTC),
            0.10,
            0.05,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 1, 25, tzinfo=UTC),
            0.20,
            0.10,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 10, tzinfo=UTC),
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
            datetime(2026, 1, 5, tzinfo=UTC),  # Monday
            0.10,
            0.05,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 1, 7, tzinfo=UTC),  # Wed same week
            0.15,
            0.05,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 1, 12, tzinfo=UTC),  # next week
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
            datetime(2026, 1, 15, tzinfo=UTC),
            0.30,
            0.10,  # variance +0.20 (over)
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
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
            datetime(2026, 1, 15, tzinfo=UTC),
            0.30,
            0.10,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
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
            datetime(2026, 1, 15, tzinfo=UTC),
            0.10,
            0.05,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
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
            datetime(2026, 1, 15, tzinfo=UTC),
            0.10,
            0.05,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
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
            datetime(2026, 1, 15, tzinfo=UTC),
            0.10,
            0.10,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
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
            datetime(2026, 1, 15, tzinfo=UTC),
            0.30,
            0.10,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
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
            datetime(2026, 1, 15, tzinfo=UTC),
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
    assert out.bias_direction_distribution == {}
    assert out.peak_bias_bin is None


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
            datetime(2026, 1, 15, tzinfo=UTC),
            0.30,
            0.10,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
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
# bias_direction_distribution
# ---------------------------------------------------------------------------


def test_trend_direction_distribution_default_when_empty() -> None:
    """Empty input → three zero-count keys (canonical shape
    preserved so the dashboard always sees the same
    keys)."""
    from app.simulation.architect_bias_trend import (
        build_architect_bias_trend,
    )

    out = build_architect_bias_trend("PricingArchitect", [])
    assert out["bias_direction_distribution"] == {
        "over_predicts": 0,
        "under_predicts": 0,
        "balanced": 0,
    }


def test_trend_direction_distribution_classifies_by_signed() -> None:
    """Each bin's mean_signed_variance → OVER_PREDICTS / UNDER
    / BALANCED bucket."""
    from app.simulation.architect_bias_trend import (
        build_architect_bias_trend,
    )

    rows = [
        # Jan: predicted > actual → +0.05 → over.
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            0.10,
            0.05,
            [{"architect_name": "PricingArchitect"}],
        ),
        # Feb: predicted < actual → -0.05 → under.
        (
            datetime(2026, 2, 15, tzinfo=UTC),
            0.05,
            0.10,
            [{"architect_name": "PricingArchitect"}],
        ),
        # Mar: predicted == actual → 0 → balanced.
        (
            datetime(2026, 3, 15, tzinfo=UTC),
            0.10,
            0.10,
            [{"architect_name": "PricingArchitect"}],
        ),
    ]
    out = build_architect_bias_trend("PricingArchitect", rows)
    assert out["bias_direction_distribution"] == {
        "over_predicts": 1,
        "under_predicts": 1,
        "balanced": 1,
    }


def test_trend_direction_distribution_skips_empty_buckets() -> None:
    """A single OVER bin → distribution has only over_predicts=1."""
    from app.simulation.architect_bias_trend import (
        build_architect_bias_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            0.20,
            0.05,
            [{"architect_name": "PricingArchitect"}],
        ),
    ]
    out = build_architect_bias_trend("PricingArchitect", rows)
    d = out["bias_direction_distribution"]
    assert d == {
        "over_predicts": 1,
        "under_predicts": 0,
        "balanced": 0,
    }


# ---------------------------------------------------------------------------
# peak_bias_bin
# ---------------------------------------------------------------------------


def test_trend_peak_bias_bin_none_when_empty() -> None:
    from app.simulation.architect_bias_trend import (
        build_architect_bias_trend,
    )

    out = build_architect_bias_trend("PricingArchitect", [])
    assert out["peak_bias_bin"] is None


def test_trend_peak_bias_bin_picks_highest_mean_abs() -> None:
    from app.simulation.architect_bias_trend import (
        build_architect_bias_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            0.10,
            0.05,  # variance 0.05
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
            0.30,
            0.10,  # variance 0.20 (highest)
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 3, 15, tzinfo=UTC),
            0.20,
            0.15,  # variance 0.05
            [{"architect_name": "PricingArchitect"}],
        ),
    ]
    out = build_architect_bias_trend("PricingArchitect", rows)
    peak = out["peak_bias_bin"]
    assert peak["bin"] == "2026-02"
    assert peak["mean_abs_variance"] == pytest.approx(0.20)
    assert peak["direction"] == "OVER_PREDICTS"


def test_trend_peak_bias_bin_tiebreak_by_latest_bin() -> None:
    """Tied |variance| → latest bin wins (stable, newest
    surface)."""
    from app.simulation.architect_bias_trend import (
        build_architect_bias_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            0.10,
            0.05,
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
            0.15,
            0.10,
            [{"architect_name": "PricingArchitect"}],
        ),
    ]
    out = build_architect_bias_trend("PricingArchitect", rows)
    # Both have |variance|=0.05 → later bin (Feb) wins.
    assert out["peak_bias_bin"]["bin"] == "2026-02"


def test_trend_peak_bias_bin_direction_labels() -> None:
    """direction field uses OVER_PREDICTS / UNDER_PREDICTS /
    BALANCED based on signed variance."""
    from app.simulation.architect_bias_trend import (
        build_architect_bias_trend,
    )

    rows = [
        (
            datetime(2026, 1, 15, tzinfo=UTC),
            0.05,
            0.20,  # -0.15 (under)
            [{"architect_name": "PricingArchitect"}],
        ),
        (
            datetime(2026, 2, 15, tzinfo=UTC),
            0.30,
            0.10,  # +0.20 (over, peak)
            [{"architect_name": "PricingArchitect"}],
        ),
    ]
    out = build_architect_bias_trend("PricingArchitect", rows)
    peak = out["peak_bias_bin"]
    # Peak is the OVER bin (Feb).
    assert peak["bin"] == "2026-02"
    assert peak["direction"] == "OVER_PREDICTS"
    assert peak["mean_signed_variance"] == pytest.approx(0.20)


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
