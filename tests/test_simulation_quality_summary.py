"""Tests for the project simulation quality digest.

The digest rolls the existing per-run quality gate over a project's
simulation history: per-run trust rows plus PASS / REVIEW / FAIL counts,
mean / min / max trust, and an overall verdict. These tests pin the pure
aggregation (no DB) and the project route contract (fake session, no DB).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.simulation_quality_summary import (
    LABEL_INSUFFICIENT_DATA,
    build_project_simulation_quality,
)


def _healthy_results() -> dict:
    """Build a fully valid completed-results payload."""
    clusters = ClusterRegistry().all_clusters()
    rates = {
        c.cluster_id: round(0.03 + index * 0.0008, 6)
        for index, c in enumerate(clusters)
    }
    pwc = round(
        sum(c.population_weight * rates[c.cluster_id] for c in clusters),
        6,
    )
    converted = int(round(pwc * 10_000))
    return {
        "mean_conversion_rate": pwc,
        "population_weighted_conversion": pwc,
        "total_agents": 10_000,
        "converted": converted,
        "cluster_breakdown": rates,
        "domain_findings": [{"domain": "PricingArchitect", "severity": "WARNING"}],
        "raw_funnel": {
            "total_agents": 10_000,
            "converted": converted,
            "conversion_rate": pwc,
            "stage_counts": {
                "ARRIVE": 10_000,
                "BROWSE": 7_000,
                "CONSIDER": 4_000,
                "DECIDE": 2_000,
                "PURCHASE": converted,
            },
            "stage_metrics": [
                {
                    "state": "ARRIVE",
                    "agent_count": 10_000,
                    "entry_rate": 1.0,
                    "drop_off_rate": 0.3,
                    "avg_time_seconds": 1.0,
                },
                {
                    "state": "BROWSE",
                    "agent_count": 7_000,
                    "entry_rate": 0.7,
                    "drop_off_rate": 0.43,
                    "avg_time_seconds": 1.0,
                },
                {
                    "state": "CONSIDER",
                    "agent_count": 4_000,
                    "entry_rate": 0.4,
                    "drop_off_rate": 0.5,
                    "avg_time_seconds": 1.0,
                },
                {
                    "state": "DECIDE",
                    "agent_count": 2_000,
                    "entry_rate": 0.2,
                    "drop_off_rate": 0.5,
                    "avg_time_seconds": 1.0,
                },
            ],
        },
    }


def _row(
    sim_id: int,
    *,
    status: str = "COMPLETED",
    results: object | None = None,
    signal_quality: object = 0.62,
    created_at: object = "2026-08-10T00:00:00+00:00",
) -> dict:
    return {
        "id": sim_id,
        "status": status,
        "created_at": created_at,
        "signal_quality": signal_quality,
        "results_json": results if results is not None else _healthy_results(),
    }


# ---------------------------------------------------------------------------
# Pure helper
# ---------------------------------------------------------------------------


def test_empty_rows_returns_insufficient_data() -> None:
    payload = build_project_simulation_quality([], project_id=1)
    assert payload["project_id"] == 1
    assert payload["total_runs"] == 0
    assert payload["completed_runs"] == 0
    assert payload["evaluated_runs"] == 0
    assert payload["pass_count"] == 0
    assert payload["overall_verdict"] == LABEL_INSUFFICIENT_DATA
    assert payload["mean_trust_score"] is None
    assert payload["min_trust_score"] is None
    assert payload["max_trust_score"] is None
    assert payload["runs"] == []


def test_mixed_rows_aggregate_verdicts_and_scores() -> None:
    payload = build_project_simulation_quality(
        [
            _row(1, results=_healthy_results()),
            _row(2, results={}),
            _row(3, status="QUEUED", results=None),
        ],
        project_id=7,
    )
    assert payload["total_runs"] == 3
    assert payload["completed_runs"] == 2
    assert payload["evaluated_runs"] == 2
    assert payload["pass_count"] == 1
    assert payload["review_count"] == 0
    assert payload["fail_count"] == 1
    assert payload["mean_trust_score"] == round(
        (1.0 + payload["runs"][1]["trust_score"]) / 2, 4
    )
    assert payload["min_trust_score"] == pytest.approx(payload["runs"][1]["trust_score"])
    assert payload["max_trust_score"] == 1.0
    assert payload["overall_verdict"] == "FAIL"

    by_id = {row["simulation_id"]: row for row in payload["runs"]}
    assert by_id[1]["trust_score"] == 1.0
    assert by_id[1]["verdict"] == "PASS"
    assert 0.0 < by_id[2]["trust_score"] < 1.0
    assert by_id[2]["verdict"] == "FAIL"
    assert by_id[2]["failed_checks"] > 0
    assert by_id[3]["trust_score"] is None
    assert by_id[3]["verdict"] is None
    assert by_id[3]["status"] == "QUEUED"


def test_healthy_plus_empty_lands_below_review_band() -> None:
    payload = build_project_simulation_quality(
        [_row(1, results=_healthy_results()), _row(2, results={})],
        project_id=3,
    )
    empty_trust = payload["runs"][1]["trust_score"]
    assert empty_trust < 1.0
    assert payload["mean_trust_score"] == round((1.0 + empty_trust) / 2, 4)
    # Mean is below the 0.60 REVIEW threshold, so the digest must not hide
    # the broken run behind a single healthy one.
    assert payload["overall_verdict"] == "FAIL"


def test_string_results_json_is_coerced() -> None:
    import json

    payload = build_project_simulation_quality(
        [
            _row(
                9,
                results=json.dumps(_healthy_results()),
                signal_quality="0.62",
            )
        ],
        project_id=4,
    )
    assert payload["evaluated_runs"] == 1
    assert payload["runs"][0]["trust_score"] == 1.0
    assert payload["runs"][0]["signal_quality"] == 0.62


def test_out_of_range_signal_quality_is_sanitized() -> None:
    payload = build_project_simulation_quality(
        [_row(1, results=_healthy_results(), signal_quality=1.5)],
        project_id=5,
    )
    assert payload["runs"][0]["signal_quality"] is None


def test_datetime_created_at_serialises_to_iso() -> None:
    created = datetime(2026, 8, 10, 12, 30, tzinfo=UTC)
    payload = build_project_simulation_quality(
        [_row(1, results=_healthy_results(), created_at=created)],
        project_id=6,
    )
    assert payload["runs"][0]["created_at"] == "2026-08-10T12:30:00+00:00"


def test_generated_at_is_passthrough() -> None:
    payload = build_project_simulation_quality(
        [],
        project_id=8,
        generated_at="2026-08-10T01:02:03+00:00",
    )
    assert payload["generated_at"] == "2026-08-10T01:02:03+00:00"


def test_malformed_row_does_not_crash() -> None:
    payload = build_project_simulation_quality(
        [None, {"id": 3}, _row(4, status="  completed  ", results={})],
        project_id=9,
    )
    assert payload["total_runs"] == 3
    assert payload["completed_runs"] == 1
    assert payload["runs"][0]["status"] == "UNKNOWN"
    assert payload["runs"][1]["status"] == "UNKNOWN"
    assert payload["runs"][2]["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_project_quality_schema_defaults() -> None:
    from app.schemas.simulation_quality import ProjectSimulationQualityOut

    out = ProjectSimulationQualityOut(project_id=1)
    assert out.total_runs == 0
    assert out.overall_verdict == LABEL_INSUFFICIENT_DATA
    assert out.mean_trust_score is None
    assert out.runs == []


# ---------------------------------------------------------------------------
# Route contract
# ---------------------------------------------------------------------------


class _FakeProject:
    id = 1
    user_id = 42


_MISSING = object()


class _FakeQuery:
    def __init__(self, rows: list[object] | None = None, first: object = None) -> None:
        self.rows = rows if rows is not None else []
        self._first = first

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def first(self):
        return self._first

    def all(self):
        return self.rows


class _FakeRow:
    """Mimic a SQLAlchemy ``Row``: attribute access, not dict-iterable."""

    def __init__(self, **attrs: object) -> None:
        for key, value in attrs.items():
            setattr(self, key, value)


class _FakeSession:
    def __init__(
        self,
        sim_rows: list[object] | None = None,
        project: object = _MISSING,
    ) -> None:
        self.sim_rows = sim_rows or []
        self.project = _FakeProject() if project is _MISSING else project

    def query(self, *args, **kwargs):
        target = args[0] if args else None
        class_ = getattr(target, "class_", target)
        name = getattr(class_, "__name__", "")
        if name == "Project":
            return _FakeQuery(first=self.project)
        if name == "Simulation":
            return _FakeQuery(rows=self.sim_rows)
        return _FakeQuery()


def _call_route(
    *,
    project_id: int = 1,
    current_user_id: int = 42,
    session: _FakeSession | None = None,
):
    from app.api.v1 import projects as proj_mod

    return proj_mod.get_project_simulation_quality(
        project_id=project_id,
        db=session or _FakeSession(),
        current_user=type("U", (), {"id": current_user_id})(),
    )


def test_project_simulation_quality_route_registered() -> None:
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import projects as proj_mod

    paths = {r.path for r in proj_mod.router.routes}
    assert "/projects/{project_id}/simulation-quality" in paths

    methods_by_path: dict[str, set[str]] = {}
    for route in proj_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(route.methods or set())
    assert "GET" in methods_by_path["/projects/{project_id}/simulation-quality"]


def test_project_simulation_quality_route_uses_typed_response() -> None:
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import projects as proj_mod
    from app.schemas.simulation_quality import ProjectSimulationQualityOut

    matching = [
        route
        for route in proj_mod.router.routes
        if isinstance(route, APIRoute)
        and route.path.endswith("/simulation-quality")
    ]
    assert matching
    assert matching[0].response_model is ProjectSimulationQualityOut


def test_project_simulation_quality_route_builds_digest() -> None:
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    out = _call_route(
        session=_FakeSession(
            sim_rows=[
                _row(1, results=_healthy_results()),
                _row(2, status="RUNNING", results=None),
            ]
        )
    )
    assert out.project_id == 1
    assert out.total_runs == 2
    assert out.completed_runs == 1
    assert out.pass_count == 1
    assert out.overall_verdict == "PASS"
    assert out.mean_trust_score == 1.0
    assert out.runs[0].simulation_id == 1
    assert out.runs[0].trust_score == 1.0
    assert out.runs[1].trust_score is None


def test_project_simulation_quality_route_handles_row_objects() -> None:
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    rows = [
        _FakeRow(**_row(1, results=_healthy_results())),
        _FakeRow(**_row(2, status="RUNNING", results=None)),
    ]
    out = _call_route(session=_FakeSession(sim_rows=rows))
    assert out.total_runs == 2
    assert out.completed_runs == 1
    assert out.pass_count == 1
    assert out.runs[0].simulation_id == 1
    assert out.runs[0].trust_score == 1.0
    assert out.runs[1].status == "RUNNING"
    assert out.runs[1].trust_score is None


def test_project_simulation_quality_route_missing_project_raises_404() -> None:
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    with pytest.raises(HTTPException) as exc:
        _call_route(session=_FakeSession(project=None))
    assert exc.value.status_code == 404
    assert exc.value.detail == "Project not found"
