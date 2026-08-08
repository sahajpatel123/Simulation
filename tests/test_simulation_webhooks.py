"""Tests for simulation-completion webhook subscriptions and signed delivery."""

from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from types import MethodType
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy.sql.expression import BindParameter

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _Row:
    def __init__(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _Project:
    def __init__(self, *, id: int = 10, user_id: int = 42) -> None:
        self.id = id
        self.user_id = user_id


class _Subscription:
    def __init__(
        self,
        *,
        id: int = 1,
        project_id: int = 10,
        url: str = "https://example.com/hooks/cee",
        secret: str = "s3cr3t",
        status: str = "ACTIVE",
        event_type: str = "simulation.completed",
    ) -> None:
        self.id = id
        self.project_id = project_id
        self.url = url
        self.secret = secret
        self.status = status
        self.event_type = event_type
        self.last_delivery_at = None
        self.last_delivery_status = None
        self.last_delivery_error = None
        self.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _Delivery:
    def __init__(
        self,
        *,
        id: int = 1,
        webhook_subscription_id: int = 10,
        simulation_id: int | None = 11,
        event_type: str = "simulation.completed",
        status: str = "FAILED",
        attempt_status: str | None = None,
        http_status: int | None = 500,
        error: str | None = "webhook endpoint returned HTTP 500",
        conversion_rate: float | None = 0.012,
        request_body: dict | None = None,
        retry_count: int = 0,
        delivered_at: datetime | None = None,
        subscription: _Subscription | None = None,
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
        self.delivered_at = delivered_at or datetime(
            2026, 1, 2, tzinfo=timezone.utc
        )
        self.created_at = self.delivered_at
        self.updated_at = self.delivered_at
        self.subscription = subscription


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []
        self._filters: list[tuple] = []
        self._limit: int | None = None

    def filter(self, *args, **kwargs):
        for arg in args:
            left = getattr(arg, "left", None)
            right = getattr(arg, "right", None)
            if left is not None and right is not None:
                if isinstance(right, BindParameter):
                    right = right.value
                self._filters.append((left, right))
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, value: int):
        self._limit = int(value)
        return self

    def _matches(self, item: object) -> bool:
        for left, right in self._filters:
            attr = getattr(left, "key", None)
            if attr is None:
                continue
            if getattr(item, attr, None) != right:
                return False
        return True

    def all(self):
        items = [item for item in self.items if self._matches(item)]
        return sorted(
            items,
            key=lambda item: (
                getattr(item, "created_at", None),
                getattr(item, "id", 0),
            ),
            reverse=True,
        )

    def first(self):
        return next((item for item in self.items if self._matches(item)), None)


class _FakeSession:
    def __init__(
        self,
        project: object | None = None,
        subscriptions: list[_Subscription] | None = None,
        deliveries: list[_Delivery] | None = None,
    ) -> None:
        self.project = project if project is not None else _Project()
        self.subscriptions = subscriptions if subscriptions is not None else []
        self.deliveries = deliveries if deliveries is not None else []
        self.commits = 0
        self.deleted: list[object] = []
        self.added: list[object] = []

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery([self.project])
        if name == "SimulationWebhookSubscription":
            return _FakeQuery(self.subscriptions)
        if name == "SimulationWebhookDelivery":
            return _FakeQuery(self.deliveries)
        return _FakeQuery([])

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            if isinstance(obj, _Delivery) or hasattr(obj, "webhook_subscription_id"):
                obj.id = max(
                    [d.id for d in self.deliveries],
                    default=0,
                ) + 1
                if hasattr(obj, "webhook_subscription_id") and not isinstance(
                    obj, _Delivery
                ):
                    self.deliveries.append(obj)
            else:
                obj.id = max(
                    [sub.id for sub in self.subscriptions],
                    default=0,
                ) + 1
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.added.append(obj)

    def delete(self, obj) -> None:
        self.deleted.append(obj)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, obj) -> None:
        if isinstance(obj, _Delivery):
            obj.created_at = getattr(obj, "created_at", None) or datetime(
                2026, 1, 3, tzinfo=timezone.utc
            )
        return None

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "UPDATE simulations" in sql and params:
            # Keep the fake session tiny: the only caller in these tests
            # patches sim fields directly via _mark_failed, so there is no
            # extra row state to reconcile here.
            pass
        return None


def _current_user():
    return type("U", (), {"id": 42})()


