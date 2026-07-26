"""
Tests for the cluster drill-down helper + schema + route
registration.

The drill-down logic is pure-Python so we can exercise it
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
    from app.simulation import cluster_drill_down

    assert set(cluster_drill_down.__all__) == {
        "DEFAULT_OUTLIER_THRESHOLD",
        "MIN_OUTLIER_THRESHOLD",
        "MAX_OUTLIER_THRESHOLD",
        "UNDER_OBSERVED_RATIO",
        "LOW_VARIANCE_MAX_CV",
        "MODERATE_VARIANCE_MAX_CV",
        "LOW_CONVERSION_THRESHOLD",
        "PEER_PEAK_BAND",
        "PEER_ABOVE",
        "PEER_BELOW",
        "PEER_AT_PEAK",
        "PEER_UNKNOWN",
        "LABEL_HIGH_VARIANCE",
        "LABEL_MODERATE_VARIANCE",
        "LABEL_LOW_VARIANCE",
        "RECO_INVESTIGATE_OUTLIERS",
        "RECO_RECALIBRATE_VARIANCE",
        "RECO_COLLECT_MORE_OUTCOMES",
        "RECO_IMPROVE_LOW_CONVERSION",
        "RECO_CONTINUE",
        "normalise_outlier_threshold",
        "build_cluster_drill_down",
    }


# ---------------------------------------------------------------------------
# normalise_outlier_threshold
# ---------------------------------------------------------------------------


def test_normalise_outlier_threshold_default() -> None:
    from app.simulation.cluster_drill_down import (
        DEFAULT_OUTLIER_THRESHOLD,
        normalise_outlier_threshold,
    )

    assert normalise_outlier_threshold(None) == DEFAULT_OUTLIER_THRESHOLD


def test_normalise_outlier_threshold_clamps() -> None:
    from app.simulation.cluster_drill_down import normalise_outlier_threshold

    assert normalise_outlier_threshold(-0.5) == 0.0
    assert normalise_outlier_threshold(2.0) == 1.0


# ---------------------------------------------------------------------------
# build_cluster_drill_down — empty input
# ---------------------------------------------------------------------------


def test_drill_down_empty_returns_profile_only() -> None:
    """No sims → per_sim_history empty, aggregate zeros."""
    from app.simulation.cluster_drill_down import build_cluster_drill_down

    out = build_cluster_drill_down(
        "tier3_first_time_app_user",
        cluster_name="Tier-3 First-Time App User",
        population_weight=0.04,
    )
    assert out["cluster_profile"]["cluster_id"] == (
        "tier3_first_time_app_user"
    )
    assert out["cluster_profile"]["cluster_name"] == (
        "Tier-3 First-Time App User"
    )
    assert out["per_sim_history"] == []
    assert out["aggregate"]["observation_count"] == 0
    assert out["sim_count"] == 0


# ---------------------------------------------------------------------------
# Cluster profile echo
# ---------------------------------------------------------------------------


def test_drill_down_echoes_profile_fields() -> None:
    from app.simulation.cluster_drill_down import build_cluster_drill_down

    out = build_cluster_drill_down(
        "metro_power_professional",
        cluster_name="Metro Power Pro",
        cluster_description="Senior decision maker in metro India",
        cluster_traits={
            "income_level": 0.90,
            "digital_literacy": 0.85,
        },
        population_weight=0.05,
        dominant_behavior_pattern="Skips marketing, evaluates on ROI",
        known_failure_modes=["Trial exhaustion", "Procurement blocks"],
        product_affinities=["saas", "developer_tool"],
        demographic_profile={
            "geography": "tier_1", "age_bracket": "30_45",
        },
    )
    p = out["cluster_profile"]
    assert p["cluster_description"] == (
        "Senior decision maker in metro India"
    )
    assert p["cluster_traits"]["income_level"] == pytest.approx(0.90)
    assert p["population_weight"] == pytest.approx(0.05)
    assert p["dominant_behavior_pattern"] == (
        "Skips marketing, evaluates on ROI"
    )
    assert p["known_failure_modes"] == [
        "Trial exhaustion", "Procurement blocks",
    ]
    assert p["product_affinities"] == ["saas", "developer_tool"]
    assert p["demographic_profile"]["geography"] == "tier_1"


def test_drill_down_cluster_name_falls_back_to_id() -> None:
    """When no name is supplied, the cluster_id is echoed."""
    from app.simulation.cluster_drill_down import build_cluster_drill_down

    out = build_cluster_drill_down("tier3_first_time_app_user")
    assert out["cluster_profile"]["cluster_name"] == (
        "tier3_first_time_app_user"
    )


# ---------------------------------------------------------------------------
# Per-sim history
# ---------------------------------------------------------------------------


def test_drill_down_per_sim_history_carries_outlier_flag() -> None:
    """Each per-sim row carries ``sim_id``, ``conversion_rate``,
    and ``is_outlier``."""
    from app.simulation.cluster_drill_down import build_cluster_drill_down

    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[
            (101, 0.05),   # not outlier (within 10pp)
            (102, 0.30),   # outlier (above 10pp threshold)
        ],
    )
    history = out["per_sim_history"]
    assert len(history) == 2
    assert history[0]["sim_id"] == 101
    assert history[0]["conversion_rate"] == pytest.approx(0.05)
    assert history[0]["is_outlier"] is False
    assert history[1]["sim_id"] == 102
    assert history[1]["is_outlier"] is True


def test_drill_down_per_sim_history_sorted_by_sim_id() -> None:
    """History rows are sorted by sim_id ASC; None sim_ids go
    last so the dashboard's table is stable."""
    from app.simulation.cluster_drill_down import build_cluster_drill_down

    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[
            (203, 0.10),
            (101, 0.20),
            (None, 0.30),
        ],
    )
    sim_ids = [r["sim_id"] for r in out["per_sim_history"]]
    assert sim_ids == [101, 203, None]


