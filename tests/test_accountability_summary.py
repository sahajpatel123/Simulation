"""
Tests for accountability findings filtering and summary aggregation
(cycle 27 accountability-insights-api).

These tests lock in:

  1. ``filter_findings`` honours severity / architect / metric / limit /
     offset, including case-insensitivity, defaulting, and clamping.
  2. ``build_findings_summary`` correctly rolls up findings by severity,
     architect (ranked), cluster (top-N), metric (top-N), and recommended
     action frequency (top-N).
  3. Empty and malformed inputs degrade gracefully — never raise.
  4. ``DomainFindingOut.from_raw`` accepts the historical ``delta_from_benchmark``
     key as well as the new ``delta`` alias.
  5. The new ``GET /projects/{id}/findings/summary`` route is registered and
     the upgraded ``GET /projects/{id}/domain-findings`` accepts the new
     query parameters (smoke-checked via the module source).
"""
from __future__ import annotations

import json
from typing import Any

import pytest


def _sample_findings() -> list[dict[str, Any]]:
    """Realistic persisted findings list (ranked, mixed severities)."""
    return [
        {
            "architect_name": "PricingArchitect",
            "cluster_id": "metro_power_professional",
            "cluster_name": "Metro Power Professional",
            "population_fraction": 0.12,
            "finding": "Will-pay probability 20% vs benchmark 40%",
            "metric_affected": "will_pay_probability",
            "actual_value": 0.20,
            "healthy_benchmark": 0.40,
            "delta": -0.20,
            "conversion_impact": 0.0400,
            "recommended_action": "Lower price, add EMI option, or add free tier",
            "affected_agent_count": 1200,
            "severity": "CRITICAL",
        },
        {
            "architect_name": "OnboardingArchitect",
            "cluster_id": "tier2_price_sensitive_pragmatist",
            "cluster_name": "Tier-2 Price Sensitive Pragmatist",
            "population_fraction": 0.18,
            "finding": "Onboarding completion 40% vs benchmark 65%",
            "metric_affected": "onboarding_completion_rate",
            "actual_value": 0.40,
            "healthy_benchmark": 0.65,
            "delta": -0.25,
            "conversion_impact": 0.0360,
            "recommended_action": "Simplify onboarding, add templates, reduce steps",
            "affected_agent_count": 1800,
            "severity": "CRITICAL",
        },
        {
            "architect_name": "OnboardingArchitect",
            "cluster_id": "high_literacy_student_freemium_ceiling",
            "cluster_name": "High-Literacy Student (Freemium Ceiling)",
            "population_fraction": 0.10,
            "finding": "Onboarding completion 50% vs benchmark 65%",
            "metric_affected": "onboarding_completion_rate",
            "actual_value": 0.50,
            "healthy_benchmark": 0.65,
            "delta": -0.15,
            "conversion_impact": 0.0150,
            "recommended_action": "Simplify onboarding, add templates, reduce steps",
            "affected_agent_count": 1000,
            "severity": "WARNING",
        },
        {
            "architect_name": "RetentionArchitect",
            "cluster_id": "metro_power_professional",
            "cluster_name": "Metro Power Professional",
            "population_fraction": 0.12,
            "finding": "Day-7 survival 22% vs benchmark 35%",
            "metric_affected": "day7_survival",
            "actual_value": 0.22,
            "healthy_benchmark": 0.35,
            "delta": -0.13,
            "conversion_impact": 0.0100,
            "recommended_action": "Improve time-to-value, add habit triggers",
            "affected_agent_count": 1200,
            "severity": "WARNING",
        },
        {
            "architect_name": "TrustArchitect",
            "cluster_id": "tier3_first_time_app_user",
            "cluster_name": "Tier-3 First-Time App User",
            "population_fraction": 0.14,
            "finding": "Social proof 50% vs benchmark 70%",
            "metric_affected": "social_proof_met_fraction",
            "actual_value": 0.50,
            "healthy_benchmark": 0.70,
            "delta": -0.20,
            "conversion_impact": 0.0080,
            "recommended_action": "Collect reviews, publish case studies",
            "affected_agent_count": 1400,
            "severity": "WARNING",
        },
    ]


