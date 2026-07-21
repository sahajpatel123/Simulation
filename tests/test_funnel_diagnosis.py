"""
Tests for funnel bottleneck diagnosis helpers and schema contracts
(cycle 27 funnel-bottleneck-diagnosis).
"""
from __future__ import annotations

from typing import Any

import pytest

from app.simulation.funnel_diagnosis import (
    FORWARD_STAGES,
    HEALTHY_DROP_OFF,
    RECOVERY_FRACTION,
    build_funnel_diagnosis,
)


def _results(
    *,
    cr: float = 0.04,
    total: int = 10000,
    stages: list[dict[str, Any]] | None = None,
    breakdown: dict[str, Any] | None = None,
    counts: dict[str, int] | None = None,
    domain: str = "PricingArchitect",
    product_type: str = "saas",
) -> dict[str, Any]:
    converted = int(round(cr * total))
    payload: dict[str, Any] = {
        "population_weighted_conversion": cr,
        "conversion_rate": cr,
        "total_agents": total,
        "converted": converted,
        "primary_failure_domain": domain,
        "product_type_detected": product_type,
        "cluster_breakdown": breakdown
        or {
            "metro_power_professional": 0.08,
            "tier2_price_sensitive_pragmatist": 0.02,
            "anxiety_driven_researcher": 0.01,
        },
    }
    if stages is not None:
        payload["stage_metrics"] = stages
    if counts is not None:
        payload["stage_counts"] = counts
    return payload


def _healthyish_stages() -> list[dict[str, Any]]:
    return [
        {"state": "ARRIVE", "agent_count": 10000, "entry_rate": 1.0, "drop_off_rate": 0.12},
        {"state": "BROWSE", "agent_count": 8700, "entry_rate": 0.87, "drop_off_rate": 0.35},
        {"state": "CONSIDER", "agent_count": 5400, "entry_rate": 0.54, "drop_off_rate": 0.36},
        {"state": "DECIDE", "agent_count": 2500, "entry_rate": 0.25, "drop_off_rate": 0.52},
        {"state": "PURCHASE", "agent_count": 400, "entry_rate": 0.04, "drop_off_rate": 0.0},
        {"state": "ABANDON", "agent_count": 9600, "entry_rate": 0.96, "drop_off_rate": 0.0},
    ]


def _broken_decide_stages() -> list[dict[str, Any]]:
    # DECIDE drop-off far above healthy 0.55 → clear bottleneck.
    return [
        {"state": "ARRIVE", "agent_count": 10000, "entry_rate": 1.0, "drop_off_rate": 0.10},
        {"state": "BROWSE", "agent_count": 9000, "entry_rate": 0.90, "drop_off_rate": 0.30},
        {"state": "CONSIDER", "agent_count": 6300, "entry_rate": 0.63, "drop_off_rate": 0.35},
        {"state": "DECIDE", "agent_count": 2000, "entry_rate": 0.20, "drop_off_rate": 0.82},
        {"state": "PURCHASE", "agent_count": 360, "entry_rate": 0.036, "drop_off_rate": 0.0},
        {"state": "ABANDON", "agent_count": 9640, "entry_rate": 0.964, "drop_off_rate": 0.0},
    ]


# ---------------------------------------------------------------------------
# Empty / malformed inputs
# ---------------------------------------------------------------------------


def test_empty_results_yield_zero_state() -> None:
    out = build_funnel_diagnosis(None, simulation_id=1, project_id=2)
    assert out.simulation_id == 1
    assert out.project_id == 2
    assert out.overall_conversion == 0.0
    assert out.total_agents == 0
    assert out.stages == []
    assert out.primary_bottleneck is None
    assert out.recommendations == []
    assert out.health_score >= 5


def test_json_string_results_are_parsed() -> None:
    import json

    raw = json.dumps(_results(stages=_healthyish_stages()))
    out = build_funnel_diagnosis(raw, simulation_id=9, project_id=3)
    assert out.overall_conversion == 0.04
    assert len(out.stages) >= 4


def test_garbage_string_results_yield_zero_state() -> None:
    out = build_funnel_diagnosis("{not-json", simulation_id=1, project_id=1)
    assert out.stages == []
    assert out.overall_conversion == 0.0


# ---------------------------------------------------------------------------
# Stage diagnosis + bottleneck selection
# ---------------------------------------------------------------------------


def test_primary_bottleneck_is_decide_when_dropoff_spikes() -> None:
    out = build_funnel_diagnosis(
        _results(stages=_broken_decide_stages(), cr=0.036),
        simulation_id=10,
        project_id=4,
    )
    assert out.primary_bottleneck == "DECIDE"
    decide = next(s for s in out.stages if s.stage == "DECIDE")
    assert decide.is_primary_bottleneck is True
    assert decide.severity == "CRITICAL"
    assert decide.delta_from_healthy == pytest.approx(0.82 - 0.55, abs=1e-3)
    assert decide.primary_domain == "PRICING"
    assert "PricingArchitect" in decide.recommended_architects
    assert out.bottleneck_severity == "CRITICAL"


