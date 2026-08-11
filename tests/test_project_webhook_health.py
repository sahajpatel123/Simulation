"""Tests for the project-wide webhook delivery health overview.

Covers the pure builder in ``app.simulation.project_webhook_health``
(grouping, active-only rollup, health labels, windowing, malformed rows) and
the route contract that composes it from all of a project's subscriptions.
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime
from unittest.mock import patch

if "razorpay" not in sys.modules:
    _razorpay_stub = types.ModuleType("razorpay")
    _razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = _razorpay_stub

from app.schemas.simulation_webhook_delivery import (  # noqa: E402
    ProjectWebhookHealthOut,
)
from app.simulation.project_webhook_health import (  # noqa: E402
    build_project_webhook_health,
)
from app.simulation.webhook_delivery_stats import (  # noqa: E402
    HEALTH_DEGRADED,
    HEALTH_DOWN,
    HEALTH_HEALTHY,
    HEALTH_NO_DATA,
)

BASE = datetime(2026, 1, 31, tzinfo=UTC)


def _subscription(
    sid: int,
    *,
    status: str = "ACTIVE",
    url: str = "https://example.com/hooks/cee",
    event_type: str = "simulation.completed",
) -> dict:
    return {
        "id": sid,
        "url": url,
        "status": status,
        "event_type": event_type,
    }


def _delivery(
    rid: int,
    webhook_id: int,
    *,
    status: str = "SUCCESS",
    created_at: str = "2026-01-15T00:00:00+00:00",
) -> dict:
    ok = status == "SUCCESS"
    return {
        "id": rid,
        "webhook_subscription_id": webhook_id,
        "simulation_id": 11,
        "event_type": "simulation.completed",
        "status": status,
        "attempt_status": "COMPLETED",
        "http_status": 200 if ok else 500,
        "error": None if ok else "webhook endpoint returned HTTP 500",
        "conversion_rate": 0.01,
        "request_body": None,
        "retry_count": 0,
        "delivered_at": created_at,
        "created_at": created_at,
    }


def _build(
    *,
    subscriptions: list[dict] | None = None,
    deliveries: list[dict] | None = None,
    days: int = 30,
    now: datetime = BASE,
) -> dict:
    return build_project_webhook_health(
        project_id=10,
        subscriptions=subscriptions,
        deliveries=deliveries,
        window_days=days,
        now=now,
    )


def test_empty_project_is_no_data() -> None:
    payload = _build()

    assert payload["project_id"] == 10
    assert payload["webhook_count"] == 0
    assert payload["active_webhook_count"] == 0
    assert payload["total_deliveries"] == 0
    assert payload["success_rate"] is None
    assert payload["health_label"] == HEALTH_NO_DATA
    assert "No active webhook subscriptions" in payload["narrative"]
    assert payload["webhooks"] == []


def test_all_success_across_one_active_webhook_is_healthy() -> None:
    payload = _build(
        subscriptions=[_subscription(7)],
        deliveries=[
            _delivery(1, 7, status="SUCCESS"),
            _delivery(2, 7, status="SUCCESS"),
        ],
    )

    assert payload["webhook_count"] == 1
    assert payload["active_webhook_count"] == 1
    assert payload["total_deliveries"] == 2
    assert payload["success_count"] == 2
    assert payload["failed_count"] == 0
    assert payload["success_rate"] == 1.0
    assert payload["health_label"] == HEALTH_HEALTHY
    assert payload["webhooks"][0]["health_label"] == HEALTH_HEALTHY
    assert payload["webhooks"][0]["last_delivery_status"] == "SUCCESS"
    assert payload["webhooks"][0]["last_delivery_error"] is None


def test_disabled_webhooks_do_not_drag_overall_health() -> None:
    payload = _build(
        subscriptions=[
            _subscription(1, status="DISABLED"),
            _subscription(2, status="ACTIVE"),
        ],
        deliveries=[
            _delivery(1, 1, status="FAILED"),
            _delivery(2, 1, status="FAILED"),
            _delivery(3, 2, status="SUCCESS"),
        ],
    )

    assert payload["webhook_count"] == 2
    assert payload["active_webhook_count"] == 1
    # Only the active webhook's deliveries count toward the project verdict.
    assert payload["total_deliveries"] == 1
    assert payload["success_count"] == 1
    assert payload["health_label"] == HEALTH_HEALTHY

    by_id = {item["webhook_id"]: item for item in payload["webhooks"]}
    assert by_id[1]["health_label"] == HEALTH_DOWN
    assert by_id[2]["health_label"] == HEALTH_HEALTHY


def test_success_rate_rolls_up_across_active_webhooks() -> None:
    payload = _build(
        subscriptions=[
            _subscription(1),
            _subscription(2),
        ],
        deliveries=[
            _delivery(1, 1, status="SUCCESS"),
            _delivery(2, 1, status="SUCCESS"),
            _delivery(3, 1, status="SUCCESS"),
            _delivery(4, 2, status="FAILED"),
            _delivery(5, 2, status="FAILED"),
        ],
    )

    assert payload["total_deliveries"] == 5
    assert payload["success_count"] == 3
    assert payload["failed_count"] == 2
    assert payload["success_rate"] == 0.6
    assert payload["health_label"] == HEALTH_DOWN


def test_degraded_boundary_is_preserved() -> None:
    payload = _build(
        subscriptions=[_subscription(7)],
        deliveries=[
            _delivery(1, 7, status="SUCCESS"),
            _delivery(2, 7, status="SUCCESS"),
            _delivery(3, 7, status="SUCCESS"),
            _delivery(4, 7, status="SUCCESS"),
            _delivery(5, 7, status="FAILED"),
        ],
    )

    assert payload["success_rate"] == 0.8
    assert payload["health_label"] == HEALTH_DEGRADED


def test_window_filters_out_older_deliveries() -> None:
    payload = _build(
        subscriptions=[_subscription(7)],
        deliveries=[
            _delivery(1, 7, created_at="2025-12-31T23:59:59+00:00"),
            _delivery(2, 7, created_at="2026-01-01T00:00:00+00:00"),
        ],
    )

    assert payload["total_deliveries"] == 1
    assert payload["success_count"] == 1
    assert payload["webhooks"][0]["total_deliveries"] == 1


def test_zero_days_clamps_to_one_day_window() -> None:
    payload = _build(
        subscriptions=[_subscription(7)],
        deliveries=[_delivery(1, 7, status="SUCCESS")],
        days=0,
    )

    assert payload["window_days"] == 1


def test_malformed_rows_are_skipped() -> None:
    payload = _build(
        subscriptions=[
            _subscription(0),
            _subscription(7),
            "not-a-dict",
        ],
        deliveries=[
            "not-a-dict",
            {"id": 9, "status": "SUCCESS"},  # no timestamp
            _delivery(10, 7, status="SUCCESS"),
        ],
    )

    assert payload["webhook_count"] == 1
    assert payload["total_deliveries"] == 1
    assert payload["success_count"] == 1
    assert payload["health_label"] == HEALTH_HEALTHY


def test_schema_round_trip() -> None:
    payload = _build(
        subscriptions=[_subscription(7)],
        deliveries=[
            _delivery(1, 7, status="SUCCESS"),
            _delivery(2, 7, status="FAILED"),
        ],
    )

    out = ProjectWebhookHealthOut(**payload)
    assert out.project_id == 10
    assert out.window_days == 30
    assert out.health_label == HEALTH_DOWN
    assert len(out.webhooks) == 1
    assert out.webhooks[0].health_label == HEALTH_DOWN
    assert out.webhooks[0].last_delivery_status == "FAILED"
    assert out.webhooks[0].last_delivery_error == (
        "webhook endpoint returned HTTP 500"
    )


def test_project_builder_counts_deliveries_with_delivered_at_only() -> None:
    delivery = _delivery(1, 7, status="SUCCESS")
    delivery["created_at"] = None
    delivery["delivered_at"] = "2026-01-15T00:00:00+00:00"

    payload = _build(
        subscriptions=[_subscription(7)],
        deliveries=[delivery],
    )

    assert payload["total_deliveries"] == 1
    assert payload["success_count"] == 1
    assert payload["webhooks"][0]["total_deliveries"] == 1
    assert payload["health_label"] == HEALTH_HEALTHY


def test_project_verdict_delegates_to_shared_health_label() -> None:
    from app.simulation import project_webhook_health as builder_mod

    with patch.object(
        builder_mod,
        "health_label_for_rate",
        return_value="CUSTOM",
    ) as mock_label:
        payload = _build(
            subscriptions=[_subscription(7)],
            deliveries=[_delivery(1, 7, status="SUCCESS")],
        )

    mock_label.assert_called_once()
    assert payload["health_label"] == "CUSTOM"


class _Subscription:
    def __init__(
        self,
        *,
        id: int,
        project_id: int = 10,
        status: str = "ACTIVE",
    ) -> None:
        self.id = id
        self.project_id = project_id
        self.url = "https://example.com/hooks/cee"
        self.secret = "s3cr3t"
        self.status = status
        self.event_type = "simulation.completed"
        self.last_delivery_at = None
        self.last_delivery_status = None
        self.last_delivery_error = None
        self.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        self.updated_at = self.created_at


class _Delivery:
    def __init__(
        self,
        *,
        id: int,
        webhook_subscription_id: int,
        status: str = "SUCCESS",
    ) -> None:
        self.id = id
        self.webhook_subscription_id = webhook_subscription_id
        self.simulation_id = 11
        self.event_type = "simulation.completed"
        self.status = status
        self.attempt_status = "COMPLETED"
        self.http_status = 200 if status == "SUCCESS" else 500
        self.error = None if status == "SUCCESS" else "boom"
        self.conversion_rate = 0.01
        self.request_body = None
        self.retry_count = 0
        self.delivered_at = datetime(2026, 1, 15, tzinfo=UTC)
        self.created_at = self.delivered_at


class _Query:
    def __init__(self, items: list[object]) -> None:
        self._items = items
        self.filters: list[object] = []

    def filter(self, *args, **kwargs):
        self.filters.extend(args)
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._items)


class _Session:
    def __init__(
        self,
        subscriptions: list[_Subscription],
        deliveries: list[_Delivery],
    ) -> None:
        self.subscriptions = subscriptions
        self.deliveries = deliveries
        self.last_query: _Query | None = None

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "SimulationWebhookSubscription":
            query = _Query(self.subscriptions)
        elif name == "SimulationWebhookDelivery":
            query = _Query(self.deliveries)
        else:
            query = _Query([])
        self.last_query = query
        return query


class _FakeDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return BASE


def _user() -> object:
    return type("U", (), {"id": 42})()


def test_route_composes_all_subscriptions_into_one_payload() -> None:
    from app.api.v1 import simulation_webhooks as mod

    session = _Session(
        subscriptions=[
            _Subscription(id=1),
            _Subscription(id=2, status="DISABLED"),
        ],
        deliveries=[
            _Delivery(id=1, webhook_subscription_id=1, status="SUCCESS"),
            _Delivery(id=2, webhook_subscription_id=2, status="FAILED"),
        ],
    )
    with patch.object(mod, "get_owned_project", return_value=None), patch.object(
        mod,
        "datetime",
        _FakeDatetime,
    ):
        payload = mod.get_project_webhook_health(
            project_id=10,
            days=30,
            db=session,
            current_user=_user(),
        )

    assert isinstance(payload, ProjectWebhookHealthOut)
    assert payload.project_id == 10
    assert payload.webhook_count == 2
    assert payload.active_webhook_count == 1
    assert payload.total_deliveries == 1
    assert payload.health_label == HEALTH_HEALTHY
    assert [item.webhook_id for item in payload.webhooks] == [1, 2]


def test_route_window_filter_includes_delivered_at_fallback() -> None:
    from app.api.v1 import simulation_webhooks as mod

    session = _Session(
        subscriptions=[_Subscription(id=1)],
        deliveries=[_Delivery(id=1, webhook_subscription_id=1)],
    )
    with patch.object(mod, "get_owned_project", return_value=None), patch.object(
        mod,
        "datetime",
        _FakeDatetime,
    ):
        mod.get_project_webhook_health(
            project_id=10,
            days=30,
            db=session,
            current_user=_user(),
        )

    assert session.last_query is not None
    rendered = " ".join(str(expr) for expr in session.last_query.filters)
    assert "created_at" in rendered
    assert "delivered_at" in rendered


def test_route_module_exports_health_endpoint() -> None:
    from app.api.v1 import simulation_webhooks as mod

    assert "get_project_webhook_health" in mod.__all__
