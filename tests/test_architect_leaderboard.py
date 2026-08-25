"""
Tests for the architect leaderboard helper + schema + route
registration.

The leaderboard logic is pure-Python so we can exercise it
without spinning up Postgres. The DB-touching route is
smoke-tested via the route-registration pattern (gated by
scipy).
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
    from app.simulation import architect_leaderboard

    assert set(architect_leaderboard.__all__) == {
        "HIGH_PRIORITY_THRESHOLD",
        "LOW_PRIORITY_THRESHOLD",
        "NONE_PRIORITY_THRESHOLD",
        "VALID_PRIORITY_LABELS",
        "MAX_LEADERS",
        "build_architect_leaderboard",
    }


def test_priority_label_allowlist_pinned() -> None:
    from app.simulation.architect_leaderboard import (
        VALID_PRIORITY_LABELS,
    )

    assert set(VALID_PRIORITY_LABELS) == {
        "HIGH",
        "MEDIUM",
        "LOW",
        "NONE",
    }


# ---------------------------------------------------------------------------
# build_architect_leaderboard — empty / malformed input
# ---------------------------------------------------------------------------


def test_leaderboard_empty_input_returns_empty_payload() -> None:
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    out = build_architect_leaderboard([])
    assert out["leaderboard"] == []
    assert out["priority_counts"] == {
        "HIGH": 0,
        "MEDIUM": 0,
        "LOW": 0,
        "NONE": 0,
    }
    assert out["total_architects"] == 0


def test_leaderboard_handles_none_input() -> None:
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    out = build_architect_leaderboard(None)
    assert out["leaderboard"] == []


def test_leaderboard_skips_empty_architect_name() -> None:
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    out = build_architect_leaderboard([
        {"architect_name": "", "finding_count": 5},
        {"architect_name": "valid", "finding_count": 3},
    ])
    assert out["total_architects"] == 1
    assert out["leaderboard"][0]["architect_name"] == "valid"


# ---------------------------------------------------------------------------
# Composite score
# ---------------------------------------------------------------------------


def test_leaderboard_score_is_abs_calibration_times_finding_count() -> None:
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    out = build_architect_leaderboard([
        {
            "architect_name": "pricing",
            "finding_count": 10,
            "calibration_variance": 0.05,
            "calibration_direction": "OVER_PREDICTS",
            "recommendation": "TIGHTEN",
        },
    ])
    assert out["leaderboard"][0]["score"] == pytest.approx(0.50)


def test_leaderboard_score_zero_for_missing_calibration() -> None:
    """calibration_variance=None → score 0.0 so uncalibrated
    architects don't crowd out real signals."""
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    out = build_architect_leaderboard([
        {
            "architect_name": "uncalibrated",
            "finding_count": 100,
            "calibration_variance": None,
            "calibration_direction": "INSUFFICIENT_DATA",
        },
    ])
    assert out["leaderboard"][0]["score"] == pytest.approx(0.0)
    assert out["leaderboard"][0]["priority_label"] == "NONE"


def test_leaderboard_score_handles_under_prediction() -> None:
    """|calibration_variance| is used — under_prediction and
    over_prediction score the same."""
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    out = build_architect_leaderboard([
        {
            "architect_name": "trust",
            "finding_count": 4,
            "calibration_variance": -0.10,
            "calibration_direction": "UNDER_PREDICTS",
        },
    ])
    # |−0.10| × 4 = 0.40.
    assert out["leaderboard"][0]["score"] == pytest.approx(0.40)