def test_parse_findings_handles_empty_and_malformed() -> None:
    from app.simulation.accountability_summary import parse_findings

    assert parse_findings(None) == []
    assert parse_findings([]) == []
    # Non-dict entries are silently dropped (no 500).
    assert parse_findings([None, "string", 123]) == []
    # Malformed dict (missing required field) is dropped, others survive.
    raw = [
        {"architect_name": "X"},  # missing everything → raises inside from_raw
        _sample_findings()[0],
    ]
    parsed = parse_findings(raw)
    # Only the well-formed entry survives (from_raw may raise on minimal).
    assert all(p.architect_name for p in parsed)


def test_filter_findings_by_severity() -> None:
    from app.simulation.accountability_summary import filter_findings

    raw = _sample_findings()
    critical = filter_findings(raw, severity="CRITICAL")
    assert len(critical) == 2
    assert all(f.severity == "CRITICAL" for f in critical)

    # Case-insensitive.
    critical_lower = filter_findings(raw, severity="critical")
    assert [f.finding for f in critical_lower] == [f.finding for f in critical]

    # Unknown severity → no filter applied (returns full list up to limit).
    unknowns = filter_findings(raw, severity="NUCLEAR", limit=10)
    assert len(unknowns) == 5

    # Blank severity → no filter.
    blanks = filter_findings(raw, severity="", limit=10)
    assert len(blanks) == 5


def test_filter_findings_by_architect_substring() -> None:
    from app.simulation.accountability_summary import filter_findings

    raw = _sample_findings()
    onboarding = filter_findings(raw, architect="Onboarding", limit=10)
    assert len(onboarding) == 2
    assert all("Onboarding" in f.architect_name for f in onboarding)

    # Case-insensitive substring.
    lower = filter_findings(raw, architect="onboarding", limit=10)
    assert len(lower) == 2

    # No match.
    assert filter_findings(raw, architect="NotPresent") == []


def test_filter_findings_by_metric_exact() -> None:
    from app.simulation.accountability_summary import filter_findings

    raw = _sample_findings()
    onboarding_metric = filter_findings(
        raw, metric="onboarding_completion_rate", limit=10
    )
    assert len(onboarding_metric) == 2
    assert all(
        f.metric_affected == "onboarding_completion_rate" for f in onboarding_metric
    )

    # Case-sensitive (metric names are exact in the engine).
    assert filter_findings(raw, metric="Onboarding_Completion_Rate") == []


def test_filter_findings_combines_predicates_and_pagination() -> None:
    from app.simulation.accountability_summary import filter_findings

    raw = _sample_findings()
    # CRITICAL + Onboarding → exactly 1.
    critical_onboarding = filter_findings(
        raw, severity="CRITICAL", architect="Onboarding", limit=10
    )
    assert len(critical_onboarding) == 1
    assert critical_onboarding[0].metric_affected == "onboarding_completion_rate"

    # Pagination: limit=1, offset=0 then offset=1 over the same filter.
    page1 = filter_findings(raw, metric="onboarding_completion_rate", limit=1, offset=0)
    page2 = filter_findings(raw, metric="onboarding_completion_rate", limit=1, offset=1)
    assert len(page1) == 1 and len(page2) == 1
    assert page1[0].finding != page2[0].finding


def test_filter_findings_clamps_limit_and_offset() -> None:
    from app.simulation.accountability_summary import (
        DEFAULT_LIMIT,
        MAX_LIMIT,
        filter_findings,
    )

    raw = _sample_findings()

    # Bad inputs → defaults. limit=0 / negative / non-int all fall back to
    # DEFAULT_LIMIT (10), which is bigger than our 5-item sample, so the
    # entire filtered list is returned.
    assert len(filter_findings(raw, limit=0)) == len(raw)
    assert len(filter_findings(raw, limit=-1)) == len(raw)
    assert len(filter_findings(raw, limit="100")) == len(raw)  # type: ignore[arg-type]
    # Negative offsets clamp to 0 → returns from the start (up to DEFAULT_LIMIT).
    assert len(filter_findings(raw, offset=-1)) == len(raw)
    # Past-end offset → empty slice.
    assert filter_findings(raw, offset=999) == []

    # Explicit limit=10_000 is clamped to MAX_LIMIT (100), still > len(raw).
    assert len(filter_findings(raw, limit=10_000)) == len(raw)
    assert len(filter_findings(raw, limit=MAX_LIMIT + 1)) == len(raw)
    # Sanity: DEFAULT_LIMIT constant is what we fall back to.
    assert DEFAULT_LIMIT == 10
    assert MAX_LIMIT == 100