def test_drill_down_per_sim_history_keeps_missing_rate_rows() -> None:
    """A sim without this cluster in its breakdown still gets
    a row (conversion_rate=None) so the dashboard can render
    'X of Y saw this cluster'."""
    from app.simulation.cluster_drill_down import build_cluster_drill_down

    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[
            (101, 0.10),
            (102, None),  # cluster missing from this sim
        ],
    )
    history = out["per_sim_history"]
    assert len(history) == 2
    missing_row = next(r for r in history if r["sim_id"] == 102)
    assert missing_row["conversion_rate"] is None
    assert missing_row["is_outlier"] is False


def test_drill_down_defensively_coerces_bad_rates() -> None:
    """String / bool / NaN / out-of-range rates are coerced to
    None so they don't poison the aggregate."""
    import math

    from app.simulation.cluster_drill_down import build_cluster_drill_down

    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[
            (101, 0.10),     # good
            (102, "abc"),    # non-numeric string
            (103, True),     # bool
            (104, math.nan), # NaN
            (105, 1.5),      # out of range
        ],
    )
    # Only (101, 0.10) survives.
    assert out["aggregate"]["observation_count"] == 1
    rates = [
        r["conversion_rate"] for r in out["per_sim_history"]
    ]
    assert None in rates  # missing / coerced rows present
    assert 0.10 in rates


# ---------------------------------------------------------------------------
# Aggregate stats
# ---------------------------------------------------------------------------


def test_drill_down_aggregate_mean_min_max() -> None:
    from app.simulation.cluster_drill_down import build_cluster_drill_down

    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[
            (101, 0.10),
            (102, 0.20),
            (103, 0.30),
        ],
    )
    a = out["aggregate"]
    assert a["mean_conversion"] == pytest.approx(0.20)
    assert a["min_conversion"] == pytest.approx(0.10)
    assert a["max_conversion"] == pytest.approx(0.30)
    assert a["observation_count"] == 3


