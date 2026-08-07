"""Tests for the simulation sustainability-positioning read and route."""
from __future__ import annotations

import functools
import sys
import types
from typing import Any

import pytest
from fastapi import HTTPException

from app.simulation.conductor import Conductor as _RealConductor
from app.simulation.product_type import ProductType
from app.simulation.sustainability_positioning import (
    build_sustainability_positioning,
)


if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


@functools.lru_cache(maxsize=1)
def _real_conductor_result() -> object:
    """One real deterministic conductor run, shared by route tests."""
    conductor = _RealConductor()
    return conductor.run(
        agents=[],
        env_params={
            "average_order_value": 999.0,
            "price_sensitivity": 0.5,
            "market_maturity": 0.3,
            "sustainability_weight": 1.0,
        },
        assumptions=[],
        product_type=ProductType.CONSUMER_HARDWARE,
    )


@functools.lru_cache(maxsize=1)
def _real_saas_conductor_result() -> object:
    """Real saas conductor run for unknown / saas product-type tests."""
    conductor = _RealConductor()
    return conductor.run(
        agents=[],
        env_params={
            "average_order_value": 999.0,
            "price_sensitivity": 0.5,
            "market_maturity": 0.3,
            "sustainability_weight": 1.0,
        },
        assumptions=[],
        product_type=ProductType.SAAS,
    )


