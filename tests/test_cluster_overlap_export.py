"""Tests for the cluster-overlap matrix export helper + route."""
from __future__ import annotations

import asyncio
import sys
import types

import pytest
from fastapi import HTTPException

from app.simulation.cluster_overlap_export import (
    cluster_overlap_to_csv,
    cluster_overlap_to_json,
)

# ---------------------------------------------------------------------------
# CSV helper
# ---------------------------------------------------------------------------


def _traits(values: dict) -> dict:
    full = {t: 0.0 for t in [
        "income_level", "digital_literacy", "motivation",
        "trust", "price_sensitivity", "risk_aversion",
        "patience_score", "social_orientation",
    ]}
    full.update(values)
    return full


def _matrix_payload() -> dict:
    return {
        "cluster_ids": ["a", "b", "c"],
        "cluster_names": ["Alpha", "Bravo", "Charlie"],
        "matrix": [
            [1.0, 0.85, 0.2],
            [0.85, 1.0, 0.3],
            [0.2, 0.3, 1.0],
        ],
        "pair_summaries": [
            {"cluster_a": "a", "cluster_b": "b", "score": 0.85, "label": "STRONG"},
            {"cluster_a": "b", "cluster_b": "c", "score": 0.3, "label": "WEAK"},
            {"cluster_a": "a", "cluster_b": "c", "score": 0.2, "label": "WEAK"},
        ],
        "consolidation_candidates": [
            {"cluster_a": "a", "cluster_b": "b", "score": 0.85, "label": "STRONG"},
        ],
        "cluster_metadata": {
            "a": {"cluster_name": "Alpha", "traits": _traits({"income_level": 0.5})},
            "b": {"cluster_name": "Bravo", "traits": _traits({"income_level": 0.5})},
            "c": {"cluster_name": "Charlie", "traits": _traits({"income_level": 0.1})},
        },
        "strong_pair_count": 1,
    }


def test_csv_renders_summary_matrix_pairs_and_candidates() -> None:
    csv_text = cluster_overlap_to_csv(
        _matrix_payload(),
        metadata={
            "generated_at": "now",
            "user_id": 42,
            "format_version": "1",
            "requested_ids": ["a", "b", "c"],
        },
    )

    assert "generated_at,now" in csv_text
    assert "user_id,42" in csv_text
    assert "section,Cluster Overlap Summary" in csv_text
    assert "cluster_count,3" in csv_text
    assert "pair_count,3" in csv_text
    assert "strong_pair_count,1" in csv_text
    assert "weak_pair_count,2" in csv_text
    assert "moderate_pair_count,0" in csv_text
    assert "section,Cluster Details" in csv_text
    assert "cluster_id,cluster_name,income_level,digital_literacy" in csv_text
    assert "a,Alpha,0.5,0.0" in csv_text
    assert "b,Bravo,0.5,0.0" in csv_text
    assert "c,Charlie,0.1,0.0" in csv_text
    assert "section,Similarity Matrix" in csv_text
    assert ",a,b,c" in csv_text
    assert "a,1.0,0.85,0.2" in csv_text
    assert "b,0.85,1.0,0.3" in csv_text
    assert "c,0.2,0.3,1.0" in csv_text
    assert "section,Pair Summaries" in csv_text
    assert "a,b,0.85,STRONG" in csv_text
    assert "b,c,0.3,WEAK" in csv_text
    assert "section,Consolidation Candidates" in csv_text
    assert "a,b,0.85,STRONG" in csv_text


def test_csv_empty_payload_still_renders_sections() -> None:
    csv_text = cluster_overlap_to_csv({})

    assert "section,Cluster Overlap Summary" in csv_text
    assert "cluster_count,0" in csv_text
    assert "pair_count,0" in csv_text
    assert "strong_pair_count,0" in csv_text
    assert "section,Cluster Details" in csv_text
    assert "cluster_id,cluster_name,income_level,digital_literacy" in csv_text
    assert "section,Similarity Matrix" in csv_text
    assert "section,Pair Summaries" in csv_text
    assert "section,Consolidation Candidates" in csv_text


def test_csv_summary_counts_derive_from_pair_summaries() -> None:
    """The summary counts come from the pair rows, so a stale or
    missing ``strong_pair_count`` payload field can't desync the
    export from the actual pair data."""
    payload = _matrix_payload()
    payload["strong_pair_count"] = 999  # deliberately stale
    csv_text = cluster_overlap_to_csv(payload)

    assert "strong_pair_count,1" in csv_text
    assert "weak_pair_count,2" in csv_text
    assert "moderate_pair_count,0" in csv_text


