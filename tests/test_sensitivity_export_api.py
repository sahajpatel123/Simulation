"""Tests for the sensitivity-analysis export helper and route."""
from __future__ import annotations

import asyncio
import sys
import types

import pytest
from fastapi import HTTPException

from app.schemas.sensitivity import (
    AssumptionSensitivity,
    SensitivityOut,
    SensitivitySummary,
)
from app.simulation.sensitivity_export import (
    sensitivity_to_csv,
    sensitivity_to_json,
)


def _payload() -> SensitivityOut:
    return SensitivityOut(
        simulation_id=1,
        project_id=2,
        status="COMPLETED",
        baseline_conversion=0.031,
        baseline_revenue_per_1000=30.97,
        summary=SensitivitySummary(
            total_assumptions=1,
            baseline_conversion=0.031,
            most_sensitive_assumption="Price is critical for adoption",
            most_sensitive_score=0.42,
            critical_assumptions=1,
            high_assumptions=0,
            medium_assumptions=0,
            low_assumptions=0,
            avg_sensitivity_score=0.42,
        ),
        assumptions=[
            AssumptionSensitivity(
                assumption_text="Price is critical for adoption",
                sensitivity="HIGH",
                baseline_impact_score=7.0,
                baseline_conversion=0.031,
                max_delta=-0.013,
                sensitivity_score=0.42,
                sensitivity_tier="CRITICAL",
                curve=[],
                triggers_markov_rules=True,
                affected_transitions=["DECIDE->PURCHASE"],
                recommendation="Validate willingness to pay first.",
            )
        ],
        recommendations=[
            "1 assumption(s) have CRITICAL sensitivity — validate 'Price is critical for adoption' first.",
            "Non-triggering assumption count: 0",
        ],
        product_type_detected="saas",
        signal_quality=0.62,
        meta={
            "generated_at": "now",
            "impact_levels": [0.0, 0.25, 0.5, 0.75, 1.0],
            "assumption_count": 1,
        },
    )


def test_csv_renders_summary_assumptions_and_recommendations() -> None:
    csv_text = sensitivity_to_csv(
        _payload(),
        metadata={
            "generated_at": "now",
            "user_id": 42,
            "format_version": "1",
            "simulation_id": 1,
            "project_id": 2,
        },
    )

    assert "generated_at,now" in csv_text
    assert "user_id,42" in csv_text
    assert "simulation_id,1" in csv_text
    assert "project_id,2" in csv_text
    assert "section,Sensitivity Summary" in csv_text
    assert "most_sensitive_assumption,Price is critical for adoption" in csv_text
    assert "critical_assumptions,1" in csv_text
    assert "section,Assumption Sensitivity" in csv_text
    assert (
        "Price is critical for adoption,HIGH,7.0,0.031,-0.013,0.42,CRITICAL,"
        "True,DECIDE->PURCHASE,Validate willingness to pay first."
    ) in csv_text
    assert "section,Recommendations" in csv_text
    assert "CRITICAL sensitivity" in csv_text


def test_csv_empty_payload_still_renders_sections() -> None:
    csv_text = sensitivity_to_csv(
        SensitivityOut(
            simulation_id=0,
            project_id=0,
            summary=SensitivitySummary(),
        )
    )

    assert "section,Sensitivity Summary" in csv_text
    assert "section,Assumption Sensitivity" in csv_text
    assert "section,Recommendations" in csv_text
    assert "assumption_text,sensitivity,baseline_impact_score" in csv_text
    assert "recommendation" in csv_text


def test_csv_handles_missing_optional_blocks() -> None:
    csv_text = sensitivity_to_csv(
        {
            "simulation_id": 7,
            "project_id": 8,
            "status": "COMPLETED",
            "summary": {},
            "assumptions": [],
            "recommendations": [],
        }
    )

    assert "simulation_id,7" in csv_text
    assert "section,Assumption Sensitivity" in csv_text
    assert "section,Recommendations" in csv_text


def test_json_renders_metadata_and_payload() -> None:
    json_text = sensitivity_to_json(
        _payload(),
        metadata={
            "generated_at": "now",
            "user_id": 42,
            "format_version": "1",
            "simulation_id": 1,
            "project_id": 2,
        },
    )

    assert '"metadata"' in json_text
    assert '"sensitivity"' in json_text
    assert '"most_sensitive_assumption"' in json_text
    assert '"Price is critical for adoption"' in json_text


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------


def _import_simulations_module():
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub
    from app.api.v1 import simulations as sim_mod

    return sim_mod


async def _collect(resp) -> bytes:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def _body(resp) -> bytes:
    return asyncio.run(_collect(resp))


def _call_route(
    monkeypatch: pytest.MonkeyPatch,
    *,
    simulation_id: int = 1,
    format: str = "csv",
    payload: SensitivityOut | None = None,
):
    sim_mod = _import_simulations_module()
    fake_payload = payload if payload is not None else _payload()

    def _fake_get_sensitivity(**kwargs: object) -> SensitivityOut:
        return fake_payload

    monkeypatch.setattr(
        sim_mod,
        "get_sensitivity_analysis",
        _fake_get_sensitivity,
    )
    return sim_mod.export_sensitivity_analysis(
        simulation_id=simulation_id,
        format=format,
        db=object(),  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )


def test_export_route_returns_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _call_route(monkeypatch)

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="sensitivity.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "section,Sensitivity Summary" in body
    assert "critical_assumptions,1" in body
    assert "section,Assumption Sensitivity" in body
    assert "Price is critical for adoption,HIGH" in body
    assert "section,Recommendations" in body


def test_export_route_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _call_route(monkeypatch, format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    assert 'filename="sensitivity.json"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert '"metadata"' in body
    assert '"sensitivity"' in body
    assert '"most_sensitive_assumption"' in body


def test_export_route_rejects_unknown_format(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _call_route(monkeypatch, format="yaml")

    assert exc_info.value.status_code == 400
    assert "unsupported export format" in exc_info.value.detail


def test_export_route_unknown_format_fails_before_payload_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unsupported format must not pay for the expensive payload build."""
    sim_mod = _import_simulations_module()
    calls: list[object] = []

    def _forbidden_get(**kwargs: object) -> object:
        calls.append(kwargs)
        raise AssertionError("payload builder should not run for bad format")

    monkeypatch.setattr(sim_mod, "get_sensitivity_analysis", _forbidden_get)

    with pytest.raises(HTTPException) as exc_info:
        sim_mod.export_sensitivity_analysis(
            simulation_id=1,
            format="yaml",
            db=object(),  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )

    assert exc_info.value.status_code == 400
    assert calls == []