class _StubConductor:
    """Route-level stand-in that reuses cached real conductor results."""

    last_run: dict | None = None

    def run(self, agents, env_params, assumptions, product_type=None, **kwargs):
        type(self).last_run = {
            "assumptions": list(assumptions or []),
            "product_type": product_type,
            "sustainability_weight": env_params.get("sustainability_weight")
            if isinstance(env_params, dict)
            else None,
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
    def __init__(
        self,
        sim: object = None,
        assumptions: list | None = None,
    ) -> None:
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
    return sim_mod.get_sustainability_positioning(
        simulation_id=simulation_id,
        db=db,
        current_user=type("U", (), {"id": current_user_id})(),
    )


def _cluster(
    cluster_id: str,
    name: str,
    weight: float = 1.0,
) -> dict[str, Any]:
    return {
        "cluster_id": cluster_id,
        "name": name,
        "population_weight": weight,
    }


def _conductor(
    cid: str,
    *,
    signal: float = 0.8,
    affinity: float = 0.7,
    lift: float = 0.2,
    premium_tolerance: float = 0.7,
    premium_friction: float = 0.1,
    credibility: float = 1.0,
) -> dict[str, Any]:
    return {
        cid: {
            "SustainabilityArchitect": {
                "metrics": {
                    "sustainability_signal": signal,
                    "esg_affinity": affinity,
                    "green_premium_tolerance": premium_tolerance,
                    "conversion_lift": lift,
                    "premium_friction": premium_friction,
                    "claim_credibility": credibility,
                },
                "flags": {
                    "sustainability_positioned": signal > 0.0,
                    "greenwashing_risk": signal > 0.0 and credibility < 1.0,
                    "premium_friction": premium_friction >= 0.55,
                    "strong_esg_affinity": affinity >= 0.65,
                    "low_esg_reach": signal > 0.0 and affinity < 0.40,
                },
            }
        }
    }


# ---------------------------------------------------------------------------
# Pure builder
# ---------------------------------------------------------------------------


def test_build_empty_registry_returns_safe_defaults() -> None:
    out = build_sustainability_positioning(
        results={},
        simulation_id=1,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.6,
        conductor_results={},
        cluster_registry=[],
        product_type="saas",
    )

    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.verdict == "INSUFFICIENT_DATA"
    assert out.positioned is False
    assert out.cluster_profiles == []
    assert out.meta["total_clusters"] == 0
    assert out.recommendations


def test_build_no_sustainability_claims_returns_not_positioned() -> None:
    out = build_sustainability_positioning(
        results={"product_type_detected": "saas"},
        simulation_id=7,
        project_id=11,
        status="COMPLETED",
        signal_quality=0.81,
        conductor_results=_conductor(
            "demo_cluster",
            signal=0.0,
            lift=0.0,
            credibility=0.25,
        ),
        cluster_registry=[_cluster("demo_cluster", "Demo Cluster", 0.03)],
        product_type="saas",
    )

    assert out.verdict == "NOT_POSITIONED"
    assert out.positioned is False
    assert out.response_share == 0.0
    assert out.cluster_profiles[0].tier == "NO_SIGNAL"
    assert any("sustainability claims" in rec.lower() for rec in out.recommendations)


def test_build_evidence_backed_strong_positioning() -> None:
    out = build_sustainability_positioning(
        results={"product_type_detected": "consumer_hardware"},
        simulation_id=2,
        project_id=12,
        status="COMPLETED",
        signal_quality=0.9,
        conductor_results=_conductor("eco_cluster"),
        cluster_registry=[
            _cluster("eco_cluster", "Eco Cluster", 0.5),
            _cluster("other_cluster", "Other Cluster", 0.5),
        ],
        product_type="consumer_hardware",
    )

    assert out.verdict == "STRONG"
    assert out.positioned is True
    assert out.evidence_backed is True
    assert out.response_share == pytest.approx(0.5)
    assert out.weighted_conversion_lift > 0
    assert out.weighted_esg_affinity > 0.5
    assert out.top_opportunities
    assert out.top_opportunities[0].cluster_id == "eco_cluster"
    assert "evidence-backed" in " ".join(out.recommendations).lower()


def test_build_handles_malformed_metrics_deterministically() -> None:
    out = build_sustainability_positioning(
        results={},
        simulation_id=3,
        project_id=13,
        status="COMPLETED",
        signal_quality=None,
        conductor_results={
            "bad_cluster": {
                "SustainabilityArchitect": {
                    "metrics": {
                        "sustainability_signal": "garbage",
                        "esg_affinity": None,
                        "green_premium_tolerance": float("nan"),
                        "conversion_lift": float("inf"),
                        "premium_friction": False,
                        "claim_credibility": {},
                    },
                    "flags": {},
                }
            }
        },
        cluster_registry=[_cluster("bad_cluster", "Bad Cluster", 0.5)],
        product_type="saas",
    )

    assert out.verdict == "NOT_POSITIONED"
    assert out.positioned is False
    assert out.response_share == 0.0
    profile = out.cluster_profiles[0]
    assert profile.sustainability_signal == 0.0
    assert profile.esg_affinity == pytest.approx(0.5)
    assert profile.conversion_lift == 0.0
    assert profile.premium_friction == 0.0


def test_build_handles_non_finite_signal_quality() -> None:
    out = build_sustainability_positioning(
        results={"product_type_detected": "consumer_hardware"},
        simulation_id=4,
        project_id=14,
        status="COMPLETED",
        signal_quality=float("nan"),
        conductor_results=_conductor("eco_cluster"),
        cluster_registry=[_cluster("eco_cluster", "Eco Cluster", 1.0)],
        product_type="consumer_hardware",
    )

    assert out.meta["signal_quality"] is None
    assert out.verdict == "STRONG"


def test_build_clamps_out_of_range_signal_quality() -> None:
    out = build_sustainability_positioning(
        results={"product_type_detected": "consumer_hardware"},
        simulation_id=5,
        project_id=15,
        status="COMPLETED",
        signal_quality=2.0,
        conductor_results=_conductor("eco_cluster"),
        cluster_registry=[_cluster("eco_cluster", "Eco Cluster", 1.0)],
        product_type="consumer_hardware",
    )

    assert out.meta["signal_quality"] == 1.0


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


def test_completed_simulation_returns_sustainability_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = _call_route(monkeypatch=monkeypatch)

    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.product_type == "consumer_hardware"
    assert out.verdict in {
        "STRONG",
        "MODERATE",
        "WEAK",
        "NOT_POSITIONED",
        "INSUFFICIENT_DATA",
    }
    assert out.meta["product_type_supported"] is True
    assert len(out.cluster_profiles) >= 50
    assert out.meta["total_clusters"] >= 50
    assert out.meta["covered_weight"] > 0.9
    assert out.recommendations


def test_unknown_product_type_falls_back_to_saas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(
        _FakeSimulation(
            results={
                "population_weighted_conversion": 0.04,
                "product_type_detected": "unknown_future_type",
            }
        )
    )
    out = _call_route(session=session, monkeypatch=monkeypatch)

    assert out.product_type == "saas"
    assert len(out.cluster_profiles) >= 50
    assert out.recommendations


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


def test_route_handles_malformed_signal_quality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(
        sim=_FakeSimulation(signal_quality="not-a-number")
    )
    out = _call_route(session=session, monkeypatch=monkeypatch)

    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.meta["signal_quality"] is None
    assert len(out.cluster_profiles) >= 50
