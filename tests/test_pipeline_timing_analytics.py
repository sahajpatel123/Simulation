"""Tests for the fleet-level pipeline-timing analytics feature.

Covers the pure aggregation helper (``build_pipeline_timing_summary``) and
the admin route wiring for ``GET /api/v1/analytics/pipeline-timing``.
"""

from __future__ import annotations

import json
import sys
import types
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.schemas.pipeline_timing import (  # noqa: E402
    PipelineTimingSummaryOut,
)
from app.simulation.pipeline_timing_analytics import (  # noqa: E402
    build_pipeline_timing_summary,
)


def _payload(
    *,
    agent: float | None = None,
    conductor: float | None = None,
    total: float,
    per_agent_ms: float | None = None,
    end_to_end: float | None = None,
) -> dict[str, Any]:
    stages: dict[str, Any] = {}
    if agent is not None:
        stages["agent_profile_generation"] = agent
    if conductor is not None:
        stages["conductor_run"] = conductor
    stages["total_seconds"] = total
    stages["stage_count"] = len(stages) - 1
    if per_agent_ms is not None:
        stages["per_agent_ms"] = per_agent_ms
    if end_to_end is not None:
        stages["end_to_end_seconds"] = end_to_end
    return stages


# ---------------------------------------------------------------------------
# Pure aggregation helper
# ---------------------------------------------------------------------------


def test_summary_empty_input_returns_zeroed_payload() -> None:
    out = build_pipeline_timing_summary(
        [],
        total_completed=0,
        with_timing=0,
        sample_limit=500,
    )
    assert out["runs_analysed"] == 0
    assert out["total_completed"] == 0
    assert out["with_timing"] == 0
    assert out["coverage_pct"] == 0.0
    assert out["stages"] == []
    assert out["slowest_runs"] == []
    assert out["totals"] == {
        "runs": 0,
        "mean_seconds": None,
        "median_seconds": None,
        "p95_seconds": None,
        "max_seconds": None,
        "sum_seconds": None,
        "mean_per_agent_ms": None,
        "p95_per_agent_ms": None,
        "mean_end_to_end_seconds": None,
    }


def test_summary_aggregates_stage_and_fleet_stats() -> None:
    rows = [
        {
            "id": 1,
            "project_id": 10,
            "created_at": "2026-08-01T00:00:00+00:00",
            "pipeline_timing": _payload(
                agent=1.0,
                conductor=2.0,
                total=3.0,
                per_agent_ms=0.3,
                end_to_end=4.0,
            ),
        },
        {
            "id": 2,
            "project_id": 11,
            "created_at": datetime(2026, 8, 2, tzinfo=UTC),
            "pipeline_timing": _payload(
                agent=3.0,
                conductor=5.0,
                total=8.0,
                per_agent_ms=0.8,
                end_to_end=10.0,
            ),
        },
        {
            "id": 3,
            "project_id": 12,
            "created_at": "not-a-date",
            "pipeline_timing": _payload(
                conductor=9.0,
                total=12.0,
                per_agent_ms=1.2,
            ),
        },
    ]
    out = build_pipeline_timing_summary(
        rows,
        total_completed=100,
        with_timing=75,
        sample_limit=500,
        top_slowest=10,
    )

    assert out["runs_analysed"] == 3
    assert out["coverage_pct"] == 75.0
    assert out["sample_limit"] == 500
    assert [s["stage"] for s in out["stages"]] == [
        "conductor_run",
        "agent_profile_generation",
    ]

    conductor = out["stages"][0]
    assert conductor["runs"] == 3
    assert conductor["mean_seconds"] == pytest.approx(5.3333, abs=1e-3)
    assert conductor["median_seconds"] == 5.0
    assert conductor["p95_seconds"] == pytest.approx(8.6, abs=1e-3)
    assert conductor["max_seconds"] == 9.0
    assert conductor["mean_share"] == pytest.approx(0.6957, abs=1e-3)

    agent = out["stages"][1]
    assert agent["runs"] == 2
    assert agent["mean_seconds"] == 2.0
    assert agent["median_seconds"] == 2.0
    assert agent["p95_seconds"] == pytest.approx(2.9, abs=1e-3)
    assert agent["max_seconds"] == 3.0
    assert agent["mean_share"] == pytest.approx(0.2609, abs=1e-3)

    totals = out["totals"]
    assert totals["runs"] == 3
    assert totals["mean_seconds"] == pytest.approx(7.6667, abs=1e-3)
    assert totals["median_seconds"] == 8.0
    assert totals["p95_seconds"] == pytest.approx(11.6, abs=1e-3)
    assert totals["max_seconds"] == 12.0
    assert totals["sum_seconds"] == 23.0
    assert totals["mean_per_agent_ms"] == pytest.approx(0.766667, abs=1e-5)
    assert totals["p95_per_agent_ms"] == pytest.approx(1.16, abs=1e-5)
    assert totals["mean_end_to_end_seconds"] == 7.0

    assert [r["simulation_id"] for r in out["slowest_runs"]] == [3, 2, 1]
    assert out["slowest_runs"][0]["dominant_stage"] == "conductor_run"


