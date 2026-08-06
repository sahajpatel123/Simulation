"""Route-level tests for the /simulations/{id}/anomalies endpoint and cache.
"""
from __future__ import annotations

import sys
import types
import pytest

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def _patch_redis(monkeypatch, fake) -> None:
    from app.core import redis_client

    monkeypatch.setattr(
        redis_client, "get_redis_client", lambda: fake,
    )


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.setex_calls: list[tuple[str, int, str]] = []

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def setex(
        self, key: str, ttl_seconds: int, value: str,
    ) -> None:
        self.setex_calls.append((key, ttl_seconds, value))
        self.store[key] = value


class _FakeSimulation:
    def __init__(self, sim_id: int = 1) -> None:
        self.id = sim_id
        self.project_id = 10
        self.results_json = {
            "stage_conversions": {
                "ARRIVE": 1.0,
                "BROWSE": 0.9,
                "CONSIDER": 0.1,  # spike
            }
        }


class _FakeQuery:
    def __init__(self, items: list = None) -> None:
        self.items = items if items is not None else [_FakeSimulation()]

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None


class _FakeSession:
    def __init__(self, items: list = None) -> None:
        self.items = items

    def query(self, *args, **kwargs):
        return _FakeQuery(self.items)


def _call_route(
    current_user_id: int = 42,
    simulation_id: int = 1,
    session: _FakeSession | None = None,
):
    from app.api.v1 import simulations as sim_mod

    db = session or _FakeSession()
    return sim_mod.get_simulation_anomalies(
        simulation_id=simulation_id,
        outlier_z_threshold=2.0,
        dropoff_spike_threshold=0.75,
        db=db,
        current_user=type("U", (), {"id": current_user_id})(),
    )


def test_simulation_anomalies_caches_payload(monkeypatch) -> None:
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    out1 = _call_route()
    assert out1.anomalies_count >= 1
    assert len(out1.stage_spikes) >= 1
    assert len(fake.setex_calls) == 1
    assert fake.setex_calls[0][1] == 60

    out2 = _call_route()
    assert out2.anomalies_count >= 1
    assert len(fake.setex_calls) == 1  # Cache hit


def test_simulation_anomalies_cache_isolated_per_user(monkeypatch) -> None:
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    _call_route(current_user_id=42)
    _call_route(current_user_id=99)

    assert len(fake.setex_calls) == 2


def test_simulation_anomalies_cache_isolated_per_sim(monkeypatch) -> None:
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    _call_route(simulation_id=1)
    _call_route(simulation_id=2)

    assert len(fake.setex_calls) == 2


def test_simulation_anomalies_noop_when_redis_down(monkeypatch) -> None:
    from app.core import redis_client

    monkeypatch.setattr(redis_client, "get_redis_client", lambda: None)

    for _ in range(2):
        out = _call_route()
        assert out.anomalies_count >= 1
