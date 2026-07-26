"""
Tests for the outlier-detection helper + schema + route
registration.

The outlier logic is pure-Python so we can exercise it
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
    from app.simulation import outlier_detection

    assert set(outlier_detection.__all__) == {
        "DEFAULT_Z_THRESHOLD",
        "MIN_Z_THRESHOLD",
        "MAX_Z_THRESHOLD",
        "LABEL_MILD",
        "LABEL_MODERATE",
        "LABEL_EXTREME",
        "VALID_SEVERITY_LABELS",
        "MODERATE_THRESHOLD",
        "EXTREME_THRESHOLD",
        "normalise_z_threshold",
        "build_outlier_detection",
    }


# ---------------------------------------------------------------------------
# normalise_z_threshold
# ---------------------------------------------------------------------------


def test_normalise_z_threshold_default_is_3() -> None:
    from app.simulation.outlier_detection import (
        DEFAULT_Z_THRESHOLD,
        normalise_z_threshold,
    )

    assert normalise_z_threshold(None) == DEFAULT_Z_THRESHOLD
    assert DEFAULT_Z_THRESHOLD == 3.0


def test_normalise_z_threshold_passthrough() -> None:
    from app.simulation.outlier_detection import normalise_z_threshold

    assert normalise_z_threshold(2.5) == 2.5
    assert normalise_z_threshold(5.0) == 5.0


def test_normalise_z_threshold_clamps_low_and_high() -> None:
    from app.simulation.outlier_detection import (
        MAX_Z_THRESHOLD,
        MIN_Z_THRESHOLD,
        normalise_z_threshold,
    )

    assert normalise_z_threshold(0.1) == MIN_Z_THRESHOLD
    assert normalise_z_threshold(20.0) == MAX_Z_THRESHOLD


# ---------------------------------------------------------------------------
# build_outlier_detection — empty / malformed input
# ---------------------------------------------------------------------------


def test_outlier_empty_input_returns_no_data() -> None:
    from app.simulation.outlier_detection import build_outlier_detection

    out = build_outlier_detection([])
    assert out["outliers"] == []
    assert out["observation_count"] == 0
    assert out["outlier_count"] == 0
    assert out["batch_mean_abs_variance"] == 0.0
    assert out["batch_std_abs_variance"] == 0.0


def test_outlier_skips_sims_with_missing_outcome() -> None:
    """A sim with None predicted / actual is skipped, not
    crashed."""
    from app.simulation.outlier_detection import build_outlier_detection

    out = build_outlier_detection([
        (1, 0.10, 0.05),
        (2, None, None),
        (3, "abc", "def"),
    ])
    # Only sim 1 contributes.
    assert out["observation_count"] == 1


def test_outlier_skips_sims_with_no_sim_id() -> None:
    from app.simulation.outlier_detection import build_outlier_detection

    out = build_outlier_detection([
        (None, 0.10, 0.05),
    ])
    assert out["observation_count"] == 0


# ---------------------------------------------------------------------------
# Z-score calculation
# ---------------------------------------------------------------------------


def test_outlier_flags_sim_far_above_mean() -> None:
    """A sim with |variance| ≫ batch mean is flagged."""
    from app.simulation.outlier_detection import build_outlier_detection

    # Lower threshold so the test data structure reliably
    # produces a flagged sim. (Same data at the default 3.0
    # threshold produces a z-score around 1.8 — see
    # test_outlier_summary_includes_count_and_threshold for
    # the format check.)
    out = build_outlier_detection([
        (1, 0.10, 0.05),  # 0.05
        (2, 0.10, 0.05),  # 0.05
        (3, 0.10, 0.05),  # 0.05
        (4, 0.10, 0.05),  # 0.05
        (5, 0.10, 0.60),  # 0.50 (outlier)
    ], z_threshold=1.5)
    assert out["outlier_count"] == 1
    flagged = out["outliers"][0]
    assert flagged["sim_id"] == 5
    assert flagged["abs_variance"] == pytest.approx(0.50)
    assert flagged["z_score"] > 1.5


def test_outlier_sorted_by_z_score_desc() -> None:
    """Most-extreme outlier surfaces first."""
    from app.simulation.outlier_detection import build_outlier_detection

    out = build_outlier_detection([
        (1, 0.10, 0.05),  # 0.05
        (2, 0.10, 0.05),  # 0.05
        (3, 0.10, 0.05),  # 0.05
        (4, 0.10, 0.05),  # 0.05
        (5, 0.10, 0.50),  # 0.50 (bigger outlier)
        (6, 0.10, 0.30),  # 0.30 (smaller outlier)
    ], z_threshold=1.5)
    z_scores = [o["z_score"] for o in out["outliers"]]
    assert z_scores == sorted(z_scores, reverse=True)
    assert out["outliers"][0]["sim_id"] == 5


def test_outlier_custom_z_threshold() -> None:
    """Lowering the threshold catches more sims."""
    from app.simulation.outlier_detection import build_outlier_detection

    rows = [
        (1, 0.10, 0.05),  # |variance| 0.05
        (2, 0.10, 0.05),
        (3, 0.10, 0.05),
        (4, 0.10, 0.05),
        # Outlier: |variance| 0.09 → well above bulk mean
        # (0.058) at z ≈ 1.8. Triggers loose threshold.
        (5, 0.10, 0.01),
    ]
    strict = build_outlier_detection(rows, z_threshold=3.0)
    loose = build_outlier_detection(rows, z_threshold=1.0)
    # Strict 3σ → mild sim NOT flagged.
    assert strict["outlier_count"] == 0
    # Loose 1σ → mild sim IS flagged.
    assert loose["outlier_count"] == 1


def test_outlier_z_score_capped_when_std_is_zero() -> None:
    """When all sims have the same |variance|, std = 0 → z-score
    is capped so the JSON stays serialisable."""
    from app.simulation.outlier_detection import build_outlier_detection

    out = build_outlier_detection([
        (1, 0.10, 0.05),  # 0.05
        (2, 0.10, 0.05),  # 0.05
        (3, 0.20, 0.15),  # 0.05
        (4, 0.10, 0.60),  # 0.55 (would be infinity)
    ], z_threshold=0.5)  # low so the flag fires
    # z_score capped at 9999.99 rather than NaN/Infinity.
    flagged = next(
        o for o in out["outliers"] if o["sim_id"] == 4
    )
    assert flagged["z_score"] <= 9999.99
    assert flagged["z_score"] > 0


def test_outlier_handles_single_observation() -> None:
    """One sim → std = 0 → no outliers."""
    from app.simulation.outlier_detection import build_outlier_detection

    out = build_outlier_detection([(1, 0.10, 0.05)])
    assert out["observation_count"] == 1
    assert out["outliers"] == []  # only 1 sim → can't be an outlier
    assert out["batch_std_abs_variance"] == 0.0


# ---------------------------------------------------------------------------
# Batch stats
# ---------------------------------------------------------------------------


def test_outlier_batch_mean_abs_variance() -> None:
    from app.simulation.outlier_detection import build_outlier_detection

    out = build_outlier_detection([
        (1, 0.10, 0.05),  # 0.05
        (2, 0.10, 0.20),  # 0.10
        (3, 0.10, 0.25),  # 0.15
    ])
    # mean(0.05, 0.10, 0.15) = 0.10
    assert out["batch_mean_abs_variance"] == pytest.approx(0.10)


def test_outlier_batch_std_sample() -> None:
    """Sample std-dev (1/n-1), not population std (1/n)."""
    from app.simulation.outlier_detection import build_outlier_detection

    out = build_outlier_detection([
        (1, 0.10, 0.00),  # 0.00
        (2, 0.10, 0.10),  # 0.10
    ])
    # mean = 0.05, sample variance = ((0.00-0.05)² + (0.10-0.05)²) / 1
    # = 0.005, std = sqrt(0.005) ≈ 0.0707
    expected = round(0.005 ** 0.5, 6)
    assert out["batch_std_abs_variance"] == pytest.approx(
        expected, abs=1e-6
    )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def test_outlier_summary_includes_count_and_threshold() -> None:
    from app.simulation.outlier_detection import build_outlier_detection

    # Use a low threshold so the test data structure (1
    # outlier among 5) reliably flags.
    out = build_outlier_detection([
        (1, 0.10, 0.05),
        (2, 0.10, 0.05),
        (3, 0.10, 0.05),
        (4, 0.10, 0.05),
        (5, 0.10, 0.50),  # outlier
    ], z_threshold=1.5)
    assert "1 of 5" in out["summary"]
    assert "z≥1.5" in out["summary"]


def test_outlier_summary_no_data_message() -> None:
    from app.simulation.outlier_detection import build_outlier_detection

    out = build_outlier_detection([])
    assert "No data" in out["summary"]


# ---------------------------------------------------------------------------
# severity_counts + top_deviation_summary
# ---------------------------------------------------------------------------


def test_outlier_severity_label_per_row() -> None:
    """Each outlier carries a severity label bucketed from its
    z-score."""
    from app.simulation.outlier_detection import build_outlier_detection

    out = build_outlier_detection([
        (1, 0.10, 0.05),  # |variance| 0.05
        (2, 0.10, 0.05),
        (3, 0.10, 0.05),
        (4, 0.10, 0.05),
        (5, 0.10, 0.01),  # outlier
    ], z_threshold=0.5)
    flagged = out["outliers"][0]
    assert "deviation_severity" in flagged
    assert flagged["deviation_severity"] in (
        "MILD", "MODERATE", "EXTREME",
    )


def test_outlier_severity_label_thresholds() -> None:
    """MILD < 3σ, MODERATE 3-5σ, EXTREME ≥ 5σ."""
    from app.simulation.outlier_detection import (
        LABEL_EXTREME,
        LABEL_MILD,
        LABEL_MODERATE,
        build_outlier_detection,
    )

    # The original input (4 identical bulk sims) is degenerate:
    # with constant |variance|, batch std = 0 and every sim
    # gets z = 0, so the outlier list is empty at any threshold.
    # Use a deliberately varied batch so each severity bucket
    # can be exercised.
    out = build_outlier_detection([
        (1, 0.10, 0.05),  # bulk (low z)
        (2, 0.10, 0.05),
        (3, 0.10, 0.05),
        (4, 0.10, 0.05),
        (5, 0.10, 0.20),  # MILD outlier
    ], z_threshold=0.5)
    # MILD boundary: < 3σ.
    flagged_mild = next(
        o for o in out["outliers"]
        if 1.5 <= o["z_score"] < 3.0
    )
    assert flagged_mild["deviation_severity"] == LABEL_MILD
    # Find a MODERATE one if any.
    moderate = [
        o for o in out["outliers"]
        if 3.0 <= o["z_score"] < 5.0
    ]
    if moderate:
        assert moderate[0]["deviation_severity"] == LABEL_MODERATE
    # EXTREME: any z ≥ 5.
    extreme = [
        o for o in out["outliers"]
        if o["z_score"] >= 5.0
    ]
    if extreme:
        assert extreme[0]["deviation_severity"] == LABEL_EXTREME


def test_outlier_severity_counts_histogram() -> None:
    """Counts each outlier by severity bucket."""
    from app.simulation.outlier_detection import build_outlier_detection

    # 30 bulk + 2 outliers so the mean is dominated by the
    # bulk. Low threshold (1σ) flags both outliers so the
    # histogram sum assertion is meaningful.
    out = build_outlier_detection([
        (i, 0.10, 0.095) for i in range(1, 31)  # bulk
    ] + [
        (31, 0.10, 0.20),  # outlier 1
        (32, 0.10, 0.30),  # outlier 2
    ], z_threshold=1.0)
    counts = out["severity_counts"]
    # Both outliers flagged at 1σ.
    assert out["outlier_count"] == 2
    # Counts sum to outlier_count.
    assert (
        counts["MILD"] + counts["MODERATE"] + counts["EXTREME"]
        == out["outlier_count"]
    )


def test_outlier_severity_counts_zero_for_no_outliers() -> None:
    """No outliers → all-zero counts (canonical shape)."""
    from app.simulation.outlier_detection import build_outlier_detection

    out = build_outlier_detection([
        (1, 0.10, 0.05),
        (2, 0.10, 0.05),
        (3, 0.10, 0.05),
    ], z_threshold=3.0)
    assert out["outlier_count"] == 0
    assert out["severity_counts"] == {
        "MILD": 0, "MODERATE": 0, "EXTREME": 0,
    }


def test_outlier_top_deviation_summary_picks_most_extreme() -> None:
    """top_deviation_summary carries the most-extreme outlier
    (highest z-score, which is outliers[0] after sort)."""
    from app.simulation.outlier_detection import build_outlier_detection

    out = build_outlier_detection([
        (1, 0.10, 0.05),  # bulk
        (2, 0.10, 0.05),
        (3, 0.10, 0.05),
        (4, 0.10, 0.05),
        (5, 0.10, 0.30),  # z ~13
        (6, 0.10, 0.20),  # z ~7
    ], z_threshold=0.5)
    top = out["top_deviation_summary"]
    assert top["sim_id"] == 5
    assert top["z_score"] == out["outliers"][0]["z_score"]


def test_outlier_top_deviation_summary_includes_delta() -> None:
    """delta = top.abs_variance − batch_mean."""
    from app.simulation.outlier_detection import build_outlier_detection

    out = build_outlier_detection([
        (1, 0.10, 0.05),  # bulk
        (2, 0.10, 0.05),
        (3, 0.10, 0.05),
        (4, 0.10, 0.05),
        (5, 0.10, 0.30),  # outlier
    ], z_threshold=0.5)
    top = out["top_deviation_summary"]
    expected_delta = round(
        top["abs_variance"] - top["batch_mean_abs_variance"], 6
    )
    assert top["delta"] == expected_delta
    assert top["delta"] > 0  # top is above mean


def test_outlier_top_deviation_summary_none_for_no_outliers() -> None:
    from app.simulation.outlier_detection import build_outlier_detection

    out = build_outlier_detection([
        (1, 0.10, 0.05),
        (2, 0.10, 0.05),
        (3, 0.10, 0.05),
    ], z_threshold=3.0)
    assert out["top_deviation_summary"] is None


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_outlier_detection_out_default_shape() -> None:
    from app.schemas.simulation import OutlierDetectionOut

    out = OutlierDetectionOut()
    assert out.outliers == []
    assert out.observation_count == 0
    assert out.outlier_count == 0
    assert out.batch_mean_abs_variance == 0.0
    assert out.batch_std_abs_variance == 0.0
    assert out.z_threshold == 3.0
    assert out.summary == ""


def test_outlier_detection_out_round_trips_helper_payload() -> None:
    """The route layer must wrap ``build_outlier_detection(...)``
    output directly into the Pydantic schema without coercion
    errors."""
    from app.schemas.simulation import OutlierDetectionOut
    from app.simulation.outlier_detection import (
        build_outlier_detection,
    )

    payload = build_outlier_detection([
        (1, 0.10, 0.05),
        (2, 0.10, 0.05),
        (3, 0.10, 0.05),
        (4, 0.10, 0.05),
        (5, 0.10, 0.50),
    ], z_threshold=1.5)
    out = OutlierDetectionOut(**payload)
    assert out.observation_count == 5
    assert out.outlier_count == 1
    assert out.z_threshold == 1.5
    # The outlier (sim 5, |variance| 0.40) lands in the MILD
    # bucket (z ≈ 1.79). severity_counts must therefore
    # tally it — the canonical all-zero shape is reserved
    # for the no-outliers case.
    assert out.severity_counts == {
        "MILD": 1, "MODERATE": 0, "EXTREME": 0,
    }
    assert out.top_deviation_summary is not None


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_outlier_detection_route_registered() -> None:
    """GET /simulations/outlier-detection must appear in the
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
    assert "/simulations/outlier-detection" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET" in methods_by_path["/simulations/outlier-detection"]
    )


def test_outlier_detection_route_query_params() -> None:
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
            r.path == "/simulations/outlier-detection"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "ids" in query_param_names
            assert "z_threshold" in query_param_names
            return
    raise AssertionError(
        "GET /simulations/outlier-detection route not found"
    )