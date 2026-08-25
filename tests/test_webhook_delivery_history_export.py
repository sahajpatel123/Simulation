"""Tests for webhook delivery history export helpers and route."""

from __future__ import annotations

import asyncio
import sys
import types
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.simulation.webhook_delivery_history_export import (
    webhook_deliveries_to_csv,
    webhook_deliveries_to_json,
)


def _row(
    *,
    id: int,
    delivered_at: datetime,
    created_at: datetime | None = None,
    request_body: dict | None = None,
) -> dict:
    return {
        "id": id,
        "webhook_subscription_id": 1,
        "simulation_id": 11,
        "event_type": "simulation.completed",
        "status": "FAILED",
        "attempt_status": "COMPLETED",
        "http_status": 500,
        "error": "webhook endpoint returned HTTP 500",
        "conversion_rate": 0.0123,
        "request_body": request_body,
        "retry_count": 1,
        "delivered_at": delivered_at,
        "created_at": created_at or delivered_at,
    }


def test_webhook_deliveries_to_csv_renders_rows_newest_first() -> None:
    older = _row(id=1, delivered_at=datetime(2026, 1, 2, tzinfo=UTC))
    newer = _row(id=2, delivered_at=datetime(2026, 1, 3, tzinfo=UTC))
    csv_text = webhook_deliveries_to_csv(
        [older, newer],
        metadata={
            "generated_at": "2026-01-03T00:00:00+00:00",
            "user_id": 42,
            "project_id": 10,
            "webhook_id": 7,
        },
    )

    assert csv_text.startswith("generated_at,")
    assert "user_id,42" in csv_text
    assert "project_id,10" in csv_text
    assert "webhook_id,7" in csv_text
    assert "id,webhook_subscription_id,simulation_id" in csv_text
    lines = csv_text.strip().splitlines()
    assert "2" in lines[-2]
    assert "1" in lines[-1]


def test_webhook_deliveries_to_csv_sorts_by_created_at_matching_list_order() -> None:
    # delivered_at intentionally disagrees with created_at; the list/JSON
    # export order is created_at desc, so CSV must not silently reorder.
    older = _row(
        id=1,
        delivered_at=datetime(2026, 1, 5, tzinfo=UTC),
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    newer = _row(
        id=2,
        delivered_at=datetime(2026, 1, 1, tzinfo=UTC),
        created_at=datetime(2026, 1, 3, tzinfo=UTC),
    )

    csv_text = webhook_deliveries_to_csv([older, newer])
    lines = csv_text.strip().splitlines()

    assert lines[-2].startswith("2,")
    assert lines[-1].startswith("1,")


def test_webhook_deliveries_to_csv_handles_json_body_and_blanks() -> None:
    row = _row(
        id=3,
        delivered_at=datetime(2026, 1, 4, tzinfo=UTC),
        request_body={"event": "simulation.completed", "simulation_id": 11},
    )
    row["http_status"] = None
    row["error"] = None
    csv_text = webhook_deliveries_to_csv([row])

    assert "simulation.completed" in csv_text
    assert "simulation_id" in csv_text
    assert csv_text.count(",,,") >= 1


def test_webhook_deliveries_to_csv_guards_spreadsheet_formulas() -> None:
    row = _row(id=4, delivered_at=datetime(2026, 1, 5, tzinfo=UTC))
    row["error"] = "=HYPERLINK(\"https://evil.example\")"
    csv_text = webhook_deliveries_to_csv([row])

    assert "'=HYPERLINK" in csv_text


def test_webhook_deliveries_to_csv_guards_formula_after_leading_whitespace() -> None:
    row = _row(id=6, delivered_at=datetime(2026, 1, 7, tzinfo=UTC))
    row["error"] = " \t=2+2"
    csv_text = webhook_deliveries_to_csv([row])

    assert "' \t=2+2" in csv_text


def test_webhook_deliveries_to_json_renders_envelope() -> None:
    row = _row(id=5, delivered_at=datetime(2026, 1, 6, tzinfo=UTC))
    text = webhook_deliveries_to_json([row], metadata={"total": 1})

    assert '"total": 1' in text
    assert '"id": 5' in text
    assert text.endswith("\n")


class _Delivery:
    def __init__(
        self,
        *,
        id: int,
        webhook_subscription_id: int,
        simulation_id: int,
        event_type: str,
        status: str,
        attempt_status: str | None,
        http_status: int | None,
        error: str | None,
        conversion_rate: float | None,
        request_body: dict | None,
        retry_count: int,
        delivered_at: datetime,
        created_at: datetime,
    ) -> None:
        self.id = id
        self.webhook_subscription_id = webhook_subscription_id
        self.simulation_id = simulation_id
        self.event_type = event_type
        self.status = status
        self.attempt_status = attempt_status
        self.http_status = http_status
        self.error = error
        self.conversion_rate = conversion_rate
        self.request_body = request_body
        self.retry_count = retry_count
        self.delivered_at = delivered_at
        self.created_at = created_at


def _delivery(id: int) -> _Delivery:
    dt = datetime(2026, 1, 2, tzinfo=UTC)
    return _Delivery(
        id=id,
        webhook_subscription_id=7,
        simulation_id=11,
        event_type="simulation.completed",
        status="FAILED",
        attempt_status="COMPLETED",
        http_status=500,
        error="boom",
        conversion_rate=0.01,
        request_body={"event": "simulation.completed"},
        retry_count=0,
        delivered_at=dt,
        created_at=dt,
    )


class _Query:
    def __init__(self, items: list[_Delivery]) -> None:
        self._items = items

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, value: int):
        self._items = self._items[: int(value)]
        return self

    def all(self):
        return list(self._items)


