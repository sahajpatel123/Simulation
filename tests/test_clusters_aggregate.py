"""
Tests for the cross-simulation cluster portfolio aggregate helper
+ schema + route registration.

The aggregating logic is pure-Python so we can exercise it without
spinning up Postgres. The DB-touching route is smoke-tested via
the route-registration pattern (gated by scipy).
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# normalise_top_n
# ---------------------------------------------------------------------------


def test_normalise_top_n_default_and_bounds() -> None:
    from app.simulation.clusters_aggregate import (
        DEFAULT_TOP_N,
        MAX_TOP_N,
        normalise_top_n,
    )

    assert normalise_top_n(None) == DEFAULT_TOP_N
    assert normalise_top_n(0) == 1
    assert normalise_top_n(-5) == 1
    assert normalise_top_n(MAX_TOP_N + 1) == MAX_TOP_N
    assert normalise_top_n(25) == 25


# ---------------------------------------------------------------------------
# aggregate_clusters — empty / malformed input
# ---------------------------------------------------------------------------


def test_aggregate_empty_input_returns_zero_summary() -> None:
    from app.simulation.clusters_aggregate import aggregate_clusters

    out = aggregate_clusters([])
    assert out["by_cluster"] == []
    assert out["top_laggards"] == []
    assert out["top_performers"] == []
    assert out["simulation_count"] == 0
    assert out["clusters_seen"] == 0
    assert out["under_observed_count"] == 0
    assert out["needs_attention_count"] == 0


def test_aggregate_handles_missing_results_json() -> None:
    """Defensive — None / non-dict payloads shouldn't crash."""
    from app.simulation.clusters_aggregate import aggregate_clusters

    out = aggregate_clusters([None, {}, "not a dict", []])
    assert out["simulation_count"] == 4
    assert out["by_cluster"] == []


def test_aggregate_handles_empty_breakdowns() -> None:
    from app.simulation.clusters_aggregate import aggregate_clusters

    out = aggregate_clusters([
        {"cluster_breakdown": {}},
        {"cluster_breakdown": None},
        {},
    ])
    assert out["simulation_count"] == 3
    assert out["by_cluster"] == []


def test_aggregate_handles_legacy_conductor_nested_shape() -> None:
    """Older persisted shape stores the breakdown under
    ``results_json.conductor.cluster_breakdown`` — both shapes
    must be accepted."""
    from app.simulation.clusters_aggregate import aggregate_clusters

    out = aggregate_clusters([
        {"conductor": {"cluster_breakdown": {"c1": 0.05}}},
        {"cluster_breakdown": {"c1": 0.07}},
    ])
    assert out["clusters_seen"] == 1
    assert out["by_cluster"][0]["observation_count"] == 2


def test_aggregate_skips_non_numeric_cluster_values() -> None:
    from app.simulation.clusters_aggregate import aggregate_clusters

    out = aggregate_clusters([
        {"cluster_breakdown": {
            "c1": 0.05,
            "c2": "NaN",
            "c3": 1.5,  # out of range — skip
            "c4": None,
            "c5": True,  # bool — skip
            "c6": "abc",  # non-numeric — skip
        }},
    ])
    # Only c1 should survive.
    assert out["clusters_seen"] == 1
    assert out["by_cluster"][0]["cluster_id"] == "c1"


def test_aggregate_skips_empty_cluster_id_keys() -> None:
    """Defensive — an empty string is not a valid cluster id."""
    from app.simulation.clusters_aggregate import aggregate_clusters

    out = aggregate_clusters([
        {"cluster_breakdown": {"": 0.05, "c1": 0.10}},
    ])
    cluster_ids = {r["cluster_id"] for r in out["by_cluster"]}
    assert cluster_ids == {"c1"}


# ---------------------------------------------------------------------------
# aggregate_clusters — per-cluster stats
# ---------------------------------------------------------------------------


def test_aggregate_computes_mean_min_max() -> None:
    from app.simulation.clusters_aggregate import aggregate_clusters

    out = aggregate_clusters([
        {"cluster_breakdown": {"c1": 0.10, "c2": 0.20}},
        {"cluster_breakdown": {"c1": 0.20, "c2": 0.30}},
        {"cluster_breakdown": {"c1": 0.30}},
    ])
    by_id = {r["cluster_id"]: r for r in out["by_cluster"]}
    assert by_id["c1"]["mean_conversion"] == pytest.approx(0.20)
    assert by_id["c1"]["min_conversion"] == pytest.approx(0.10)
    assert by_id["c1"]["max_conversion"] == pytest.approx(0.30)
    assert by_id["c1"]["observation_count"] == 3
    # c2 was seen twice with values [0.20, 0.30].
    assert by_id["c2"]["mean_conversion"] == pytest.approx(0.25)
    assert by_id["c2"]["observation_count"] == 2