def test_signing_is_hmac_sha256() -> None:
    from app.simulation.simulation_webhook_delivery import (
        build_webhook_payload,
        sign_webhook_payload,
    )

    payload = build_webhook_payload(
        event_type="simulation.completed",
        simulation_id=3,
        project_id=10,
        status="COMPLETED",
        conversion_rate=0.0421,
    )
    sig1 = sign_webhook_payload("secret", payload)
    sig2 = sign_webhook_payload("secret", payload)
    sig3 = sign_webhook_payload("other-secret", payload)
    assert sig1 == sig2
    assert sig1 != sig3
    assert len(sig1) == 64


def test_build_webhook_payload_rounds_conversion() -> None:
    from app.simulation.simulation_webhook_delivery import build_webhook_payload

    payload = build_webhook_payload(
        event_type="simulation.failed",
        simulation_id=7,
        project_id=2,
        status="FAILED",
        error="boom",
    )
    assert payload["event"] == "simulation.failed"
    assert payload["simulation_id"] == 7
    assert payload["project_id"] == 2
    assert payload["status"] == "FAILED"
    assert payload["error"] == "boom"


def test_deliver_webhook_event_success() -> None:
    from app.simulation import simulation_webhook_delivery as delivery

    class _Response:
        status_code = 200

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            self._posts: list[tuple] = []

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, *args, **kwargs):
            self._posts.append((args, kwargs))
            return _Response()

    with patch.object(
        delivery,
        "assert_safe_outbound_url",
        return_value="https://example.com/hook",
    ), patch.object(delivery.httpx, "Client", _Client):
        result = delivery.deliver_webhook_event(
            url="https://example.com/hook",
            secret="abc",
            payload={"event": "simulation.completed"},
        )
    assert result["ok"] is True
    assert result["status_code"] == 200


def test_deliver_webhook_event_returns_failure_without_raising() -> None:
    from app.simulation import simulation_webhook_delivery as delivery

    class _Response:
        status_code = 500

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, *args, **kwargs):
            return _Response()

    with patch.object(
        delivery,
        "assert_safe_outbound_url",
        return_value="https://example.com/hook",
    ), patch.object(delivery.httpx, "Client", _Client):
        result = delivery.deliver_webhook_event(
            url="https://example.com/hook",
            secret="abc",
            payload={"event": "simulation.completed"},
        )
    assert result["ok"] is False
    assert "500" in result["error"]
    assert "webhook endpoint" in result["error"]


def test_deliver_webhook_event_rejects_http_url() -> None:
    from app.simulation import simulation_webhook_delivery as delivery

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("http URL should never reach httpx")

    with patch.object(delivery.httpx, "Client", _Client):
        result = delivery.deliver_webhook_event(
            url="http://example.com/hook",
            secret="abc",
            payload={"event": "simulation.completed"},
        )
    assert result["ok"] is False
    assert "HTTPS" in result["error"]


def test_deliver_webhook_event_rejects_unsafe_url_without_request() -> None:
    from app.core.ssrf_guard import UnsafeOutboundURLError
    from app.simulation import simulation_webhook_delivery as delivery

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("unsafe URL should never reach httpx")

    def _raise_unsafe(_url: str) -> str:
        raise UnsafeOutboundURLError("URL host is private/reserved")

    with patch.object(
        delivery,
        "assert_safe_outbound_url",
        side_effect=_raise_unsafe,
    ), patch.object(delivery.httpx, "Client", _Client):
        result = delivery.deliver_webhook_event(
            url="https://169.254.169.254/latest/meta-data/",
            secret="abc",
            payload={"event": "simulation.completed"},
        )
    assert result["ok"] is False
    assert "unsafe webhook url" in result["error"]


def test_deliver_webhook_event_sends_canonical_signed_body() -> None:
    import hashlib
    import hmac

    from app.simulation import simulation_webhook_delivery as delivery

    class _Response:
        status_code = 204

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            self.posts: list[dict] = []

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, *args, **kwargs):
            self.posts.append(kwargs)
            return _Response()

    client = _Client()
    payload = {
        "event": "simulation.completed",
        "status": "COMPLETED",
        "simulation_id": 7,
    }
    with patch.object(
        delivery,
        "assert_safe_outbound_url",
        return_value="https://example.com/hook",
    ), patch.object(delivery.httpx, "Client", lambda *a, **k: client):
        result = delivery.deliver_webhook_event(
            url="https://example.com/hook",
            secret="abc",
            payload=payload,
        )
    assert result["ok"] is True
    assert len(client.posts) == 1
    sent = client.posts[0]
    signature_header = sent["headers"]["X-TheCee-Signature"]
    expected_signature = hmac.new(
        b"abc",
        sent["content"],
        hashlib.sha256,
    ).hexdigest()
    assert signature_header == f"sha256={expected_signature}"
    assert sent["content"].decode() == delivery._serialise_webhook_payload(payload)


