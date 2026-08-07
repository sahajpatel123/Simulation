"""Tests for the pure findings-export helpers."""
from __future__ import annotations

from app.simulation.findings_export import extract_findings, findings_to_csv


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