def test_aggregate_std_zero_for_single_observation() -> None:
    """Sample std-dev is undefined for n=1 — pin to 0.0 rather than
    dividing by zero."""
    from app.simulation.clusters_aggregate import aggregate_clusters

    out = aggregate_clusters([
        {"cluster_breakdown": {"c1": 0.10}},
    ])
    assert out["by_cluster"][0]["std_conversion"] == pytest.approx(0.0)


def test_aggregate_std_population_for_multiple_observations() -> None:
    """Sample std-dev uses 1/(n-1). For [0.10, 0.20] the mean is
    0.15 and the variance is 0.005 → std ≈ 0.0707. We round to
    6 decimal places in the helper, so compare at that precision."""
    from app.simulation.clusters_aggregate import aggregate_clusters

    out = aggregate_clusters([
        {"cluster_breakdown": {"c1": 0.10}},
        {"cluster_breakdown": {"c1": 0.20}},
    ])
    expected = round((0.005) ** 0.5, 6)
    assert out["by_cluster"][0]["std_conversion"] == pytest.approx(
        expected, abs=1e-6
    )


def test_aggregate_total_conversion_sums() -> None:
    from app.simulation.clusters_aggregate import aggregate_clusters

    out = aggregate_clusters([
        {"cluster_breakdown": {"c1": 0.10, "c2": 0.05}},
        {"cluster_breakdown": {"c1": 0.20}},
    ])
    by_id = {r["cluster_id"]: r for r in out["by_cluster"]}
    assert by_id["c1"]["total_conversion"] == pytest.approx(0.30)
    assert by_id["c2"]["total_conversion"] == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# aggregate_clusters — sorting
# ---------------------------------------------------------------------------


def test_aggregate_by_cluster_sorted_by_mean_asc() -> None:
    """Worst-performing cluster first — the dashboard reads the
    rollup as 'clusters we should worry about'."""
    from app.simulation.clusters_aggregate import aggregate_clusters

    out = aggregate_clusters([
        {"cluster_breakdown": {"good": 0.50, "bad": 0.05, "mid": 0.20}},
    ])
    ids = [r["cluster_id"] for r in out["by_cluster"]]
    assert ids == ["bad", "mid", "good"]


def test_aggregate_by_cluster_observation_count_breaks_ties() -> None:
    """On equal mean_conversion, the cluster seen more often wins
    — its mean is more reliable."""
    from app.simulation.clusters_aggregate import aggregate_clusters

    out = aggregate_clusters([
        {"cluster_breakdown": {"a": 0.10, "b": 0.10}},
        {"cluster_breakdown": {"a": 0.10, "b": 0.10}},
        {"cluster_breakdown": {"a": 0.10}},  # b seen once less
    ])
    ids = [r["cluster_id"] for r in out["by_cluster"]]
    # Both have mean 0.10; a has count=3, b has count=2 → a first.
    assert ids == ["a", "b"]


def test_aggregate_top_laggards_first_n() -> None:
    from app.simulation.clusters_aggregate import aggregate_clusters

    sims = [{"cluster_breakdown": {f"c{i}": float(i) / 100}}
            for i in range(1, 11)]  # c1=0.01, c10=0.10
    out = aggregate_clusters(sims, top_n=3)
    assert out["top_laggards"] == ["c1", "c2", "c3"]


def test_aggregate_top_performers_first_n_desc() -> None:
    from app.simulation.clusters_aggregate import aggregate_clusters

    sims = [{"cluster_breakdown": {f"c{i}": float(i) / 100}}
            for i in range(1, 11)]
    out = aggregate_clusters(sims, top_n=3)
    assert out["top_performers"] == ["c10", "c9", "c8"]


def test_aggregate_top_n_caps_lists() -> None:
    from app.simulation.clusters_aggregate import (
        DEFAULT_TOP_N,
        aggregate_clusters,
    )

    sims = [{"cluster_breakdown": {f"c{i}": float(i) / 100}}
            for i in range(1, 11)]
    out = aggregate_clusters(sims, top_n=2)
    assert len(out["top_laggards"]) == 2
    assert len(out["top_performers"]) == 2
    # Default top_n = 5.
    default_out = aggregate_clusters(sims)
    assert len(default_out["top_laggards"]) == min(DEFAULT_TOP_N, 10)


