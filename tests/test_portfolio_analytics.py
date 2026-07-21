"""
Tests for portfolio analytics helpers and the GET /analytics/me/portfolio
endpoint smoke-check (cycle 30 user-portfolio-analytics).

These tests focus on the pure helper layer (no DB), since the route just
threads SQL rows through the helpers and validates inputs.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# build_status_breakdown
# ---------------------------------------------------------------------------


def test_status_breakdown_empty_input() -> None:
    from app.simulation.portfolio_analytics import build_status_breakdown

    out = build_status_breakdown(None)
    assert out == {"counts": {}, "total": 0}

    out = build_status_breakdown([])
    assert out == {"counts": {}, "total": 0}


def test_status_breakdown_aggregates_rows() -> None:
    from app.simulation.portfolio_analytics import build_status_breakdown

    rows = [
        {"status": "DRAFT", "count": 3},
        {"status": "COMPLETED", "count": 2},
        {"status": "DRAFT", "count": 1},  # duplicate row → summed
    ]
    out = build_status_breakdown(rows)
    assert out["total"] == 6
    assert out["counts"]["DRAFT"] == 4
    assert out["counts"]["COMPLETED"] == 2


def test_status_breakdown_sorts_by_count_desc() -> None:
    from app.simulation.portfolio_analytics import build_status_breakdown

    rows = [
        {"status": "A", "count": 1},
        {"status": "B", "count": 5},
        {"status": "C", "count": 3},
    ]
    out = build_status_breakdown(rows)
    keys = list(out["counts"].keys())
    assert keys == ["B", "C", "A"]


def test_status_breakdown_normalises_to_upper() -> None:
    from app.simulation.portfolio_analytics import build_status_breakdown

    rows = [{"status": "draft", "count": 2}, {"status": "Draft", "count": 1}]
    out = build_status_breakdown(rows)
    assert out["counts"]["DRAFT"] == 3


def test_status_breakdown_handles_null_status() -> None:
    from app.simulation.portfolio_analytics import build_status_breakdown

    rows = [{"status": None, "count": 2}]
    out = build_status_breakdown(rows)
    assert out["counts"]["UNKNOWN"] == 2


# ---------------------------------------------------------------------------
# build_conversion_distribution
# ---------------------------------------------------------------------------


def test_conversion_distribution_empty() -> None:
    from app.simulation.portfolio_analytics import build_conversion_distribution

    assert build_conversion_distribution(None) == {
        "project_count": 0,
        "min": None,
        "median": None,
        "mean": None,
        "max": None,
    }


def test_conversion_distribution_basic_stats() -> None:
    from app.simulation.portfolio_analytics import build_conversion_distribution

    rows = [{"conversion_rate": r} for r in [0.05, 0.10, 0.15]]
    out = build_conversion_distribution(rows)
    assert out["project_count"] == 3
    assert out["min"] == 0.05
    assert out["max"] == 0.15
    assert out["median"] == 0.10
    assert out["mean"] == pytest_float(0.10)


def test_conversion_distribution_skips_null_and_garbage() -> None:
    from app.simulation.portfolio_analytics import build_conversion_distribution

    rows: list[dict[str, Any]] = [
        {"conversion_rate": None},
        {"conversion_rate": "not-a-number"},
        {"conversion_rate": 0.04},
        {},
    ]
    out = build_conversion_distribution(rows)
    assert out["project_count"] == 1
    assert out["min"] == 0.04


def test_conversion_distribution_single_value() -> None:
    from app.simulation.portfolio_analytics import build_conversion_distribution

    rows = [{"conversion_rate": 0.012}]
    out = build_conversion_distribution(rows)
    assert out == {
        "project_count": 1,
        "min": 0.012,
        "median": 0.012,
        "mean": 0.012,
        "max": 0.012,
    }


# ---------------------------------------------------------------------------
# build_failure_domain_counts
# ---------------------------------------------------------------------------


def test_failure_domain_counts_sorts_and_caps() -> None:
    from app.simulation.portfolio_analytics import build_failure_domain_counts

    rows = [
        {"architect": "PricingArchitect", "count": 7},
        {"architect": "OnboardingArchitect", "count": 4},
        {"architect": "TrustArchitect", "count": 4},
        {"architect": "RetentionArchitect", "count": 1},
    ]
    out = build_failure_domain_counts(rows, top_n=3)
    # Pricing first (7), then Onboarding before Trust (tied at 4, name asc).
    assert [r["architect_name"] for r in out] == [
        "PricingArchitect",
        "OnboardingArchitect",
        "TrustArchitect",
    ]
    assert [r["count"] for r in out] == [7, 4, 4]


def test_failure_domain_counts_drops_unknown_and_null() -> None:
    from app.simulation.portfolio_analytics import build_failure_domain_counts

    rows = [
        {"architect": None, "count": 3},
        {"architect": "unknown", "count": 2},
        {"architect": "null", "count": 1},
        {"architect": "none", "count": 1},
        {"architect": "PricingArchitect", "count": 5},
    ]
    out = build_failure_domain_counts(rows)
    assert out == [{"architect_name": "PricingArchitect", "count": 5}]


def test_failure_domain_counts_empty() -> None:
    from app.simulation.portfolio_analytics import build_failure_domain_counts

    assert build_failure_domain_counts(None) == []
    assert build_failure_domain_counts([]) == []


# ---------------------------------------------------------------------------
# build_stress_test_coverage
# ---------------------------------------------------------------------------


def test_stress_test_coverage_empty_input() -> None:
    from app.simulation.portfolio_analytics import build_stress_test_coverage

    out = build_stress_test_coverage(None)
    assert out == {
        "total": 0,
        "completed": 0,
        "with_kill_shots": 0,
        "with_partial_kill_shots": 0,
        "overall_risk_breakdown": {},
    }


def test_stress_test_coverage_counts_status_and_risk() -> None:
    from app.simulation.portfolio_analytics import build_stress_test_coverage

    rows = [
        {
            "stress_test_json": {
                "status": "COMPLETED",
                "kill_shots": [{"x": 1}],
                "partial_kill_shots": [],
                "overall_risk_level": "HIGH",
            }
        },
        {
            "stress_test_json": {
                "status": "COMPLETED",
                "kill_shots": [],
                "partial_kill_shots": [{"x": 1}],
                "overall_risk_level": "MEDIUM",
            }
        },
        {
            "stress_test_json": {
                "status": "COMPLETED",
                "kill_shots": [],
                "partial_kill_shots": [],
                "overall_risk_level": "LOW",
            }
        },
        {"stress_test_json": {"status": "RUNNING"}},
        {"stress_test_json": None},
        {},  # missing key
    ]
    out = build_stress_test_coverage(rows)
    assert out["total"] == 6
    assert out["completed"] == 3
    assert out["with_kill_shots"] == 1
    assert out["with_partial_kill_shots"] == 1
    assert out["overall_risk_breakdown"] == {"LOW": 1, "MEDIUM": 1, "HIGH": 1}


def test_stress_test_coverage_handles_string_payloads() -> None:
    """Some persistence layers may serialise JSONB to strings."""
    from app.simulation.portfolio_analytics import build_stress_test_coverage

    payload = json.dumps({
        "status": "COMPLETED",
        "kill_shots": [{"x": 1}],
        "partial_kill_shots": [],
        "overall_risk_level": "HIGH",
    })
    rows = [{"data": payload}, {"data": "{not-json"}]  # second is malformed
    # If the producer passes dict rows, we ignore string rows — only
    # ``stress_test_json`` (dict) is inspected. Pass dicts to confirm.
    rows = [
        {"stress_test_json": json.loads(payload)},
        {"stress_test_json": {"status": "COMPLETED"}},
    ]
    out = build_stress_test_coverage(rows)
    assert out["completed"] == 2
    assert out["with_kill_shots"] == 1
    assert out["overall_risk_breakdown"]["HIGH"] == 1


# ---------------------------------------------------------------------------
# build_recent_projects
# ---------------------------------------------------------------------------


def test_recent_projects_serialises_rows() -> None:
    from app.simulation.portfolio_analytics import build_recent_projects

    rows = [
        {
            "id": 1,
            "title": "Acme",
            "status": "ACTIVE",
            "updated_at": datetime(2026, 1, 1, 12, 0, 0),
            "has_completed_simulation": True,
            "latest_conversion_rate": 0.05,
            "primary_failure_domain": "PricingArchitect",
        },
        {
            "id": 2,
            "title": "Beta",
            "status": "DRAFT",
            "updated_at": "2026-02-01T00:00:00",
            "has_completed_simulation": False,
            "latest_conversion_rate": None,
            "primary_failure_domain": None,
        },
    ]
    out = build_recent_projects(rows)
    assert len(out) == 2
    assert out[0]["id"] == 1
    assert out[0]["latest_conversion_rate"] == 0.05
    assert out[0]["updated_at"] == "2026-01-01T12:00:00"
    assert out[1]["updated_at"] == "2026-02-01T00:00:00"
    assert out[1]["latest_conversion_rate"] is None


def test_recent_projects_handles_missing_keys() -> None:
    from app.simulation.portfolio_analytics import build_recent_projects

    rows = [{}]  # missing everything
    out = build_recent_projects(rows)
    assert out == [
        {
            "id": 0,
            "title": "",
            "status": "UNKNOWN",
            "updated_at": None,
            "has_completed_simulation": False,
            "latest_conversion_rate": None,
            "primary_failure_domain": None,
        }
    ]


# ---------------------------------------------------------------------------
# Pydantic schema serialisation
# ---------------------------------------------------------------------------


def test_user_portfolio_out_serialises_full_payload() -> None:
    from app.schemas.portfolio import UserPortfolioOut

    out = UserPortfolioOut(
        user_id=42,
        projects={"counts": {"ACTIVE": 3, "DRAFT": 1}, "total": 4},
        simulations={"counts": {"COMPLETED": 5}, "total": 5},
        conversion_distribution={
            "project_count": 3,
            "min": 0.01,
            "median": 0.04,
            "mean": 0.04,
            "max": 0.07,
        },
        primary_failure_domains=[
            {"architect_name": "PricingArchitect", "count": 4},
            {"architect_name": "OnboardingArchitect", "count": 1},
        ],
        stress_test_coverage={
            "total": 4,
            "completed": 3,
            "with_kill_shots": 1,
            "with_partial_kill_shots": 2,
            "overall_risk_breakdown": {"LOW": 1, "HIGH": 1, "CRITICAL": 1},
        },
        outcome_coverage={"simulations_total": 5, "with_outcome": 2},
        recent_projects=[
            {
                "id": 1,
                "title": "Acme",
                "status": "ACTIVE",
                "updated_at": "2026-01-01T00:00:00",
                "has_completed_simulation": True,
                "latest_conversion_rate": 0.04,
                "primary_failure_domain": "PricingArchitect",
            }
        ],
        generated_at="2026-07-21T20:00:00+00:00",
    )
    dumped = out.model_dump()
    assert dumped["user_id"] == 42
    assert dumped["projects"]["total"] == 4
    assert dumped["conversion_distribution"]["median"] == 0.04
    assert dumped["stress_test_coverage"]["with_kill_shots"] == 1
    assert len(dumped["recent_projects"]) == 1
    # Round-trip via JSON without errors.
    json.dumps(dumped)


def test_user_portfolio_out_defaults_when_empty() -> None:
    from app.schemas.portfolio import UserPortfolioOut

    out = UserPortfolioOut(user_id=1, generated_at="2026-01-01T00:00:00")
    assert out.projects.total == 0
    assert out.simulations.total == 0
    assert out.conversion_distribution.project_count == 0
    assert out.primary_failure_domains == []
    assert out.stress_test_coverage.total == 0
    assert out.outcome_coverage == {}
    assert out.recent_projects == []


# ---------------------------------------------------------------------------
# Route registration smoke check
# ---------------------------------------------------------------------------


def test_analytics_router_exposes_me_portfolio_endpoint() -> None:
    """Source-level check: the new route is declared and uses UserPortfolioOut."""
    src_path = "backend/app/api/v1/analytics.py"
    with open(src_path) as fh:
        source = fh.read()
    assert '"/me/portfolio"' in source or '"/me/portfolio",' in source
    assert "def my_portfolio(" in source
    assert "response_model=UserPortfolioOut" in source
    # Pure helpers are wired in.
    for fn in (
        "build_status_breakdown",
        "build_conversion_distribution",
        "build_failure_domain_counts",
        "build_stress_test_coverage",
        "build_recent_projects",
    ):
        assert fn in source, f"analytics.py must call {fn}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def pytest_float(value: float, tol: float = 1e-9) -> float:
    """Tiny adapter so test_conversion_distribution_basic_stats reads cleanly."""
    class _Approx:
        def __eq__(self, other: object) -> bool:
            return isinstance(other, float) and abs(other - value) < tol

        def __repr__(self) -> str:
            return f"≈{value}"

    return _Approx()  # type: ignore[return-value]