def test_build_findings_summary_empty() -> None:
    from app.simulation.accountability_summary import build_findings_summary

    summary = build_findings_summary(None)
    assert summary.total_findings == 0
    assert summary.severity_breakdown == {}
    assert summary.by_architect == []
    assert summary.by_cluster == []
    assert summary.by_metric == []
    assert summary.recommended_actions == []
    assert summary.top_critical_findings == []


def test_build_findings_summary_severity_breakdown() -> None:
    from app.simulation.accountability_summary import build_findings_summary

    summary = build_findings_summary(_sample_findings())
    assert summary.total_findings == 5
    assert summary.severity_breakdown == {"CRITICAL": 2, "WARNING": 3, "INFO": 0}


def test_build_findings_summary_by_architect_ranked_by_impact() -> None:
    from app.simulation.accountability_summary import build_findings_summary

    summary = build_findings_summary(_sample_findings())
    ranks = [(a.architect_name, a.rank, a.total_impact, a.finding_count) for a in summary.by_architect]

    # Total impact per architect (sum of conversion_impact):
    #   Onboarding: 0.0360 + 0.0150 = 0.0510
    #   Pricing:    0.0400
    #   Trust:      0.0080
    #   Retention:  0.0100
    by_name = {a.architect_name: a for a in summary.by_architect}
    assert by_name["OnboardingArchitect"].total_impact == pytest.approx(0.0510)
    assert by_name["PricingArchitect"].total_impact == pytest.approx(0.0400)
    assert by_name["RetentionArchitect"].total_impact == pytest.approx(0.0100)
    assert by_name["TrustArchitect"].total_impact == pytest.approx(0.0080)

    # Ranking is by total_impact desc, ties broken by name asc.
    assert [a.architect_name for a in summary.by_architect] == [
        "OnboardingArchitect",
        "PricingArchitect",
        "RetentionArchitect",
        "TrustArchitect",
    ]
    # Ranks are 1-indexed and contiguous.
    assert [a.rank for a in summary.by_architect] == [1, 2, 3, 4]

    # Onboarding has 1 CRITICAL + 1 WARNING.
    onboarding = by_name["OnboardingArchitect"]
    assert onboarding.severity_breakdown == {"CRITICAL": 1, "WARNING": 1, "INFO": 0}
    assert onboarding.finding_count == 2


def test_build_findings_summary_by_cluster_top_n() -> None:
    from app.simulation.accountability_summary import build_findings_summary

    summary = build_findings_summary(_sample_findings())
    by_cluster = summary.by_cluster
    # 4 distinct clusters; top-N defaults to 10 so all are returned.
    assert len(by_cluster) == 4
    # Sorted by total_impact desc:
    #   tier2:           0.0360
    #   metro_power:     0.0400 + 0.0100 = 0.0500
    #   high_lit:        0.0150
    #   tier3:           0.0080
    impacts = [c.total_impact for c in by_cluster]
    assert impacts == sorted(impacts, reverse=True)
    assert by_cluster[0].cluster_id == "metro_power_professional"


def test_build_findings_summary_by_metric_top_n() -> None:
    from app.simulation.accountability_summary import build_findings_summary

    summary = build_findings_summary(_sample_findings())
    metric_names = {m.metric_affected for m in summary.by_metric}
    assert metric_names == {
        "will_pay_probability",
        "onboarding_completion_rate",
        "day7_survival",
        "social_proof_met_fraction",
    }
    # Onboarding has the highest combined impact (0.0510).
    assert summary.by_metric[0].metric_affected == "onboarding_completion_rate"
    assert summary.by_metric[0].finding_count == 2


