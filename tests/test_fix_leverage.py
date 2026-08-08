"""
Tests for the fix-leverage conversion projection (ADD pass).

Covers the pure builder, schema contract, and route-level ownership/status
gates without spinning up PostgreSQL.
"""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


from app.schemas.fix_leverage import FixLeverageOut  # noqa: E402
from app.simulation.fix_leverage import (  # noqa: E402
    MAX_UPLIFT_PER_TRANSITION,
    build_fix_leverage,
)


def _results(
    *,
    cr: float = 0.031,
    include_stages: bool = True,
    include_findings: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "population_weighted_conversion": cr,
        "conversion_rate": cr,
        "total_agents": 10000,
        "product_type_detected": "saas",
    }
    if include_stages:
        payload["raw_funnel"] = {
            "total_agents": 10000,
            "conversion_rate": cr,
            "stage_counts": {
                "ARRIVE": 10000,
                "BROWSE": 6500,
                "CONSIDER": 4000,
                "DECIDE": 2200,
                "PURCHASE": 310,
                "ABANDON": 9690,
                "RETURN": 50,
            },
        }
    if include_findings:
        payload["domain_findings"] = [
            {
                "architect_name": "PricingArchitect",
                "cluster_id": "cluster_b",
                "cluster_name": "Budget Shoppers",
                "metric_affected": "will_pay_probability",
                "finding": "Only 20% of Budget Shoppers will pay at current price.",
                "recommended_action": "Simplify pricing or add a cheaper tier.",
                "severity": "CRITICAL",
                "actual_value": 0.2,
                "healthy_benchmark": 0.4,
                "conversion_impact": 0.05,
                "affected_agent_count": 1200,
            },
            {
                "architect_name": "OnboardingArchitect",
                "cluster_id": "cluster_a",
                "cluster_name": "Power Pros",
                "metric_affected": "onboarding_completion_rate",
                "finding": "Only 40% of Power Pros complete onboarding.",
                "recommended_action": "Cut onboarding steps.",
                "severity": "WARNING",
                "actual_value": 0.4,
                "healthy_benchmark": 0.65,
                "conversion_impact": 0.03,
                "affected_agent_count": 800,
            },
        ]
    return payload


class _FakeSession:
    def __init__(self, sim: _FakeSimulation | None = None) -> None:
        self._sim = sim

    def query(self, *args: Any, **kwargs: Any) -> "_FakeSession":
        return self

    def join(self, *args: Any, **kwargs: Any) -> "_FakeSession":
        return self

    def filter(self, *args: Any, **kwargs: Any) -> "_FakeSession":
        return self

    def first(self) -> Any:
        return self._sim


class _FakeSimulation:
    def __init__(
        self,
        sim_id: int = 1,
        *,
        project_id: int = 10,
        status: str = "COMPLETED",
        results: dict | None = None,
        error_message: str | None = None,
        signal_quality: float | None = None,
    ) -> None:
        self.id = sim_id
        self.project_id = project_id
        self.status = status
        self.results_json = results if results is not None else _results()
        self.error_message = error_message
        self.signal_quality = signal_quality


