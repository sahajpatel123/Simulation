"""
Tests for the cluster overlap matrix helper + schema +
route registration.

The matrix logic is pure-Python so we can exercise it
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
    from app.simulation import cluster_overlap_matrix

    assert set(cluster_overlap_matrix.__all__) == {
        "MAX_CLUSTERS",
        "WEAK_THRESHOLD",
        "STRONG_THRESHOLD",
        "LABEL_WEAK",
        "LABEL_MODERATE",
        "LABEL_STRONG",
        "VALID_RELATIONSHIP_LABELS",
        "build_cluster_overlap_matrix",
    }


def test_relationship_label_allowlist_pinned() -> None:
    from app.simulation.cluster_overlap_matrix import (
        VALID_RELATIONSHIP_LABELS,
    )

    assert set(VALID_RELATIONSHIP_LABELS) == {
        "WEAK",
        "MODERATE",
        "STRONG",
    }


# ---------------------------------------------------------------------------
# build_cluster_overlap_matrix — empty input
# ---------------------------------------------------------------------------


def test_matrix_empty_returns_empty_payload() -> None:
    from app.simulation.cluster_overlap_matrix import (
        build_cluster_overlap_matrix,
    )

    out = build_cluster_overlap_matrix([])
    assert out["cluster_ids"] == []
    assert out["cluster_names"] == []
    assert out["matrix"] == []
    assert out["pair_summaries"] == []
    assert out["strong_pair_count"] == 0


def test_matrix_rejects_empty_cluster_id() -> None:
    from app.simulation.cluster_overlap_matrix import (
        build_cluster_overlap_matrix,
    )

    with pytest.raises(ValueError, match="non-empty cluster_id"):
        build_cluster_overlap_matrix([
            {"cluster_id": "", "traits": {}},
        ])


def test_matrix_rejects_too_many_clusters() -> None:
    from app.simulation.cluster_overlap_matrix import (
        MAX_CLUSTERS,
        build_cluster_overlap_matrix,
    )

    with pytest.raises(ValueError, match=f"max is {MAX_CLUSTERS}"):
        build_cluster_overlap_matrix(
            [
                {"cluster_id": f"c{i}", "traits": {}}
                for i in range(MAX_CLUSTERS + 1)
            ]
        )


# ---------------------------------------------------------------------------
# Matrix structure
# ---------------------------------------------------------------------------


def _traits(values: dict) -> dict:
    """Build a full trait dict by filling missing keys
    with 0.0."""
    full = {t: 0.0 for t in [
        "income_level", "digital_literacy", "motivation",
        "trust", "price_sensitivity", "risk_aversion",
        "patience_score", "social_orientation",
    ]}
    full.update(values)
    return full


def test_matrix_diagonal_is_one() -> None:
    from app.simulation.cluster_overlap_matrix import (
        build_cluster_overlap_matrix,
    )

    out = build_cluster_overlap_matrix([
        {"cluster_id": "a", "traits": _traits({})},
        {"cluster_id": "b", "traits": _traits({})},
    ])
    matrix = out["matrix"]
    assert matrix[0][0] == pytest.approx(1.0)
    assert matrix[1][1] == pytest.approx(1.0)


def test_matrix_is_symmetric() -> None:
    from app.simulation.cluster_overlap_matrix import (
        build_cluster_overlap_matrix,
    )

    out = build_cluster_overlap_matrix([
        {
            "cluster_id": "a",
            "traits": _traits({"income_level": 0.5}),
        },
        {
            "cluster_id": "b",
            "traits": _traits({"income_level": 0.2}),
        },
    ])
    matrix = out["matrix"]
    assert matrix[0][1] == pytest.approx(matrix[1][0])


def test_matrix_identical_clusters_score_one() -> None:
    from app.simulation.cluster_overlap_matrix import (
        build_cluster_overlap_matrix,
    )

    out = build_cluster_overlap_matrix([
        {
            "cluster_id": "a",
            "traits": _traits({
                "income_level": 0.7, "trust": 0.4,
            }),
        },
        {
            "cluster_id": "b",
            "traits": _traits({
                "income_level": 0.7, "trust": 0.4,
            }),
        },
    ])
    # All 8 traits identical → score = 1.0.
    assert out["matrix"][0][1] == pytest.approx(1.0)


def test_matrix_maximally_different_clusters_score_zero() -> None:
    from app.simulation.cluster_overlap_matrix import (
        build_cluster_overlap_matrix,
    )

    traits_a = {t: 1.0 for t in [
        "income_level", "digital_literacy", "motivation",
        "trust", "price_sensitivity", "risk_aversion",
        "patience_score", "social_orientation",
    ]}
    traits_b = {t: 0.0 for t in traits_a}
    out = build_cluster_overlap_matrix([
        {"cluster_id": "a", "traits": traits_a},
        {"cluster_id": "b", "traits": traits_b},
    ])
    assert out["matrix"][0][1] == pytest.approx(0.0)


def test_matrix_cluster_names_echoed_in_input_order() -> None:
    from app.simulation.cluster_overlap_matrix import (
        build_cluster_overlap_matrix,
    )

    out = build_cluster_overlap_matrix([
        {"cluster_id": "a", "cluster_name": "Alpha", "traits": _traits({})},
        {"cluster_id": "b", "cluster_name": "Bravo", "traits": _traits({})},
        {"cluster_id": "c", "cluster_name": "Charlie", "traits": _traits({})},
    ])
    assert out["cluster_ids"] == ["a", "b", "c"]
    assert out["cluster_names"] == ["Alpha", "Bravo", "Charlie"]
    assert len(out["matrix"]) == 3
    for row in out["matrix"]:
        assert len(row) == 3


def test_matrix_cluster_name_falls_back_to_id() -> None:
    from app.simulation.cluster_overlap_matrix import (
        build_cluster_overlap_matrix,
    )

    out = build_cluster_overlap_matrix([
        {"cluster_id": "a", "traits": _traits({})},
        {"cluster_id": "b", "traits": _traits({})},
    ])
    assert out["cluster_names"] == ["a", "b"]


# ---------------------------------------------------------------------------
# pair_summaries
# ---------------------------------------------------------------------------


def test_matrix_pair_summaries_count_is_n_choose_2() -> None:
    from app.simulation.cluster_overlap_matrix import (
        build_cluster_overlap_matrix,
    )

    out = build_cluster_overlap_matrix([
        {"cluster_id": f"c{i}", "traits": _traits({})}
        for i in range(5)
    ])
    # 5 clusters → 5*4/2 = 10 pairs (no self-pairs).
    assert len(out["pair_summaries"]) == 10


def test_matrix_pair_summaries_excludes_self_pairs() -> None:
    from app.simulation.cluster_overlap_matrix import (
        build_cluster_overlap_matrix,
    )

    out = build_cluster_overlap_matrix([
        {"cluster_id": "a", "traits": _traits({})},
        {"cluster_id": "b", "traits": _traits({})},
    ])
    for pair in out["pair_summaries"]:
        assert pair["cluster_a"] != pair["cluster_b"]


def test_matrix_pair_summaries_sorted_by_score_desc() -> None:
    from app.simulation.cluster_overlap_matrix import (
        build_cluster_overlap_matrix,
    )

    out = build_cluster_overlap_matrix([
        {"cluster_id": "a", "traits": _traits({})},
        {"cluster_id": "b", "traits": _traits({})},
        {"cluster_id": "c", "traits": _traits({})},
    ])
    scores = [p["score"] for p in out["pair_summaries"]]
    assert scores == sorted(scores, reverse=True)


def test_matrix_pair_summary_label_thresholds() -> None:
    """WEAK < 0.50, MODERATE < 0.85, STRONG ≥ 0.85.

    Use clusters that differ on ALL 8 traits so the scores
    span the full label range rather than being dominated by
    the default zeros on every other trait.
    """
    from app.simulation.cluster_overlap_matrix import (
        LABEL_MODERATE,
        LABEL_STRONG,
        LABEL_WEAK,
        build_cluster_overlap_matrix,
    )

    all_traits = [
        "income_level", "digital_literacy", "motivation",
        "trust", "price_sensitivity", "risk_aversion",
        "patience_score", "social_orientation",
    ]
    traits_strong = {t: 0.50 for t in all_traits}
    traits_mid = {t: 0.25 for t in all_traits}
    traits_weak = {t: 0.0 for t in all_traits}
    # The (mid, weak) pair differs on all 8 traits by 0.25
    # → score 0.75 → MODERATE. The (strong, weak) pair differs
    # by 0.50 → score 0.50 → MODERATE boundary. We need a
    # third cluster that differs from mid by enough to push
    # the average delta above 0.50 (i.e. score < 0.50 →
    # WEAK).
    traits_extreme = {t: 0.95 for t in all_traits}
    out = build_cluster_overlap_matrix([
        {"cluster_id": "a", "traits": traits_strong},
        {"cluster_id": "b", "traits": traits_strong},
        {"cluster_id": "c", "traits": traits_mid},
        {"cluster_id": "d", "traits": traits_extreme},
    ])
    labels = {p["label"] for p in out["pair_summaries"]}
    assert LABEL_STRONG in labels
    assert LABEL_MODERATE in labels
    assert LABEL_WEAK in labels


# ---------------------------------------------------------------------------
# strong_pair_count
# ---------------------------------------------------------------------------


def test_matrix_strong_pair_count() -> None:
    """Counts only pairs ≥ STRONG_THRESHOLD."""
    from app.simulation.cluster_overlap_matrix import (
        build_cluster_overlap_matrix,
    )

    # (a,b) identical on all 8 traits → STRONG.
    # (c,d) identical on all 8 traits → STRONG.
    # Cross pairs differ on every trait → WEAK (not STRONG).
    all_traits = [
        "income_level", "digital_literacy", "motivation",
        "trust", "price_sensitivity", "risk_aversion",
        "patience_score", "social_orientation",
    ]
    traits_ab = {t: 0.50 for t in all_traits}
    traits_cd = {t: 0.20 for t in all_traits}
    out = build_cluster_overlap_matrix([
        {"cluster_id": "a", "traits": traits_ab},
        {"cluster_id": "b", "traits": traits_ab},
        {"cluster_id": "c", "traits": traits_cd},
        {"cluster_id": "d", "traits": traits_cd},
    ])
    assert out["strong_pair_count"] == 2


def test_matrix_strong_pair_count_zero_for_all_different() -> None:
    from app.simulation.cluster_overlap_matrix import (
        build_cluster_overlap_matrix,
    )

    # All 8 traits maximally different → score = 0.0 → WEAK.
    all_traits = [
        "income_level", "digital_literacy", "motivation",
        "trust", "price_sensitivity", "risk_aversion",
        "patience_score", "social_orientation",
    ]
    traits_a = {t: 1.0 for t in all_traits}
    traits_b = {t: 0.0 for t in all_traits}
    out = build_cluster_overlap_matrix([
        {"cluster_id": "a", "traits": traits_a},
        {"cluster_id": "b", "traits": traits_b},
    ])
    assert out["strong_pair_count"] == 0


# ---------------------------------------------------------------------------
# Missing-traits handling
# ---------------------------------------------------------------------------


def test_matrix_handles_partial_traits_gracefully() -> None:
    """When one cluster is missing a trait, that trait is
    skipped rather than treated as 0."""
    from app.simulation.cluster_overlap_matrix import (
        build_cluster_overlap_matrix,
    )

    out = build_cluster_overlap_matrix([
        {
            "cluster_id": "a",
            "traits": {
                "income_level": 0.50,
                "digital_literacy": 0.50,
            },
        },
        {
            "cluster_id": "b",
            "traits": {
                "income_level": 0.50,
                # digital_literacy missing.
            },
        },
    ])
    # Only income_level scored (delta=0) → similarity = 1.0.
    assert out["matrix"][0][1] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_cluster_overlap_matrix_out_default_shape() -> None:
    from app.schemas.simulation import ClusterOverlapMatrixOut

    out = ClusterOverlapMatrixOut()
    assert out.cluster_ids == []
    assert out.cluster_names == []
    assert out.matrix == []
    assert out.pair_summaries == []
    assert out.strong_pair_count == 0


def test_cluster_overlap_matrix_out_round_trips_helper_payload() -> None:
    """The route layer must wrap
    ``build_cluster_overlap_matrix(...)`` output directly into
    the Pydantic schema without coercion errors."""
    from app.schemas.simulation import ClusterOverlapMatrixOut
    from app.simulation.cluster_overlap_matrix import (
        build_cluster_overlap_matrix,
    )

    payload = build_cluster_overlap_matrix([
        {"cluster_id": "a", "cluster_name": "Alpha", "traits": _traits({})},
        {"cluster_id": "b", "cluster_name": "Bravo", "traits": _traits({})},
    ])
    out = ClusterOverlapMatrixOut(**payload)
    assert out.cluster_ids == ["a", "b"]
    assert len(out.matrix) == 2
    assert all(len(row) == 2 for row in out.matrix)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_cluster_overlap_matrix_route_registered() -> None:
    """GET /simulations/cluster-overlap-matrix must appear in
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
    assert "/simulations/cluster-overlap-matrix" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET"
        in methods_by_path["/simulations/cluster-overlap-matrix"]
    )


def test_cluster_overlap_matrix_route_query_params() -> None:
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
            r.path == "/simulations/cluster-overlap-matrix"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "cluster_ids" in query_param_names
            return
    raise AssertionError(
        "GET /simulations/cluster-overlap-matrix route not found"
    )