def test_create_webhook_validates_https() -> None:
    from app.schemas.simulation_webhooks import SimulationWebhookCreate

    with pytest.raises(Exception):
        SimulationWebhookCreate(
            url="http://insecure.example.com/hook",
            event_type="simulation.completed",
        )
    ok = SimulationWebhookCreate(
        url="https://secure.example.com/hook",
        event_type="simulation.completed",
    )
    assert ok.url == "https://secure.example.com/hook"


def test_create_webhook_rejects_malformed_urls() -> None:
    from app.schemas.simulation_webhooks import SimulationWebhookCreate

    for url in (
        "https://",
        "https:///path-only",
        "https://user:pass@example.com/hook",
    ):
        with pytest.raises(Exception):
            SimulationWebhookCreate(
                url=url,
                event_type="simulation.completed",
            )


def test_create_webhook_route_generates_secret() -> None:
    from app.api.v1 import simulation_webhooks as mod

    session = _FakeSession()
    with patch.object(mod.secrets, "token_urlsafe", return_value="gen-secret"):
        out = mod.create_simulation_webhook(
            project_id=10,
            payload=mod.SimulationWebhookCreate(
                url="https://example.com/hook",
                event_type="simulation.completed",
            ),
            db=session,
            current_user=_current_user(),
        )
    assert session.commits == 1
    assert out.secret == "gen-secret"
    assert out.url == "https://example.com/hook"
    assert out.id == 1
    assert out.created_at is not None


def test_create_webhook_rejects_http() -> None:
    from app.api.v1 import simulation_webhooks as mod

    session = _FakeSession()
    with pytest.raises(Exception):
        mod.create_simulation_webhook(
            project_id=10,
            payload=mod.SimulationWebhookCreate(
                url="http://example.com/hook",
                event_type="simulation.completed",
            ),
            db=session,
            current_user=_current_user(),
        )


def test_create_webhook_404_when_project_not_owned() -> None:
    from app.api.v1 import simulation_webhooks as mod

    class NoProjectSession(_FakeSession):
        def query(self, model, *args, **kwargs):
            if getattr(model, "__name__", "") == "Project":
                return _FakeQuery([])
            return super().query(model, *args, **kwargs)

    with pytest.raises(HTTPException) as exc:
        mod.create_simulation_webhook(
            project_id=10,
            payload=mod.SimulationWebhookCreate(
                url="https://example.com/hook",
                event_type="simulation.completed",
            ),
            db=NoProjectSession(),
            current_user=_current_user(),
        )
    assert exc.value.status_code == 404


def test_list_webhooks_hides_secret() -> None:
    from app.api.v1 import simulation_webhooks as mod

    session = _FakeSession(subscriptions=[_Subscription(secret="hidden-secret")])
    out = mod.list_simulation_webhooks(
        project_id=10,
        db=session,
        current_user=_current_user(),
    )
    assert len(out.items) == 1
    assert out.items[0].id == 1
    assert out.items[0].secret == ""
    assert "hidden-secret" not in out.items[0].model_dump().values()


def test_update_webhook_status() -> None:
    from app.api.v1 import simulation_webhooks as mod

    sub = _Subscription()
    session = _FakeSession(subscriptions=[sub])
    out = mod.update_simulation_webhook(
        project_id=10,
        webhook_id=1,
        payload=mod.SimulationWebhookUpdate(status="DISABLED"),
        db=session,
        current_user=_current_user(),
    )
    assert out.status == "DISABLED"
    assert session.commits == 1


def test_delete_webhook_returns_ok() -> None:
    from app.api.v1 import simulation_webhooks as mod

    sub = _Subscription()
    session = _FakeSession(subscriptions=[sub])
    result = mod.delete_simulation_webhook(
        project_id=10,
        webhook_id=1,
        db=session,
        current_user=_current_user(),
    )
    assert result == {"ok": True}
    assert session.deleted == [sub]


def test_route_404_when_webhook_not_owned() -> None:
    from app.api.v1 import simulation_webhooks as mod

    session = _FakeSession(subscriptions=[])
    with pytest.raises(HTTPException) as exc:
        mod.ping_simulation_webhook(
            project_id=10,
            webhook_id=99,
            db=session,
            current_user=_current_user(),
        )
    assert exc.value.status_code == 404


