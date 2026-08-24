"""Tests for the per-project outcomes digest helper +
schema + route registration.

The helper is pure-Python so it can be exercised without
a DB. The route-registration check is gated by scipy + a
razorpay stub (same pattern as the other route tests).
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import outcomes_digest_v2

    assert set(outcomes_digest_v2.__all__) == {
        "MAX_PAIRS",
        "MAE_OK_THRESHOLD",
        "MAE_WATCH_THRESHOLD",
        "TREND_DELTA_THRESHOLD",
        "ARCHITECT_BIN_TRUSTED",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_outcomes_digest",
    }


# ---------------------------------------------------------------------------
# Empty + single-pair input
# ---------------------------------------------------------------------------


def test_digest_empty_returns_insufficient() -> None:
    from app.simulation.outcomes_digest_v2 import build_outcomes_digest

    out = build_outcomes_digest([])
    assert out["outcome_count"] == 0
    assert out["usable_count"] == 0
    assert out["mean_abs_variance"] is None
    assert out["bias_direction"] == "INSUFFICIENT_DATA"


def test_digest_skips_none_pairs() -> None:
    """Pairs with None predicted or actual must not
    inflate usable_count."""
    from app.simulation.outcomes_digest_v2 import build_outcomes_digest

    out = build_outcomes_digest([
        (None, 0.05),
        (0.04, None),
        (0.05, 0.06),
        (0.05, 0.04),
    ])
    assert out["outcome_count"] == 4
    assert out["usable_count"] == 2


# ---------------------------------------------------------------------------
# MAE severity
# ---------------------------------------------------------------------------


def test_digest_mae_severity_ok() -> None:
    from app.simulation.outcomes_digest_v2 import (
        SIGNAL_OK,
        build_outcomes_digest,
    )

    out = build_outcomes_digest([
        (0.05, 0.05), (0.05, 0.06),
    ])
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "mean_abs_variance"
    )
    assert sig["severity"] == SIGNAL_OK


def test_digest_mae_severity_critical() -> None:
    from app.simulation.outcomes_digest_v2 import (
        SIGNAL_CRITICAL,
        build_outcomes_digest,
    )

    out = build_outcomes_digest([
        (0.05, 0.20),
    ])
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "mean_abs_variance"
    )
    assert sig["severity"] == SIGNAL_CRITICAL


# ---------------------------------------------------------------------------
# Bias direction
# ---------------------------------------------------------------------------


def test_digest_bias_direction_over_predicting() -> None:
    from app.simulation.outcomes_digest_v2 import build_outcomes_digest

    # Predictions systematically higher than actuals.
    out = build_outcomes_digest([
        (0.10, 0.05), (0.10, 0.04), (0.10, 0.06),
    ])
    assert out["bias_direction"] == "OVER-PREDICTING"


def test_digest_bias_direction_under_predicting() -> None:
    from app.simulation.outcomes_digest_v2 import build_outcomes_digest

    # Predictions systematically lower than actuals.
    out = build_outcomes_digest([
        (0.02, 0.10), (0.02, 0.12), (0.02, 0.09),
    ])
    assert out["bias_direction"] == "UNDER-PREDICTING"


def test_digest_bias_direction_balanced() -> None:
    from app.simulation.outcomes_digest_v2 import build_outcomes_digest

    out = build_outcomes_digest([
        (0.05, 0.051), (0.05, 0.049), (0.05, 0.050),
    ])
    assert out["bias_direction"] == "BALANCED"


# ---------------------------------------------------------------------------
# Accuracy trend
# ---------------------------------------------------------------------------


def test_digest_trend_improving() -> None:
    """Recent MAE lower than prior MAE → IMPROVING."""
    from app.simulation.outcomes_digest_v2 import build_outcomes_digest

    # Pairs newest-first. Recent (first 4) tighter than
    # prior (last 4).
    pairs = [
        # Recent (tight)
        (0.05, 0.051), (0.05, 0.049),
        (0.05, 0.052), (0.05, 0.048),
        # Prior (loose)
        (0.05, 0.10),  (0.05, 0.02),
        (0.05, 0.11),  (0.05, 0.01),
    ]
    out = build_outcomes_digest(pairs)
    assert out["accuracy_trend"] == "IMPROVING"


def test_digest_trend_degrading() -> None:
    from app.simulation.outcomes_digest_v2 import build_outcomes_digest

    pairs = [
        # Recent (loose)
        (0.05, 0.10), (0.05, 0.02),
        (0.05, 0.11), (0.05, 0.01),
        # Prior (tight)
        (0.05, 0.051), (0.05, 0.049),
        (0.05, 0.052), (0.05, 0.048),
    ]
    out = build_outcomes_digest(pairs)
    assert out["accuracy_trend"] == "DEGRADING"


def test_digest_trend_stable_when_window_too_small() -> None:
    from app.simulation.outcomes_digest_v2 import build_outcomes_digest

    # Only 3 pairs → INSUFFICIENT_DATA per the trend rule.
    out = build_outcomes_digest([
        (0.05, 0.10), (0.05, 0.02), (0.05, 0.06),
    ])
    assert out["accuracy_trend"] == "INSUFFICIENT_DATA"


# ---------------------------------------------------------------------------
# Architect extremes
# ---------------------------------------------------------------------------


def test_digest_picks_worst_architect_when_tighten() -> None:
    from app.simulation.outcomes_digest_v2 import build_outcomes_digest

    out = build_outcomes_digest(
        prediction_pairs=[(0.05, 0.05)],
        architect_leaderboard=[
            {
                "architect_name": "PricingArchitect",
                "recommendation": "TIGHTEN",
                "score": 0.5,
                "priority_label": "HIGH",
            },
            {
                "architect_name": "TrustArchitect",
                "recommendation": "TRUSTED",
                "score": 0.0,
                "priority_label": "NONE",
            },
        ],
    )
    assert out["worst_architect"]["architect_name"] == (
        "PricingArchitect"
    )


def test_digest_picks_best_architect_when_trusted() -> None:
    from app.simulation.outcomes_digest_v2 import build_outcomes_digest

    out = build_outcomes_digest(
        prediction_pairs=[(0.05, 0.05)],
        architect_leaderboard=[
            {
                "architect_name": "PricingArchitect",
                "recommendation": "TIGHTEN",
                "score": 0.5,
                "priority_label": "HIGH",
            },
            {
                "architect_name": "TrustArchitect",
                "recommendation": "TRUSTED",
                "score": 0.0,
                "priority_label": "NONE",
            },
        ],
    )
    assert out["best_architect"]["architect_name"] == (
        "TrustArchitect"
    )


def test_digest_no_worst_architect_when_leaderboard_empty() -> None:
    from app.simulation.outcomes_digest_v2 import build_outcomes_digest

    out = build_outcomes_digest(
        prediction_pairs=[(0.05, 0.05)],
        architect_leaderboard=None,
    )
    assert out["worst_architect"] is None
    assert out["best_architect"] is None


# ---------------------------------------------------------------------------
# Calibration health passthrough
# ---------------------------------------------------------------------------


def test_digest_passes_calibration_health_through() -> None:
    from app.simulation.outcomes_digest_v2 import build_outcomes_digest

    health = {
        "overall_health": "WELL_CALIBRATED",
        "mean_abs_variance": 0.012,
    }
    out = build_outcomes_digest(
        prediction_pairs=[(0.05, 0.05)],
        calibration_health=health,
    )
    assert out["calibration_health"] == health


# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------


def test_digest_narrative_over_predicting_warning() -> None:
    from app.simulation.outcomes_digest_v2 import build_outcomes_digest

    out = build_outcomes_digest([
        (0.10, 0.05), (0.10, 0.04), (0.10, 0.06),
    ])
    assert (
        "overshoot" in out["narrative"].lower()
        or "over-predict" in out["narrative"].lower()
    )


def test_digest_narrative_under_predicting_warning() -> None:
    from app.simulation.outcomes_digest_v2 import build_outcomes_digest

    out = build_outcomes_digest([
        (0.02, 0.10), (0.02, 0.12), (0.02, 0.09),
    ])
    assert "undershoot" in out["narrative"].lower()


def test_digest_narrative_mentions_architects_when_present() -> None:
    from app.simulation.outcomes_digest_v2 import build_outcomes_digest

    out = build_outcomes_digest(
        prediction_pairs=[(0.05, 0.05)],
        architect_leaderboard=[
            {
                "architect_name": "PricingArchitect",
                "recommendation": "TIGHTEN",
                "score": 0.5,
                "priority_label": "HIGH",
            },
            {
                "architect_name": "TrustArchitect",
                "recommendation": "TRUSTED",
                "score": 0.0,
                "priority_label": "NONE",
            },
        ],
    )
    assert "PricingArchitect" in out["narrative"]
    assert "TrustArchitect" in out["narrative"]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_outcomes_digest_out_default_shape() -> None:
    from app.schemas.outcome import OutcomesDigestOut

    out = OutcomesDigestOut()
    assert out.outcome_count == 0
    assert out.usable_count == 0
    assert out.mean_abs_variance is None
    assert (
        out.bias_direction == "INSUFFICIENT_DATA"
    )
    assert (
        out.accuracy_trend == "INSUFFICIENT_DATA"
    )


def test_outcomes_digest_out_round_trips_helper_payload() -> None:
    from app.schemas.outcome import OutcomesDigestOut
    from app.simulation.outcomes_digest_v2 import (
        build_outcomes_digest,
    )

    payload = build_outcomes_digest([
        (0.10, 0.05), (0.10, 0.04), (0.10, 0.06),
    ])
    out = OutcomesDigestOut(**payload)
    assert out.outcome_count == 3
    assert out.usable_count == 3
    assert out.bias_direction == "OVER-PREDICTING"


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_outcomes_digest_route_registered() -> None:
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import outcomes as out_mod

    paths = {r.path for r in out_mod.router.routes}
    assert (
        "/projects/{project_id}/outcomes-digest" in paths
    )

    methods_by_path: dict[str, set[str]] = {}
    for r in out_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET"
        in methods_by_path[
            "/projects/{project_id}/outcomes-digest"
        ]
    )
