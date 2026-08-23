"""Tests for the per-project simulation-evolution helper + route.

The helper is pure-Python, mirroring ``simulation_trend`` and ``sim_diff``,
so it can be exercised without a database. The route is smoke-tested via
the route-registration pattern used elsewhere in this suite.
"""
from __future__ import annotations

from typing import Any

import pytest


def _row(
    sim_id: int,
    status: str,
    cr: float | None,
    findings: list[dict[str, Any]] | None = None,
    stage_metrics: list[dict[str, Any]] | None = None,
    signal: float | None = 0.7,
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "id": sim_id,
        "status": status,
        "signal_quality": signal,
        "results_json": {
            "population_weighted_conversion": cr,
            "conversion_rate": cr,
            "domain_findings": findings or [],
            "stage_metrics": stage_metrics or [],
        },
        "created_at": created_at,
    }


def _critical(domain: str, metric: str, finding: str = "bad") -> dict[str, Any]:
    return {
        "architect_name": domain,
        "metric_affected": metric,
        "severity": "CRITICAL",
        "finding": finding,
        "conversion_impact": 0.05,
    }


def _stages(
    browse_drop: float,
    decide_drop: float,
) -> list[dict[str, Any]]:
    return [
        {"state": "ARRIVE", "drop_off_rate": 0.13},
        {"state": "BROWSE", "drop_off_rate": browse_drop},
        {"state": "CONSIDER", "drop_off_rate": 0.38},
        {"state": "DECIDE", "drop_off_rate": decide_drop},
    ]


# ---------------------------------------------------------------------------
# Public surface + purity
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import simulation_evolution

    assert set(simulation_evolution.__all__) == {
        "build_simulation_evolution",
    }


def test_helper_is_pure() -> None:
    import inspect

    from app.simulation import simulation_evolution

    source = inspect.getsource(simulation_evolution)
    forbidden = ("sqlalchemy", "SessionLocal", "get_db")
    for token in forbidden:
        assert token.lower() not in source.lower(), (
            f"simulation_evolution.py must not depend on {token}"
        )


# ---------------------------------------------------------------------------
# Empty / insufficient data
# ---------------------------------------------------------------------------


def test_requires_two_completed_runs() -> None:
    from app.simulation.simulation_evolution import build_simulation_evolution

    out = build_simulation_evolution(
        [
            _row(1, "COMPLETED", 0.05),
            _row(2, "FAILED", 0.99),
            _row(3, "RUNNING", 0.0),
        ],
        project_id=7,
    )
    assert out["project_id"] == 7
    assert out["previous_run"] is None
    assert out["latest_run"] is None
    assert out["conversion"]["direction"] == "STABLE"
    assert out["summary"]["verdict"] == "NO_DATA"


def test_empty_input_returns_no_data() -> None:
    from app.simulation.simulation_evolution import build_simulation_evolution

    out = build_simulation_evolution([], project_id=1)
    assert out["previous_run"] is None
    assert out["latest_run"] is None
    assert out["critical_findings"] == []
    assert out["recommendations"] == []


# ---------------------------------------------------------------------------
# Conversion movement
# ---------------------------------------------------------------------------


def test_improved_conversion_direction() -> None:
    from app.simulation.simulation_evolution import build_simulation_evolution

    out = build_simulation_evolution(
        [
            _row(1, "COMPLETED", 0.04),
            _row(2, "COMPLETED", 0.07),
        ],
        project_id=1,
    )
    assert out["previous_run"]["simulation_id"] == 1
    assert out["latest_run"]["simulation_id"] == 2
    assert out["conversion"]["previous"] == pytest.approx(0.04)
    assert out["conversion"]["latest"] == pytest.approx(0.07)
    assert out["conversion"]["delta"] == pytest.approx(0.03)
    assert out["conversion"]["direction"] == "IMPROVED"
    assert out["summary"]["verdict"] == "IMPROVED"


def test_worsened_conversion_direction() -> None:
    from app.simulation.simulation_evolution import build_simulation_evolution

    out = build_simulation_evolution(
        [
            _row(1, "COMPLETED", 0.06),
            _row(2, "COMPLETED", 0.04),
        ],
        project_id=1,
    )
    assert out["conversion"]["direction"] == "WORSENED"


def test_stable_within_epsilon() -> None:
    from app.simulation.simulation_evolution import build_simulation_evolution

    out = build_simulation_evolution(
        [
            _row(1, "COMPLETED", 0.05),
            _row(2, "COMPLETED", 0.0504),
        ],
        project_id=1,
    )
    assert out["conversion"]["direction"] == "STABLE"