def test_drill_down_std_zero_for_single_observation() -> None:
    from app.simulation.cluster_drill_down import build_cluster_drill_down

    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[(101, 0.10)],
    )
    assert out["aggregate"]["std_conversion"] == pytest.approx(0.0)


def test_drill_down_is_outlier_count_counts_threshold_breaches() -> None:
    from app.simulation.cluster_drill_down import build_cluster_drill_down

    # Default threshold 0.10 — 0.30 and 0.50 are outliers, 0.05
    # is not.
    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[
            (101, 0.05),
            (102, 0.30),
            (103, 0.50),
        ],
    )
    assert out["aggregate"]["is_outlier_count"] == 2


def test_drill_down_custom_outlier_threshold() -> None:
    """Pass ``outlier_threshold=0.01`` — every value above 0.01
    is now an outlier."""
    from app.simulation.cluster_drill_down import build_cluster_drill_down

    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[(101, 0.05), (102, 0.10)],
        outlier_threshold=0.01,
    )
    assert out["aggregate"]["is_outlier_count"] == 2


# ---------------------------------------------------------------------------
# Stability / coverage / needs_attention
# ---------------------------------------------------------------------------


def test_drill_down_stability_low_variance_for_consistent_rates() -> None:
    from app.simulation.cluster_drill_down import (
        LABEL_LOW_VARIANCE,
        build_cluster_drill_down,
    )

    # [0.10, 0.10] → CV=0 → LOW_VARIANCE.
    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[(101, 0.10), (102, 0.10)],
    )
    assert out["stability"] == LABEL_LOW_VARIANCE


def test_drill_down_stability_high_variance_for_spread_rates() -> None:
    from app.simulation.cluster_drill_down import (
        LABEL_HIGH_VARIANCE,
        build_cluster_drill_down,
    )

    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[(101, 0.05), (102, 0.30)],
    )
    assert out["stability"] == LABEL_HIGH_VARIANCE


def test_drill_down_observation_ratio_fraction() -> None:
    """observation_count / sim_count."""
    from app.simulation.cluster_drill_down import build_cluster_drill_down

    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[
            (101, 0.10),
            (102, 0.20),
            (103, None),  # missing
            (104, None),  # missing
        ],
    )
    assert out["aggregate"]["observation_count"] == 2
    assert out["sim_count"] == 4
    assert out["observation_ratio"] == pytest.approx(0.5)


def test_drill_down_under_observed_when_ratio_below_threshold() -> None:
    """observation_count / sim_count < 30% → under_observed."""
    from app.simulation.cluster_drill_down import build_cluster_drill_down

    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[
            (101, 0.10),
        ] + [(None, None) for _ in range(9)],
    )
    assert out["observation_ratio"] < 0.30
    assert out["under_observed"] is True


def test_drill_down_needs_attention_for_under_observed_or_high_variance() -> None:
    from app.simulation.cluster_drill_down import build_cluster_drill_down

    # under-observed → needs_attention.
    out1 = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[(101, 0.10)]
        + [(None, None) for _ in range(9)],
    )
    assert out1["needs_attention"] is True

    # High variance, well-observed → needs_attention.
    out2 = build_cluster_drill_down(
        "c2",
        per_sim_conversions=[
            (101, 0.05),
            (102, 0.05),
            (103, 0.30),
            (104, 0.30),
        ],
    )
    assert out2["under_observed"] is False
    assert out2["needs_attention"] is True


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_cluster_drill_down_out_default_shape() -> None:
    from app.schemas.simulation import ClusterDrillDownOut

    out = ClusterDrillDownOut()
    assert out.cluster_profile == {}
    assert out.per_sim_history == []
    assert out.aggregate == {}
    assert out.stability == "INSUFFICIENT_DATA"
    assert out.observation_ratio == 0.0
    assert out.under_observed is False
    assert out.needs_attention is False
    assert out.sim_count == 0
    assert out.recommendation == "Continue current calibration"
    assert out.peer_comparison == {}