def test_build_findings_summary_recommended_action_frequency() -> None:
    from app.simulation.accountability_summary import build_findings_summary

    summary = build_findings_summary(_sample_findings())
    actions = {a.recommended_action: a for a in summary.recommended_actions}
    # "Simplify onboarding..." appears twice.
    assert actions[
        "Simplify onboarding, add templates, reduce steps"
    ].count == 2
    # Other actions appear once.
    once = [
        a for a in summary.recommended_actions if a.count == 1
    ]
    assert len(once) == 3


def test_build_findings_summary_top_critical_findings_capped() -> None:
    from app.simulation.accountability_summary import build_findings_summary

    summary = build_findings_summary(_sample_findings(), top_critical_limit=1)
    assert len(summary.top_critical_findings) == 1
    assert summary.top_critical_findings[0].severity == "CRITICAL"


def test_build_findings_summary_clamps_top_n() -> None:
    from app.simulation.accountability_summary import build_findings_summary

    summary = build_findings_summary(_sample_findings(), top_n_by_group=2)
    assert len(summary.by_cluster) == 2
    assert len(summary.by_metric) == 2
    assert len(summary.recommended_actions) == 2


def test_domain_finding_from_raw_accepts_legacy_delta_from_benchmark() -> None:
    from app.schemas.accountability import DomainFindingOut

    legacy = {
        "architect_name": "X",
        "cluster_id": "y",
        "cluster_name": "Y",
        "population_fraction": 0.1,
        "finding": "f",
        "metric_affected": "m",
        "actual_value": 0.1,
        "healthy_benchmark": 0.2,
        "delta_from_benchmark": -0.1,  # legacy key
        "conversion_impact": 0.01,
        "recommended_action": "r",
        "affected_agent_count": 100,
        "severity": "warning",  # lowercase, should normalise
    }
    out = DomainFindingOut.from_raw(legacy)
    assert out.delta == -0.1
    assert out.severity == "WARNING"  # normalised to upper


def test_findings_list_out_model_serialisation() -> None:
    from app.schemas.accountability import FindingsListOut, DomainFindingOut

    finding = DomainFindingOut.from_raw(_sample_findings()[0])
    out = FindingsListOut(
        project_id=1,
        simulation_id=42,
        primary_failure_domain="PricingArchitect",
        highest_value_cluster={"name": "Metro"},
        total=5,
        findings=[finding],
        filters={"severity": "CRITICAL", "limit": 1, "offset": 0},
    )
    dumped = out.model_dump()
    assert dumped["project_id"] == 1
    assert dumped["simulation_id"] == 42
    assert dumped["total"] == 5
    assert dumped["filters"]["severity"] == "CRITICAL"
    # Round-trip via JSON.
    json.dumps(dumped)


def test_findings_summary_out_model_serialisation() -> None:
    from app.simulation.accountability_summary import build_findings_summary
    from app.schemas.accountability import FindingsSummaryOut

    summary: FindingsSummaryOut = build_findings_summary(_sample_findings())
    summary.project_id = 7
    summary.simulation_id = 99
    summary.primary_failure_domain = "OnboardingArchitect"
    summary.highest_value_cluster = {"name": "Tier-2", "conversion_rate": 0.012}
    dumped = summary.model_dump()
    assert dumped["project_id"] == 7
    assert dumped["total_findings"] == 5
    assert len(dumped["by_architect"]) == 4
    assert dumped["primary_failure_domain"] == "OnboardingArchitect"
    json.dumps(dumped)


def test_projects_router_exposes_filterable_findings_endpoint() -> None:
    """Smoke-check: the projects router declares the upgraded + new routes."""
    src_path = "backend/app/api/v1/projects.py"
    with open(src_path) as fh:
        source = fh.read()
    # Imports for the new schemas + summary module.
    assert "from app.schemas.accountability import" in source
    assert "from app.simulation.accountability_summary import" in source
    # The route function names and registration blocks are present.
    assert "def get_domain_findings(" in source
    assert "def get_findings_summary(" in source
    assert '/{project_id}/findings/summary' in source
    # New query parameters wired in.
    for param in ("severity", "architect", "metric", "limit", "offset"):
        assert f"{param}:" in source or f"{param} = " in source, (
            f"projects.py must declare query param {param}"
        )