class _Session:
    def __init__(self, items: list[_Delivery]) -> None:
        self.items = items

    def query(self, model, *args, **kwargs):
        return _Query(self.items)


def _user() -> object:
    return type("U", (), {"id": 42})()


async def _body_bytes(response: object) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def test_export_route_returns_csv_attachment() -> None:
    from app.api.v1 import simulation_webhooks as mod

    session = _Session([_delivery(2), _delivery(1)])
    with patch.object(
        mod,
        "_get_owned_webhook",
        return_value=type("Webhook", (), {"id": 7})(),
    ):
        response = mod.export_simulation_webhook_deliveries(
            project_id=10,
            webhook_id=7,
            format="csv",
            limit=1000,
            db=session,
            current_user=_user(),
        )
    body = asyncio.run(_body_bytes(response)).decode()

    assert response.media_type == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="webhook-deliveries.csv"'
    )
    assert "webhook_subscription_id,simulation_id" in body
    assert "boom" in body
    assert "webhook-deliveries.csv" in response.headers["content-disposition"]


def test_export_route_returns_json_attachment() -> None:
    from app.api.v1 import simulation_webhooks as mod

    session = _Session([_delivery(1)])
    with patch.object(
        mod,
        "_get_owned_webhook",
        return_value=type("Webhook", (), {"id": 7})(),
    ):
        response = mod.export_simulation_webhook_deliveries(
            project_id=10,
            webhook_id=7,
            format="json",
            limit=100,
            db=session,
            current_user=_user(),
        )
    body = asyncio.run(_body_bytes(response)).decode()

    assert response.media_type == "application/json; charset=utf-8"
    assert "webhook-deliveries.json" in response.headers["content-disposition"]
    assert '"simulation_id": 11' in body


def test_export_route_rejects_unsupported_format() -> None:
    from app.api.v1 import simulation_webhooks as mod

    session = _Session([_delivery(1)])
    with patch.object(
        mod,
        "_get_owned_webhook",
        return_value=type("Webhook", (), {"id": 7})(),
    ):
        with pytest.raises(HTTPException) as exc:
            mod.export_simulation_webhook_deliveries(
                project_id=10,
                webhook_id=7,
                format="xml",
                limit=100,
                db=session,
                current_user=_user(),
            )
    assert exc.value.status_code == 400


def test_export_route_404_when_webhook_not_owned() -> None:
    from app.api.v1 import simulation_webhooks as mod

    def _raise_not_found(*args, **kwargs):
        raise HTTPException(status_code=404, detail="Webhook not found")

    session = _Session([])
    with patch.object(mod, "_get_owned_webhook", side_effect=_raise_not_found):
        with pytest.raises(HTTPException) as exc:
            mod.export_simulation_webhook_deliveries(
                project_id=10,
                webhook_id=99,
                format="csv",
                limit=100,
                db=session,
                current_user=_user(),
            )
    assert exc.value.status_code == 404