def test_healthy_funnel_has_info_or_warning_not_critical_on_decide() -> None:
    out = build_funnel_diagnosis(
        _results(stages=_healthyish_stages(), cr=0.04),
        simulation_id=11,
        project_id=4,
    )
    decide = next(s for s in out.stages if s.stage == "DECIDE")
    assert decide.severity in {"INFO", "WARNING"}
    assert decide.delta_from_healthy < 0.20


def test_purchase_never_nominated_as_primary_bottleneck() -> None:
    stages = _broken_decide_stages()
    # Inflate PURCHASE drop artificially — still must not win.
    stages = [
        {**s, "drop_off_rate": 0.99} if s["state"] == "PURCHASE" else s for s in stages
    ]
    out = build_funnel_diagnosis(
        _results(stages=stages),
        simulation_id=12,
        project_id=4,
    )
    assert out.primary_bottleneck in FORWARD_STAGES
    assert out.primary_bottleneck != "PURCHASE"


def test_stage_counts_fallback_when_metrics_absent() -> None:
    counts = {
        "ARRIVE": 10000,
        "BROWSE": 8000,
        "CONSIDER": 4000,
        "DECIDE": 1500,
        "PURCHASE": 300,
        "ABANDON": 9700,
        "RETURN": 100,
    }
    out = build_funnel_diagnosis(
        _results(cr=0.03, total=10000, counts=counts),
        simulation_id=13,
        project_id=5,
    )
    assert out.meta["stages_source"] == "stage_counts"
    assert len(out.stages) >= 5
    assert out.primary_bottleneck in FORWARD_STAGES


def test_stage_aggregations_alias_accepted() -> None:
    payload = _results(cr=0.05)
    payload["stage_aggregations"] = [
        {
            "state": "BROWSE",
            "mean_drop_off_rate": 0.70,
            "mean_entry_rate": 0.85,
            "agents": 8500,
        },
        {
            "state": "DECIDE",
            "mean_drop_off_rate": 0.50,
            "mean_entry_rate": 0.20,
            "agents": 2000,
        },
    ]
    out = build_funnel_diagnosis(payload, simulation_id=14, project_id=5)
    assert out.meta["stages_source"] == "stage_aggregations"
    browse = next(s for s in out.stages if s.stage == "BROWSE")
    assert browse.severity == "CRITICAL"
    assert out.primary_bottleneck == "BROWSE"


# ---------------------------------------------------------------------------
# Cluster drag + drop triggers
# ---------------------------------------------------------------------------


def test_cluster_drag_ranks_lowest_converters_highest() -> None:
    out = build_funnel_diagnosis(
        _results(
            stages=_healthyish_stages(),
            breakdown={
                "high_converter": 0.12,
                "mid_converter": 0.05,
                "low_converter": 0.01,
            },
        ),
        simulation_id=20,
        project_id=6,
        cluster_limit=3,
    )
    assert len(out.cluster_drag) == 3
    assert out.cluster_drag[0].cluster_id == "low_converter"
    assert out.cluster_drag[0].lost_conversion_share > out.cluster_drag[-1].lost_conversion_share


def test_cluster_summaries_feed_drop_triggers_and_weights() -> None:
    summaries = [
        {
            "cluster_id": "a",
            "agents_assigned": 5000,
            "agents_converted": 100,
            "conversion_rate": 0.02,
            "primary_drop_trigger": "PricingArchitect",
            "mean_drop_state": "DECIDE",
        },
        {
            "cluster_id": "b",
            "agents_assigned": 5000,
            "agents_converted": 400,
            "conversion_rate": 0.08,
            "primary_drop_trigger": "PricingArchitect",
            "mean_drop_state": "DECIDE",
        },
        {
            "cluster_id": "c",
            "agents_assigned": 2000,
            "agents_converted": 20,
            "conversion_rate": 0.01,
            "primary_drop_trigger": "TrustArchitect",
            "mean_drop_state": "CONSIDER",
        },
    ]
    out = build_funnel_diagnosis(
        _results(
            stages=_broken_decide_stages(),
            breakdown={"a": 0.02, "b": 0.08, "c": 0.01},
        ),
        simulation_id=21,
        project_id=6,
        cluster_summaries=summaries,
    )
    assert out.meta["cluster_summaries_used"] is True
    assert out.drop_triggers
    assert out.drop_triggers[0].trigger == "PricingArchitect"
    assert out.drop_triggers[0].cluster_count == 2
    assert out.drop_triggers[0].agents_affected == 10000
    # Weights should reflect agents_assigned shares (5k/12k, 5k/12k, 2k/12k).
    weights = {c.cluster_id: c.population_weight for c in out.cluster_drag}
    assert weights["a"] == pytest.approx(5000 / 12000, abs=1e-4)
    assert any(c.primary_drop_trigger == "PricingArchitect" for c in out.cluster_drag)