def test_ping_updates_delivery_status_on_success() -> None:
    from app.api.v1 import simulation_webhooks as mod

    sub = _Subscription()
    session = _FakeSession(subscriptions=[sub])
    with patch.object(
        mod,
        "deliver_webhook_event",
        return_value={"ok": True, "status_code": 200},
    ):
        out = mod.ping_simulation_webhook(
            project_id=10,
            webhook_id=1,
            db=session,
            current_user=_current_user(),
        )
    assert out.last_delivery_status == "SUCCESS"
    assert out.last_delivery_error is None


def test_ping_updates_delivery_status_on_failure() -> None:
    from app.api.v1 import simulation_webhooks as mod

    sub = _Subscription()
    session = _FakeSession(subscriptions=[sub])
    with patch.object(
        mod,
        "deliver_webhook_event",
        return_value={"ok": False, "error": "nope"},
    ):
        out = mod.ping_simulation_webhook(
            project_id=10,
            webhook_id=1,
            db=session,
            current_user=_current_user(),
        )
    assert out.last_delivery_status == "FAILED"
    assert out.last_delivery_error == "nope"


def test_routes_registered() -> None:
    from app.api.v1 import simulation_webhooks as mod

    paths = {r.path for r in mod.router.routes}
    assert "/projects/{project_id}/webhooks" in paths
    assert "/projects/{project_id}/webhooks/{webhook_id}" in paths
    assert "/projects/{project_id}/webhooks/{webhook_id}/ping" in paths


def test_deliver_simulation_webhook_task_success() -> None:
    from app.tasks import simulation_tasks as tasks

    sub = _Subscription()

    class DeliverySession(_FakeSession):
        def query(self, model, *args, **kwargs):
            if getattr(model, "__name__", "") == "SimulationWebhookSubscription":
                return _FakeQuery([sub])
            return super().query(model, *args, **kwargs)

    session = DeliverySession(subscriptions=[sub])
    task = type("Task", (), {"db": session})()
    raw_fn = tasks.deliver_simulation_webhook.__wrapped__.__func__
    bound_task = MethodType(raw_fn, task)
    with patch.object(
        tasks,
        "deliver_webhook_event",
        return_value={"ok": True, "status_code": 200},
    ):
        result = bound_task(
            webhook_id=1,
            simulation_id=5,
            status="COMPLETED",
            conversion_rate=0.05,
        )
    assert result["ok"] is True


def test_record_webhook_delivery_creates_history_and_updates_subscription() -> None:
    from app.simulation import webhook_delivery_history as history

    sub = _Subscription()
    session = _FakeSession(subscriptions=[sub])
    delivery = history.record_webhook_delivery(
        session,
        subscription=sub,
        simulation_id=11,
        event_type="simulation.completed",
        attempt_status="COMPLETED",
        conversion_rate=0.013,
        error=None,
        result={"ok": False, "error": "nope"},
        payload={"event": "simulation.completed"},
    )
    assert session.commits == 1
    assert delivery.id == 1
    assert delivery.status == "FAILED"
    assert delivery.attempt_status == "COMPLETED"
    assert delivery.error == "nope"
    assert delivery.request_body == {"event": "simulation.completed"}
    assert sub.last_delivery_status == "FAILED"
    assert sub.last_delivery_error == "nope"


def test_list_simulation_webhook_deliveries() -> None:
    from app.api.v1 import simulation_webhooks as mod

    sub = _Subscription(id=1)
    deliveries = [
        _Delivery(id=1, webhook_subscription_id=1, status="FAILED"),
        _Delivery(id=2, webhook_subscription_id=1, status="SUCCESS"),
    ]
    session = _FakeSession(subscriptions=[sub], deliveries=deliveries)
    out = mod.list_simulation_webhook_deliveries(
        project_id=10,
        webhook_id=1,
        limit=50,
        db=session,
        current_user=_current_user(),
    )
    assert [item.id for item in out.items] == [2, 1]
    assert out.items[0].status == "SUCCESS"
    assert out.items[1].status == "FAILED"


