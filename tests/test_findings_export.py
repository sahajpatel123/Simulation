"""Tests for the pure findings-export helpers."""
from __future__ import annotations

from app.simulation.findings_export import (
    extract_findings,
    findings_to_csv,
    findings_to_markdown,
)


def _finding() -> dict:
    return {
        "severity": "CRITICAL",
        "architect_name": "PricingArchitect",
        "cluster_id": "metro_power_professional",
        "cluster_name": "Metro Pro",
        "finding": "price ceiling too low",
        "metric_affected": "conversion",
        "recommended_action": "TIGHTEN",
        "conversion_impact": 0.042,
    }


def test_extract_findings_from_domain_findings() -> None:
    results = {"domain_findings": [_finding()]}

    assert extract_findings(results) == [_finding()]


def test_extract_findings_from_legacy_findings_and_list() -> None:
    assert extract_findings({"findings": [_finding()]}) == [_finding()]
    assert extract_findings([_finding()]) == [_finding()]
    assert extract_findings(None) == []


def test_findings_to_csv_contains_header_and_row() -> None:
    csv_text = findings_to_csv(
        [_finding()],
        metadata={"generated_at": "now", "user_id": 42},
        simulation_id=7,
        project_id=10,
    )

    assert "simulation_id,project_id,severity,architect_name,cluster_id" in csv_text
    assert "7,10,CRITICAL,PricingArchitect,metro_power_professional" in csv_text
    assert "generated_at,now" in csv_text
    assert "0.0420" in csv_text


def test_findings_to_csv_handles_missing_fields() -> None:
    csv_text = findings_to_csv([{"severity": "warning"}])

    assert "WARNING" in csv_text
    assert "0.0000" in csv_text
    assert ",,WARNING" in csv_text


def test_findings_to_markdown_renders_summary_table_and_findings() -> None:
    findings = [
        {
            "severity": "CRITICAL",
            "architect_name": "PricingArchitect",
            "cluster_name": "Metro Pro",
            "finding": "price ceiling too low for affluent professionals",
            "metric_affected": "will_pay_probability",
            "recommended_action": "Lower price, add EMI option, or add free tier",
            "conversion_impact": 0.042,
        },
        {
            "severity": "WARNING",
            "architect_name": "RetentionArchitect",
            "cluster_name": "Budget Families",
            "finding": "day-30 survival is weak",
            "metric_affected": "day30_survival",
            "recommended_action": "Add gamification, content freshness, re-engagement",
            "conversion_impact": 0.011,
        },
    ]

    md = findings_to_markdown(
        findings,
        simulation_id=7,
        project_id=10,
        primary_failure_domain="PricingArchitect",
        metadata={"generated_at": "now"},
    )

    assert md.startswith("# TheCee — Findings Brief")
    assert "| Total findings | 2 |" in md
    assert "| Critical | 1 |" in md
    assert "| Warning | 1 |" in md
    assert "| Combined conversion impact | 5.30% |" in md
    assert "| Primary failure domain | PricingArchitect |" in md
    assert "| 1 | 🔴 Critical | PricingArchitect | Metro Pro |" in md
    assert "price ceiling too low" in md
    assert "| 2 | 🟠 Warning | RetentionArchitect | Budget Families |" in md
    assert "## Recommended Actions" in md
    assert "**Lower price, add EMI option, or add free tier**" in md
    assert "**Add gamification, content freshness, re-engagement**" in md
    assert "`Metro Pro`" in md


def test_findings_to_markdown_escapes_pipes_and_handles_empty() -> None:
    md = findings_to_markdown(
        [
            {
                "severity": "CRITICAL",
                "architect_name": "Pricing|Architect",
                "cluster_name": "Metro Pro",
                "finding": "two | pipes",
                "recommended_action": "Act",
                "conversion_impact": 0.01,
            }
        ],
        project_id=1,
    )

    assert "Pricing\\|Architect" in md
    assert "two \\| pipes" in md

    empty_md = findings_to_markdown([], project_id=1)
    assert "No domain findings available." in empty_md
    assert "| Total findings | 0 |" in empty_md


def test_findings_to_markdown_suppresses_table_when_max_rows_zero() -> None:
    md = findings_to_markdown(
        [_finding(), _finding()],
        project_id=1,
        max_table_rows=0,
    )

    assert "| Total findings | 2 |" in md
    assert "## Top Findings" in md
    assert "| # | Severity | Architect | Cluster | Finding | Impact |" not in md
    assert "PricingArchitect" not in md
    assert "## Recommended Actions" in md
    assert "**TIGHTEN**" in md


def test_findings_to_markdown_negative_max_rows_is_safe() -> None:
    md = findings_to_markdown(
        [_finding()],
        project_id=1,
        max_table_rows=-3,
    )

    assert "| Total findings | 1 |" in md
    assert "| # | Severity | Architect | Cluster | Finding | Impact |" not in md
    assert "## Recommended Actions" in md


def test_findings_to_markdown_counts_unknown_severities_in_summary() -> None:
    md = findings_to_markdown(
        [
            {
                "severity": "BLOCKER",
                "architect_name": "PricingArchitect",
                "cluster_name": "Metro Pro",
                "finding": "edge case",
                "recommended_action": "Review",
                "conversion_impact": 0.01,
            }
        ],
        project_id=1,
    )

    assert "| Total findings | 1 |" in md
    assert "| Other | 1 |" in md
    assert "🔴 Critical" not in md
    assert "—" in md