# ---------------------------------------------------------------------------
# cluster_names lookup
# ---------------------------------------------------------------------------


def test_aggregate_uses_supplied_cluster_names() -> None:
    from app.simulation.clusters_aggregate import aggregate_clusters

    out = aggregate_clusters(
        [{"cluster_breakdown": {"c1": 0.05}}],
        cluster_names={"c1": "Metro Power Pro"},
    )
    assert out["by_cluster"][0]["cluster_name"] == "Metro Power Pro"


def test_aggregate_falls_back_to_cluster_id_when_no_name() -> None:
    from app.simulation.clusters_aggregate import aggregate_clusters

    out = aggregate_clusters(
        [{"cluster_breakdown": {"c1": 0.05}}],
    )
    assert out["by_cluster"][0]["cluster_name"] == "c1"


def test_aggregate_coerces_non_string_cluster_names() -> None:
    from app.simulation.clusters_aggregate import aggregate_clusters

    out = aggregate_clusters(
        [{"cluster_breakdown": {"c1": 0.05}}],
        cluster_names={"c1": 42},  # non-string → coerce
    )
    assert out["by_cluster"][0]["cluster_name"] == "42"


def test_aggregate_drops_invalid_cluster_name_entries() -> None:
    """Defensive — empty key, non-string keys, un-coercible values
    must not poison the lookup."""
    from app.simulation.clusters_aggregate import aggregate_clusters

    class _Exploding:
        def __str__(self) -> str:
            raise RuntimeError("nope")

    out = aggregate_clusters(
        [{"cluster_breakdown": {"c1": 0.05}}],
        cluster_names={"": "empty", 123: "non-str-key", "c1": _Exploding()},
    )
    # None of the bogus entries survive; c1 falls back to its id.
    assert out["by_cluster"][0]["cluster_name"] == "c1"


def test_aggregate_skips_empty_cluster_names_lookup() -> None:
    """None / non-dict inputs are no-ops."""
    from app.simulation.clusters_aggregate import aggregate_clusters

    out = aggregate_clusters(
        [{"cluster_breakdown": {"c1": 0.05}}],
        cluster_names=None,
    )
    assert out["by_cluster"][0]["cluster_name"] == "c1"


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    """Pin the module's ``__all__`` so a future rename surfaces as
    an import error rather than a silent attribute miss in the
    route."""
    from app.simulation import clusters_aggregate

    assert set(clusters_aggregate.__all__) == {
        "DEFAULT_TOP_N",
        "MAX_TOP_N",
        "MIN_CONVERSION",
        "MAX_CONVERSION",
        "LOW_VARIANCE_MAX_CV",
        "MODERATE_VARIANCE_MAX_CV",
        "LABEL_HIGH_VARIANCE",
        "LABEL_MODERATE_VARIANCE",
        "LABEL_LOW_VARIANCE",
        "VALID_STABILITY_LABELS",
        "UNDER_OBSERVED_RATIO",
        "DROPOFF_ZONE_MAX_MEAN",
        "normalise_top_n",
        "aggregate_clusters",
    }


# ---------------------------------------------------------------------------
# stability / coverage / needs_attention
# ---------------------------------------------------------------------------


def test_aggregate_stability_low_variance_when_cv_is_small() -> None:
    """CV < 0.15 → LOW_VARIANCE."""
    from app.simulation.clusters_aggregate import (
        LABEL_LOW_VARIANCE,
        aggregate_clusters,
    )

    # mean=0.20, std=0.02 → CV=0.10.
    out = aggregate_clusters([
        {"cluster_breakdown": {"c1": 0.20}},
        {"cluster_breakdown": {"c1": 0.20}},
    ])
    assert out["by_cluster"][0]["stability"] == LABEL_LOW_VARIANCE


def test_aggregate_stability_moderate_variance_for_mid_cv() -> None:
    """0.15 ≤ CV < 0.50 → MODERATE_VARIANCE."""
    from app.simulation.clusters_aggregate import (
        LABEL_LOW_VARIANCE,
        LABEL_MODERATE_VARIANCE,
        aggregate_clusters,
    )

    # mean=0.20, std=0.06 → CV=0.30.
    out = aggregate_clusters([
        {"cluster_breakdown": {"c1": 0.20}},
        {"cluster_breakdown": {"c1": 0.20}},
    ])
    # Force a non-zero std by feeding two different values:
    # [0.14, 0.20] → mean=0.17, std=0.042 → CV=0.247.
    out2 = aggregate_clusters([
        {"cluster_breakdown": {"c1": 0.14}},
        {"cluster_breakdown": {"c1": 0.20}},
    ])
    assert out["by_cluster"][0]["stability"] == LABEL_LOW_VARIANCE
    assert out2["by_cluster"][0]["stability"] == LABEL_MODERATE_VARIANCE


