"""
Tests for the assumption-postmortem digest
(pure builder + schema contracts + route registration).
"""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from app.schemas.assumption_postmortem import (
    VERDICT_INSUFFICIENT_DATA,
    VERDICT_INVALIDATED,
    VERDICT_MIXED,
    VERDICT_VALIDATED,
    AssumptionPostmortemOut,
)
from app.simulation.assumption_postmortem import (
    build_assumption_postmortem,
)


def _assumptions() -> list[dict[str, Any]]:
    return [
        {
            "id": 1,
            "text": "Indian SMEs will pay for a monthly SaaS tool.",
            "category": "pricing",
            "sensitivity": "HIGH",
            "impact_score": 8.0,
        },
        {
            "id": 2,
            "text": "Users will install a mobile app.",
            "category": "distribution",
            "sensitivity": "MEDIUM",
            "impact_score": 5.0,
        },
        {
            "id": 3,
            "text": "Referrals will drive 40% of signups.",
            "category": "virality",
            "sensitivity": "CRITICAL",
            "impact_score": 9.0,
        },
    ]


def _results(cr: float = 0.05) -> dict[str, Any]:
    return {
        "population_weighted_conversion": cr,
        "conversion_rate": cr,
        "product_type_detected": "saas",
    }


def _outcome(actual: float, simulation_id: int = 99) -> dict[str, Any]:
    return {
        "simulation_id": simulation_id,
        "actual_conversion_rate": actual,
    }


def test_no_outcome_yields_insufficient_data() -> None:
    out = build_assumption_postmortem(
        _results(),
        simulation_id=1,
        project_id=2,
        assumptions=_assumptions(),
        outcome=None,
    )

    assert isinstance(out, AssumptionPostmortemOut)
    assert out.simulation_id == 1
    assert out.project_id == 2
    assert out.verdict == VERDICT_INSUFFICIENT_DATA
    assert out.actual_conversion_rate is None
    assert out.summary.insufficient_count == 3
    assert all(i.verdict == VERDICT_INSUFFICIENT_DATA for i in out.summary.top_invalidated)


def test_outcome_without_assumptions_returns_empty_summary() -> None:
    out = build_assumption_postmortem(
        _results(cr=0.04),
        simulation_id=1,
        project_id=2,
        assumptions=None,
        outcome=_outcome(0.01),
    )

    assert out.verdict == VERDICT_INSUFFICIENT_DATA
    assert out.summary.total_assumptions == 0
    assert out.outcome_source == "SIMULATION"


def test_matching_conversion_validates_assumptions() -> None:
    out = build_assumption_postmortem(
        _results(cr=0.041),
        simulation_id=99,
        project_id=2,
        assumptions=_assumptions(),
        outcome=_outcome(0.04),
    )

    assert out.predicted_conversion_rate == pytest.approx(0.041)
    assert out.actual_conversion_rate == pytest.approx(0.04)
    assert out.conversion_delta == pytest.approx(0.001)
    assert out.verdict == VERDICT_VALIDATED
    assert out.summary.validated_count == 3
    assert all(i.verdict == VERDICT_VALIDATED for i in out.summary.top_invalidated)


def test_large_gap_invalidates_critical_assumption_first() -> None:
    out = build_assumption_postmortem(
        _results(cr=0.08),
        simulation_id=99,
        project_id=2,
        assumptions=_assumptions(),
        outcome=_outcome(0.005),
        outcome_confidence="EXACT",
    )

    assert out.verdict == VERDICT_INVALIDATED
    assert out.summary.invalidated_count >= 1
    assert out.summary.top_invalidated[0].text.startswith("Referrals")
    assert out.summary.top_invalidated[0].verdict == VERDICT_INVALIDATED
    assert out.summary.top_invalidated[0].invalidation_score > 0.5


def test_estimated_confidence_discounts_gap_to_validated() -> None:
    out = build_assumption_postmortem(
        _results(cr=0.10),
        simulation_id=99,
        project_id=2,
        assumptions=[
            {
                "id": 1,
                "text": "High sensitivity assumption.",
                "category": "pricing",
                "sensitivity": "HIGH",
                "impact_score": 8.0,
            }
        ],
        outcome=_outcome(0.08),
        outcome_confidence="ESTIMATED",
    )

    # |gap| 2pp × 0.8 × 0.6 × 10 + small impact bonus ≈ 0.136 → VALIDATED.
    assert out.summary.top_invalidated[0].verdict == VERDICT_VALIDATED
    assert out.summary.top_invalidated[0].invalidation_score == pytest.approx(
        0.136, abs=1e-6
    )
    assert out.verdict == VERDICT_VALIDATED