def test_uses_latest_two_by_created_at() -> None:
    from app.simulation.simulation_evolution import build_simulation_evolution

    out = build_simulation_evolution(
        [
            _row(1, "COMPLETED", 0.01, created_at="2026-01-01"),
            _row(2, "COMPLETED", 0.02, created_at="2026-01-03"),
            _row(3, "COMPLETED", 0.09, created_at="2026-01-02"),
            _row(4, "FAILED", 0.99, created_at="2026-01-04"),
        ],
        project_id=1,
    )
    assert out["previous_run"]["simulation_id"] == 3
    assert out["latest_run"]["simulation_id"] == 2
    assert out["conversion"]["previous"] == pytest.approx(0.09)
    assert out["conversion"]["latest"] == pytest.approx(0.02)


def test_missing_conversion_in_one_run_returns_no_data() -> None:
    from app.simulation.simulation_evolution import build_simulation_evolution

    out = build_simulation_evolution(
        [
            _row(1, "COMPLETED", None),
            _row(2, "COMPLETED", 0.06),
        ],
        project_id=1,
    )
    assert out["conversion"]["delta"] is None
    assert out["conversion"]["direction"] == "NO_DATA"


def test_zero_conversion_rate_is_not_treated_as_missing() -> None:
    from app.simulation.simulation_evolution import build_simulation_evolution

    out = build_simulation_evolution(
        [
            _row(1, "COMPLETED", 0.0),
            _row(2, "COMPLETED", 0.05),
        ],
        project_id=1,
    )
    assert out["conversion"]["previous"] == pytest.approx(0.0)
    assert out["conversion"]["latest"] == pytest.approx(0.05)
    assert out["conversion"]["delta"] == pytest.approx(0.05)
    assert out["conversion"]["direction"] == "IMPROVED"


def test_zero_conversion_rate_both_runs_is_stable() -> None:
    from app.simulation.simulation_evolution import build_simulation_evolution

    out = build_simulation_evolution(
        [
            _row(1, "COMPLETED", 0.0),
            _row(2, "COMPLETED", 0.0),
        ],
        project_id=1,
    )
    assert out["conversion"]["previous"] == pytest.approx(0.0)
    assert out["conversion"]["latest"] == pytest.approx(0.0)
    assert out["conversion"]["delta"] == pytest.approx(0.0)
    assert out["conversion"]["direction"] == "STABLE"


# ---------------------------------------------------------------------------
# Critical findings movement
# ---------------------------------------------------------------------------


def test_finding_added_and_resolved() -> None:
    from app.simulation.simulation_evolution import build_simulation_evolution

    prev = _row(
        1,
        "COMPLETED",
        0.04,
        findings=[
            _critical("PricingArchitect", "pricing"),
            _critical("TrustArchitect", "trust"),
        ],
    )
    latest = _row(
        2,
        "COMPLETED",
        0.06,
        findings=[
            _critical("PricingArchitect", "pricing"),
            _critical("OnboardingArchitect", "onboarding"),
        ],
    )
    out = build_simulation_evolution([prev, latest], project_id=1)
    directions = {f["direction"] for f in out["critical_findings"]}
    assert directions == {"ADDED", "RESOLVED"}
    added = [f for f in out["critical_findings"] if f["direction"] == "ADDED"]
    resolved = [f for f in out["critical_findings"] if f["direction"] == "RESOLVED"]
    assert added[0]["metric_affected"] == "onboarding"
    assert resolved[0]["metric_affected"] == "trust"
    assert out["latest_run"]["critical_finding_count"] == 2
    assert out["previous_run"]["critical_finding_count"] == 2


# ---------------------------------------------------------------------------
# Bottleneck movement
# ---------------------------------------------------------------------------


def test_bottleneck_changes() -> None:
    from app.simulation.simulation_evolution import build_simulation_evolution

    prev = _row(1, "COMPLETED", 0.04, stage_metrics=_stages(0.80, 0.55))
    latest = _row(2, "COMPLETED", 0.04, stage_metrics=_stages(0.40, 0.80))
    out = build_simulation_evolution([prev, latest], project_id=1)
    assert out["bottleneck"]["previous"] == "BROWSE"
    assert out["bottleneck"]["latest"] == "DECIDE"
    assert out["bottleneck"]["changed"] is True


def test_bottleneck_uses_mean_drop_off_when_primary_key_is_none() -> None:
    from app.simulation.simulation_evolution import build_simulation_evolution

    prev = _row(1, "COMPLETED", 0.04, stage_metrics=_stages(0.40, 0.80))
    latest = _row(
        2,
        "COMPLETED",
        0.04,
        stage_metrics=[
            {"state": "ARRIVE", "drop_off_rate": 0.13},
            {"state": "BROWSE", "drop_off_rate": None, "mean_drop_off_rate": 0.80},
            {"state": "CONSIDER", "drop_off_rate": 0.38},
            {"state": "DECIDE", "drop_off_rate": 0.60},
        ],
    )
    out = build_simulation_evolution([prev, latest], project_id=1)
    assert out["bottleneck"]["latest"] == "BROWSE"
    assert out["bottleneck"]["changed"] is True


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------


