"""Tests for the unit-economics export helper and route."""
from __future__ import annotations

import asyncio
import sys
import types

import pytest
from fastapi import HTTPException

from app.schemas.unit_economics import UnitEconomicsOut
from app.simulation.unit_economics_export import unit_economics_to_csv


def _payload() -> UnitEconomicsOut:
    return UnitEconomicsOut(
        simulation_id=1,
        project_id=2,
        status="COMPLETED",
        signal_quality=0.62,
        product_type="saas",
        aov=999.0,
        gross_margin=0.6,
        purchase_frequency_per_year=12.0,
        base_cac=250.0,
        effective_base_cac=250.0,
        blended_price=899.0,
        blended_monthly_contribution=500.0,
        blended_lifetime_months=18.0,
        blended_ltv=9000.0,
        blended_cac=250.0,
        blended_ltv_cac_ratio=36.0,
        blended_payback_months=0.5,
        affordable_cac_ceiling=3000.0,
        verdict="STRONG",
        strong_share=0.8,
        profitable_share=0.9,
        unprofitable_share=0.1,
        at_ceiling_share=0.2,
        best_cluster_id="c1",
        best_cluster_name="Cluster One",
        worst_cluster_id="c2",
        worst_cluster_name="Cluster Two",
        total_clusters=52,
        clusters_with_data=52,
        cluster_profiles=[
            {
                "cluster_id": "c1",
                "cluster_name": "Cluster One",
                "population_weight": 0.2,
                "conversion_rate": 0.08,
                "demand_weight": 0.3,
                "effective_price": 899.0,
                "price_ceiling": 999.0,
                "will_pay_probability": 0.9,
                "monthly_contribution": 500.0,
                "average_lifetime_months": 24.0,
                "ltv": 12000.0,
                "cac": 150.0,
                "cac_multiplier": 0.6,
                "primary_channel": "organic",
                "ltv_cac_ratio": 80.0,
                "payback_months": 0.3,
                "affordable_cac": 3000.0,
                "verdict": "STRONG",
            }
        ],
        cac_scenarios=[
            {"label": "0.5x", "cac_multiplier": 0.5, "blended_cac": 125.0, "blended_ltv_cac_ratio": 72.0},
            {"label": "1.0x", "cac_multiplier": 1.0, "blended_cac": 250.0, "blended_ltv_cac_ratio": 36.0},
        ],
        price_scenarios=[
            {"label": "PRICE_DOWN_20", "price_multiplier": 0.8, "blended_price": 799.0, "blended_ltv": 8000.0, "blended_ltv_cac_ratio": 32.0, "capped_share": 0.1},
            {"label": "BASE_PRICE", "price_multiplier": 1.0, "blended_price": 899.0, "blended_ltv": 9000.0, "blended_ltv_cac_ratio": 36.0, "capped_share": 0.2},
        ],
        recommendations=[
            "Blended LTV:CAC of 36.0 is healthy — defend retention and keep CAC inside the ceiling.",
            "Best unit economics: Cluster One (80.0 LTV:CAC, 0.3 mo payback) via organic — a double-down candidate.",
        ],
    )


def test_csv_renders_summary_clusters_scenarios_and_recommendations() -> None:
    csv_text = unit_economics_to_csv(
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
    assert "section,Unit Economics Summary" in csv_text
    assert "verdict,STRONG" in csv_text
    assert "blended_ltv_cac_ratio,36.0" in csv_text
    assert "best_cluster_name,Cluster One" in csv_text
    assert "section,Cluster Unit Economics" in csv_text
    assert "c1,Cluster One,0.2,0.08,0.3,899.0,999.0,0.9,500.0,24.0,12000.0,150.0,0.6,organic,80.0,0.3,3000.0,STRONG" in csv_text
    assert "section,CAC Scenarios" in csv_text
    assert "0.5x,0.5,125.0,72.0" in csv_text
    assert "section,Price Scenarios" in csv_text
    assert "PRICE_DOWN_20,0.8,799.0,8000.0,32.0,0.1" in csv_text
    assert "section,Recommendations" in csv_text
    assert "Blended LTV:CAC of 36.0 is healthy" in csv_text


def test_csv_empty_payload_still_renders_sections() -> None:
    csv_text = unit_economics_to_csv(UnitEconomicsOut(simulation_id=0, project_id=0))

    assert "section,Unit Economics Summary" in csv_text
    assert "section,Cluster Unit Economics" in csv_text
    assert "section,CAC Scenarios" in csv_text
    assert "section,Price Scenarios" in csv_text
    assert "section,Recommendations" in csv_text
    assert "cluster_id,cluster_name,population_weight" in csv_text
    assert "label,cac_multiplier,blended_cac,blended_ltv_cac_ratio" in csv_text


def test_csv_handles_missing_optional_blocks() -> None:
    csv_text = unit_economics_to_csv(
        {
            "simulation_id": 7,
            "project_id": 8,
            "status": "COMPLETED",
            "verdict": "INSUFFICIENT_DATA",
            "total_clusters": 0,
            "clusters_with_data": 0,
        }
    )

    assert "simulation_id,7" in csv_text
    assert "verdict,INSUFFICIENT_DATA" in csv_text
    assert "cluster_profiles" not in csv_text
    assert "recommendations" not in csv_text
    assert "section,Recommendations" in csv_text


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
    payload: UnitEconomicsOut | None = None,
):
    sim_mod = _import_simulations_module()
    fake_payload = payload if payload is not None else _payload()
    monkeypatch.setattr(
        sim_mod,
        "_build_unit_economics_payload",
        lambda **kwargs: fake_payload,
    )
    return sim_mod.export_unit_economics(
        simulation_id=simulation_id,
        format=format,
        db=object(),  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )


def test_export_route_returns_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _call_route(monkeypatch)

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="unit-economics.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "section,Unit Economics Summary" in body
    assert "verdict,STRONG" in body
    assert "section,Cluster Unit Economics" in body
    assert "c1,Cluster One,0.2" in body
    assert "section,CAC Scenarios" in body
    assert "section,Price Scenarios" in body


def test_export_route_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _call_route(monkeypatch, format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    assert 'filename="unit-economics.json"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert '"metadata"' in body
    assert '"unit_economics"' in body
    assert '"simulation_id"' in body
    assert '"verdict"' in body


def test_export_route_rejects_unknown_format(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _call_route(monkeypatch, format="yaml")

    assert exc_info.value.status_code == 400
    assert "unsupported export format" in exc_info.value.detail


def test_export_route_registered() -> None:
    """The unit-economics export route is present in the router."""
    sim_mod = _import_simulations_module()
    paths = [r.path for r in sim_mod.router.routes]
    assert "/simulations/{simulation_id}/unit-economics/export" in paths