def test_cluster_drill_down_out_round_trips_helper_payload() -> None:
    """The route layer must wrap ``build_cluster_drill_down(...)``
    output directly into the Pydantic schema without coercion
    errors."""
    from app.schemas.simulation import ClusterDrillDownOut
    from app.simulation.cluster_drill_down import (
        build_cluster_drill_down,
    )

    payload = build_cluster_drill_down(
        "tier3_first_time_app_user",
        cluster_name="Tier-3 First-Time App User",
        population_weight=0.04,
        per_sim_conversions=[(101, 0.05), (102, 0.30)],
    )
    out = ClusterDrillDownOut(**payload)
    assert out.cluster_profile["cluster_id"] == (
        "tier3_first_time_app_user"
    )
    assert out.aggregate["observation_count"] == 2
    assert out.sim_count == 2


# ---------------------------------------------------------------------------
# recommendation
# ---------------------------------------------------------------------------


def test_drill_down_recommendation_continue_for_healthy_cluster() -> None:
    from app.simulation.cluster_drill_down import (
        RECO_CONTINUE,
        build_cluster_drill_down,
    )

    # All values below the 0.10 outlier threshold, low variance,
    # well-observed, mean > 5pp → CONTINUE.
    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[
            (101, 0.08),
            (102, 0.08),
            (103, 0.08),
            (104, 0.08),
        ],
    )
    assert out["under_observed"] is False
    assert out["stability"] != "HIGH_VARIANCE"
    assert out["aggregate"]["is_outlier_count"] == 0
    assert out["recommendation"] == RECO_CONTINUE


def test_drill_down_recommendation_collect_for_under_observed() -> None:
    """Priority 1 — under-observed beats every other signal."""
    from app.simulation.cluster_drill_down import (
        RECO_COLLECT_MORE_OUTCOMES,
        build_cluster_drill_down,
    )

    # High variance AND under-observed → COLLECT wins.
    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[
            (101, 0.05),
            (102, 0.30),
        ] + [(None, None) for _ in range(8)],
    )
    assert out["under_observed"] is True
    assert out["recommendation"] == RECO_COLLECT_MORE_OUTCOMES


def test_drill_down_recommendation_recalibrate_for_high_variance() -> None:
    """Priority 2 — HIGH_VARIANCE beats outliers."""
    from app.simulation.cluster_drill_down import (
        RECO_RECALIBRATE_VARIANCE,
        build_cluster_drill_down,
    )

    # Well-observed, high variance, has outliers → RECALIBRATE wins.
    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[
            (101, 0.05),
            (102, 0.05),
            (103, 0.30),
            (104, 0.30),
            (105, 0.05),
            (106, 0.30),
        ],
    )
    assert out["under_observed"] is False
    assert out["stability"] == "HIGH_VARIANCE"
    assert out["aggregate"]["is_outlier_count"] >= 1
    assert out["recommendation"] == RECO_RECALIBRATE_VARIANCE


def test_drill_down_recommendation_investigate_for_outliers() -> None:
    """Priority 3 — outliers present (moderate variance, not high).

    With one outlier among a tight bulk, the CV stays below the
    HIGH_VARIANCE threshold only when there are many bulk
    observations. We use 30 bulk + 1 outlier so the variance
    contribution from the outlier stays small relative to the
    mean, leaving CV in the MODERATE band.
    """
    from app.simulation.cluster_drill_down import (
        RECO_INVESTIGATE_OUTLIERS,
        build_cluster_drill_down,
    )

    per_sim = [(i, 0.07) for i in range(101, 131)]
    # Outlier above the 0.10 threshold but close enough to the
    # bulk (0.07) that CV stays in MODERATE_VARIANCE band
    # rather than spiking to HIGH_VARIANCE.
    per_sim.append((131, 0.20))
    out = build_cluster_drill_down("c1", per_sim_conversions=per_sim)
    assert out["under_observed"] is False
    assert out["stability"] != "HIGH_VARIANCE"
    assert out["aggregate"]["is_outlier_count"] == 1
    assert out["recommendation"] == RECO_INVESTIGATE_OUTLIERS


