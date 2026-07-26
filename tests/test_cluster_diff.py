"""
Tests for the cluster diff helper + schema + route
registration.

The diff logic is pure-Python so we can exercise it without
spinning up Postgres. The DB-touching route is smoke-tested
via the route-registration pattern (gated by scipy).
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
    from app.simulation import cluster_diff

    assert set(cluster_diff.__all__) == {
        "REQUIRED_TRAITS",
        "SIMILARITY_HIGH_THRESHOLD",
        "SIMILARITY_LOW_THRESHOLD",
        "LABEL_VERY_SIMILAR",
        "LABEL_SIMILAR",
        "LABEL_DIFFERENT",
        "LABEL_VERY_DIFFERENT",
        "VALID_SIMILARITY_LABELS",
        "build_cluster_diff",
    }


def test_similarity_label_allowlist_pinned() -> None:
    from app.simulation.cluster_diff import VALID_SIMILARITY_LABELS

    assert set(VALID_SIMILARITY_LABELS) == {
        "VERY_SIMILAR",
        "SIMILAR",
        "DIFFERENT",
        "VERY_DIFFERENT",
    }


def test_required_traits_pinned_to_eight() -> None:
    """The 8 trait keys must match ClusterDefinition.REQUIRED_TRAITS."""
    from app.simulation.clusters.definitions import REQUIRED_TRAITS
    from app.simulation.cluster_diff import REQUIRED_TRAITS

    assert set(REQUIRED_TRAITS) == set(REQUIRED_TRAITS)


# ---------------------------------------------------------------------------
# build_cluster_diff — profile echo
# ---------------------------------------------------------------------------


def test_diff_echoes_profile_metadata() -> None:
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff(
        "metro_power_professional",
        "senior_enterprise_decision_maker",
        cluster_a_name="Metro Power Pro",
        cluster_b_name="Senior Enterprise DM",
    )
    assert out["cluster_a_profile"]["cluster_id"] == (
        "metro_power_professional"
    )
    assert out["cluster_a_profile"]["cluster_name"] == "Metro Power Pro"
    assert out["cluster_b_profile"]["cluster_id"] == (
        "senior_enterprise_decision_maker"
    )
    assert out["cluster_b_profile"]["cluster_name"] == (
        "Senior Enterprise DM"
    )


def test_diff_profile_name_falls_back_to_id() -> None:
    """No name supplied → cluster_id is echoed."""
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff("c1", "c2")
    assert out["cluster_a_profile"]["cluster_name"] == "c1"
    assert out["cluster_b_profile"]["cluster_name"] == "c2"


# ---------------------------------------------------------------------------
# Per-trait diff
# ---------------------------------------------------------------------------


def test_diff_traits_diff_returns_eight_rows_in_canonical_order() -> None:
    from app.simulation.cluster_diff import REQUIRED_TRAITS, build_cluster_diff

    out = build_cluster_diff("a", "b")
    traits = out["traits_diff"]
    assert len(traits) == 8
    # Canonical order — pinned so the dashboard renders a
    # stable table.
    assert [t["trait"] for t in traits] == list(REQUIRED_TRAITS)


def test_diff_traits_diff_calculates_deltas() -> None:
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff(
        "a", "b",
        cluster_a_traits={
            "income_level": 0.80,
            "digital_literacy": 0.70,
        },
        cluster_b_traits={
            "income_level": 0.40,
            "digital_literacy": 0.30,
        },
    )
    rows = {r["trait"]: r for r in out["traits_diff"]}
    assert rows["income_level"]["delta"] == pytest.approx(0.40)
    assert rows["income_level"]["winner"] == "CLUSTER_A"
    assert rows["digital_literacy"]["delta"] == pytest.approx(0.40)
    assert rows["digital_literacy"]["winner"] == "CLUSTER_A"


def test_diff_traits_diff_winner_label_for_each_axis() -> None:
    """Each axis carries a winner label so the dashboard can
    highlight the leading side without recomputing."""
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff(
        "a", "b",
        cluster_a_traits={
            "income_level": 0.90,    # A wins
            "trust": 0.20,           # B wins
            "patience_score": 0.50,  # TIE
        },
        cluster_b_traits={
            "income_level": 0.10,
            "trust": 0.80,
            "patience_score": 0.50,
        },
    )
    rows = {r["trait"]: r for r in out["traits_diff"]}
    assert rows["income_level"]["winner"] == "CLUSTER_A"
    assert rows["trust"]["winner"] == "CLUSTER_B"
    assert rows["patience_score"]["winner"] == "TIE"


def test_diff_traits_diff_handles_missing_trait_gracefully() -> None:
    """A trait missing on one side is echoed as None — no
    crash. Winner defaults to TIE when both sides are missing
    (no data to compare)."""
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff(
        "a", "b",
        cluster_a_traits={"income_level": 0.70},
        cluster_b_traits={"income_level": 0.30},
    )
    rows = {r["trait"]: r for r in out["traits_diff"]}
    assert rows["income_level"]["cluster_a"] == pytest.approx(0.70)
    assert rows["income_level"]["cluster_b"] == pytest.approx(0.30)
    # digital_literacy missing on BOTH sides → winner TIE.
    assert rows["digital_literacy"]["cluster_a"] is None
    assert rows["digital_literacy"]["cluster_b"] is None
    assert rows["digital_literacy"]["delta"] is None
    assert rows["digital_literacy"]["winner"] == "TIE"


def test_diff_traits_diff_winner_is_missing_side_when_only_one_present() -> None:
    """If the trait is present on A but missing on B → CLUSTER_A
    wins (B has no value to compare)."""
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff(
        "a", "b",
        cluster_a_traits={"trust": 0.50},
        cluster_b_traits={},  # no traits at all
    )
    rows = {r["trait"]: r for r in out["traits_diff"]}
    assert rows["trust"]["winner"] == "CLUSTER_A"


# ---------------------------------------------------------------------------
# Aggregate diff
# ---------------------------------------------------------------------------


def test_diff_aggregate_diff_rows_for_each_metric() -> None:
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff(
        "a", "b",
        cluster_a_aggregate={
            "mean_conversion": 0.20,
            "min_conversion": 0.10,
            "max_conversion": 0.30,
            "std_conversion": 0.05,
            "observation_count": 10,
            "is_outlier_count": 1,
        },
        cluster_b_aggregate={
            "mean_conversion": 0.10,
            "min_conversion": 0.05,
            "max_conversion": 0.15,
            "std_conversion": 0.03,
            "observation_count": 8,
            "is_outlier_count": 0,
        },
    )
    rows = {r["metric"]: r for r in out["aggregate_diff"]}
    assert rows["mean_conversion"]["delta"] == pytest.approx(0.10)
    assert rows["mean_conversion"]["winner"] == "CLUSTER_A"
    assert rows["observation_count"]["delta"] == 2
    assert rows["observation_count"]["winner"] == "CLUSTER_A"
    assert rows["is_outlier_count"]["winner"] == "CLUSTER_A"


def test_diff_aggregate_diff_handles_missing_metric() -> None:
    """A missing metric on one side renders None."""
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff(
        "a", "b",
        cluster_a_aggregate={"mean_conversion": 0.10},
    )
    rows = {r["metric"]: r for r in out["aggregate_diff"]}
    assert rows["mean_conversion"]["cluster_b"] is None
    assert rows["mean_conversion"]["winner"] == "CLUSTER_A"


# ---------------------------------------------------------------------------
# Similarity score
# ---------------------------------------------------------------------------


def test_diff_similarity_score_is_one_for_identical_traits() -> None:
    from app.simulation.cluster_diff import build_cluster_diff

    # All 8 traits identical → score = 1.0 − 0 = 1.0.
    traits = {t: 0.50 for t in [
        "income_level", "digital_literacy", "motivation",
        "trust", "price_sensitivity", "risk_aversion",
        "patience_score", "social_orientation",
    ]}
    out = build_cluster_diff(
        "a", "b",
        cluster_a_traits=traits,
        cluster_b_traits=dict(traits),
    )
    assert out["similarity_score"] == pytest.approx(1.0)
    assert out["similarity_label"] == "VERY_SIMILAR"


def test_diff_similarity_score_is_zero_for_maximally_different() -> None:
    """All 8 traits differ by 1.0 → score = 0.0."""
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff(
        "a", "b",
        cluster_a_traits={
            "income_level": 1.0, "digital_literacy": 1.0,
            "motivation": 1.0, "trust": 1.0,
            "price_sensitivity": 1.0, "risk_aversion": 1.0,
            "patience_score": 1.0, "social_orientation": 1.0,
        },
        cluster_b_traits={
            "income_level": 0.0, "digital_literacy": 0.0,
            "motivation": 0.0, "trust": 0.0,
            "price_sensitivity": 0.0, "risk_aversion": 0.0,
            "patience_score": 0.0, "social_orientation": 0.0,
        },
    )
    assert out["similarity_score"] == pytest.approx(0.0)
    assert out["similarity_label"] == "VERY_DIFFERENT"


def test_diff_similarity_label_thresholds() -> None:
    """Bucket boundaries for similarity label."""
    from app.simulation.cluster_diff import (
        LABEL_DIFFERENT,
        LABEL_SIMILAR,
        LABEL_VERY_SIMILAR,
        build_cluster_diff,
    )

    # Half-different on average (delta = 0.5) → score = 0.5 →
    # SIMILAR (boundary inclusive).
    traits_a = {t: 0.75 for t in [
        "income_level", "digital_literacy", "motivation",
        "trust", "price_sensitivity", "risk_aversion",
        "patience_score", "social_orientation",
    ]}
    traits_b = {t: 0.25 for t in traits_a}
    out = build_cluster_diff(
        "a", "b",
        cluster_a_traits=traits_a,
        cluster_b_traits=traits_b,
    )
    assert out["similarity_score"] == pytest.approx(0.5)
    assert out["similarity_label"] == LABEL_SIMILAR

    # Almost identical (delta = 0.1) → score = 0.9 → VERY_SIMILAR.
    traits_a2 = {t: 0.55 for t in traits_a}
    traits_b2 = {t: 0.45 for t in traits_a}
    out2 = build_cluster_diff(
        "a", "b",
        cluster_a_traits=traits_a2,
        cluster_b_traits=traits_b2,
    )
    assert out2["similarity_label"] == LABEL_VERY_SIMILAR

    # Very different (delta = 0.7) → score = 0.3 → DIFFERENT.
    traits_a3 = {t: 0.85 for t in traits_a}
    traits_b3 = {t: 0.15 for t in traits_a}
    out3 = build_cluster_diff(
        "a", "b",
        cluster_a_traits=traits_a3,
        cluster_b_traits=traits_b3,
    )
    assert out3["similarity_label"] == LABEL_DIFFERENT


def test_diff_similarity_score_skips_missing_traits() -> None:
    """Missing traits on both sides don't penalise the score."""
    from app.simulation.cluster_diff import build_cluster_diff

    # Only 2 traits supplied → mean(0) over 2 → score = 1.0.
    out = build_cluster_diff(
        "a", "b",
        cluster_a_traits={"income_level": 0.5, "trust": 0.5},
        cluster_b_traits={"income_level": 0.5, "trust": 0.5},
    )
    assert out["similarity_score"] == pytest.approx(1.0)


