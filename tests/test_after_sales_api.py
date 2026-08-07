"""Route-level tests for the /simulations/{id}/after-sales endpoint."""
from __future__ import annotations

import functools
import sys
import types

import pytest
from fastapi import HTTPException

from app.simulation.conductor import Conductor as _RealConductor
from app.simulation.product_type import ProductType


if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


@functools.lru_cache(maxsize=1)
def _real_conductor_result() -> object:
    """One real deterministic consumer_hardware conductor run, shared
    by all route tests that exercise the after-sales stack."""
    conductor = _RealConductor()
    return conductor.run(
        agents=[],
        env_params={
            "average_order_value": 999.0,
            "price_sensitivity": 0.5,
            "market_maturity": 0.3,
        },
        assumptions=[{"text": "durable device with premium support"}],
        product_type=ProductType.CONSUMER_HARDWARE,
    )


@functools.lru_cache(maxsize=1)
def _real_saas_conductor_result() -> object:
    """One real deterministic saas conductor run (no
    AftersalesLifecycleArchitect metrics), used for unknown /
    non-hardware product-type fallback."""
    conductor = _RealConductor()
    return conductor.run(
        agents=[],
        env_params={
            "average_order_value": 999.0,
            "price_sensitivity": 0.5,
            "market_maturity": 0.3,
        },
        assumptions=[],
        product_type=ProductType.SAAS,
    )


class _StubConductor:
    """Route-level stand-in that reuses the cached real conductor result."""

    last_run: dict | None = None

    def run(self, agents, env_params, assumptions, product_type=None, **kwargs):
        type(self).last_run = {
            "assumptions": list(assumptions or []),
            "product_type": product_type,
        }
        if product_type is ProductType.SAAS:
            return _real_saas_conductor_result()
        return _real_conductor_result()


class _FakeEnvironment:
    def __init__(self) -> None:
        self.average_order_value = 999.0
        self.price_sensitivity = 0.5
        self.market_maturity = 0.3


class _FakeAssumption:
    def __init__(
        self,
        text: str,
        *,
        sensitivity: str = "MEDIUM",
        impact_score: float = 5.0,
    ) -> None:
        self.text = text
        self.sensitivity = sensitivity
        self.impact_score = impact_score


class _FakeSimulation:
    def __init__(
        self,
        sim_id: int = 1,
        *,
        status: str = "COMPLETED",
        results: dict | None = None,
        error_message: str | None = None,
        signal_quality: float | str | None = 0.62,
    ) -> None:
        self.id = sim_id
        self.project_id = 10
        self.environment_id = 5
        self.status = status
        self.error_message = error_message
        self.signal_quality = signal_quality
        self.results_json = (
            results
            if results is not None
            else {
                "population_weighted_conversion": 0.04,
                "product_type_detected": "consumer_hardware",
                "cluster_breakdown": {
                    "metro_power_professional": 0.06,
                    "tier3_first_time_app_user": 0.03,
                },
            }
        )


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else [_FakeSimulation()]

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return list(self.items)


class _FakeSession:
    def __init__(self, sim: object = None, assumptions: list | None = None) -> None:
        self.sim = sim
        self.assumptions = assumptions

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Simulation":
            return _FakeQuery([self.sim] if self.sim is not None else [])
        if name == "Environment":
            return _FakeQuery([_FakeEnvironment()])
        if name == "Assumption":
            return _FakeQuery(self.assumptions or [])
        return _FakeQuery([])


def _call_route(
    *,
    simulation_id: int = 1,
    current_user_id: int = 42,
    session: _FakeSession | None = None,
    monkeypatch: pytest.MonkeyPatch | None = None,
):
    from app.api.v1 import simulations as sim_mod

    if monkeypatch is not None:
        monkeypatch.setattr(sim_mod, "Conductor", _StubConductor)
    db = session if session is not None else _FakeSession(_FakeSimulation())
    return sim_mod.get_after_sales(
        simulation_id=simulation_id,
        db=db,
        current_user=type("U", (), {"id": current_user_id})(),
    )


def test_completed_simulation_returns_after_sales_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = _call_route(monkeypatch=monkeypatch)

    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.product_type == "consumer_hardware"
    assert out.verdict in {
        "HEALTHY",
        "WATCH",
        "STRAINED",
        "AT_RISK",
        "INSUFFICIENT_DATA",
    }
    assert out.verdict != "INSUFFICIENT_DATA"
    assert 0.0 <= out.after_sales_index <= 1.0
    assert len(out.cluster_profiles) >= 50
    assert len(out.levers) >= 5
    assert out.recommendations
    assert out.meta["total_clusters"] >= 50
    assert out.meta["covered_clusters"] == out.meta["total_clusters"]
    assert out.meta["covered_weight"] > 0.9
    assert out.meta["product_type_supported"] is True
    assert out.primary_risk in {
        "support_burden",
        "loyalty_gap",
        "warranty_claims",
        "review_risk",
        "spare_parts",
        "lifespan_risk",
    }
    assert out.meta["visible_assumptions"] == 0


def test_hardware_product_type_is_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(
        _FakeSimulation(
            results={
                "population_weighted_conversion": 0.04,
                "product_type_detected": "iot_hardware",
            }
        )
    )
    out = _call_route(session=session, monkeypatch=monkeypatch)

    assert out.product_type == "iot_hardware"
    assert out.verdict != "INSUFFICIENT_DATA"
    assert out.meta["product_type_supported"] is True


def test_malformed_signal_quality_route_still_returns_safe_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(
        sim=_FakeSimulation(signal_quality="not-a-number")
    )
    out = _call_route(session=session, monkeypatch=monkeypatch)

    assert out.meta["signal_quality"] is None
    assert not any("signal quality is low" in rec for rec in out.recommendations)


def test_failed_simulation_raises_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(
        sim=_FakeSimulation(status="FAILED", error_message="boom")
    )
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session, monkeypatch=monkeypatch)
    assert exc.value.status_code == 422
    assert "boom" in exc.value.detail


def test_pending_simulation_raises_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(sim=_FakeSimulation(status="PENDING"))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session, monkeypatch=monkeypatch)
    assert exc.value.status_code == 409


def test_empty_results_raises_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(sim=_FakeSimulation(results={}))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session, monkeypatch=monkeypatch)
    assert exc.value.status_code == 422


def test_missing_simulation_raises_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(sim=None)
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session, monkeypatch=monkeypatch)
    assert exc.value.status_code == 404


def test_route_feeds_project_assumptions_into_conductor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(
        _FakeSimulation(),
        assumptions=[
            _FakeAssumption("durable device with premium support"),
        ],
    )

    out = _call_route(session=session, monkeypatch=monkeypatch)

    run = _StubConductor.last_run
    assert run is not None
    assert any("durable device" in a["text"] for a in run["assumptions"])
    assert run["product_type"].value == "consumer_hardware"
    assert out.meta["product_type_supported"] is True


def test_unknown_product_type_falls_back_to_saas_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(
        _FakeSimulation(
            results={
                "population_weighted_conversion": 0.04,
                "product_type_detected": "quantum_gadget",
            }
        )
    )

    out = _call_route(session=session, monkeypatch=monkeypatch)

    assert out.product_type == "saas"
    assert out.verdict == "INSUFFICIENT_DATA"
    assert out.meta["product_type_supported"] is False
