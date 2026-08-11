"""Pure-helper tests for the risk-register CSV/JSON export module."""

from __future__ import annotations

import json

from app.schemas.risk_register import RiskRegisterOut
from app.simulation.risk_register_export import (
    risk_register_to_csv,
    risk_register_to_json,
)


def _payload() -> dict:
    return {
        "project_id": 10,
        "generated_at": "2026-08-11T12:00:00+00:00",
        "total_risks": 2,
        "top_risk_count": 2,
        "overall_risk_level": "HIGH",
        "top_risk_score": 0.63,
        "severity_breakdown": {
            "CRITICAL": 1,
            "MAJOR": 0,
            "MINOR": 1,
            "INFO": 0,
        },
        "source_breakdown": {
            "STRESS_TEST": 1,
            "SIMULATION_FINDING": 1,
            "PRE_MORTEM": 0,
            "COMPETITIVE": 0,
        },
        "risks": [
            {
                "id": "stress-1",
                "source": "STRESS_TEST",
                "category": "PRICING",
                "title": "Premium pricing kill shot",
                "description": "Users refuse to pay for premium",
                "severity": "CRITICAL",
                "probability": 0.7,
                "impact": 0.9,
                "risk_score": 0.63,
                "recommended_action": "A/B test the price",
                "metric": "conversion_delta_pct",
            },
            {
                "id": "sim-1",
                "source": "SIMULATION_FINDING",
                "category": "TRUST",
                "title": "Trust barrier",
                "description": "Cluster A distrusts the brand",
                "severity": "MINOR",
                "probability": 0.3,
                "impact": 0.35,
                "risk_score": 0.105,
                "recommended_action": "Add social proof",
                "metric": None,
            },
        ],
        "narrative": "2 risk(s) identified across 2 source(s); 1 critical.",
        "key_signals": [
            {
                "label": "overall_risk_level",
                "value": "HIGH",
                "severity": "critical",
                "display": "Overall risk: high",
            },
            {
                "label": "total_risks",
                "value": 2,
                "severity": "watch",
                "display": "2 risk(s) on the register",
            },
        ],
    }


def test_csv_contains_metadata_and_summary() -> None:
    csv_text = risk_register_to_csv(
        _payload(),
        metadata={
            "generated_at": "2026-08-11T12:00:00+00:00",
            "project_id": 10,
            "user_id": 42,
            "format_version": "1",
        },
    )

    assert "generated_at,2026-08-11T12:00:00+00:00" in csv_text
    assert "project_id,10" in csv_text
    assert "user_id,42" in csv_text
    assert "section,Risk Register Summary" in csv_text
    assert "total_risks,2" in csv_text
    assert "overall_risk_level,HIGH" in csv_text
    assert "top_risk_score,0.63" in csv_text


def test_csv_renders_breakdowns_risks_and_key_signals() -> None:
    csv_text = risk_register_to_csv(_payload())

    assert "section,Severity Breakdown" in csv_text
    assert "CRITICAL,1" in csv_text
    assert "MINOR,1" in csv_text
    assert "section,Source Breakdown" in csv_text
    assert "STRESS_TEST,1" in csv_text
    assert "SIMULATION_FINDING,1" in csv_text
    assert "section,Risks" in csv_text
    assert (
        "id,source,category,title,description,severity,probability,impact,"
        "risk_score,recommended_action,metric" in csv_text
    )
    assert "stress-1,STRESS_TEST,PRICING,Premium pricing kill shot" in csv_text
    assert "0.7,0.9,0.63,A/B test the price,conversion_delta_pct" in csv_text
    assert "section,Key Signals" in csv_text
    assert "overall_risk_level,HIGH,critical,Overall risk: high" in csv_text


def test_csv_empty_payload_keeps_headers_and_sections() -> None:
    csv_text = risk_register_to_csv(
        {
            "project_id": 7,
            "generated_at": "",
            "total_risks": 0,
            "top_risk_count": 0,
            "overall_risk_level": "LOW",
            "top_risk_score": None,
            "severity_breakdown": {},
            "source_breakdown": {},
            "risks": [],
            "narrative": "No risks identified yet",
            "key_signals": [],
        }
    )

    assert "section,Risk Register Summary" in csv_text
    assert "section,Severity Breakdown" in csv_text
    assert "section,Source Breakdown" in csv_text
    assert "section,Risks" in csv_text
    assert (
        "id,source,category,title,description,severity,probability,impact,"
        "risk_score,recommended_action,metric" in csv_text
    )
    assert "section,Key Signals" in csv_text
    assert "top_risk_score," in csv_text


def test_csv_neutralizes_spreadsheet_formula_injection() -> None:
    payload = _payload()
    payload["risks"][0]["title"] = '=HYPERLINK("http://evil")'
    payload["narrative"] = "  +SUM(A1:A9)"

    csv_text = risk_register_to_csv(payload)

    assert "'=HYPERLINK(" in csv_text
    assert "'  +SUM(A1:A9)" in csv_text
    assert "http://evil" in csv_text


def test_json_round_trips_payload() -> None:
    payload = _payload()
    metadata = {
        "generated_at": "2026-08-11T12:00:00+00:00",
        "project_id": 10,
        "user_id": 42,
        "format_version": "1",
    }

    json_text = risk_register_to_json(payload, metadata=metadata)
    parsed = json.loads(json_text)

    assert parsed["metadata"]["user_id"] == 42
    assert parsed["risk_register"]["overall_risk_level"] == "HIGH"
    assert len(parsed["risk_register"]["risks"]) == 2
    assert parsed["risk_register"]["key_signals"][0]["label"] == ("overall_risk_level")


def test_helper_accepts_pydantic_model() -> None:
    model = RiskRegisterOut(**_payload())

    csv_text = risk_register_to_csv(model, metadata={"project_id": 10})

    assert "project_id,10" in csv_text
    assert "stress-1" in csv_text


def test_export_module_all_contract() -> None:
    from app.simulation import risk_register_export

    assert set(risk_register_export.__all__) == {
        "risk_register_to_csv",
        "risk_register_to_json",
    }
