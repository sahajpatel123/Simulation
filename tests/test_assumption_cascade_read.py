"""Tests for the pure assumption-cascade builder
(``app.simulation.assumption_cascade_read``).
"""
from __future__ import annotations

from typing import Any

import pytest
from app.schemas.assumption_cascade import (
    BLOCKER_BLIND_SPOT,
    BLOCKER_DUAL_FAILURE,
    BLOCKER_EXISTENTIAL,
    BLOCKER_NONE,
    TIER_CRITICAL,
    TIER_HIGH,
    TIER_LOW,
    VALID_TIERS,
    VALID_VERDICTS,
    VERDICT_HIGH_RISK,
    VERDICT_INSUFFICIENT,
    VERDICT_STABLE,
    VERDICT_WATCH,
)
from app.simulation.assumption_cascade_read import build_assumption_cascade


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


def _metrics(
    *,
    risk: float = 0.0,
    compound: float = 0.0,
    blind: float = 0.0,
    delta: float = 0.0,
    critical: float = 0.0,
    validated: float = 0.0,
    positive: float = 0.0,
) -> dict[str, float]:
    return {
        "total_cascade_risk": risk,
        "compound_failure_probability": compound,
        "blind_spot_score": blind,
        "primary_failure_domain_delta": delta,
        "critical_assumption_count": critical,
        "validated_assumption_count": validated,
        "positive_cascade_active": positive,
    }


def _conductor(
    specs: dict[str, tuple[dict[str, float], dict[str, bool]]],
) -> dict[str, Any]:
    return {
        cid: {
            "AssumptionCascadeArchitect": {
                "metrics": metrics,
                "flags": flags,
            }
        }
        for cid, (metrics, flags) in specs.items()
    }


def _build(
    *,
    specs: dict[str, tuple[dict[str, float], dict[str, bool]]] | None = None,
    weights: dict[str, float] | None = None,
    conductor_results: dict[str, Any] | None = None,
    registry: list[dict[str, Any]] | None = None,
    product_type: str = "saas",
    signal_quality: float | None = 0.62,
    visible_assumption_count: int | None = 3,
) -> Any:
    specs = specs or {
        "a": (_metrics(risk=0.05), {}),
        "b": (_metrics(risk=0.10), {}),
    }
    weights = weights or {"a": 0.5, "b": 0.5}
    if registry is None:
        registry = [
            _cluster(cid, cid.upper(), weights[cid]) for cid in specs
        ]
    if conductor_results is None:
        conductor_results = _conductor(specs)
    return build_assumption_cascade(
        {"product_type_detected": product_type},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=signal_quality,
        visible_assumption_count=visible_assumption_count,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type,
    )


def test_empty_registry_returns_safe_defaults() -> None:
    out = _build(
        specs={},
        weights={},
        registry=[],
        conductor_results={},
    )

    assert out.simulation_id == 7
    assert out.project_id == 10
    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.verdict in VALID_VERDICTS
    assert out.cluster_profiles == []
    assert out.top_risk_clusters == []
    assert out.meta["total_clusters"] == 0
    assert out.meta["covered_clusters"] == 0
    assert out.meta["covered_weight"] == 0.0
    assert out.meta["product_type_supported"] is True
    assert out.recommendations