def test_leaderboard_score_skips_non_numeric_calibration() -> None:
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    out = build_architect_leaderboard([
        {
            "architect_name": "broken",
            "finding_count": 5,
            "calibration_variance": "NaN",
        },
    ])
    assert out["leaderboard"][0]["score"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Priority label
# ---------------------------------------------------------------------------


def test_leaderboard_priority_label_high_above_threshold() -> None:
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    # Score = 0.10 × 10 = 1.0 → HIGH.
    out = build_architect_leaderboard([
        {
            "architect_name": "x",
            "finding_count": 10,
            "calibration_variance": 0.10,
        },
    ])
    assert out["leaderboard"][0]["priority_label"] == "HIGH"


def test_leaderboard_priority_label_medium_in_band() -> None:
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    # Score = 0.025 × 1 = 0.025 → MEDIUM (≥0.02 but < 0.05).
    out = build_architect_leaderboard([
        {
            "architect_name": "x",
            "finding_count": 1,
            "calibration_variance": 0.025,
        },
    ])
    assert out["leaderboard"][0]["score"] == pytest.approx(0.025)
    assert out["leaderboard"][0]["priority_label"] == "MEDIUM"


def test_leaderboard_priority_label_low_in_band() -> None:
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    # Score = 0.005 × 2 = 0.01 → LOW (≥0.005).
    out = build_architect_leaderboard([
        {
            "architect_name": "x",
            "finding_count": 2,
            "calibration_variance": 0.005,
        },
    ])
    assert out["leaderboard"][0]["priority_label"] == "LOW"


def test_leaderboard_priority_label_none_below_threshold() -> None:
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    # Score = 0.001 × 3 = 0.003 → NONE (<0.005).
    out = build_architect_leaderboard([
        {
            "architect_name": "x",
            "finding_count": 3,
            "calibration_variance": 0.001,
        },
    ])
    assert out["leaderboard"][0]["priority_label"] == "NONE"


def test_leaderboard_priority_counts_histogram() -> None:
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    out = build_architect_leaderboard([
        # HIGH: 0.10 × 10 = 1.0
        {"architect_name": "high", "finding_count": 10,
         "calibration_variance": 0.10},
        # MEDIUM: 0.025 × 1 = 0.025
        {"architect_name": "med", "finding_count": 1,
         "calibration_variance": 0.025},
        # LOW: 0.005 × 2 = 0.01
        {"architect_name": "low", "finding_count": 2,
         "calibration_variance": 0.005},
        # NONE: 0.001 × 3 = 0.003
        {"architect_name": "none", "finding_count": 3,
         "calibration_variance": 0.001},
    ])
    assert out["priority_counts"] == {
        "HIGH": 1,
        "MEDIUM": 1,
        "LOW": 1,
        "NONE": 1,
    }


# ---------------------------------------------------------------------------
# Sort order
# ---------------------------------------------------------------------------


def test_leaderboard_sorted_by_score_desc() -> None:
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    out = build_architect_leaderboard([
        {"architect_name": "a", "finding_count": 5, "calibration_variance": 0.02},
        {"architect_name": "b", "finding_count": 10, "calibration_variance": 0.10},
        {"architect_name": "c", "finding_count": 3, "calibration_variance": 0.05},
    ])
    scores = [r["score"] for r in out["leaderboard"]]
    assert scores == sorted(scores, reverse=True)


def test_leaderboard_tiebreak_by_finding_count_then_name() -> None:
    """Equal scores → more findings wins; still tied → name ASC."""
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    # Both have score 0.20 (5 × 0.04 vs 10 × 0.02).
    out = build_architect_leaderboard([
        {
            "architect_name": "alpha",
            "finding_count": 10,
            "calibration_variance": 0.02,
        },
        {
            "architect_name": "bravo",
            "finding_count": 5,
            "calibration_variance": 0.04,
        },
    ])
    # Both score 0.20 → finding_count DESC → bravo (10)... wait,
    # alpha has 10. So alpha first.
    assert out["leaderboard"][0]["architect_name"] == "alpha"


def test_leaderboard_still_tied_breaks_by_name_asc() -> None:
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    # Both identical scores + finding counts → name ASC.
    out = build_architect_leaderboard([
        {
            "architect_name": "zebra",
            "finding_count": 5,
            "calibration_variance": 0.04,
        },
        {
            "architect_name": "alpha",
            "finding_count": 5,
            "calibration_variance": 0.04,
        },
    ])
    assert out["leaderboard"][0]["architect_name"] == "alpha"


# ---------------------------------------------------------------------------
# top_n cap
# ---------------------------------------------------------------------------


def test_leaderboard_top_n_caps_results() -> None:
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    entries = [
        {
            "architect_name": f"a{i}",
            "finding_count": 5,
            "calibration_variance": 0.04,
        }
        for i in range(10)
    ]
    out = build_architect_leaderboard(entries, top_n=3)
    assert len(out["leaderboard"]) == 3
    assert out["top_n"] == 3
    # total_architects reflects the full set, not the cap.
    assert out["total_architects"] == 10


def test_leaderboard_default_top_n_is_max_leaders() -> None:
    from app.simulation.architect_leaderboard import (
        MAX_LEADERS,
        build_architect_leaderboard,
    )

    entries = [
        {
            "architect_name": f"a{i}",
            "finding_count": 5,
            "calibration_variance": 0.04,
        }
        for i in range(MAX_LEADERS + 5)
    ]
    out = build_architect_leaderboard(entries)
    assert len(out["leaderboard"]) == MAX_LEADERS
    assert out["total_architects"] == MAX_LEADERS + 5


def test_leaderboard_top_n_at_least_one() -> None:
    """Negative / zero top_n clamps to 1 (still returns one row)."""
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    out = build_architect_leaderboard(
        [{"architect_name": "a", "finding_count": 5,
          "calibration_variance": 0.04}],
        top_n=-5,
    )
    assert len(out["leaderboard"]) == 1
    assert out["top_n"] == 1


# ---------------------------------------------------------------------------
# Row fields
# ---------------------------------------------------------------------------


def test_leaderboard_row_echoes_calibration_direction() -> None:
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    out = build_architect_leaderboard([
        {
            "architect_name": "pricing",
            "finding_count": 10,
            "calibration_variance": 0.05,
            "calibration_direction": "OVER_PREDICTS",
            "recommendation": "TIGHTEN",
        },
    ])
    row = out["leaderboard"][0]
    assert row["calibration_direction"] == "OVER_PREDICTS"
    assert row["recommendation"] == "TIGHTEN"
    assert row["finding_count"] == 10
    assert row["calibration_variance"] == pytest.approx(0.05)


def test_leaderboard_row_uses_defaults_when_missing() -> None:
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    out = build_architect_leaderboard([
        {"architect_name": "a", "finding_count": 5},
    ])
    row = out["leaderboard"][0]
    assert row["calibration_variance"] is None
    assert row["calibration_direction"] == "INSUFFICIENT_DATA"
    assert row["recommendation"] == (
        "Continue — architect is calibrated"
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_architect_leaderboard_out_default_shape() -> None:
    from app.schemas.simulation import ArchitectLeaderboardOut

    out = ArchitectLeaderboardOut()
    assert out.leaderboard == []
    assert out.priority_counts == {}
    assert out.top_recommendation == (
        "Continue — architect is calibrated"
    )
    assert out.score_distribution == {}
    assert out.total_architects == 0
    assert out.top_n == 0


def test_architect_leaderboard_out_round_trips_helper_payload() -> None:
    """The route layer must wrap ``build_architect_leaderboard(...)``
    output directly into the Pydantic schema without coercion
    errors."""
    from app.schemas.simulation import ArchitectLeaderboardOut
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    payload = build_architect_leaderboard([
        {
            "architect_name": "pricing",
            "finding_count": 10,
            "calibration_variance": 0.05,
            "calibration_direction": "OVER_PREDICTS",
            "recommendation": "TIGHTEN",
        },
    ])
    out = ArchitectLeaderboardOut(**payload)
    assert out.total_architects == 1
    assert out.leaderboard[0]["architect_name"] == "pricing"
    assert out.leaderboard[0]["priority_label"] == "HIGH"


# ---------------------------------------------------------------------------
# top_recommendation
# ---------------------------------------------------------------------------


def test_leaderboard_top_recommendation_default_when_empty() -> None:
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    out = build_architect_leaderboard([])
    assert out["top_recommendation"] == (
        "Continue — architect is calibrated"
    )


def test_leaderboard_top_recommendation_picks_most_common() -> None:
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    out = build_architect_leaderboard([
        {
            "architect_name": "a",
            "finding_count": 10,
            "calibration_variance": 0.10,
            "recommendation": "TIGHTEN",
        },
        {
            "architect_name": "b",
            "finding_count": 8,
            "calibration_variance": 0.08,
            "recommendation": "TIGHTEN",
        },
        {
            "architect_name": "c",
            "finding_count": 5,
            "calibration_variance": 0.05,
            "recommendation": "LOOSEN",
        },
    ])
    assert out["top_recommendation"] == "TIGHTEN"


def test_leaderboard_top_recommendation_tiebreak_alphabetical() -> None:
    """Tied counts → alphabetical label wins for deterministic
    output."""
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    out = build_architect_leaderboard([
        {
            "architect_name": "a",
            "finding_count": 5,
            "calibration_variance": 0.10,
            "recommendation": "LOOSEN",
        },
        {
            "architect_name": "b",
            "finding_count": 5,
            "calibration_variance": 0.10,
            "recommendation": "TIGHTEN",
        },
    ])
    # LOOSEN < TIGHTEN alphabetically → LOOSEN wins.
    assert out["top_recommendation"] == "LOOSEN"


# ---------------------------------------------------------------------------
# score_distribution
# ---------------------------------------------------------------------------


def test_leaderboard_score_distribution_default_when_empty() -> None:
    """Empty leaderboard → all four bands present with zero
    counts (the dashboard always sees the canonical key
    shape)."""
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    out = build_architect_leaderboard([])
    assert out["score_distribution"] == {
        "score_zero": 0,
        "score_low": 0,
        "score_moderate": 0,
        "score_high": 0,
    }


def test_leaderboard_score_distribution_bands() -> None:
    """Each row lands in one of four score bands."""
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    out = build_architect_leaderboard([
        # score_zero: calibration_variance=None → score 0.0
        {"architect_name": "zero", "finding_count": 5,
         "calibration_variance": None},
        # score_low: 0.001 × 5 = 0.005 → 0 < score < 0.01
        {"architect_name": "low", "finding_count": 5,
         "calibration_variance": 0.001},
        # score_moderate: 0.005 × 5 = 0.025 → 0.01 ≤ score < 0.05
        {"architect_name": "moderate", "finding_count": 5,
         "calibration_variance": 0.005},
        # score_high: 0.10 × 5 = 0.5 → score ≥ 0.05
        {"architect_name": "high", "finding_count": 5,
         "calibration_variance": 0.10},
    ])
    sd = out["score_distribution"]
    assert sd == {
        "score_zero": 1,
        "score_low": 1,
        "score_moderate": 1,
        "score_high": 1,
    }


def test_leaderboard_score_distribution_boundary_values() -> None:
    """score == 0.01 → score_moderate (inclusive lower bound).
    score == 0.05 → score_high (inclusive lower bound)."""
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    # Two rows with score == 0.01 and 0.05 exactly.
    # finding_count=1, calibration=0.01 → score 0.01 →
    # score_moderate. finding_count=1, calibration=0.05 →
    # score 0.05 → score_high.
    out = build_architect_leaderboard([
        {"architect_name": "boundary_low",
         "finding_count": 1, "calibration_variance": 0.01},
        {"architect_name": "boundary_high",
         "finding_count": 1, "calibration_variance": 0.05},
    ])
    sd = out["score_distribution"]
    assert sd["score_moderate"] == 1
    assert sd["score_high"] == 1
    assert sd["score_zero"] == 0
    assert sd["score_low"] == 0


def test_leaderboard_score_distribution_caps_at_top_n() -> None:
    """Distribution reflects only the rows in the returned
    leaderboard (top_n), not the full by_architect list."""
    from app.simulation.architect_leaderboard import (
        build_architect_leaderboard,
    )

    # 3 rows, top_n=2 — only the top 2 (highest scores)
    # land in the distribution.
    entries = [
        {"architect_name": f"a{i}", "finding_count": 1,
         "calibration_variance": 0.10}  # score 0.10 → high
        for i in range(3)
    ]
    out = build_architect_leaderboard(entries, top_n=2)
    assert len(out["leaderboard"]) == 2
    assert out["score_distribution"] == {
        "score_zero": 0,
        "score_low": 0,
        "score_moderate": 0,
        "score_high": 2,
    }


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_architect_leaderboard_route_registered() -> None:
    """GET /simulations/architect-leaderboard must appear in the
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
    assert "/simulations/architect-leaderboard" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET" in methods_by_path["/simulations/architect-leaderboard"]
    )


def test_architect_leaderboard_route_query_params() -> None:
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
            r.path == "/simulations/architect-leaderboard"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "ids" in query_param_names
            assert "top_n" in query_param_names
            return
    raise AssertionError(
        "GET /simulations/architect-leaderboard route not found"
    )