# ---------------------------------------------------------------------------
# Recommendations + recoverable conversion + health score
# ---------------------------------------------------------------------------


def test_recommendations_lead_with_primary_bottleneck() -> None:
    out = build_funnel_diagnosis(
        _results(stages=_broken_decide_stages(), cr=0.036),
        simulation_id=30,
        project_id=7,
    )
    assert out.recommendations
    lead = out.recommendations[0]
    assert lead.priority == 1
    assert lead.stage == "DECIDE"
    assert lead.domain == "PRICING"
    assert lead.estimated_lift > 0
    assert "PricingArchitect" in lead.architects


def test_recoverable_conversion_exceeds_current_when_bottleneck_exists() -> None:
    out = build_funnel_diagnosis(
        _results(stages=_broken_decide_stages(), cr=0.036),
        simulation_id=31,
        project_id=7,
    )
    assert out.recoverable_conversion is not None
    assert out.recoverable_conversion > out.overall_conversion
    assert out.recoverable_conversion <= 0.99


def test_recoverable_equals_current_when_no_excess_drop() -> None:
    # All stages at or below healthy benchmarks.
    stages = [
        {"state": "ARRIVE", "agent_count": 10000, "entry_rate": 1.0, "drop_off_rate": 0.10},
        {"state": "BROWSE", "agent_count": 9000, "entry_rate": 0.90, "drop_off_rate": 0.30},
        {"state": "CONSIDER", "agent_count": 6300, "entry_rate": 0.63, "drop_off_rate": 0.30},
        {"state": "DECIDE", "agent_count": 3000, "entry_rate": 0.30, "drop_off_rate": 0.40},
        {"state": "PURCHASE", "agent_count": 800, "entry_rate": 0.08, "drop_off_rate": 0.0},
    ]
    out = build_funnel_diagnosis(
        _results(stages=stages, cr=0.08),
        simulation_id=32,
        project_id=7,
    )
    # No positive delta → recoverable == current (or None if no primary).
    if out.recoverable_conversion is not None:
        assert out.recoverable_conversion == pytest.approx(0.08, abs=1e-3)


def test_health_score_penalises_critical_bottlenecks() -> None:
    healthy = build_funnel_diagnosis(
        _results(stages=_healthyish_stages(), cr=0.05),
        simulation_id=33,
        project_id=8,
    )
    broken = build_funnel_diagnosis(
        _results(stages=_broken_decide_stages(), cr=0.036),
        simulation_id=34,
        project_id=8,
    )
    assert broken.health_score < healthy.health_score
    assert 5 <= broken.health_score <= 99
    assert 5 <= healthy.health_score <= 99


def test_low_conversion_adds_cluster_retarget_recommendation() -> None:
    out = build_funnel_diagnosis(
        _results(stages=_broken_decide_stages(), cr=0.02),
        simulation_id=35,
        project_id=8,
        cluster_summaries=[
            {
                "cluster_id": "tier2_price_sensitive_pragmatist",
                "agents_assigned": 4000,
                "agents_converted": 40,
                "conversion_rate": 0.01,
                "primary_drop_trigger": "PricingArchitect",
                "mean_drop_state": "DECIDE",
            }
        ],
    )
    titles = [r.title.lower() for r in out.recommendations]
    assert any("re-target" in t or "redesign" in t for t in titles)


# ---------------------------------------------------------------------------
# Schema / constants contracts
# ---------------------------------------------------------------------------


def test_healthy_drop_off_covers_forward_stages() -> None:
    for stage in FORWARD_STAGES:
        assert stage in HEALTHY_DROP_OFF
        assert 0.0 <= HEALTHY_DROP_OFF[stage] <= 1.0


def test_recovery_fraction_is_conservative() -> None:
    assert 0.0 < RECOVERY_FRACTION <= 0.5


def test_schema_round_trip() -> None:
    out = build_funnel_diagnosis(
        _results(stages=_broken_decide_stages()),
        simulation_id=40,
        project_id=9,
        signal_quality=0.72,
    )
    dumped = out.model_dump()
    assert dumped["simulation_id"] == 40
    assert dumped["signal_quality"] == 0.72
    assert isinstance(dumped["stages"], list)
    assert isinstance(dumped["recommendations"], list)
    assert "generated_at" in dumped["meta"]