def test_low_risk_market_returns_stable_verdict() -> None:
    out = _build(
        specs={
            "a": (_metrics(risk=0.05), {}),
            "b": (_metrics(risk=0.10), {}),
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert out.verdict == VERDICT_STABLE
    assert out.cascade_index == pytest.approx(0.075)
    assert out.low_share == pytest.approx(1.0)
    assert out.elevated_share == 0.0
    assert out.high_share == 0.0
    assert out.critical_share == 0.0
    assert out.primary_blocker == BLOCKER_NONE
    assert out.primary_blocker_share == pytest.approx(1.0)
    assert out.blocker_distribution[BLOCKER_NONE] == pytest.approx(1.0)
    assert len(out.cluster_profiles) == 2
    assert all(p.cascade_tier == TIER_LOW for p in out.cluster_profiles)
    assert out.meta["covered_weight"] == pytest.approx(1.0)
    assert out.recommendations


def test_high_risk_cluster_drives_high_risk_verdict() -> None:
    out = _build(
        specs={
            "a": (
                _metrics(
                    risk=0.75,
                    compound=0.45,
                    blind=0.60,
                    delta=0.20,
                    critical=2.0,
                ),
                {"existential_risk": True},
            ),
        },
        weights={"a": 1.0},
    )

    assert out.verdict == VERDICT_HIGH_RISK
    assert out.cascade_index == pytest.approx(0.75)
    assert out.critical_share == pytest.approx(1.0)
    assert out.primary_blocker == BLOCKER_EXISTENTIAL
    assert out.primary_blocker_share == pytest.approx(1.0)
    assert out.cluster_profiles[0].cascade_tier == TIER_CRITICAL
    assert BLOCKER_EXISTENTIAL in out.cluster_profiles[0].blockers
    assert BLOCKER_DUAL_FAILURE in out.cluster_profiles[0].blockers
    assert BLOCKER_BLIND_SPOT in out.cluster_profiles[0].blockers
    assert "existential_risk_market" in out.flags
    assert "compound_failure_market" in out.flags
    assert "validation_blind_spots_market" in out.flags
    assert out.top_risk_clusters == ["a"]


def test_compound_and_blind_spot_flags_raise_tier_without_high_risk() -> None:
    out = _build(
        specs={
            "a": (
                _metrics(
                    risk=0.25,
                    compound=0.40,
                    blind=0.60,
                ),
                {"dual_failure_risk": True, "blind_spot_detected": True},
            ),
        },
        weights={"a": 1.0},
    )

    assert out.verdict == VERDICT_WATCH
    assert out.cluster_profiles[0].cascade_tier == TIER_HIGH
    assert BLOCKER_DUAL_FAILURE in out.cluster_profiles[0].blockers
    assert BLOCKER_BLIND_SPOT in out.cluster_profiles[0].blockers
    assert out.primary_blocker == BLOCKER_DUAL_FAILURE
    assert "compound_failure_market" in out.flags
    assert "validation_blind_spots_market" in out.flags


def test_missing_architect_metrics_returns_insufficient() -> None:
    out = _build(
        specs={
            "a": ({}, {}),
        },
        weights={"a": 1.0},
    )

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.cluster_profiles == []
    assert out.meta["covered_clusters"] == 0


def test_non_finite_metrics_are_neutral() -> None:
    bad = {
        "total_cascade_risk": float("nan"),
        "compound_failure_probability": float("inf"),
        "blind_spot_score": "not-a-number",
    }
    out = _build(
        specs={"a": (bad, {})},
        weights={"a": 1.0},
    )

    assert out.verdict == VERDICT_STABLE
    assert out.cascade_index == 0.0
    assert out.cluster_profiles[0].cascade_tier == TIER_LOW
    assert out.cluster_profiles[0].blockers == []


def test_positive_cascade_share_is_surfaced() -> None:
    out = _build(
        specs={
            "a": (_metrics(risk=0.05, positive=1.0), {}),
            "b": (_metrics(risk=0.05), {}),
        },
        weights={"a": 0.4, "b": 0.6},
    )

    assert out.positive_cascade_share == pytest.approx(0.4)
    assert out.meta["positive_cascade_share"] == pytest.approx(0.4)
    assert "positive_cascade_market" in out.flags
    profile_a = next(
        p for p in out.cluster_profiles if p.cluster_id == "a"
    )
    assert profile_a.positive_cascade_active is True


def test_critical_share_overrides_numerically_lower_verdict() -> None:
    out = _build(
        specs={
            "a": (_metrics(risk=0.10), {}),
            "b": (_metrics(risk=0.65), {"existential_risk": True}),
        },
        weights={"a": 0.6, "b": 0.4},
    )

    assert out.cascade_index == pytest.approx(0.32)
    assert out.verdict == VERDICT_HIGH_RISK
    assert out.critical_share == pytest.approx(0.4)
    assert "critical_segment_concentration" in out.flags


def test_profiles_are_sorted_by_risk_desc() -> None:
    out = _build(
        specs={
            "a": (_metrics(risk=0.10), {}),
            "b": (_metrics(risk=0.45), {}),
        },
        weights={"a": 0.4, "b": 0.6},
    )

    assert out.top_risk_clusters == ["b", "a"]
    assert [p.cluster_id for p in out.cluster_profiles] == ["b", "a"]
    assert [p.cascade_tier for p in out.cluster_profiles] == [
        TIER_HIGH,
        TIER_LOW,
    ]
    assert all(p.cascade_tier in VALID_TIERS for p in out.cluster_profiles)


def test_signal_quality_non_finite_is_stripped_from_meta() -> None:
    out = _build(signal_quality=float("nan"))

    assert out.meta["signal_quality"] is None
    assert out.verdict != VERDICT_INSUFFICIENT


def test_visible_assumption_count_reaches_meta_and_recommendations() -> None:
    out = _build(visible_assumption_count=0)

    assert out.meta["visible_assumptions"] == 0
    assert any("No visible project assumptions" in r for r in out.recommendations)