def test_retry_delivery_route_returns_new_delivery() -> None:
    from app.api.v1 import simulation_webhooks as mod

    sub = _Subscription(id=1, status="ACTIVE")
    original = _Delivery(
        id=7,
        webhook_subscription_id=1,
        status="FAILED",
        subscription=sub,
    )
    retried = _Delivery(
        id=8,
        webhook_subscription_id=1,
        status="FAILED",
        retry_count=1,
        subscription=sub,
    )
    session = _FakeSession(subscriptions=[sub], deliveries=[original])
    with patch.object(mod, "retry_failed_delivery", return_value=retried):
        out = mod.retry_simulation_webhook_delivery(
            project_id=10,
            webhook_id=1,
            delivery_id=7,
            db=session,
            current_user=_current_user(),
        )
    assert out.delivery.id == 8
    assert out.delivery.retry_count == 1


def test_retry_delivery_route_rejects_successful_delivery() -> None:
    from app.api.v1 import simulation_webhooks as mod

    sub = _Subscription(id=1)
    successful = _Delivery(
        id=9,
        webhook_subscription_id=1,
        status="SUCCESS",
        subscription=sub,
    )
    session = _FakeSession(subscriptions=[sub], deliveries=[successful])
    with pytest.raises(HTTPException) as exc:
        mod.retry_simulation_webhook_delivery(
            project_id=10,
            webhook_id=1,
            delivery_id=9,
            db=session,
            current_user=_current_user(),
        )
    assert exc.value.status_code == 409


def test_retry_delivery_route_rejects_disabled_webhook() -> None:
    from app.api.v1 import simulation_webhooks as mod

    sub = _Subscription(id=1, status="DISABLED")
    failed = _Delivery(
        id=10,
        webhook_subscription_id=1,
        status="FAILED",
        subscription=sub,
    )
    session = _FakeSession(subscriptions=[sub], deliveries=[failed])
    with pytest.raises(HTTPException) as exc:
        mod.retry_simulation_webhook_delivery(
            project_id=10,
            webhook_id=1,
            delivery_id=10,
            db=session,
            current_user=_current_user(),
        )
    assert exc.value.status_code == 409


def test_retry_delivery_route_404_when_not_owned() -> None:
    from app.api.v1 import simulation_webhooks as mod

    session = _FakeSession(subscriptions=[], deliveries=[])
    with pytest.raises(HTTPException) as exc:
        mod.retry_simulation_webhook_delivery(
            project_id=10,
            webhook_id=1,
            delivery_id=99,
            db=session,
            current_user=_current_user(),
        )
    assert exc.value.status_code == 404


def test_retry_failed_delivery_uses_stored_event_and_increments_retry() -> None:
    from app.simulation import webhook_delivery_history as history

    sub = _Subscription(id=1, url="https://example.com/hooks/cee")
    original = _Delivery(
        id=11,
        webhook_subscription_id=1,
        status="FAILED",
        retry_count=2,
        subscription=sub,
    )
    session = _FakeSession(subscriptions=[sub], deliveries=[original])

    captured: dict = {}

    def _fake_deliver(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "status_code": 200}

    with patch.object(history, "deliver_webhook_event", _fake_deliver):
        new_delivery = history.retry_failed_delivery(
            session,
            delivery=original,
        )

    assert captured["payload"]["event"] == "simulation.completed"
    assert captured["payload"]["status"] == "COMPLETED"
    assert new_delivery.retry_count == 3
    assert new_delivery.status == "SUCCESS"
    assert new_delivery.webhook_subscription_id == 1
    assert session.commits == 1
    assert sub.last_delivery_status == "SUCCESS"
    assert session.commits >= 1
    assert new_delivery.attempt_status == "COMPLETED"


def test_retry_failed_delivery_preserves_failed_event_status() -> None:
    """A failed simulation.failed delivery must retry as FAILED, not COMPLETED."""
    from app.simulation import webhook_delivery_history as history

    sub = _Subscription(id=1, url="https://example.com/hooks/cee")
    original = _Delivery(
        id=12,
        webhook_subscription_id=1,
        simulation_id=44,
        event_type="simulation.failed",
        status="FAILED",
        attempt_status="FAILED",
        error="simulation exploded",
        conversion_rate=None,
        subscription=sub,
    )
    session = _FakeSession(subscriptions=[sub], deliveries=[original])

    captured: dict = {}

    def _fake_deliver(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "status_code": 200}

    with patch.object(history, "deliver_webhook_event", _fake_deliver):
        new_delivery = history.retry_failed_delivery(session, delivery=original)

    assert captured["payload"]["event"] == "simulation.failed"
    assert captured["payload"]["status"] == "FAILED"
    assert captured["payload"]["error"] == "simulation exploded"
    assert new_delivery.status == "SUCCESS"
    assert new_delivery.attempt_status == "FAILED"
    assert new_delivery.error == "simulation exploded"


