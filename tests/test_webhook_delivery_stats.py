"""Tests for webhook delivery health statistics (pure builder + route)."""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime
from unittest.mock import patch

if "razorpay" not in sys.modules:
    _razorpay_stub = types.ModuleType("razorpay")
    _razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = _razorpay_stub

from app.schemas.simulation_webhook_delivery import (
    SimulationWebhookDeliveryStatsOut,
)
from app.simulation.webhook_delivery_stats import (
    HEALTH_DEGRADED,
    HEALTH_DOWN,
    HEALTH_HEALTHY,
    HEALTH_NO_DATA,
    MAX_TOP_ERRORS,
    build_webhook_delivery_stats,
)

BASE = datetime(2026, 1, 31, tzinfo=UTC)


def _row(
    rid: int,
    *,
    status: str = "SUCCESS",
    created_at: str | None = "2026-01-15T00:00:00+00:00",
    delivered_at: str | None = None,
    http_status: int | None = 200,
    event_type: str = "simulation.completed",
    error: str | None = None,
    retry_count: int = 0,
) -> dict:
    return {
        "id": rid,
        "webhook_subscription_id": 7,
        "simulation_id": 11,
        "event_type": event_type,
        "status": status,
        "attempt_status": None,
        "http_status": http_status,
        "error": error,
        "conversion_rate": 0.01,
        "request_body": None,
        "retry_count": retry_count,
        "delivered_at": delivered_at or created_at,
        "created_at": created_at,
    }


def _build(
    rows: list[dict] | None = None,
    *,
    webhook_id: int = 7,
    days: int = 30,
    now: datetime = BASE,
) -> dict:
    return build_webhook_delivery_stats(
        rows,
        webhook_id=webhook_id,
        days=days,
        now=now,
    )


def test_empty_rows_return_no_data_state() -> None:
    out = _build([])
    assert out["webhook_id"] == 7
    assert out["window_days"] == 30
    assert out["total_deliveries"] == 0
    assert out["success_count"] == 0
    assert out["failed_count"] == 0
    assert out["success_rate"] is None
    assert out["status_breakdown"] == {}
    assert out["http_status_breakdown"] == {}
    assert out["event_type_breakdown"] == {}
    assert out["retry_count_total"] == 0
    assert out["max_retry_count"] == 0
    assert out["top_errors"] == []
    assert out["first_delivery_at"] is None
    assert out["last_delivery_at"] is None
    assert out["health_label"] == HEALTH_NO_DATA
    assert "No webhook deliveries" in out["narrative"]


def test_window_filters_out_older_rows() -> None:
    rows = [
        _row(1, created_at="2025-12-31T23:59:59+00:00"),  # outside 30 days
        _row(2, created_at="2026-01-01T00:00:00+00:00"),  # boundary
        _row(3, created_at="2026-01-15T00:00:00+00:00"),
    ]
    out = _build(rows)
    assert out["total_deliveries"] == 2
    assert out["success_count"] == 2
    assert out["first_delivery_at"] == datetime(
        2026, 1, 1, tzinfo=UTC
    )


def test_counts_success_failed_and_rate() -> None:
    rows = [
        _row(1, status="SUCCESS"),
        _row(2, status="SUCCESS"),
        _row(3, status="FAILED", http_status=500),
        _row(4, status="FAILED", http_status=503),
        _row(5, status="SUCCESS"),
    ]
    out = _build(rows)
    assert out["total_deliveries"] == 5
    assert out["success_count"] == 3
    assert out["failed_count"] == 2
    assert out["success_rate"] == 0.6
    assert out["status_breakdown"] == {"SUCCESS": 3, "FAILED": 2}
    assert out["http_status_breakdown"] == {"200": 3, "500": 1, "503": 1}
    assert out["health_label"] == HEALTH_DOWN


def test_health_labels_cover_all_verdicts() -> None:
    all_ok = _build(
        [_row(1, status="SUCCESS"), _row(2, status="SUCCESS")]
    )
    assert all_ok["health_label"] == HEALTH_HEALTHY
    assert all_ok["narrative"].startswith("All 2 deliveries")

    degraded = _build(
        [
            _row(1, status="SUCCESS"),
            _row(2, status="SUCCESS"),
            _row(3, status="SUCCESS"),
            _row(4, status="SUCCESS"),
            _row(5, status="FAILED"),
        ]
    )
    assert degraded["health_label"] == HEALTH_DEGRADED
    assert degraded["success_rate"] == 0.8

    down = _build(
        [
            _row(1, status="SUCCESS"),
            _row(2, status="FAILED"),
            _row(3, status="FAILED"),
        ]
    )
    assert down["health_label"] == HEALTH_DOWN
    assert down["narrative"].startswith("Most deliveries failed")


def test_event_type_and_retry_pressure_are_aggregated() -> None:
    rows = [
        _row(1, event_type="simulation.completed", retry_count=0),
        _row(2, event_type="simulation.completed", retry_count=2),
        _row(3, event_type="simulation.failed", retry_count=4),
        _row(4, event_type="simulation.completed", retry_count=1),
    ]
    out = _build(rows)
    assert out["event_type_breakdown"] == {
        "simulation.completed": 3,
        "simulation.failed": 1,
    }
    assert out["retry_count_total"] == 7
    assert out["max_retry_count"] == 4