def test_csv_cluster_details_falls_back_to_cluster_names() -> None:
    """Without cluster_metadata, the export still labels rows using
    the payload's cluster_names list."""
    csv_text = cluster_overlap_to_csv({
        "cluster_ids": ["a", "b"],
        "cluster_names": ["Alpha", "Bravo"],
        "matrix": [],
        "pair_summaries": [],
        "consolidation_candidates": [],
        "strong_pair_count": 0,
    })

    assert "a,Alpha" in csv_text
    assert "b,Bravo" in csv_text


def test_csv_guards_formula_injection() -> None:
    evil = '=HYPERLINK("http://evil")'
    payload = {
        "cluster_ids": [evil],
        "cluster_names": [],
        "matrix": [[1.0]],
        "pair_summaries": [],
        "consolidation_candidates": [],
        "cluster_metadata": {},
        "strong_pair_count": 0,
    }
    csv_text = cluster_overlap_to_csv(payload)

    # The injection is neutralised with a leading single quote.
    # csv.writer doubles the embedded quotes, so we check the
    # unquoted-escape prefix with the inner quotes doubled.
    assert "'=HYPERLINK(\"\"http://evil\"\")" in csv_text


def test_json_round_trip() -> None:
    json_text = cluster_overlap_to_json(
        _matrix_payload(),
        metadata={"user_id": 42},
    )

    assert '"cluster_overlap"' in json_text
    assert '"cluster_ids"' in json_text
    assert '"user_id"' in json_text
    assert '"strong_pair_count"' in json_text


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------


def _import_simulations_module():
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub
    from app.api.v1 import simulations as sim_mod

    return sim_mod


def _cluster_ids() -> list[str]:
    """Grab two real registered cluster ids for the route test."""
    from app.simulation.clusters.registry import ClusterRegistry

    clusters = ClusterRegistry().all_clusters()
    return [clusters[0].cluster_id, clusters[1].cluster_id]


def _call_route(*, cluster_ids: list[str] | None = None, format: str = "csv"):
    sim_mod = _import_simulations_module()
    ids = cluster_ids if cluster_ids is not None else _cluster_ids()
    return sim_mod.export_cluster_overlap_matrix(
        cluster_ids=ids,
        format=format,
        current_user=type("U", (), {"id": 42})(),
    )


async def _collect(resp) -> bytes:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def _body(resp) -> bytes:
    return asyncio.run(_collect(resp))


def test_export_route_returns_csv() -> None:
    resp = _call_route()

    assert resp.media_type == "text/csv; charset=utf-8"
    assert (
        'filename="cluster-overlap-matrix.csv"'
        in resp.headers["Content-Disposition"]
    )
    assert resp.headers["Cache-Control"] == "no-store"
    body = _body(resp).decode("utf-8")
    assert "section,Cluster Overlap Summary" in body
    assert "section,Cluster Details" in body
    assert "cluster_id,cluster_name,income_level,digital_literacy" in body
    assert "section,Similarity Matrix" in body
    assert "section,Consolidation Candidates" in body
    assert "cluster_count,2" in body


def test_export_route_returns_json() -> None:
    resp = _call_route(format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    assert (
        'filename="cluster-overlap-matrix.json"'
        in resp.headers["Content-Disposition"]
    )
    assert resp.headers["Cache-Control"] == "no-store"
    body = _body(resp).decode("utf-8")
    assert '"cluster_overlap"' in body
    assert '"cluster_ids"' in body
    assert '"requested_ids"' in body


def test_export_route_rejects_unknown_format() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _call_route(format="yaml")

    assert exc_info.value.status_code == 400
    assert "unsupported export format" in exc_info.value.detail


def test_export_route_rejects_empty_ids() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _call_route(cluster_ids=[])

    assert exc_info.value.status_code == 400
    assert "cluster_ids must supply at least one non-empty" in exc_info.value.detail


def test_export_route_rejects_unknown_cluster() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _call_route(cluster_ids=["does_not_exist"])

    assert exc_info.value.status_code == 400
    assert "Unknown cluster_id" in exc_info.value.detail


def test_export_route_registered() -> None:
    sim_mod = _import_simulations_module()

    paths = [r.path for r in sim_mod.router.routes]
    assert "/simulations/cluster-overlap-matrix/export" in paths
