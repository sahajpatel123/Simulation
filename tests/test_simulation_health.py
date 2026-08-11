"""Tests for the simulation-pipeline health digest endpoint.

Covers the pure digest builder in ``app.core.simulation_health``
(verdicts, rates, latency percentiles, failure buckets, daily trend), the
SQLAlchemy collector with a fake session, and the route contract. These
run without a live database or Celery worker.
"""

from __future__ import annotations

import sys
import types
from collections import namedtuple
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

if "razorpay" not in sys.modules:
    _razorpay_stub = types.ModuleType("razorpay")
    _razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = _razorpay_stub

from app.api.v1 import system_health as system_health_module  # noqa: E402
from app.core.simulation_health import (  # noqa: E402
    BUCKET_NO_ERROR_MESSAGE,
    BUCKET_OTHER,
    REASON_FAILURE_RATE_HIGH,
    REASON_NO_TERMINAL_RUNS,
    REASON_STUCK_RUNNING,
    VERDICT_DEGRADED,
    VERDICT_HEALTHY,
    VERDICT_NO_DATA,
    VERDICT_WATCH,
    build_simulation_health,
    classify_failure,
    collect_simulation_snapshot,
)
from app.schemas.system_health import SimulationHealthOut  # noqa: E402

_SimRow = namedtuple(
    "_SimRow",
    "id project_id status created_at updated_at error_message",
)


def _failure(
    simulation_id: int,
    error: str | None = "LLM request timed out",
    created_at: str | None = "2026-08-10T12:00:00+00:00",
) -> dict[str, Any]:
    return {
        "simulation_id": simulation_id,
        "project_id": 7,
        "created_at": created_at,
        "error_message": error,
    }


def _base_inputs() -> dict[str, Any]:
    return {
        "status_counts": {},
        "completed_durations_ms": [],
        "failures": [],
        "daily_counts": {},
        "oldest_running_at": None,
        "window_days": 7,
        "generated_at": "2026-08-11T12:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


def test_empty_snapshot_is_no_data_and_zero_filled() -> None:
    payload = build_simulation_health(**_base_inputs())

    assert payload["verdict"] == VERDICT_NO_DATA
    assert payload["reasons"] == []
    assert payload["total_simulations"] == 0
    assert payload["status_breakdown"] == {}
    assert payload["completed_count"] == 0
    assert payload["failed_count"] == 0
    assert payload["completion_rate"] is None
    assert payload["failure_rate"] is None
    assert payload["latency"]["count"] == 0
    assert payload["failure_buckets"] == []
    assert payload["oldest_running_at"] is None
    assert [row["date"] for row in payload["daily_trend"]] == [
        "2026-08-05",
        "2026-08-06",
        "2026-08-07",
        "2026-08-08",
        "2026-08-09",
        "2026-08-10",
        "2026-08-11",
    ]
    assert isinstance(SimulationHealthOut(**payload), SimulationHealthOut)


def test_healthy_digest_aggregates_rates_latency_and_trend() -> None:
    inputs = _base_inputs()
    inputs["status_counts"] = {
        "COMPLETED": 19,
        "FAILED": 1,
        "RUNNING": 1,
        "CANCELLED": 2,
    }
    inputs["completed_durations_ms"] = [1000.0, 2000.0, 4000.0]
    inputs["failures"] = [_failure(501, "grok rate limit")]
    inputs["daily_counts"] = {
        "2026-08-10": {"created": 3, "completed": 2, "failed": 1},
        "2026-08-11": {"created": 1, "completed": 1, "failed": 0},
    }

    payload = build_simulation_health(**inputs)

    assert payload["verdict"] == VERDICT_HEALTHY
    assert payload["reasons"] == []
    assert payload["total_simulations"] == 23
    assert payload["completed_count"] == 19
    assert payload["failed_count"] == 1
    assert payload["terminal_count"] == 20
    assert payload["completion_rate"] == 0.95
    assert payload["failure_rate"] == 0.05
    assert payload["latency"]["count"] == 3
    assert payload["latency"]["mean_ms"] == pytest.approx(7000.0 / 3.0, abs=0.001)
    assert payload["latency"]["p50_ms"] == pytest.approx(2000.0)
    assert payload["latency"]["p95_ms"] == pytest.approx(4000.0)
    assert payload["latency"]["p99_ms"] == pytest.approx(4000.0)
    assert payload["latency"]["min_ms"] == pytest.approx(1000.0)
    assert payload["latency"]["max_ms"] == pytest.approx(4000.0)
    assert payload["failure_buckets"] == [
        {
            "bucket": "llm_api",
            "count": 1,
            "latest_at": "2026-08-10T12:00:00+00:00",
            "sample_error": "grok rate limit",
        }
    ]
    assert [row["date"] for row in payload["daily_trend"]] == [
        "2026-08-05",
        "2026-08-06",
        "2026-08-07",
        "2026-08-08",
        "2026-08-09",
        "2026-08-10",
        "2026-08-11",
    ]
    trend_by_date = {row["date"]: row for row in payload["daily_trend"]}
    assert trend_by_date["2026-08-10"] == {
        "date": "2026-08-10",
        "created": 3,
        "completed": 2,
        "failed": 1,
    }
    assert trend_by_date["2026-08-05"] == {
        "date": "2026-08-05",
        "created": 0,
        "completed": 0,
        "failed": 0,
    }
    assert isinstance(SimulationHealthOut(**payload), SimulationHealthOut)


def test_failure_rate_at_watch_threshold_is_watch() -> None:
    inputs = _base_inputs()
    inputs["status_counts"] = {"COMPLETED": 16, "FAILED": 2}
    payload = build_simulation_health(**inputs)

    assert payload["failure_rate"] == pytest.approx(2 / 18)
    assert payload["verdict"] == VERDICT_WATCH
    assert payload["reasons"] == [REASON_FAILURE_RATE_HIGH]


def test_failure_rate_at_degraded_threshold_is_degraded() -> None:
    inputs = _base_inputs()
    inputs["status_counts"] = {"COMPLETED": 5, "FAILED": 5}
    payload = build_simulation_health(**inputs)

    assert payload["failure_rate"] == 0.5
    assert payload["verdict"] == VERDICT_DEGRADED
    assert payload["reasons"] == [REASON_FAILURE_RATE_HIGH]


def test_no_terminal_runs_is_watch() -> None:
    inputs = _base_inputs()
    inputs["status_counts"] = {"QUEUED": 2, "RUNNING": 1}
    payload = build_simulation_health(**inputs)

    assert payload["verdict"] == VERDICT_WATCH
    assert payload["reasons"] == [REASON_NO_TERMINAL_RUNS]
    assert payload["completion_rate"] is None
    assert payload["failure_rate"] is None


def test_stuck_running_adds_watch_reason() -> None:
    inputs = _base_inputs()
    inputs["status_counts"] = {"COMPLETED": 10, "FAILED": 0}
    inputs["oldest_running_at"] = (
        datetime.now(UTC) - timedelta(hours=48)
    ).isoformat()
    payload = build_simulation_health(**inputs)

    assert payload["verdict"] == VERDICT_WATCH
    assert payload["reasons"] == [REASON_STUCK_RUNNING]


def test_stuck_running_keeps_degraded_verdict_when_failure_rate_high() -> None:
    inputs = _base_inputs()
    inputs["status_counts"] = {"COMPLETED": 5, "FAILED": 5}
    inputs["oldest_running_at"] = (
        datetime.now(UTC) - timedelta(hours=48)
    ).isoformat()
    payload = build_simulation_health(**inputs)

    assert payload["verdict"] == VERDICT_DEGRADED
    assert payload["reasons"] == [
        REASON_FAILURE_RATE_HIGH,
        REASON_STUCK_RUNNING,
    ]


# ---------------------------------------------------------------------------
# Failure classification and buckets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("worker timed out after 600s", "timeout"),
        ("grok API returned 429 rate limit", "llm_api"),
        ("sqlalchemy OperationalError: connection", "database"),
        ("redis ConnectionError: connection refused", "infrastructure"),
        ("", BUCKET_NO_ERROR_MESSAGE),
        (None, BUCKET_NO_ERROR_MESSAGE),
        ("some unexpected panic", BUCKET_OTHER),
    ],
)
def test_classify_failure_buckets_error_messages(
    error: str | None,
    expected: str,
) -> None:
    assert classify_failure(error) == expected