def test_top_errors_are_count_sorted_and_bounded() -> None:
    rows = [
        _row(1, status="FAILED", error="timeout"),
        _row(2, status="FAILED", error="timeout"),
        _row(3, status="FAILED", error="timeout"),
        _row(4, status="FAILED", error="500"),
        _row(5, status="FAILED", error="500"),
        _row(6, status="FAILED", error="a"),
        _row(7, status="FAILED", error="b"),
        _row(8, status="FAILED", error="c"),
    ]
    out = _build(rows)
    assert len(out["top_errors"]) == MAX_TOP_ERRORS
    assert out["top_errors"][0] == {"error": "timeout", "count": 3}
    assert out["top_errors"][1] == {"error": "500", "count": 2}
    assert [item["error"] for item in out["top_errors"][2:]] == ["a", "b", "c"]


def test_success_rows_with_simulation_errors_are_not_delivery_failures() -> None:
    rows = [
        _row(
            1,
            status="SUCCESS",
            error="product market fit is weak",  # simulation.failed event
        ),
        _row(2, status="SUCCESS"),
    ]
    out = _build(rows)
    assert out["success_count"] == 2
    assert out["failed_count"] == 0
    assert out["top_errors"] == []
    assert out["last_delivery_error"] is None
    assert out["health_label"] == HEALTH_HEALTHY


def test_malformed_rows_are_skipped() -> None:
    rows = [
        "not-a-dict",
        _row(1),
        {"id": 2, "status": "SUCCESS"},  # no timestamp
        _row(3, created_at="not-a-timestamp"),
        _row(4, created_at=None),
    ]
    out = _build(rows)
    assert out["total_deliveries"] == 1
    assert out["success_count"] == 1


def test_naive_and_z_suffix_timestamps_are_parsed() -> None:
    rows = [
        _row(1, created_at="2026-01-15T00:00:00Z"),
        _row(2, created_at="2026-01-20T00:00:00"),
        _row(3, created_at=datetime(2026, 1, 25, 0, 0)),
    ]
    out = _build(rows)
    assert out["total_deliveries"] == 3
    assert out["last_delivery_at"] == datetime(2026, 1, 25, tzinfo=UTC)


def test_days_is_sanitised_to_at_least_one() -> None:
    out = _build([_row(1)], days=0)
    assert out["window_days"] == 1


def test_schema_round_trip() -> None:
    payload = _build(
        [
            _row(1, status="SUCCESS"),
            _row(2, status="FAILED", error="boom"),
        ]
    )
    out = SimulationWebhookDeliveryStatsOut(**payload)
    assert out.webhook_id == 7
    assert out.total_deliveries == 2
    assert out.health_label == HEALTH_DOWN
    assert out.top_errors[0].error == "boom"
    assert out.last_delivery_error == "boom"


class _Delivery:
    def __init__(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class _Query:
    def __init__(self, items: list[_Delivery]) -> None:
        self._items = items

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._items)


class _Session:
    def __init__(self, items: list[_Delivery]) -> None:
        self.items = items

    def query(self, model, *args, **kwargs):
        return _Query(self.items)


def _delivery_row(
    rid: int,
    *,
    status: str,
    error: str | None = None,
) -> _Delivery:
    created = datetime(2026, 1, 15, tzinfo=UTC)
    return _Delivery(
        id=rid,
        webhook_subscription_id=7,
        simulation_id=11,
        event_type="simulation.completed",
        status=status,
        attempt_status="COMPLETED",
        http_status=200 if status == "SUCCESS" else 500,
        error=error,
        conversion_rate=0.01,
        request_body=None,
        retry_count=1,
        delivered_at=created,
        created_at=created,
    )


class _FixedDatetime:
    """Minimal stand-in for the route module's ``datetime`` import."""

    @staticmethod
    def now(tz=None):
        return datetime(2026, 1, 31, tzinfo=UTC)


def test_route_returns_delivery_stats() -> None:
    from app.api.v1 import simulation_webhooks as mod

    session = _Session(
        [
            _delivery_row(1, status="SUCCESS"),
            _delivery_row(2, status="FAILED", error="boom"),
        ]
    )
    with patch.object(
        mod,
        "_get_owned_webhook",
        return_value=type("Webhook", (), {"id": 7})(),
    ), patch.object(mod, "datetime", _FixedDatetime):
        out = mod.get_simulation_webhook_delivery_stats(
            project_id=10,
            webhook_id=7,
            days=30,
            db=session,
            current_user=type("U", (), {"id": 42})(),
        )

    assert out.webhook_id == 7
    assert out.total_deliveries == 2
    assert out.success_count == 1
    assert out.failed_count == 1
    assert out.success_rate == 0.5
    assert out.http_status_breakdown == {"200": 1, "500": 1}
    assert out.health_label == HEALTH_DOWN
    assert out.top_errors[0].error == "boom"