def test_diff_similarity_score_zero_for_all_missing_traits() -> None:
    """No traits on either side → no data → 0.0."""
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff("a", "b")
    assert out["similarity_score"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def test_diff_summary_includes_similarity_label_and_score() -> None:
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff(
        "metro_pro",
        "students",
        cluster_a_name="Metro Pro",
        cluster_b_name="Students",
        cluster_a_aggregate={"mean_conversion": 0.15},
        cluster_b_aggregate={"mean_conversion": 0.05},
    )
    assert "Metro Pro" in out["summary"]
    assert "Students" in out["summary"]
    assert "SIMILAR" in out["summary"] or "DIFFERENT" in out["summary"]
    assert "similarity" in out["summary"]


def test_diff_summary_includes_mean_conversion_delta() -> None:
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff(
        "a", "b",
        cluster_a_aggregate={"mean_conversion": 0.20},
        cluster_b_aggregate={"mean_conversion": 0.10},
    )
    assert "+0.1000" in out["summary"]


def test_diff_summary_handles_no_aggregate() -> None:
    from app.simulation.cluster_diff import build_cluster_diff

    # No aggregate dicts → no mean_conv delta in summary.
    out = build_cluster_diff("a", "b")
    assert "mean conv" not in out["summary"]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_cluster_diff_out_default_shape() -> None:
    from app.schemas.simulation import ClusterDiffOut

    out = ClusterDiffOut()
    assert out.cluster_a_profile == {}
    assert out.cluster_b_profile == {}
    assert out.traits_diff == []
    assert out.aggregate_diff == []
    assert out.similarity_score == 0.0
    assert out.similarity_label == "VERY_DIFFERENT"
    assert out.summary == ""
    assert out.top_differences == []
    assert out.product_overlap == []


def test_cluster_diff_out_round_trips_helper_payload() -> None:
    """The route layer must wrap ``build_cluster_diff(...)``
    output directly into the Pydantic schema without coercion
    errors."""
    from app.schemas.simulation import ClusterDiffOut
    from app.simulation.cluster_diff import build_cluster_diff

    payload = build_cluster_diff(
        "metro_pro",
        "students",
        cluster_a_name="Metro Pro",
        cluster_b_name="Students",
    )
    out = ClusterDiffOut(**payload)
    assert out.cluster_a_profile["cluster_id"] == "metro_pro"
    assert len(out.traits_diff) == 8
    assert out.summary != ""


# ---------------------------------------------------------------------------
# top_differences
# ---------------------------------------------------------------------------


def test_diff_top_differences_empty_when_no_data() -> None:
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff("a", "b")
    assert out["top_differences"] == []


def test_diff_top_differences_sorts_by_abs_delta_desc() -> None:
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff(
        "a", "b",
        cluster_a_traits={
            "income_level": 0.90,    # |delta| = 0.40
            "trust": 0.20,           # |delta| = 0.20
            "patience_score": 0.50,  # tie on 0.0
        },
        cluster_b_traits={
            "income_level": 0.50,
            "trust": 0.40,
            "patience_score": 0.50,
        },
        cluster_a_aggregate={"mean_conversion": 0.30},   # |delta| = 0.10
        cluster_b_aggregate={"mean_conversion": 0.20},
    )
    top = out["top_differences"]
    # 3 valid axes: income (0.40), trust (0.20), mean_conv (0.10).
    assert len(top) == 3
    axes = [row["axis"] for row in top]
    assert axes[0] == "income_level"
    assert axes[1] == "trust"
    assert axes[2] == "mean_conversion"


def test_diff_top_differences_capped_at_three() -> None:
    """Top 3 only — keeps the dashboard tile readable."""
    from app.simulation.cluster_diff import build_cluster_diff

    traits = {
        "income_level": 0.10, "digital_literacy": 0.10,
        "motivation": 0.10, "trust": 0.10,
        "price_sensitivity": 0.10, "risk_aversion": 0.10,
        "patience_score": 0.10, "social_orientation": 0.10,
    }
    out = build_cluster_diff(
        "a", "b",
        cluster_a_traits=traits,
        cluster_b_traits={k: 0.90 for k in traits},
    )
    assert len(out["top_differences"]) == 3


def test_diff_top_differences_carries_source_label() -> None:
    """Each row labels its source so the dashboard can render
    'trait' vs 'aggregate' rows differently."""
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff(
        "a", "b",
        cluster_a_traits={"income_level": 0.90},
        cluster_b_traits={"income_level": 0.10},
        cluster_a_aggregate={"mean_conversion": 0.20},
        cluster_b_aggregate={"mean_conversion": 0.05},
    )
    sources = {row["axis"]: row["source"] for row in out["top_differences"]}
    assert sources["income_level"] == "trait"
    assert sources["mean_conversion"] == "aggregate"


def test_diff_top_differences_skips_missing_deltas() -> None:
    """A trait / metric missing on one side (delta=None) is
    skipped, not counted as 0.0."""
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff(
        "a", "b",
        cluster_a_traits={"income_level": 0.90},  # delta = 0.40
        cluster_b_traits={"income_level": 0.50},
        # cluster_b_aggregate empty → mean_conversion delta = None.
        cluster_a_aggregate={"mean_conversion": 0.30},
    )
    top = out["top_differences"]
    axes = [row["axis"] for row in top]
    assert "mean_conversion" not in axes
    assert axes[0] == "income_level"


# ---------------------------------------------------------------------------
# product_overlap
# ---------------------------------------------------------------------------


def test_diff_product_overlap_empty_when_no_affinities() -> None:
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff("a", "b")
    assert out["product_overlap"] == []


def test_diff_product_overlap_intersects_case_insensitive() -> None:
    """Case-insensitive match: 'SaaS' on A and 'saas' on B
    overlap."""
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff(
        "a", "b",
        cluster_a_product_affinities=["SaaS", "Mobile App"],
        cluster_b_product_affinities=["saas", "Developer Tool"],
    )
    # Single overlap: saas. Original case from A's side wins.
    assert out["product_overlap"] == ["SaaS"]


def test_diff_product_overlap_returns_sorted_unique_list() -> None:
    """Sorted alphabetically, deduplicated."""
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff(
        "a", "b",
        cluster_a_product_affinities=["saas", "iot_hardware"],
        cluster_b_product_affinities=["iot_hardware", "saas"],
    )
    assert out["product_overlap"] == ["iot_hardware", "saas"]


def test_diff_product_overlap_empty_when_no_intersection() -> None:
    """Two disjoint sets → empty overlap."""
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff(
        "a", "b",
        cluster_a_product_affinities=["saas"],
        cluster_b_product_affinities=["iot_hardware"],
    )
    assert out["product_overlap"] == []


def test_diff_product_overlap_skips_empty_strings() -> None:
    """Defensive — empty strings in either list are skipped."""
    from app.simulation.cluster_diff import build_cluster_diff

    out = build_cluster_diff(
        "a", "b",
        cluster_a_product_affinities=["saas", ""],
        cluster_b_product_affinities=["saas"],
    )
    assert out["product_overlap"] == ["saas"]


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_cluster_diff_route_registered() -> None:
    """GET /simulations/cluster-diff must appear in the router."""
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
    assert "/simulations/cluster-diff" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert "GET" in methods_by_path["/simulations/cluster-diff"]


def test_cluster_diff_route_query_params() -> None:
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
            r.path == "/simulations/cluster-diff"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "cluster_a" in query_param_names
            assert "cluster_b" in query_param_names
            assert "ids" in query_param_names
            return
    raise AssertionError(
        "GET /simulations/cluster-diff route not found"
    )