def test_larger_estimated_gap_produces_mixed_verdict() -> None:
    out = build_assumption_postmortem(
        _results(cr=0.10),
        simulation_id=99,
        project_id=2,
        assumptions=[
            {
                "id": 1,
                "text": "High sensitivity assumption.",
                "category": "pricing",
                "sensitivity": "HIGH",
                "impact_score": 8.0,
            }
        ],
        outcome=_outcome(0.05),
        outcome_confidence="ESTIMATED",
    )

    # |gap| 5pp × 0.8 × 0.6 × 10 + bonus ≈ 0.28 → MIXED.
    assert out.summary.top_invalidated[0].verdict == VERDICT_MIXED
    assert out.verdict == VERDICT_MIXED


def test_rough_confidence_discounts_gap() -> None:
    exact = build_assumption_postmortem(
        _results(cr=0.10),
        simulation_id=99,
        project_id=2,
        assumptions=_assumptions(),
        outcome=_outcome(0.06),
        outcome_confidence="EXACT",
    )
    rough = build_assumption_postmortem(
        _results(cr=0.10),
        simulation_id=99,
        project_id=2,
        assumptions=_assumptions(),
        outcome=_outcome(0.06),
        outcome_confidence="ROUGH",
    )

    assert exact.summary.invalidated_count >= rough.summary.invalidated_count
    exact_score = exact.summary.top_invalidated[0].invalidation_score
    rough_score = rough.summary.top_invalidated[0].invalidation_score
    assert exact_score > rough_score


def test_zero_actual_conversion_is_usable_outcome() -> None:
    out = build_assumption_postmortem(
        _results(cr=0.06),
        simulation_id=99,
        project_id=2,
        assumptions=_assumptions(),
        outcome=_outcome(0.0),
        outcome_confidence="EXACT",
    )

    assert out.actual_conversion_rate == 0.0
    assert out.verdict == VERDICT_INVALIDATED
    assert out.summary.insufficient_count == 0
    assert out.summary.invalidated_count >= 1
    assert out.summary.top_invalidated[0].verdict == VERDICT_INVALIDATED


def test_predicted_conversion_falls_back_to_raw_funnel() -> None:
    out = build_assumption_postmortem(
        {"raw_funnel": {"conversion_rate": 0.07}},
        simulation_id=99,
        project_id=2,
        assumptions=_assumptions(),
        outcome=_outcome(0.01),
        outcome_confidence="EXACT",
    )

    assert out.predicted_conversion_rate == pytest.approx(0.07)
    assert out.verdict == VERDICT_INVALIDATED
    assert out.summary.insufficient_count == 0


def test_unparseable_conversion_rate_is_not_treated_as_zero() -> None:
    out = build_assumption_postmortem(
        {"population_weighted_conversion": "not-a-number"},
        simulation_id=99,
        project_id=2,
        assumptions=_assumptions(),
        outcome=_outcome(0.01),
    )

    assert out.predicted_conversion_rate is None
    assert out.verdict == VERDICT_INSUFFICIENT_DATA


def test_handles_malformed_assumptions_and_results() -> None:
    out = build_assumption_postmortem(
        "not-json",
        simulation_id=1,
        project_id=2,
        assumptions=[None, {"text": ""}, {"text": "valid", "sensitivity": "HOT"}],
        outcome=None,
    )

    assert out.summary.total_assumptions == 1
    assert out.summary.top_invalidated[0].sensitivity == "MEDIUM"
    assert out.verdict == VERDICT_INSUFFICIENT_DATA


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def _import_simulations_module():
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub
    from app.api.v1 import simulations as sim_mod

    return sim_mod


def test_assumption_postmortem_route_registered() -> None:
    sim_mod = _import_simulations_module()
    paths = {r.path for r in sim_mod.router.routes}
    assert "/simulations/{simulation_id}/assumption-postmortem" in paths


def test_assumption_postmortem_route_uses_get() -> None:
    sim_mod = _import_simulations_module()
    for route in sim_mod.router.routes:
        if getattr(route, "path", "") == "/simulations/{simulation_id}/assumption-postmortem":
            assert "GET" in (route.methods or set())
            return
    raise AssertionError("assumption-postmortem route not found")