def _call_route(sim: _FakeSimulation, session: _FakeSession | None = None) -> FixLeverageOut:
    from app.api.v1 import simulations as sim_mod

    db = session or _FakeSession(sim)
    return sim_mod.get_fix_leverage(
        simulation_id=sim.id,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


# ---------------------------------------------------------------------------
# Pure builder
# ---------------------------------------------------------------------------


def test_build_fix_leverage_projects_uplift_for_mapped_findings() -> None:
    out = build_fix_leverage(
        _results(),
        simulation_id=1,
        project_id=10,
    )

    assert isinstance(out, FixLeverageOut)
    assert out.baseline_conversion is not None
    assert out.projected_conversion is not None
    assert out.projected_conversion > out.baseline_conversion
    assert out.absolute_lift is not None and out.absolute_lift > 0.0
    assert out.summary.actionable_findings == 2
    assert out.summary.unmapped_findings == 0
    assert out.summary.total_findings == 2
    assert out.summary.transitions_improved == ["BROWSE→CONSIDER", "DECIDE→PURCHASE"]
    assert out.summary.verdict == "ACTIONABLE"
    # Schema fields are present and bounded.
    assert 0.0 <= out.baseline_conversion <= 1.0
    assert 0.0 <= out.projected_conversion <= 1.0


def test_build_fix_leverage_keeps_unmapped_findings_but_marks_them() -> None:
    results = _results(include_findings=False)
    results["domain_findings"] = [
        {
            "architect_name": "RetentionArchitect",
            "cluster_id": "c",
            "cluster_name": "C",
            "metric_affected": "day30_survival",
            "finding": "Day-30 survival is low.",
            "recommended_action": "Improve retention.",
            "severity": "WARNING",
            "conversion_impact": 0.02,
        }
    ]
    out = build_fix_leverage(results, simulation_id=1, project_id=10)

    assert out.summary.total_findings == 1
    assert out.summary.actionable_findings == 0
    assert out.summary.unmapped_findings == 1
    assert out.findings[0].affected_transition is None
    assert out.findings[0].projected_uplift == 0.0
    # No mapped findings → no lift.
    assert out.projected_conversion == pytest.approx(out.baseline_conversion)
    assert out.summary.verdict == "NO_UPLIFT_PROJECTED"


def test_build_fix_leverage_empty_findings_returns_insufficient() -> None:
    out = build_fix_leverage(
        _results(include_findings=False),
        simulation_id=1,
        project_id=10,
    )

    assert out.summary.total_findings == 0
    assert out.summary.verdict == "INSUFFICIENT_DATA"
    assert out.absolute_lift == 0.0
    assert out.relative_lift_pct == 0.0


def test_build_fix_leverage_falls_back_without_funnel_counts() -> None:
    out = build_fix_leverage(
        _results(include_stages=False),
        simulation_id=1,
        project_id=10,
    )

    # No stage counts: baseline comes from the persisted headline conversion
    # and current transition rates come from the base Markov matrix.
    assert out.baseline_conversion is not None
    assert out.projected_conversion is not None
    assert out.projected_conversion >= out.baseline_conversion
    assert out.summary.actionable_findings == 2


def test_build_fix_leverage_caps_per_transition_uplift() -> None:
    results = _results(include_findings=False)
    # Two findings on the same transition with very large impacts. The cap
    # must keep the combined effect bounded.
    results["domain_findings"] = [
        {
            "architect_name": "PricingArchitect",
            "cluster_id": "a",
            "cluster_name": "A",
            "metric_affected": "will_pay_probability",
            "finding": "Weak willingness to pay.",
            "recommended_action": "Cut price.",
            "severity": "CRITICAL",
            "conversion_impact": 0.5,
        },
        {
            "architect_name": "PricingArchitect",
            "cluster_id": "b",
            "cluster_name": "B",
            "metric_affected": "annual_payment_probability",
            "finding": "Annual payment is low.",
            "recommended_action": "Offer a free month.",
            "severity": "WARNING",
            "conversion_impact": 0.5,
        },
    ]
    out = build_fix_leverage(results, simulation_id=1, project_id=10)

    decide_findings = [
        f for f in out.findings if f.affected_transition == "DECIDE→PURCHASE"
    ]
    assert len(decide_findings) == 2
    assert all(f.projected_uplift <= MAX_UPLIFT_PER_TRANSITION for f in decide_findings)
    assert out.summary.verdict == "ACTIONABLE"


def test_build_fix_leverage_handles_malformed_results() -> None:
    out = build_fix_leverage(
        "not-a-dict",
        simulation_id=1,
        project_id=10,
    )

    # Malformed input falls back to the base Markov product, so the payload
    # remains renderable instead of returning a hard error.
    assert out.baseline_conversion is not None
    assert out.projected_conversion is not None
    assert out.summary.total_findings == 0
    assert out.summary.verdict == "INSUFFICIENT_DATA"


def test_build_fix_leverage_falls_back_to_base_rate_baseline() -> None:
    results = _results()
    # Remove every persisted conversion key/raw-funnel headline so the base
    # Markov chain product becomes the deterministic baseline.
    results.pop("population_weighted_conversion", None)
    results.pop("conversion_rate", None)
    results["raw_funnel"].pop("conversion_rate", None)

    out = build_fix_leverage(results, simulation_id=1, project_id=10)

    assert out.baseline_conversion == pytest.approx(
        round(0.87 * 0.62 * 0.46 * 0.31, 6)
    )
    assert out.projected_conversion is not None


def test_build_fix_leverage_ignores_malformed_stage_counts() -> None:
    results = _results()
    results["raw_funnel"]["stage_counts"] = {
        "ARRIVE": 10000,
        "BROWSE": "6500.0",
        "CONSIDER": "not-a-number",
        "DECIDE": 2200,
        "PURCHASE": None,
    }

    out = build_fix_leverage(results, simulation_id=1, project_id=10)

    # Malformed counts degrade to zero instead of crashing the endpoint.
    assert out.baseline_conversion is not None
    assert out.projected_conversion is not None
    assert out.summary.total_findings == 2


def test_build_fix_leverage_falls_back_to_stage_metrics_when_counts_missing() -> None:
    results = _results()
    # Strip the preferred stage_counts dict entirely so the fallback path has
    # to derive transition rates from stage_metrics rows.
    results.pop("raw_funnel", None)
    results["stage_metrics"] = [
        {"state": "ARRIVE", "agent_count": 10000},
        # A row where agent_count is None but the aliased key exists should
        # still be readable instead of silently dropping the stage.
        {"state": "BROWSE", "agent_count": None, "agents": 6500},
        {"stage": "CONSIDER", "agents": "4000.0"},
        {"state": "DECIDE", "agent_count": 2200},
        {"state": "PURCHASE", "agent_count": 310},
    ]

    out = build_fix_leverage(results, simulation_id=1, project_id=10)

    assert out.baseline_conversion is not None
    assert out.projected_conversion is not None
    assert out.projected_conversion > out.baseline_conversion
    assert out.summary.actionable_findings == 2


def test_build_fix_leverage_preserves_explicit_zero_impact() -> None:
    results = _results(include_findings=False)
    results["domain_findings"] = [
        {
            "architect_name": "PricingArchitect",
            "cluster_id": "b",
            "cluster_name": "Budget Shoppers",
            "metric_affected": "will_pay_probability",
            "finding": "Explicitly flagged as no conversion impact.",
            "recommended_action": "Monitor only.",
            "severity": "INFO",
            "conversion_impact": 0.0,
            "impact_on_overall_conversion": 0.05,
        }
    ]

    out = build_fix_leverage(results, simulation_id=1, project_id=10)

    assert len(out.findings) == 1
    assert out.findings[0].conversion_impact == 0.0
    assert out.findings[0].projected_uplift == 0.0
    assert out.summary.verdict == "NO_UPLIFT_PROJECTED"


def test_build_fix_leverage_omits_nonfinite_signal_quality() -> None:
    out = build_fix_leverage(
        _results(),
        simulation_id=1,
        project_id=10,
        signal_quality=float("nan"),
    )

    assert "signal_quality" not in out.meta


# ---------------------------------------------------------------------------
# Route contract
# ---------------------------------------------------------------------------


def test_route_requires_completed_simulation() -> None:
    sim = _FakeSimulation(status="RUNNING")
    with pytest.raises(Exception) as exc_info:
        _call_route(sim)
    assert "requires completed results" in str(exc_info.value)


def test_route_failed_simulation_returns_422_message() -> None:
    sim = _FakeSimulation(status="FAILED", error_message="boom")
    with pytest.raises(Exception) as exc_info:
        _call_route(sim)
    assert "boom" in str(exc_info.value)


def test_route_empty_results_rejected() -> None:
    sim = _FakeSimulation(status="COMPLETED", results={})
    with pytest.raises(Exception) as exc_info:
        _call_route(sim)
    assert "results_json is empty" in str(exc_info.value)


def test_route_returns_projection_for_completed_simulation() -> None:
    sim = _FakeSimulation(
        sim_id=7,
        project_id=10,
        results=_results(),
        signal_quality=0.8,
    )
    out = _call_route(sim)

    assert out.simulation_id == 7
    assert out.project_id == 10
    assert out.status == "COMPLETED"
    assert out.meta["signal_quality"] == 0.8
    assert out.summary.verdict == "ACTIONABLE"