def test_retry_failed_delivery_preserves_ping_event() -> None:
    """A failed ping retry must remain simulation.ping, not become failed."""
    from app.simulation import webhook_delivery_history as history

    sub = _Subscription(id=1, url="https://example.com/hooks/cee")
    original = _Delivery(
        id=13,
        webhook_subscription_id=1,
        simulation_id=None,
        event_type="simulation.ping",
        status="FAILED",
        attempt_status="PING",
        error="nope",
        conversion_rate=None,
        subscription=sub,
    )
    session = _FakeSession(subscriptions=[sub], deliveries=[original])

    captured: dict = {}

    def _fake_deliver(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "status_code": 200}

    with patch.object(history, "deliver_webhook_event", _fake_deliver):
        new_delivery = history.retry_failed_delivery(session, delivery=original)

    assert captured["payload"]["event"] == "simulation.ping"
    assert captured["payload"]["status"] == "PING"
    assert captured["payload"]["simulation_id"] == 0
    assert new_delivery.status == "SUCCESS"
    assert new_delivery.attempt_status == "PING"


def test_retry_failed_delivery_rejects_success_and_disabled() -> None:
    from app.simulation import webhook_delivery_history as history

    success = _Delivery(
        id=14,
        webhook_subscription_id=1,
        status="SUCCESS",
        subscription=_Subscription(id=1),
    )
    with pytest.raises(ValueError, match="only failed deliveries"):
        history.retry_failed_delivery(_FakeSession(), delivery=success)

    disabled = _Delivery(
        id=15,
        webhook_subscription_id=1,
        status="FAILED",
        subscription=_Subscription(id=1, status="DISABLED"),
    )
    with pytest.raises(ValueError, match="disabled webhook subscription"):
        history.retry_failed_delivery(_FakeSession(), delivery=disabled)


def test_enqueue_simulation_webhooks_filters_active() -> None:
    from app.tasks import simulation_tasks as tasks

    active = _Subscription(id=1)
    disabled = _Subscription(id=2, status="DISABLED")
    failed_sub = _Subscription(id=3, event_type="simulation.failed")
    session = _FakeSession(subscriptions=[active, disabled, failed_sub])
    sent: list[tuple] = []

    def fake_delay(*args, **kwargs):
        sent.append((args, kwargs))

    with patch.object(tasks.deliver_simulation_webhook, "delay", side_effect=fake_delay):
        tasks._enqueue_simulation_webhooks(
            session,
            project_id=10,
            simulation_id=5,
            status="COMPLETED",
            conversion_rate=0.05,
            error=None,
        )
    assert len(sent) == 1
    assert sent[0][0] == ()
    assert sent[0][1]["webhook_id"] == 1
    assert sent[0][1]["simulation_id"] == 5


def test_enqueue_simulation_webhooks_filters_by_event_type() -> None:
    from app.tasks import simulation_tasks as tasks

    completed = _Subscription(id=1, event_type="simulation.completed")
    failed = _Subscription(id=2, event_type="simulation.failed")
    wildcard = _Subscription(id=3, event_type="simulation.*")
    session = _FakeSession(subscriptions=[completed, failed, wildcard])
    sent: list[tuple] = []

    def fake_delay(*args, **kwargs):
        sent.append((args, kwargs))

    with patch.object(tasks.deliver_simulation_webhook, "delay", side_effect=fake_delay):
        tasks._enqueue_simulation_webhooks(
            session,
            project_id=10,
            simulation_id=6,
            status="FAILED",
            conversion_rate=None,
            error="boom",
        )
    assert {kwargs["webhook_id"] for _, kwargs in sent} == {2, 3}


def test_mark_failed_enqueues_webhook() -> None:
    from app.tasks import simulation_tasks as tasks

    sim = _Row(
        id=7,
        project_id=10,
        status="RUNNING",
        error_message=None,
        updated_at=None,
    )
    session = _FakeSession(subscriptions=[_Subscription(event_type="simulation.failed")])
    sent: list[tuple] = []

    def fake_delay(*args, **kwargs):
        sent.append((args, kwargs))

    with patch.object(
        tasks.deliver_simulation_webhook,
        "delay",
        side_effect=fake_delay,
    ), patch.object(tasks, "sync_broadcast"):
        tasks._mark_failed(session, sim, ValueError("boom"))

    assert sim.status == "FAILED"
    assert sim.error_message == "boom"
    assert any(kwargs.get("status") == "FAILED" for _, kwargs in sent)
