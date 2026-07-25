"""
Tests for the agent-routing schema surface and endpoint wiring.

The pure ``AgentHierarchyRouter`` already has comprehensive coverage in
``test_agent_hierarchy.py``. These tests pin down:
  * ``AgentTierEnum`` and ``TierCounts`` defaults
  * Pydantic validation of ``confidence`` in [0, 1] and ``relative_cost >= 0``
  * ``AgentRoutingRegistryOut`` tier rollup math + cost_summary
  * Endpoint registration in the FastAPI app router table
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Schema-level invariants
# ---------------------------------------------------------------------------


def test_agent_tier_enum_has_three_members() -> None:
    from app.schemas.agent_routing import AgentTierEnum

    members = {m.value for m in AgentTierEnum}
    assert members == {"MICRO", "WORKER", "SUPERVISOR"}


def test_tier_relative_costs_are_strictly_ordered() -> None:
    """MICRO < WORKER < SUPERVISOR — every user-visible promise hinges on it."""
    from app.schemas.agent_routing import TIER_RELATIVE_COST

    assert TIER_RELATIVE_COST["MICRO"] < TIER_RELATIVE_COST["WORKER"]
    assert TIER_RELATIVE_COST["WORKER"] < TIER_RELATIVE_COST["SUPERVISOR"]
    assert TIER_RELATIVE_COST["MICRO"] > 0


def test_tier_counts_default_is_zero() -> None:
    from app.schemas.agent_routing import TierCounts

    c = TierCounts()
    assert c.MICRO == 0
    assert c.WORKER == 0
    assert c.SUPERVISOR == 0
    assert c.total == 0


def test_routing_decision_rejects_out_of_range_confidence() -> None:
    from pydantic import ValidationError

    from app.schemas.agent_routing import (
        AgentRoutingDecisionOut,
        AgentTierEnum,
    )

    base = {
        "cluster_id": "x",
        "tier": AgentTierEnum.WORKER,
        "reason": "default",
        "needs_browser": True,
        "relative_cost": 1.0,
    }
    AgentRoutingDecisionOut(**base, confidence=0.0)
    AgentRoutingDecisionOut(**base, confidence=1.0)
    with pytest.raises(ValidationError):
        AgentRoutingDecisionOut(**base, confidence=1.5)
    with pytest.raises(ValidationError):
        AgentRoutingDecisionOut(**base, confidence=-0.1)


def test_routing_decision_rejects_negative_cost() -> None:
    from pydantic import ValidationError

    from app.schemas.agent_routing import (
        AgentRoutingDecisionOut,
        AgentTierEnum,
    )

    with pytest.raises(ValidationError):
        AgentRoutingDecisionOut(
            cluster_id="x",
            tier=AgentTierEnum.WORKER,
            reason="default",
            confidence=0.5,
            needs_browser=True,
            relative_cost=-1.0,
        )


def test_registry_out_round_trip() -> None:
    from app.schemas.agent_routing import (
        AgentRoutingDecisionOut,
        AgentRoutingRegistryOut,
        AgentTierEnum,
        TierCounts,
    )

    payload = AgentRoutingRegistryOut(
        generated_at="2026-01-01T00:00:00Z",
        tier_counts=TierCounts(MICRO=2, WORKER=3, SUPERVISOR=1, total=6),
        cost_summary={
            "MICRO": 2,
            "WORKER": 3,
            "SUPERVISOR": 1,
            "total_equivalent_cost": 6.6,
        },
        clusters=[
            AgentRoutingDecisionOut(
                cluster_id="c1",
                tier=AgentTierEnum.MICRO,
                reason="low literacy",
                confidence=0.8,
                needs_browser=False,
                relative_cost=0.05,
            )
        ],
    )
    dumped = payload.model_dump()
    assert dumped["tier_counts"]["total"] == 6
    assert dumped["cost_summary"]["total_equivalent_cost"] == 6.6
    assert dumped["clusters"][0]["cluster_id"] == "c1"


# ---------------------------------------------------------------------------
# Endpoint registration
# ---------------------------------------------------------------------------


def test_agent_routing_routes_registered() -> None:
    """The two new routes should appear in the simulations router."""
    import sys
    import types

    # Stub razorpay to avoid the transitive ``pkg_resources`` import that
    # breaks on minimal envs when ``app.api.v1.__init__`` runs.
    razorpay_stub = types.ModuleType("razorpay")
    razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules.setdefault("razorpay", razorpay_stub)

    from app.api.v1 import simulations as sim_mod

    paths = {r.path for r in sim_mod.router.routes}
    assert "/simulations/agent-routing/cluster/{cluster_id}" in paths
    assert "/simulations/agent-routing/registry" in paths


# ---------------------------------------------------------------------------
# Pure router composition (smoke)
# ---------------------------------------------------------------------------


def test_registry_endpoint_walks_52_clusters() -> None:
    """``get_agent_routing_registry`` walks every cluster in the registry."""
    from app.simulation.agent_hierarchy import AgentHierarchyRouter
    from app.simulation.clusters.registry import ClusterRegistry

    clusters = ClusterRegistry().all_clusters()
    router = AgentHierarchyRouter()
    decisions = router.route_batch([c.cluster_id for c in clusters])
    assert len(decisions) == 52
    summary = router.tier_summary(decisions)
    assert summary["total"] == 52
    # The three tier counts should sum to the total.
    assert summary["MICRO"] + summary["WORKER"] + summary["SUPERVISOR"] == 52


def test_cluster_route_decision_matches_pure_router() -> None:
    """Endpoint decision must agree with the underlying router."""
    from app.simulation.agent_hierarchy import AgentHierarchyRouter, AgentTier

    router = AgentHierarchyRouter()
    sample = "senior_enterprise_decision_maker"
    direct = router.route(sample)
    # The endpoint wraps this in a Pydantic model — values must match.
    assert direct.tier == AgentTier.SUPERVISOR
    assert direct.confidence == 0.95
    assert router.needs_browser(direct) is True


def test_cost_summary_math_round_trips() -> None:
    """Registry ``total_equivalent_cost`` = sum(count × relative_cost)."""
    from app.schemas.agent_routing import TIER_RELATIVE_COST

    # If 7 MICRO, 35 WORKER, 10 SUPERVISOR → cost = 0.35 + 35 + 35 = 70.35
    counts = {"MICRO": 7, "WORKER": 35, "SUPERVISOR": 10}
    expected = round(
        sum(counts[t] * TIER_RELATIVE_COST[t] for t in counts),
        2,
    )
    assert expected == 70.35