def test_recommendations_prioritise_critical_then_impact() -> None:
    from app.simulation.simulation_evolution import build_simulation_evolution

    latest = _row(
        2,
        "COMPLETED",
        0.06,
        findings=[
            {
                "architect_name": "PricingArchitect",
                "metric_affected": "pricing",
                "severity": "WARNING",
                "finding": "price too high",
                "conversion_impact": 0.01,
            },
            {
                "architect_name": "TrustArchitect",
                "metric_affected": "trust",
                "severity": "CRITICAL",
                "finding": "no social proof",
                "conversion_impact": 0.09,
            },
        ],
    )
    out = build_simulation_evolution([_row(1, "COMPLETED", 0.04)], project_id=1)
    # Only one completed run -> no evolution payload.
    assert out["recommendations"] == []

    out2 = build_simulation_evolution(
        [_row(1, "COMPLETED", 0.04), latest],
        project_id=1,
    )
    recs = out2["recommendations"]
    assert recs
    assert recs[0]["domain"] == "TrustArchitect"
    assert recs[0]["priority"] == 1


def test_zero_conversion_impact_does_not_fall_through_to_secondary_key() -> None:
    from app.simulation.simulation_evolution import build_simulation_evolution

    latest = _row(
        2,
        "COMPLETED",
        0.06,
        findings=[
            {
                "architect_name": "PricingArchitect",
                "metric_affected": "pricing",
                "severity": "INFO",
                "finding": "explicit zero impact",
                "conversion_impact": 0.0,
                "impact_on_overall_conversion": 0.09,
            },
            {
                "architect_name": "OnboardingArchitect",
                "metric_affected": "onboarding",
                "severity": "INFO",
                "finding": "small real impact",
                "conversion_impact": 0.02,
            },
        ],
    )
    out = build_simulation_evolution(
        [_row(1, "COMPLETED", 0.04), latest],
        project_id=1,
    )
    recs = out["recommendations"]
    assert recs
    assert recs[0]["domain"] == "OnboardingArchitect"
    assert recs[0]["priority"] == 1
    assert recs[1]["domain"] == "PricingArchitect"


# ---------------------------------------------------------------------------
# Schema round-trip
# ---------------------------------------------------------------------------


def test_schema_round_trip() -> None:
    from app.schemas.simulation_evolution import SimulationEvolutionOut

    payload = SimulationEvolutionOut(project_id=1)
    dumped = payload.model_dump()
    assert dumped["project_id"] == 1
    assert dumped["conversion"]["direction"] == "STABLE"
    assert dumped["summary"]["verdict"] == "NO_DATA"


# ---------------------------------------------------------------------------
# Route registration smoke-check
# ---------------------------------------------------------------------------


def test_projects_router_exposes_latest_sim_evolution_endpoint() -> None:
    src_path = "backend/app/api/v1/projects.py"
    with open(src_path) as fh:
        source = fh.read()
    assert '"/{project_id}/latest-sim-evolution"' in source
    assert "def get_latest_simulation_evolution(" in source
    assert "response_model=SimulationEvolutionOut" in source
    assert "build_simulation_evolution" in source


def test_helper_produces_serialisable_payload() -> None:
    from app.schemas.simulation_evolution import SimulationEvolutionOut
    from app.simulation.simulation_evolution import build_simulation_evolution

    out = build_simulation_evolution(
        [
            _row(
                1,
                "COMPLETED",
                0.04,
                findings=[_critical("PricingArchitect", "pricing")],
            ),
            _row(2, "COMPLETED", 0.07),
        ],
        project_id=7,
    )
    parsed = SimulationEvolutionOut(**out)
    assert parsed.previous_run is not None
    assert parsed.latest_run is not None
    assert parsed.summary.verdict == "IMPROVED"


def test_stable_narrative_uses_stayed_stable_wording() -> None:
    from app.simulation.simulation_evolution import build_simulation_evolution

    out = build_simulation_evolution(
        [
            _row(1, "COMPLETED", 0.05),
            _row(2, "COMPLETED", 0.0504),
        ],
        project_id=1,
    )
    assert out["summary"]["headline"].startswith("Latest sim conversion stayed stable at ")
    assert out["summary"]["headline"].find("stable to") == -1