def test_aggregate_stability_high_variance_for_large_cv() -> None:
    """CV ≥ 0.50 → HIGH_VARIANCE."""
    from app.simulation.clusters_aggregate import (
        LABEL_HIGH_VARIANCE,
        aggregate_clusters,
    )

    # [0.05, 0.20] → mean=0.125, std=0.106 → CV=0.848.
    out = aggregate_clusters([
        {"cluster_breakdown": {"c1": 0.05}},
        {"cluster_breakdown": {"c1": 0.20}},
    ])
    assert out["by_cluster"][0]["stability"] == LABEL_HIGH_VARIANCE


def test_aggregate_stability_zero_mean_is_high_variance() -> None:
    """Zero-mean clusters have undefined CV — surface them as
    HIGH_VARIANCE so the dashboard investigates instead of silently
    marking them as 'low variance'."""
    from app.simulation.clusters_aggregate import (
        LABEL_HIGH_VARIANCE,
        aggregate_clusters,
    )

    out = aggregate_clusters([
        {"cluster_breakdown": {"c1": 0.0}},
        {"cluster_breakdown": {"c1": 0.0}},
    ])
    assert out["by_cluster"][0]["stability"] == LABEL_HIGH_VARIANCE


def test_aggregate_observation_ratio_fraction() -> None:
    from app.simulation.clusters_aggregate import aggregate_clusters

    # 3 sims, cluster "c1" appears in 2 → ratio = 0.6667.
    out = aggregate_clusters([
        {"cluster_breakdown": {"c1": 0.10}},
        {"cluster_breakdown": {"c1": 0.20}},
        {},
    ])
    assert out["by_cluster"][0]["observation_count"] == 2
    assert out["by_cluster"][0]["observation_ratio"] == pytest.approx(
        2 / 3, abs=1e-6
    )


def test_aggregate_under_observed_when_ratio_below_threshold() -> None:
    """observation_count / simulation_count < 30 % → under_observed
    is True."""
    from app.simulation.clusters_aggregate import aggregate_clusters

    # 10 sims, "c1" appears in 2 → 20 % → under-observed.
    sims = [{"cluster_breakdown": {}} for _ in range(8)]
    sims.insert(0, {"cluster_breakdown": {"c1": 0.10}})
    sims.insert(1, {"cluster_breakdown": {"c1": 0.20}})
    out = aggregate_clusters(sims)
    assert out["by_cluster"][0]["under_observed"] is True


def test_aggregate_not_under_observed_at_or_above_threshold() -> None:
    """30 % exactly is NOT under-observed (inclusive lower bound)."""
    from app.simulation.clusters_aggregate import (
        UNDER_OBSERVED_RATIO,
        aggregate_clusters,
    )

    n_target = 10
    n_seen = int(n_target * UNDER_OBSERVED_RATIO)  # exactly 30 %
    sims_seen = [{"cluster_breakdown": {"c1": 0.10}} for _ in range(n_seen)]
    sims_empty = [{"cluster_breakdown": {}} for _ in range(
        n_target - n_seen
    )]
    out = aggregate_clusters(sims_seen + sims_empty)
    assert out["by_cluster"][0]["under_observed"] is False


def test_aggregate_needs_attention_is_under_observed_or_high_variance() -> None:
    """Combined flag: needs_attention = under_observed OR
    stability == HIGH_VARIANCE."""
    from app.simulation.clusters_aggregate import aggregate_clusters

    # 10 sims, "c1" appears in 1 → under-observed → needs_attention.
    sims = [{"cluster_breakdown": {}} for _ in range(9)]
    sims.insert(0, {"cluster_breakdown": {"c1": 0.10}})
    out1 = aggregate_clusters(sims)
    assert out1["by_cluster"][0]["needs_attention"] is True

    # Cluster seen everywhere but with high variance → needs_attention.
    out2 = aggregate_clusters([
        {"cluster_breakdown": {"c2": 0.05}},
        {"cluster_breakdown": {"c2": 0.20}},
        {"cluster_breakdown": {"c2": 0.05}},
        {"cluster_breakdown": {"c2": 0.20}},
    ])
    assert out2["by_cluster"][0]["needs_attention"] is True