def test_drill_down_recommendation_low_conversion_below_5pp() -> None:
    """Priority 4 — mean < 5pp (with stable, well-observed data,
    no outliers)."""
    from app.simulation.cluster_drill_down import (
        RECO_IMPROVE_LOW_CONVERSION,
        build_cluster_drill_down,
    )

    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[
            (101, 0.02),
            (102, 0.03),
            (103, 0.04),
        ],
    )
    assert out["under_observed"] is False
    assert out["stability"] != "HIGH_VARIANCE"
    assert out["aggregate"]["is_outlier_count"] == 0
    assert out["aggregate"]["mean_conversion"] < 0.05
    assert out["recommendation"] == RECO_IMPROVE_LOW_CONVERSION


# ---------------------------------------------------------------------------
# peer_comparison
# ---------------------------------------------------------------------------


def test_drill_down_peer_comparison_above_when_above_mean() -> None:
    from app.simulation.cluster_drill_down import (
        PEER_ABOVE,
        build_cluster_drill_down,
    )

    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[(101, 0.20), (102, 0.20)],
        batch_overall_mean=0.10,
    )
    pc = out["peer_comparison"]
    assert pc["cluster_mean"] == pytest.approx(0.20)
    assert pc["batch_overall_mean"] == pytest.approx(0.10)
    assert pc["delta"] == pytest.approx(0.10)
    assert pc["direction"] == PEER_ABOVE


def test_drill_down_peer_comparison_below_when_below_mean() -> None:
    from app.simulation.cluster_drill_down import (
        PEER_BELOW,
        build_cluster_drill_down,
    )

    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[(101, 0.02), (102, 0.02)],
        batch_overall_mean=0.10,
    )
    assert out["peer_comparison"]["direction"] == PEER_BELOW


def test_drill_down_peer_comparison_at_peak_when_within_band() -> None:
    """Within ±2pp of the batch mean → AT_BATCH_MEAN, not
    ABOVE / BELOW."""
    from app.simulation.cluster_drill_down import (
        PEER_AT_PEAK,
        build_cluster_drill_down,
    )

    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[(101, 0.10), (102, 0.11)],
        batch_overall_mean=0.10,
    )
    # Delta = 0.005, within the 2pp band.
    assert out["peer_comparison"]["direction"] == PEER_AT_PEAK


def test_drill_down_peer_comparison_unknown_when_batch_mean_absent() -> None:
    """batch_overall_mean=None → UNKNOWN, delta=None."""
    from app.simulation.cluster_drill_down import (
        PEER_UNKNOWN,
        build_cluster_drill_down,
    )

    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[(101, 0.10)],
    )
    pc = out["peer_comparison"]
    assert pc["batch_overall_mean"] is None
    assert pc["delta"] is None
    assert pc["direction"] == PEER_UNKNOWN


def test_drill_down_peer_comparison_handles_empty_per_sim() -> None:
    """No rates → mean=0 → delta=None when batch mean given."""
    from app.simulation.cluster_drill_down import build_cluster_drill_down

    out = build_cluster_drill_down(
        "c1",
        per_sim_conversions=[(101, None)],
        batch_overall_mean=0.10,
    )
    pc = out["peer_comparison"]
    assert pc["cluster_mean"] == 0.0
    assert pc["delta"] == pytest.approx(-0.10)
    assert pc["direction"] == "BELOW_BATCH_MEAN"


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_cluster_drill_down_route_registered() -> None:
    """GET /simulations/cluster-drill-down must appear in the
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
    assert "/simulations/cluster-drill-down" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET" in methods_by_path["/simulations/cluster-drill-down"]
    )


def test_cluster_drill_down_route_query_params() -> None:
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
            r.path == "/simulations/cluster-drill-down"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "cluster_id" in query_param_names
            assert "ids" in query_param_names
            assert "outlier_threshold" in query_param_names
            return
    raise AssertionError(
        "GET /simulations/cluster-drill-down route not found"
    )