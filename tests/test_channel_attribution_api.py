"""Tests for the simulation channel-attribution read and route."""
from __future__ import annotations

import functools
import sys
import types
from typing import Any

import pytest
from fastapi import HTTPException

from app.simulation.channel_attribution_read import build_channel_attribution
from app.simulation.conductor import Conductor as _RealConductor
from app.simulation.product_type import ProductType

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
    ) -> None:
        self.id = sim_id
        self.project_id = 10
        self.environment_id = 5
        self.status = status
        self.error_message = error_message
        self.signal_quality = 0.62
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
    return sim_mod.get_channel_attribution(
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


def _conductor(cid: str) -> dict[str, Any]:
    return {
        cid: {
            "ViralityArchitect": {"metrics": {
                "word_of_mouth_coefficient": 0.5,
                "organic_referral_trigger_score": 0.1,
                "invite_completion_rate": 0.3,
                "content_virality_rate": 0.1,
                "community_building_participation": 0.2,
                "viral_coefficient": 0.05,
            }},
            "TrustArchitect": {"metrics": {
                "press_mention_lift": 0.1,
                "brand_deficit_multiplier": 0.8,
                "free_trial_as_trust_substitute": 0.3,
            }},
            "MarketTimingArchitect": {"metrics": {
                "category_awareness_score": 0.6,
                "problem_urgency_intensity": 0.5,
            }},
            "CompetitiveDynamicsArchitect": {"metrics": {
                "incumbent_switching_friction": 0.4,
            }},
        }
    }


# ---------------------------------------------------------------------------
# Pure builder
# ---------------------------------------------------------------------------


def test_build_empty_registry_returns_safe_defaults() -> None:
    out = build_channel_attribution(
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
    assert out.cluster_profiles == []
    assert out.market_channel_ranking
    assert out.recommended_channel_mix == {}
    assert out.meta["total_clusters"] == 0
    assert any("viral" in rec.lower() for rec in out.recommendations)


def test_build_single_cluster_returns_profile_and_recommendations() -> None:
    out = build_channel_attribution(
        results={"cluster_breakdown": {"demo_cluster": 0.03}},
        simulation_id=7,
        project_id=11,
        status="COMPLETED",
        signal_quality=0.81,
        conductor_results=_conductor("demo_cluster"),
        cluster_registry=[_cluster("demo_cluster", "Demo Cluster", 0.03)],
        product_type="saas",
    )

    assert len(out.cluster_profiles) == 1
    assert out.cluster_profiles[0].cluster_id == "demo_cluster"
    assert out.cluster_profiles[0].channel_scores
    assert out.market_channel_ranking
    assert out.recommended_channel_mix
    assert out.meta["total_clusters"] == 1
    assert out.meta["covered_weight"] == pytest.approx(0.03)
    assert out.recommendations


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


def test_completed_simulation_returns_channel_attribution_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = _call_route(monkeypatch=monkeypatch)

    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.product_type == "consumer_hardware"
    assert out.highest_roi_channel
    assert out.lowest_cac_channel
    assert out.recommended_channel_mix
    assert len(out.market_channel_ranking) >= 10
    assert len(out.cluster_profiles) >= 50
    assert out.recommendations
    assert out.meta["total_clusters"] >= 50
    assert out.meta["covered_weight"] > 0.9
    assert all(ranking.channel for ranking in out.market_channel_ranking)


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
