"""
Tests for the per-cluster calibration evidence digest.

The builder is pure-Python, so the digest's status tiers, totals,
malformed-input guards and deterministic ordering are verifiable with plain
dicts. The route itself is covered with a fake session plus the admin gate,
mirroring the existing calibration route-test patterns.
"""
from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    """Pin the module's ``__all__`` so a future rename surfaces as an
    import error rather than a silent attribute miss in the route."""
    from app.simulation import cluster_calibration_evidence

    assert set(cluster_calibration_evidence.__all__) == {
        "CALIBRATED",
        "UNDER_EVIDENCED",
        "NO_EVIDENCE",
        "VALID_STATUSES",
        "build_cluster_calibration_digest",
    }


def test_status_allowlist_pinned() -> None:
    from app.simulation.cluster_calibration_evidence import VALID_STATUSES

    assert VALID_STATUSES == {
        "CALIBRATED",
        "UNDER_EVIDENCED",
        "NO_EVIDENCE",
    }


# ---------------------------------------------------------------------------
# Pure builder helpers
# ---------------------------------------------------------------------------


def _def(cluster_id: str, name: str = "", weight: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(
        cluster_id=cluster_id,
        name=name or cluster_id,
        population_weight=weight,
    )


def _ev(
    cluster_id: str,
    validated: int = 0,
    weight: float = 0.0,
    consumed: int | None = None,
    pending: int | None = None,
    last_id: int | None = None,
) -> dict:
    return {
        "cluster_id": cluster_id,
        "validated_outcomes": validated,
        "learning_weight": weight,
        "consumed_outcomes": consumed,
        "pending_outcomes": pending,
        "last_processed_outcome_id": last_id,
    }


def test_empty_inputs_return_canonical_shape() -> None:
    from app.simulation.cluster_calibration_evidence import (
        build_cluster_calibration_digest,
    )

    out = build_cluster_calibration_digest(
        evidence_rows=[],
        trait_rows=[],
        clusters=[],
        generated_at="2026-01-01T00:00:00Z",
    )
    assert out["generated_at"] == "2026-01-01T00:00:00Z"
    assert out["overall"] == {
        "total_clusters": 0,
        "clusters_with_evidence": 0,
        "calibrated_clusters": 0,
        "under_evidenced_clusters": 0,
        "zero_evidence_clusters": 0,
        "total_validated_outcomes": 0,
        "total_consumed_outcomes": 0,
        "total_pending_outcomes": 0,
        "total_trait_updates": 0,
    }
    assert out["clusters"] == []


def test_real_registry_always_covers_52_clusters() -> None:
    from app.simulation.cluster_calibration_evidence import (
        NO_EVIDENCE,
        build_cluster_calibration_digest,
    )
    from app.simulation.clusters.registry import ClusterRegistry

    out = build_cluster_calibration_digest(clusters=ClusterRegistry().all_clusters())
    assert out["overall"]["total_clusters"] == 52
    assert out["overall"]["zero_evidence_clusters"] == 52
    assert len(out["clusters"]) == 52
    assert all(row["status"] == NO_EVIDENCE for row in out["clusters"])
    # Deterministic ordering: zero-evidence clusters are alphabetical.
    ids = [row["cluster_id"] for row in out["clusters"]]
    assert ids == sorted(ids)


def test_digest_validates_against_schema() -> None:
    """The route's response_model must accept the builder's payload."""
    from app.schemas.cluster_calibration_evidence import ClusterCalibrationDigestOut
    from app.simulation.cluster_calibration_evidence import (
        build_cluster_calibration_digest,
    )

    out = build_cluster_calibration_digest(
        evidence_rows=[_ev("a", validated=6, weight=5.5, consumed=4, pending=2)],
        trait_rows=[
            {"cluster_id": "a", "trait_name": "price_sensitivity", "calibration_count": 1}
        ],
        clusters=[_def("a", "Cluster A", 0.10)],
        generated_at="2026-01-01T00:00:00Z",
    )
    parsed = ClusterCalibrationDigestOut.model_validate(out)
    assert parsed.overall.total_clusters == 1
    assert parsed.clusters[0].status == "CALIBRATED"


def test_status_tiers_and_totals() -> None:
    from app.simulation.cluster_calibration_evidence import (
        CALIBRATED,
        NO_EVIDENCE,
        UNDER_EVIDENCED,
        build_cluster_calibration_digest,
    )

    out = build_cluster_calibration_digest(
        evidence_rows=[
            _ev("a", validated=8, weight=6.2, consumed=5, pending=3, last_id=140),
            _ev("b", validated=3, weight=2.1, consumed=0, pending=3, last_id=0),
        ],
        trait_rows=[
            {"cluster_id": "a", "trait_name": "price_sensitivity", "calibration_count": 2},
            {"cluster_id": "a", "trait_name": "digital_literacy", "calibration_count": 1},
            # Duplicate trait rows must de-duplicate the name but keep counts.
            {"cluster_id": "a", "trait_name": "price_sensitivity", "calibration_count": 1},
            # Zero / malformed counts never contribute.
            {"cluster_id": "b", "trait_name": "trust", "calibration_count": 0},
        ],
        clusters=[_def("a", "Cluster A", 0.10), _def("b", "Cluster B", 0.05), _def("c", "Cluster C", 0.02)],
        generated_at="2026-01-01T00:00:00Z",
    )

    by_id = {row["cluster_id"]: row for row in out["clusters"]}
    assert [row["cluster_id"] for row in out["clusters"]] == ["a", "b", "c"]

    a = by_id["a"]
    assert a["status"] == CALIBRATED
    assert a["validated_outcomes"] == 8
    assert a["learning_weight"] == pytest.approx(6.2)
    assert a["consumed_outcomes"] == 5
    assert a["pending_outcomes"] == 3
    assert a["last_processed_outcome_id"] == 140
    assert a["calibration_count"] == 4
    assert a["calibrated_traits"] == ["digital_literacy", "price_sensitivity"]

    b = by_id["b"]
    assert b["status"] == UNDER_EVIDENCED
    assert b["consumed_outcomes"] == 0
    assert b["pending_outcomes"] == 3
    assert b["calibration_count"] == 0

    c = by_id["c"]
    assert c["status"] == NO_EVIDENCE
    assert c["validated_outcomes"] == 0

    assert out["overall"]["total_clusters"] == 3
    assert out["overall"]["clusters_with_evidence"] == 2
    assert out["overall"]["calibrated_clusters"] == 1
    assert out["overall"]["under_evidenced_clusters"] == 1
    assert out["overall"]["zero_evidence_clusters"] == 1
    assert out["overall"]["total_validated_outcomes"] == 11
    assert out["overall"]["total_consumed_outcomes"] == 5
    assert out["overall"]["total_pending_outcomes"] == 6
    assert out["overall"]["total_trait_updates"] == 4


def test_recomputes_missing_consumed_or_pending() -> None:
    from app.simulation.cluster_calibration_evidence import (
        build_cluster_calibration_digest,
    )

    out = build_cluster_calibration_digest(
        evidence_rows=[
            _ev("x", validated=5, weight=1.0, consumed=2),  # pending missing
            _ev("y", validated=4, weight=1.0, pending=1),  # consumed missing
            _ev("z", validated=6, weight=1.0),  # neither missing
        ],
        clusters=[_def("x"), _def("y"), _def("z")],
    )
    by_id = {row["cluster_id"]: row for row in out["clusters"]}
    assert by_id["x"]["pending_outcomes"] == 3
    assert by_id["y"]["consumed_outcomes"] == 3
    assert by_id["z"]["consumed_outcomes"] == 0
    assert by_id["z"]["pending_outcomes"] == 6


def test_skips_malformed_rows() -> None:
    from app.simulation.cluster_calibration_evidence import (
        NO_EVIDENCE,
        build_cluster_calibration_digest,
    )

    out = build_cluster_calibration_digest(
        evidence_rows=[
            _ev("good", validated=4, weight=2.0, consumed=1, pending=3),
            {"cluster_id": None, "validated_outcomes": 9},
            {"cluster_id": 123, "validated_outcomes": 9},
            _ev("bad_count", validated="abc", weight="not-a-number"),
            _ev("negative", validated=-3, weight=-1.0),
            _ev("bool_trap", validated=True, weight=True),
            _ev("nan", validated=5, weight=float("nan")),
            "not-a-mapping",
        ],
        trait_rows=[
            {"cluster_id": "good", "trait_name": "trust", "calibration_count": 1},
            {"cluster_id": "good", "trait_name": "", "calibration_count": 5},
            {"cluster_id": "good", "trait_name": None, "calibration_count": 5},
            {"cluster_id": "good", "trait_name": "risk_aversion", "calibration_count": "bad"},
            {"cluster_id": "good", "trait_name": "patience_score", "calibration_count": -2},
            {"cluster_id": "good", "trait_name": "motivation", "calibration_count": True},
        ],
        clusters=[_def("good"), _def("bad_count"), _def("negative"), _def("bool_trap"), _def("nan")],
    )
    by_id = {row["cluster_id"]: row for row in out["clusters"]}
    assert by_id["good"]["validated_outcomes"] == 4
    assert by_id["good"]["calibrated_traits"] == ["trust"]
    for cid in ("bad_count", "negative", "bool_trap", "nan"):
        row = by_id[cid]
        assert row["validated_outcomes"] == 0
        assert row["learning_weight"] == 0.0
        assert row["status"] == NO_EVIDENCE


def test_unknown_clusters_are_surfaced() -> None:
    """Evidence rows outside the registry are not silently dropped."""
    from app.simulation.cluster_calibration_evidence import (
        UNDER_EVIDENCED,
        build_cluster_calibration_digest,
    )

    out = build_cluster_calibration_digest(
        evidence_rows=[_ev("ghost_cluster", validated=2, weight=1.5)],
        clusters=[_def("known", "Known", 0.10)],
    )
    by_id = {row["cluster_id"]: row for row in out["clusters"]}
    ghost = by_id["ghost_cluster"]
    assert ghost["cluster_name"] == ""
    assert ghost["population_weight"] == 0.0
    assert ghost["status"] == UNDER_EVIDENCED
    # Registry count stays canonical while totals reflect all surfaced rows.
    assert out["overall"]["total_clusters"] == 1
    assert out["overall"]["clusters_with_evidence"] == 1


def test_sorts_by_evidence_weight_then_cluster_id() -> None:
    from app.simulation.cluster_calibration_evidence import (
        build_cluster_calibration_digest,
    )

    out = build_cluster_calibration_digest(
        evidence_rows=[
            _ev("b", validated=4, weight=3.0),
            _ev("a", validated=9, weight=7.0),
            _ev("c", validated=1, weight=1.0),
        ],
        clusters=[_def("a"), _def("b"), _def("c")],
    )
    assert [row["cluster_id"] for row in out["clusters"]] == ["a", "b", "c"]


def test_status_uses_unrounded_learning_weight() -> None:
    """Display rounding must not flip the engine's calibration gate."""
    from app.simulation.cluster_calibration_evidence import (
        CALIBRATED,
        UNDER_EVIDENCED,
        build_cluster_calibration_digest,
    )

    below = build_cluster_calibration_digest(
        evidence_rows=[_ev("below", validated=6, weight=4.99996)],
        clusters=[_def("below")],
    )["clusters"][0]
    above = build_cluster_calibration_digest(
        evidence_rows=[_ev("above", validated=6, weight=5.00004)],
        clusters=[_def("above")],
    )["clusters"][0]

    # Both display values round to the gate at 4 decimals, but only the
    # raw sum above 5.0 may claim CALIBRATED.
    assert below["learning_weight"] == 5.0
    assert below["status"] == UNDER_EVIDENCED
    assert above["learning_weight"] == 5.0
    assert above["status"] == CALIBRATED


def test_sort_uses_unrounded_learning_weight() -> None:
    """Rows that display identically still rank by their true evidence sum."""
    from app.simulation.cluster_calibration_evidence import (
        build_cluster_calibration_digest,
    )

    out = build_cluster_calibration_digest(
        evidence_rows=[
            _ev("low", validated=6, weight=4.99996),
            _ev("high", validated=6, weight=5.00004),
        ],
        clusters=[_def("low"), _def("high")],
    )
    assert [row["cluster_id"] for row in out["clusters"]] == ["high", "low"]
    assert [row["learning_weight"] for row in out["clusters"]] == [5.0, 5.0]


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


class _FakeRow:
    def __init__(self, **mapping) -> None:
        self._mapping = mapping


class _FakeResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def fetchall(self) -> list:
        return self._value if isinstance(self._value, list) else []

    def scalar(self):
        return self._value


class _FakeSession:
    """Serves queued execute() responses and records every call."""

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    def execute(self, statement, params: dict | None = None):
        self.calls.append(str(statement))
        value = self._responses.pop(0) if self._responses else None
        return _FakeResult(value)


def test_route_registered() -> None:
    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1.calibration import router

    methods_by_path: dict[str, set[str]] = {}
    for route in router.routes:
        methods_by_path.setdefault(route.path, set()).update(route.methods or set())
    assert "GET" in methods_by_path.get("/calibration/cluster-evidence", set())


def test_route_requires_admin_before_any_query() -> None:
    from app.api.v1.calibration import get_cluster_calibration_evidence

    session = _FakeSession([])
    with patch(
        "app.api.v1.calibration._require_admin",
        side_effect=HTTPException(status_code=403, detail="Admin only"),
    ):
        with pytest.raises(HTTPException) as exc:
            get_cluster_calibration_evidence(
                db=session,
                current_user=SimpleNamespace(id=1),
            )
    assert exc.value.status_code == 403
    assert session.calls == [], "admin gate must run before any DB work"


def test_route_returns_full_registry_when_tables_missing() -> None:
    from app.api.v1.calibration import get_cluster_calibration_evidence

    session = _FakeSession([False])  # first table check fails
    out = get_cluster_calibration_evidence(
        db=session,
        current_user=SimpleNamespace(is_admin=True),
    )
    assert out["overall"]["total_clusters"] == 52
    assert out["overall"]["zero_evidence_clusters"] == 52
    assert len(out["clusters"]) == 52
    assert not any("COUNT(DISTINCT fo.id)" in call for call in session.calls)


def test_route_happy_path_composes_digest() -> None:
    from app.api.v1.calibration import get_cluster_calibration_evidence

    session = _FakeSession(
        [
            True,  # cluster_run_summaries exists
            True,  # founder_outcomes exists
            True,  # cluster_trait_calibration_state exists
            True,  # cluster_parameters exists
            [
                _FakeRow(
                    cluster_id="a",
                    validated_outcomes=8,
                    learning_weight=6.2,
                    consumed_outcomes=5,
                    pending_outcomes=3,
                    last_processed_outcome_id=140,
                )
            ],
            [
                _FakeRow(
                    cluster_id="a",
                    trait_name="price_sensitivity",
                    calibration_count=2,
                )
            ],
        ]
    )
    out = get_cluster_calibration_evidence(
        db=session,
        current_user=SimpleNamespace(is_admin=True),
    )
    assert out["overall"]["total_clusters"] == 52
    assert out["overall"]["clusters_with_evidence"] == 1
    assert out["overall"]["total_trait_updates"] == 2

    a = next(row for row in out["clusters"] if row["cluster_id"] == "a")
    assert a["status"] == "CALIBRATED"
    assert a["validated_outcomes"] == 8
    assert a["consumed_outcomes"] == 5
    assert a["pending_outcomes"] == 3
    assert a["calibrated_traits"] == ["price_sensitivity"]
    # The evidence query and trait query both ran against the session.
    assert any("COUNT(DISTINCT fo.id)" in call for call in session.calls)
    assert any("calibration_count > 0" in call for call in session.calls)
