"""Tests for the stress-scenario resilience exports (CSV / JSON / Markdown).

The export reuses the exact payload produced by
``ScenarioStressAnalyzer.to_dict``; these tests pin the section layout,
formula-injection guarding, non-finite-number handling, strict JSON
envelope, and the founder-facing Markdown brief.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.simulation.stress_scenarios_export import (  # noqa: E402
    FORMAT_VERSION,
    stress_scenarios_to_csv,
    stress_scenarios_to_json,
    stress_scenarios_to_markdown,
)


def _payload(**overrides) -> dict:
    data = {
        "simulation_id": 77,
        "base_conversion_rate": 0.24,
        "overall_resilience_score": 61.5,
        "most_vulnerable_scenario": "RECESSION",
        "most_resilient_scenario": "VIRAL_CATALYST",
        "scenario_impacts": [
            {
                "scenario_key": "RECESSION",
                "scenario_name": "Recession",
                "description": "Purchasing power contraction.",
                "projected_conversion_rate": 0.18,
                "conversion_delta_pct": -0.25,
                "vulnerability_score": 0.72,
                "risk_level": "SEVERE",
                "impact_summary": "Price-sensitive clusters abandon cart.",
                "mitigation_recommendation": "Introduce a down-tier plan.",
            },
            {
                "scenario_key": "PRICE_WAR",
                "scenario_name": "Side idea | notes",
                "description": "Incumbents slash prices.",
                "projected_conversion_rate": 0.21,
                "conversion_delta_pct": -0.125,
                "vulnerability_score": 0.4,
                "risk_level": "HIGH",
                "impact_summary": "Switching friction erodes.",
                "mitigation_recommendation": "=SUM(A1:A2)",
            },
        ],
    }
    data.update(overrides)
    return data


_METADATA = {
    "generated_at": "2026-08-23T10:30:00+00:00",
    "user_id": 42,
    "simulation_id": 77,
    "format_version": FORMAT_VERSION,
}


def _csv_lines(payload: dict, metadata: dict | None = _METADATA) -> list[str]:
    return stress_scenarios_to_csv(payload, metadata=metadata).splitlines()


def test_csv_renders_metadata_summary_and_impacts() -> None:
    lines = _csv_lines(_payload())

    assert lines[0] == "generated_at,2026-08-23T10:30:00+00:00"
    assert any(line == "format_version,1" for line in lines[:6])

    summary_at = lines.index("section,Resilience Summary")
    assert lines[summary_at + 1] == "key,value"
    assert "overall_resilience_score,61.5" in lines
    assert "most_vulnerable_scenario,RECESSION" in lines
    # Scenario count is derived from the impacts list.
    assert "scenario_count,2" in lines

    impacts_at = lines.index("section,Scenario Impacts")
    assert lines[impacts_at + 1] == (
        "scenario_key,scenario_name,description,projected_conversion_rate,"
        "conversion_delta_pct,vulnerability_score,risk_level,impact_summary,"
        "mitigation_recommendation"
    )
    assert (
        "RECESSION,Recession,Purchasing power contraction.,0.18,-0.25,"
        "0.72,SEVERE,Price-sensitive clusters abandon cart.,"
        "Introduce a down-tier plan."
    ) in lines


def test_csv_guards_formulas_and_blanks_non_finite_numbers() -> None:
    payload = _payload()
    payload["scenario_impacts"][1]["mitigation_recommendation"] = "=SUM(A1:A2)"
    payload["scenario_impacts"][1]["vulnerability_score"] = float("nan")
    payload["overall_resilience_score"] = float("nan")

    body = stress_scenarios_to_csv(payload, metadata=_METADATA)

    assert "'=SUM(A1:A2)" in body
    # NaN renders as an empty cell, never as Python's 'nan' text.
    assert ",nan," not in body
    lines = body.splitlines()
    summary_row = next(
        line for line in lines if line.startswith("overall_resilience_score,")
    )
    assert summary_row == "overall_resilience_score,"


def test_csv_handles_empty_scenario_list() -> None:
    lines = _csv_lines(_payload(scenario_impacts=[]), metadata=None)

    assert "scenario_count,0" in lines
    impacts_at = lines.index("section,Scenario Impacts")
    # Only header follows — no rows, no crash.
    assert lines[impacts_at + 2] == ""
    assert all(not line.startswith("RECESSION") for line in lines)


def test_json_envelope_is_strict_and_stable() -> None:
    payload = _payload()
    payload["scenario_impacts"][0]["vulnerability_score"] = float("inf")

    text = stress_scenarios_to_json(payload, metadata=_METADATA)
    assert text.endswith("\n")

    parsed = json.loads(text)
    assert set(parsed) == {"metadata", "stress_scenarios"}
    assert parsed["metadata"]["format_version"] == "1"
    envelope = parsed["stress_scenarios"]
    assert envelope["most_resilient_scenario"] == "VIRAL_CATALYST"
    # allow_nan=False would have raised; inf was replaced by None instead.
    assert envelope["scenario_impacts"][0]["vulnerability_score"] is None


def test_markdown_brief_renders_headlines_and_table() -> None:
    body = stress_scenarios_to_markdown(_payload(), metadata=_METADATA)

    assert body.startswith("# Stress Scenarios")
    assert "*Generated: 2026-08-23*" in body
    assert "T10:30" not in body  # date-only rendering, no time leakage

    assert "| Base conversion rate | 0.24 |" in body
    assert "| Resilience score (/100) | 61.5 |" in body
    assert "| Scenarios evaluated | 2 |" in body

    # Δ% and vulnerability render as percentages; pipes are escaped and
    # mitigation text passes through unguarded (the guard is CSV-only).
    assert "| Recession | SEVERE | 0.18 | -25.0% | 72.0% | Introduce a down-tier plan. |" in body
    assert "| Side idea \\| notes | HIGH | 0.21 | -12.5% | 40.0% | =SUM(A1:A2) |" in body

    assert "*Stress scenarios · Simulation 77 · Generated 2026-08-23*" in body


def test_markdown_brief_empty_fallback() -> None:
    body = stress_scenarios_to_markdown(
        _payload(scenario_impacts=[]),
        metadata=None,
    )

    assert "_No scenarios returned._" in body
    assert "| Scenarios evaluated | 0 |" in body


def test_markdown_brief_dash_for_non_finite_numbers() -> None:
    payload = _payload()
    payload["scenario_impacts"][0]["vulnerability_score"] = float("nan")

    body = stress_scenarios_to_markdown(payload)

    # Vulnerability column (after Δ%) dashes; the rest of the row survives.
    assert "| -25.0% | — | Introduce a down-tier plan. |" in body
    assert "nan" not in body


def test_export_route_registered() -> None:
    from app.api.v1 import simulations as sim_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in sim_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    path = "/simulations/{simulation_id}/stress-scenarios/export"
    assert "GET" in methods_by_path.get(path, set())


def test_route_rejects_unsupported_format() -> None:
    """Bad format fails before the analysis (and any DB access) runs."""
    from fastapi import HTTPException

    from app.api.v1 import simulations as sim_mod

    class _Boom:
        def __getattr__(self, name):  # pragma: no cover - must never be hit
            raise AssertionError("DB accessed before format validation")

    with pytest.raises(HTTPException) as exc:
        sim_mod.export_simulation_stress_scenarios(
            simulation_id=77,
            format="xlsx",
            db=_Boom(),  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )

    assert exc.value.status_code == 400
    assert "unsupported export format" in exc.value.detail