def test_aggregate_not_needs_attention_when_stable_and_well_observed() -> None:
    """Low-variance, well-observed cluster → needs_attention = False."""
    from app.simulation.clusters_aggregate import aggregate_clusters

    out = aggregate_clusters([
        {"cluster_breakdown": {"c1": 0.10}},
        {"cluster_breakdown": {"c1": 0.10}},
        {"cluster_breakdown": {"c1": 0.10}},
    ])
    assert out["by_cluster"][0]["under_observed"] is False
    assert out["by_cluster"][0]["needs_attention"] is False


def test_aggregate_under_observed_count_top_level() -> None:
    """Top-level count of how many clusters are under-observed.

    10 sims total: c1 appears in 3 (3/10 = 30 % — exactly the
    threshold, NOT under-observed) and c2 appears in 1 (1/10 = 10 %,
    clearly under-observed). Expect under_observed_count == 1 and
    needs_attention_count == 1.
    """
    from app.simulation.clusters_aggregate import aggregate_clusters

    sims: list[dict] = [{"cluster_breakdown": {}} for _ in range(6)]
    # c1 seen 3× → ratio 3/10 = 30 % (boundary, not under).
    sims.append({"cluster_breakdown": {"c1": 0.10}})
    sims.append({"cluster_breakdown": {"c1": 0.10}})
    sims.append({"cluster_breakdown": {"c1": 0.10}})
    # c2 seen 1× → ratio 1/10 = 10 % (under).
    sims.append({"cluster_breakdown": {"c2": 0.30}})
    assert len(sims) == 10
    out = aggregate_clusters(sims)
    assert out["under_observed_count"] == 1
    # c2 is under-observed → 1 needs_attention. c1's stability is
    # LOW_VARIANCE (no spread with identical values) → no extra.
    assert out["needs_attention_count"] == 1


def test_aggregate_needs_attention_count_handles_high_variance() -> None:
    """A high-variance cluster also counts toward needs_attention."""
    from app.simulation.clusters_aggregate import aggregate_clusters

    # c1 well-observed (5/5) but with high variance → needs_attention.
    out = aggregate_clusters([
        {"cluster_breakdown": {"c1": 0.05}},
        {"cluster_breakdown": {"c1": 0.20}},
        {"cluster_breakdown": {"c1": 0.05}},
        {"cluster_breakdown": {"c1": 0.20}},
        {"cluster_breakdown": {"c1": 0.05}},
    ])
    assert out["by_cluster"][0]["under_observed"] is False
    assert out["by_cluster"][0]["needs_attention"] is True
    assert out["needs_attention_count"] == 1


def test_aggregate_needs_attention_count_zero_for_empty_input() -> None:
    from app.simulation.clusters_aggregate import aggregate_clusters

    assert aggregate_clusters([])["needs_attention_count"] == 0
    assert aggregate_clusters([])["under_observed_count"] == 0


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_clusters_aggregate_out_default_shape() -> None:
    from app.schemas.simulation import ClustersAggregateOut

    out = ClustersAggregateOut()
    assert out.by_cluster == []
    assert out.top_laggards == []
    assert out.top_performers == []
    assert out.simulation_count == 0
    assert out.clusters_seen == 0
    assert out.under_observed_count == 0
    assert out.needs_attention_count == 0


def test_clusters_aggregate_out_round_trips_aggregate_payload() -> None:
    """The route layer must be able to wrap ``aggregate_clusters(...)``
    output directly into the Pydantic schema without coercion
    errors. Default ``top_n=5`` so both lists carry both clusters."""
    from app.schemas.simulation import ClustersAggregateOut
    from app.simulation.clusters_aggregate import aggregate_clusters

    payload = aggregate_clusters([
        {"cluster_breakdown": {"c1": 0.05, "c2": 0.20}},
    ])
    out = ClustersAggregateOut(**payload)
    assert out.simulation_count == 1
    assert out.clusters_seen == 2
    # Worst first.
    assert out.by_cluster[0]["cluster_id"] == "c1"
    assert out.top_laggards == ["c1", "c2"]
    assert out.top_performers == ["c2", "c1"]


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_aggregate_clusters_route_registered() -> None:
    """GET /simulations/aggregate/clusters must appear in the router."""
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
    assert "/simulations/aggregate/clusters" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert "GET" in methods_by_path["/simulations/aggregate/clusters"]


def test_aggregate_clusters_route_query_params() -> None:
    """Pin the query-param surface so the UI contract is documented."""
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
            r.path == "/simulations/aggregate/clusters"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "ids" in query_param_names
            assert "top_n" in query_param_names
            return
    raise AssertionError(
        "GET /simulations/aggregate/clusters route not found"
    )