def test_summary_skips_malformed_payloads_and_reserved_keys() -> None:
    rows = [
        {"id": 1, "project_id": 1, "pipeline_timing": None},
        {"id": 2, "project_id": 2, "pipeline_timing": "{not-json"},
        {
            "id": 3,
            "project_id": 3,
            "pipeline_timing": {
                "good": 1.0,
                "negative": -1.0,
                "nan": float("nan"),
                "total_seconds": 99.0,
                "stage_count": 7,
                "per_agent_ms": 99.0,
                "end_to_end_seconds": 99.0,
                "failed_during": 99.0,
                "": 2.0,
                "total_seconds_evil": 3.0,
            },
        },
    ]
    out = build_pipeline_timing_summary(rows, total_completed=10, with_timing=1)
    assert out["runs_analysed"] == 1
    assert out["totals"]["runs"] == 1
    assert out["totals"]["mean_seconds"] == 99.0
    assert out["totals"]["mean_per_agent_ms"] == 99.0
    assert out["totals"]["mean_end_to_end_seconds"] == 99.0
    assert [s["stage"] for s in out["stages"]] == ["total_seconds_evil", "good"]
    assert out["stages"][0]["mean_seconds"] == 3.0


def test_summary_accepts_json_string_payloads() -> None:
    rows = [
        {
            "id": 9,
            "project_id": 4,
            "created_at": "2026-08-03T00:00:00+00:00",
            "pipeline_timing": json.dumps(
                {
                    "conductor_run": 6.0,
                    "total_seconds": 6.0,
                    "stage_count": 1,
                    "per_agent_ms": 0.6,
                }
            ),
        }
    ]
    out = build_pipeline_timing_summary(rows, total_completed=1, with_timing=1)
    assert out["runs_analysed"] == 1
    assert out["totals"]["mean_seconds"] == 6.0
    assert out["slowest_runs"][0]["created_at"] == datetime(
        2026, 8, 3, tzinfo=UTC
    )


def test_summary_coverage_clamps_and_handles_zero_completed() -> None:
    assert build_pipeline_timing_summary([], total_completed=0, with_timing=0)[
        "coverage_pct"
    ] == 0.0
    assert build_pipeline_timing_summary([], total_completed=10, with_timing=10)[
        "coverage_pct"
    ] == 100.0
    # Defensive clamp: DB count inconsistency cannot report > 100%.
    assert build_pipeline_timing_summary([], total_completed=5, with_timing=9)[
        "coverage_pct"
    ] == 100.0


def test_summary_clamps_mean_share_when_stage_exceeds_total() -> None:
    """A malformed legacy payload must not break the response schema."""
    rows = [
        {
            "id": 1,
            "project_id": 10,
            "created_at": "2026-08-01T00:00:00+00:00",
            "pipeline_timing": {
                "conductor_run": 5.0,
                "total_seconds": 1.0,
                "stage_count": 1,
            },
        },
        {
            "id": 2,
            "project_id": 11,
            "created_at": "2026-08-02T00:00:00+00:00",
            "pipeline_timing": {
                "conductor_run": 7.0,
                "total_seconds": 2.0,
                "stage_count": 1,
            },
        },
    ]
    out = build_pipeline_timing_summary(rows, total_completed=2, with_timing=2)
    assert out["runs_analysed"] == 2
    assert out["stages"][0]["stage"] == "conductor_run"
    assert out["stages"][0]["mean_seconds"] == 6.0
    assert out["stages"][0]["mean_share"] == 1.0
    # The clamped payload must still validate against the route's response
    # model — otherwise one bad row would turn the admin view into a 500.
    validated = PipelineTimingSummaryOut(**out)
    assert validated.stages[0].mean_share == 1.0