def test_failure_buckets_sorted_by_count_and_truncate_samples() -> None:
    long_error = "x" * 500
    inputs = _base_inputs()
    inputs["failures"] = [
        _failure(1, "grok timeout", "2026-08-10T09:00:00+00:00"),
        _failure(2, long_error, "2026-08-10T12:00:00+00:00"),
        _failure(3, "psycopg database down", "2026-08-10T11:00:00+00:00"),
        _failure(4, "unknown crash", "2026-08-10T10:00:00+00:00"),
    ]
    payload = build_simulation_health(**inputs)

    buckets = payload["failure_buckets"]
    assert [row["bucket"] for row in buckets] == ["other", "database", "timeout"]
    assert buckets[0]["count"] == 2
    assert buckets[0]["latest_at"] == "2026-08-10T12:00:00+00:00"
    assert buckets[0]["sample_error"].endswith("...")
    assert len(buckets[0]["sample_error"]) == 200


def test_recent_failures_are_bounded_and_error_truncated() -> None:
    long_error = "boom " * 100
    inputs = _base_inputs()
    inputs["failures"] = [_failure(99, long_error)]
    payload = build_simulation_health(**inputs)

    assert len(payload["recent_failures"]) == 1
    row = payload["recent_failures"][0]
    assert row["simulation_id"] == 99
    assert row["project_id"] == 7
    assert row["created_at"] == "2026-08-10T12:00:00+00:00"
    assert row["error_message"].endswith("...")
    assert len(row["error_message"]) == 200


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class _FakeQuery:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def filter(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def all(self) -> list[Any]:
        return self._rows


class _FakeDB:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def query(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return _FakeQuery(self.rows)


def test_collector_builds_snapshot_from_db_rows() -> None:
    created = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    updated = datetime(2026, 8, 10, 12, 30, tzinfo=UTC)
    rows = [
        _SimRow(1, 7, "COMPLETED", created, updated, None),
        _SimRow(2, 7, "FAILED", created, updated, "grok timeout"),
        _SimRow(3, 8, "RUNNING", created, updated, None),
        _SimRow(4, 8, "CANCELLED", created, updated, None),
    ]

    snapshot = collect_simulation_snapshot(
        _FakeDB(rows),
        window_days=7,
    )

    assert snapshot["status_counts"] == {
        "COMPLETED": 1,
        "FAILED": 1,
        "RUNNING": 1,
        "CANCELLED": 1,
    }
    assert snapshot["completed_durations_ms"] == [1_800_000.0]
    assert snapshot["failures"] == [
        {
            "simulation_id": 2,
            "project_id": 7,
            "created_at": "2026-08-10T12:00:00+00:00",
            "error_message": "grok timeout",
        }
    ]
    assert snapshot["daily_counts"]["2026-08-10"] == {
        "created": 4,
        "completed": 1,
        "failed": 1,
    }
    assert snapshot["oldest_running_at"] == "2026-08-10T12:00:00+00:00"


def test_collector_handles_missing_timestamps_and_errors() -> None:
    rows = [
        _SimRow(1, 7, "COMPLETED", None, None, None),
        _SimRow(2, 7, "FAILED", None, None, None),
        _SimRow(3, 7, "RUNNING", None, None, None),
    ]

    snapshot = collect_simulation_snapshot(
        _FakeDB(rows),
        window_days=7,
    )

    assert snapshot["status_counts"] == {
        "COMPLETED": 1,
        "FAILED": 1,
        "RUNNING": 1,
    }
    assert snapshot["completed_durations_ms"] == []
    assert snapshot["daily_counts"] == {}
    assert snapshot["oldest_running_at"] is None
    assert snapshot["failures"][0]["error_message"] == ""
    assert snapshot["failures"][0]["created_at"] is None


def test_collector_returns_all_failures_newest_first() -> None:
    created = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    rows = [
        _SimRow(i, 7, "FAILED", created + timedelta(hours=i), created + timedelta(hours=i), f"error-{i}")
        for i in range(1, 4)
    ]

    snapshot = collect_simulation_snapshot(
        _FakeDB(rows),
        window_days=7,
    )

    # The collector keeps every failure in the window (so buckets reconcile
    # with failed_count); the builder bounds the recent-failures list.
    assert [row["simulation_id"] for row in snapshot["failures"]] == [3, 2, 1]


def test_failure_buckets_span_window_while_recent_list_is_bounded() -> None:
    inputs = _base_inputs()
    inputs["failures"] = [
        _failure(i, f"error-{i}", f"2026-08-10T{i % 10}:00:00+00:00")
        for i in range(1, 13)
    ]

    payload = build_simulation_health(**inputs, recent_failures_limit=5)

    bucket_total = sum(row["count"] for row in payload["failure_buckets"])
    assert bucket_total == 12
    assert len(payload["recent_failures"]) == 5
    created = [row["created_at"] for row in payload["recent_failures"]]
    assert created == sorted(created, reverse=True)


def test_failure_buckets_serialize_datetime_latest_at() -> None:
    inputs = _base_inputs()
    inputs["failures"] = [
        {
            "simulation_id": 2,
            "project_id": 7,
            "created_at": datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
            "error_message": "grok timeout",
        },
        {
            "simulation_id": 1,
            "project_id": 7,
            "created_at": datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
            "error_message": "grok timeout",
        },
    ]

    payload = build_simulation_health(**inputs)

    assert payload["failure_buckets"][0]["latest_at"] == (
        "2026-08-10T12:00:00+00:00"
    )
    assert [row["created_at"] for row in payload["recent_failures"]] == [
        "2026-08-10T12:00:00+00:00",
        "2026-08-09T12:00:00+00:00",
    ]
    assert isinstance(SimulationHealthOut(**payload), SimulationHealthOut)


# ---------------------------------------------------------------------------
# Route contract
# ---------------------------------------------------------------------------


def test_simulation_health_route_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = {
        "status_counts": {"COMPLETED": 3, "FAILED": 0},
        "completed_durations_ms": [1000.0],
        "failures": [_failure(1, "grok timeout"), _failure(2, "db down")],
        "daily_counts": {},
        "oldest_running_at": None,
    }
    monkeypatch.setattr(
        system_health_module.simulation_health_module,
        "collect_simulation_snapshot",
        lambda db, window_days=7: snapshot,
    )

    payload = system_health_module.simulation_health(
        db=object(),
        window_days=3,
        recent_failures_limit=5,
    )

    assert payload["verdict"] == VERDICT_HEALTHY
    assert payload["window_days"] == 3
    assert payload["total_simulations"] == 3
    assert len(payload["daily_trend"]) == 3
    assert len(payload["recent_failures"]) == 2
    assert sum(row["count"] for row in payload["failure_buckets"]) == 2
    assert isinstance(SimulationHealthOut(**payload), SimulationHealthOut)
