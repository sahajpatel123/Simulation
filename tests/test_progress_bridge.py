"""Tests for the Redis pub/sub progress bridge (cross-process WebSocket).

In production the Celery worker and the FastAPI process are separate
processes, so ``sync_broadcast`` (worker side) cannot reach WebSocket
clients connected to the API process directly. The bridge publishes
progress payloads to a Redis channel; the API process's subscriber relays
them to local sockets. When Redis is unavailable the legacy same-process
delivery must still work (local dev).
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import redis

from app.core import websocket as ws_module
from app.core.progress_bridge import ProgressBridge


class _FakeWS:
    def __init__(self) -> None:
        self.frames: list[str] = []

    async def send_text(self, text: str) -> None:
        self.frames.append(text)


class _FakePubSub:
    def __init__(self, messages: list[dict]) -> None:
        self.messages = list(messages)
        self.subscribed_channel: str | None = None
        self.closed = False
        self.get_message_calls = 0

    def subscribe(self, channel: str, **kwargs) -> None:
        self.subscribed_channel = channel

    def get_message(self, *args, **kwargs):
        self.get_message_calls += 1
        if self.messages:
            return self.messages.pop(0)
        return None

    def close(self) -> None:
        self.closed = True


class _FakeRedis:
    def __init__(self, messages: list[dict] | None = None) -> None:
        self.pubsub_instance = _FakePubSub(messages or [])
        self.pubsub_calls = 0
        self.published: list[tuple[str, str]] = []
        self.publish_calls = 0

    def pubsub(self) -> _FakePubSub:
        self.pubsub_calls += 1
        return self.pubsub_instance

    def publish(self, channel: str, message: str) -> int:
        self.publish_calls += 1
        self.published.append((channel, message))
        return 1


class _ReconnectingRedis:
    """Redis that is down for the first connect, healthy afterwards."""

    def __init__(self, messages: list[dict]) -> None:
        self.working_pubsub = _FakePubSub(messages)
        self.pubsub_calls = 0

    def pubsub(self) -> _FakePubSub:
        self.pubsub_calls += 1
        if self.pubsub_calls == 1:
            raise redis.exceptions.ConnectionError("redis down")
        return self.working_pubsub


class _FlakyRedis:
    def __init__(self) -> None:
        self.publish_calls = 0

    def publish(self, channel: str, message: str) -> int:
        self.publish_calls += 1
        raise RuntimeError("redis down")


def _progress_payload(**overrides) -> dict:
    payload = {
        "type": "progress",
        "simulation_id": 42,
        "status": "RUNNING",
        "stage": "Loading project data",
        "pct": 5,
        "agents_processed": 0,
        "agents_total": 100,
        "ts": "2026-08-06T00:00:00+00:00",
    }
    payload.update(overrides)
    return payload


class TestSyncBroadcast:
    def test_publishes_payload_and_skips_direct_send_when_bridge_active(
        self, monkeypatch
    ) -> None:
        captured: dict = {}
        monkeypatch.setattr(
            ws_module.progress_bridge,
            "publish_sync",
            lambda payload: captured.update(payload) or True,
        )
        monkeypatch.setattr(ws_module.progress_bridge, "is_running", lambda: True)
        send_mock = AsyncMock(return_value=True)
        monkeypatch.setattr(ws_module.ws_manager, "send_update", send_mock)

        ws_module.sync_broadcast(
            42,
            "RUNNING",
            "Loading project data",
            5,
            0,
            100,
            extra={"conversion_rate": 0.5},
        )

        assert captured["type"] == "progress"
        assert captured["simulation_id"] == 42
        assert captured["status"] == "RUNNING"
        assert captured["stage"] == "Loading project data"
        assert captured["pct"] == 5
        assert captured["agents_total"] == 100
        assert captured["conversion_rate"] == 0.5
        assert captured["ts"].endswith("+00:00") or "+00:00" in captured["ts"]
        send_mock.assert_not_awaited()

    def test_falls_back_to_direct_delivery_without_redis(self, monkeypatch) -> None:
        monkeypatch.setattr(
            ws_module.progress_bridge, "publish_sync", lambda payload: False
        )
        monkeypatch.setattr(ws_module.progress_bridge, "is_running", lambda: False)
        fake_ws = _FakeWS()
        ws_module.ws_manager._connections[42] = fake_ws
        try:
            ws_module.sync_broadcast(42, "RUNNING", "stage", 50)
        finally:
            ws_module.ws_manager._connections.pop(42, None)

        assert len(fake_ws.frames) == 1
        data = json.loads(fake_ws.frames[0])
        assert data["type"] == "progress"
        assert data["simulation_id"] == 42
        assert data["stage"] == "stage"

    def test_direct_sends_when_publish_failed_but_bridge_running(
        self, monkeypatch
    ) -> None:
        """A failed publish must never drop a same-process message — the
        subscriber cannot deliver what Redis never accepted."""
        monkeypatch.setattr(
            ws_module.progress_bridge, "publish_sync", lambda payload: False
        )
        monkeypatch.setattr(ws_module.progress_bridge, "is_running", lambda: True)
        fake_ws = _FakeWS()
        ws_module.ws_manager._connections[7] = fake_ws
        try:
            ws_module.sync_broadcast(7, "RUNNING", "stage", 50)
        finally:
            ws_module.ws_manager._connections.pop(7, None)

        assert len(fake_ws.frames) == 1
        assert json.loads(fake_ws.frames[0])["simulation_id"] == 7


class TestPublishSync:
    def test_returns_false_when_redis_unavailable(self, monkeypatch) -> None:
        from app.core import progress_bridge as pb_module

        bridge = ProgressBridge()
        monkeypatch.setattr(pb_module, "get_redis_client", lambda: None)

        assert bridge.publish_sync(_progress_payload()) is False

    def test_publishes_json_payload_to_channel(self) -> None:
        fake = _FakeRedis()
        bridge = ProgressBridge(client=fake, channel="thecee:simulation-progress")
        payload = _progress_payload()

        assert bridge.publish_sync(payload) is True
        assert fake.published[0][0] == "thecee:simulation-progress"
        assert json.loads(fake.published[0][1]) == payload

    def test_circuit_breaker_skips_repeated_publishes_to_down_redis(self) -> None:
        fake = _FlakyRedis()
        bridge = ProgressBridge(client=fake)

        assert bridge.publish_sync({}) is False
        assert bridge.publish_sync({}) is False
        assert fake.publish_calls == 1

        # After the breaker window expires, a retry is attempted.
        bridge._last_publish_failure = time.monotonic() - 30.0
        assert bridge.publish_sync({}) is False
        assert fake.publish_calls == 2


class TestSubscriberLoop:
    def test_relays_redis_message_to_connection_manager(self, monkeypatch) -> None:
        payload = _progress_payload(simulation_id=7, pct=90)
        fake = _FakeRedis(
            messages=[
                {
                    "type": "message",
                    "channel": "thecee:simulation-progress",
                    "data": json.dumps(payload),
                }
            ]
        )
        bridge = ProgressBridge(client=fake, channel="thecee:simulation-progress")
        delivered = asyncio.Event()

        async def _deliver(sim_id: int, delivered_payload: dict) -> bool:
            assert sim_id == 7
            assert delivered_payload == payload
            delivered.set()
            return True

        send_mock = AsyncMock(return_value=True)
        send_mock.side_effect = _deliver
        monkeypatch.setattr(ws_module.ws_manager, "send_update", send_mock)

        async def _drain() -> None:
            task = asyncio.create_task(bridge._run())
            await asyncio.wait_for(delivered.wait(), timeout=5.0)
            await bridge.stop()
            await asyncio.wait_for(task, timeout=5.0)

        asyncio.run(_drain())

        send_mock.assert_awaited_once()
        sim_id, delivered = send_mock.await_args.args
        assert sim_id == 7
        assert fake.pubsub_instance.subscribed_channel == "thecee:simulation-progress"
        assert fake.pubsub_instance.closed
        assert bridge.is_running() is False

    def test_drops_malformed_messages_without_crashing(self, monkeypatch) -> None:
        fake = _FakeRedis(
            messages=[
                {"type": "message", "data": "not-json"},
                {
                    "type": "message",
                    "data": json.dumps(_progress_payload(simulation_id=3)),
                },
            ]
        )
        bridge = ProgressBridge(client=fake, channel="ch")
        delivered = asyncio.Event()

        async def _deliver(sim_id: int, payload: dict) -> bool:
            delivered.set()
            return True

        send_mock = AsyncMock(side_effect=_deliver)
        monkeypatch.setattr(ws_module.ws_manager, "send_update", send_mock)

        async def _drain() -> None:
            task = asyncio.create_task(bridge._run())
            await asyncio.wait_for(delivered.wait(), timeout=5.0)
            await bridge.stop()
            await asyncio.wait_for(task, timeout=5.0)

        asyncio.run(_drain())

        send_mock.assert_awaited_once()
        assert send_mock.await_args.args[0] == 3

    def test_reconnects_after_connection_failure(self, monkeypatch) -> None:
        """A dropped/absent Redis must not kill the subscriber permanently."""
        from app.core import progress_bridge as pb_module

        payload = _progress_payload(simulation_id=11, pct=60)
        fake = _ReconnectingRedis(
            messages=[
                {
                    "type": "message",
                    "data": json.dumps(payload),
                }
            ]
        )
        bridge = ProgressBridge(client=fake, channel="ch")
        monkeypatch.setattr(pb_module, "RECONNECT_DELAY_SECONDS", 0.02)
        delivered = asyncio.Event()

        async def _deliver(sim_id: int, delivered_payload: dict) -> bool:
            assert sim_id == 11
            assert delivered_payload == payload
            delivered.set()
            return True

        send_mock = AsyncMock(side_effect=_deliver)
        monkeypatch.setattr(ws_module.ws_manager, "send_update", send_mock)

        async def _drain() -> None:
            task = asyncio.create_task(bridge._run())
            await asyncio.wait_for(delivered.wait(), timeout=5.0)
            await bridge.stop()
            await asyncio.wait_for(task, timeout=5.0)

        asyncio.run(_drain())

        assert fake.pubsub_calls == 2
        assert fake.working_pubsub.subscribed_channel == "ch"
        send_mock.assert_awaited_once()
        assert bridge.is_running() is False

    def test_retries_until_stopped_when_redis_unavailable(self, monkeypatch) -> None:
        """While Redis is down the loop stays alive and keeps retrying."""
        from app.core import progress_bridge as pb_module

        bridge = ProgressBridge(client=None, channel="ch")
        monkeypatch.setattr(pb_module, "get_redis_client", lambda: None)
        monkeypatch.setattr(pb_module, "RECONNECT_DELAY_SECONDS", 0.01)

        async def _drain() -> None:
            task = asyncio.create_task(bridge._run())
            await asyncio.sleep(0.05)
            assert not task.done()
            await bridge.stop()
            await asyncio.wait_for(task, timeout=5.0)

        asyncio.run(_drain())

        assert bridge.is_running() is False

    def test_exits_permanently_when_redis_not_configured(self, monkeypatch) -> None:
        """No Redis configured means the bridge is disabled, not retrying."""
        from app.core import progress_bridge as pb_module

        bridge = ProgressBridge(client=None, channel="ch")
        monkeypatch.setattr(pb_module, "get_redis_client", lambda: None)
        monkeypatch.setattr(pb_module.settings, "REDIS_URL", "")

        async def _drain() -> None:
            await asyncio.wait_for(bridge._run(), timeout=5.0)

        asyncio.run(_drain())

        assert bridge.is_running() is False


class TestWiring:
    """Static contract tests pinning the bridge wiring (repo convention)."""

    def test_main_lifespan_starts_and_stops_bridge(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "backend" / "app" / "main.py"
        ).read_text()
        assert "await progress_bridge.ensure_running()" in source
        assert "await progress_bridge.stop()" in source

    def test_ws_route_ensures_bridge_running(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "backend"
            / "app"
            / "api"
            / "v1"
            / "websocket.py"
        ).read_text()
        assert "progress_bridge.ensure_running()" in source

    def test_ws_info_exposes_live_progress(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "backend"
            / "app"
            / "api"
            / "v1"
            / "simulations.py"
        ).read_text()
        assert "live_progress" in source
        assert "progress_bridge.is_running()" in source