def test_summary_skips_non_dict_rows_without_raising() -> None:
    rows: list[Any] = [
        None,
        "not-a-row",
        42,
        [1, 2],
        {
            "id": 1,
            "project_id": 10,
            "created_at": "2026-08-03T00:00:00+00:00",
            "pipeline_timing": {"agent_profile_generation": 1.0, "total_seconds": 1.0},
        },
    ]
    out = build_pipeline_timing_summary(rows, total_completed=5, with_timing=1)
    assert out["runs_analysed"] == 1
    assert out["totals"]["runs"] == 1
    assert out["totals"]["mean_seconds"] == 1.0
    assert out["slowest_runs"][0]["simulation_id"] == 1


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


class _FakeMappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def first(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def all(self) -> list[dict[str, Any]]:
        return self.rows


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._mappings = _FakeMappings(rows)

    def mappings(self) -> _FakeMappings:
        return self._mappings


class _FakeDB:
    def __init__(
        self,
        *,
        coverage: dict[str, Any],
        rows: list[dict[str, Any]],
    ) -> None:
        self.coverage = coverage
        self.rows = rows

    def execute(self, query: object, params: dict[str, Any] | None = None) -> _FakeResult:
        if "COUNT(*)::int" in str(query):
            return _FakeResult([self.coverage])
        return _FakeResult(self.rows)


class _FakeUser:
    def __init__(self, user_id: int, is_admin: bool) -> None:
        self.id = user_id
        self.is_admin = is_admin
        self.email = "admin@example.com"


def test_admin_route_returns_pipeline_timing_summary() -> None:
    from app.api.v1 import analytics as analytics_mod

    db = _FakeDB(
        coverage={"total_completed": 10, "with_timing": 2},
        rows=[
            {
                "id": 2,
                "project_id": 11,
                "created_at": "2026-08-02T00:00:00+00:00",
                "pipeline_timing": _payload(
                    agent=3.0,
                    conductor=5.0,
                    total=8.0,
                    per_agent_ms=0.8,
                ),
            },
            {
                "id": 1,
                "project_id": 10,
                "created_at": "2026-08-01T00:00:00+00:00",
                "pipeline_timing": _payload(
                    agent=1.0,
                    conductor=2.0,
                    total=3.0,
                    per_agent_ms=0.3,
                ),
            },
        ],
    )

    out = analytics_mod.pipeline_timing_analytics(
        limit=100,
        db=db,
        current_user=_FakeUser(user_id=1, is_admin=True),
    )

    assert isinstance(out, PipelineTimingSummaryOut)
    assert out.total_completed == 10
    assert out.with_timing == 2
    assert out.coverage_pct == 20.0
    assert out.sample_limit == 100
    assert out.runs_analysed == 2
    assert [s.stage for s in out.stages] == ["conductor_run", "agent_profile_generation"]
    assert out.slowest_runs[0].simulation_id == 2
    assert out.slowest_runs[0].dominant_stage == "conductor_run"
    assert out.totals.runs == 2
    assert out.totals.mean_seconds == pytest.approx(5.5, abs=1e-3)


def test_admin_route_rejects_non_admin() -> None:
    from app.api.v1 import analytics as analytics_mod

    db = _FakeDB(
        coverage={"total_completed": 0, "with_timing": 0},
        rows=[],
    )
    with pytest.raises(HTTPException) as exc:
        analytics_mod.pipeline_timing_analytics(
            limit=100,
            db=db,
            current_user=_FakeUser(user_id=1, is_admin=False),
        )
    assert exc.value.status_code == 403


def test_route_is_registered_and_uses_response_model() -> None:
    source = Path("backend/app/api/v1/analytics.py").read_text(encoding="utf-8")
    assert '"/pipeline-timing"' in source
    assert "def pipeline_timing_analytics(" in source
    assert "response_model=PipelineTimingSummaryOut" in source
    assert "build_pipeline_timing_summary(" in source
