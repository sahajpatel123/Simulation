"""Tests for the pricing-optimization export serializers and route."""

from __future__ import annotations

import asyncio
import json
import sys
import types
from typing import Any

import pytest
from fastapi import HTTPException

from app.schemas.pricing_optimization import (
    VERDICT_OVERPRICED,
    ClusterPriceProfile,
    PricePoint,
    PricingOptimizationOut,
)
from app.simulation.pricing_optimization_export import (
    FORMAT_VERSION,
    pricing_optimization_to_csv,
    pricing_optimization_to_json,
    pricing_optimization_to_markdown,
)


def _payload() -> PricingOptimizationOut:
    return PricingOptimizationOut(
        simulation_id=1,
        project_id=2,
        status="COMPLETED",
        product_type="saas",
        aov=999.0,
        base_price=999.0,
        base_market_conversion=0.031,
        base_market_revenue=30_969.0,
        revenue_optimal_price=499.5,
        revenue_at_optimal=34_200.0,
        revenue_lift_vs_base_pct=10.4,
        recommended_price=1248.75,
        overall_elasticity=-1.32,
        verdict=VERDICT_OVERPRICED,
        price_points=[
            PricePoint(
                price=249.75,
                market_conversion=0.045,
                market_revenue=11_238.75,
                demand_retained_pct=145.2,
            ),
            PricePoint(
                price=499.5,
                market_conversion=0.034,
                market_revenue=16_983.0,
                demand_retained_pct=109.7,
            ),
        ],
        cluster_profiles=[
            ClusterPriceProfile(
                cluster_id="c1",
                cluster_name="Budget Hunters",
                population_weight=0.12,
                price_ceiling=750.0,
                will_pay_probability=0.58,
                conversion_at_base_price=0.011,
                optimal_price=499.5,
                at_ceiling=True,
                ceiling_gap_pct=24.9,
            )
        ],
        recommendations=[
            "Lowering price from 999.00 toward 499.50 could add "
            "~10.4% cohort revenue — demand currently collapses before "
            "the base price is reached.",
            "Demand around the current price is elastic "
            "(arc elasticity -1.32): a ±20% price move shifts "
            "demand-weighted conversion materially.",
        ],
        key_signals=[
            {
                "label": "verdict",
                "value": VERDICT_OVERPRICED,
                "severity": "watch",
                "display": "Price strategy: Overpriced",
            }
        ],
        meta={
            "cohort_size": 10_000,
            "signal_quality": 0.62,
            "total_clusters": 52,
            "clusters_with_data": 48,
            "covered_weight": 0.94,
            "demand_retention_rule": 0.5,
            "elasticity_measurement": "arc_0.8x_to_1.2x",
        },
    )


def test_format_version_is_contract_constant() -> None:
    assert FORMAT_VERSION == "1"


def test_csv_has_summary_curve_profiles_and_recommendations() -> None:
    csv_text = pricing_optimization_to_csv(
        _payload(),
        metadata={
            "generated_at": "2026-08-10T00:00:00Z",
            "user_id": 42,
            "format_version": "1",
            "simulation_id": 1,
            "project_id": 2,
        },
    )

    assert "generated_at,2026-08-10T00:00:00Z" in csv_text
    assert "user_id,42" in csv_text
    assert "simulation_id,1" in csv_text
    assert "project_id,2" in csv_text
    assert "section,Pricing Optimization Summary" in csv_text
    assert "verdict,OVERPRICED" in csv_text
    assert "revenue_optimal_price,499.5" in csv_text
    assert "signal_quality,0.62" in csv_text
    assert "covered_weight,0.94" in csv_text
    assert "section,Demand Curve" in csv_text
    assert "249.75,0.045,11238.75,145.2" in csv_text
    assert "section,Cluster Price Profiles" in csv_text
    assert "c1,Budget Hunters,0.12,750.0,0.58,0.011,499.5,True,24.9" in csv_text
    assert "section,Recommendations" in csv_text
    assert "Lowering price from 999.00" in csv_text
    assert "section,Key Signals" in csv_text
    assert "verdict,OVERPRICED,watch,Price strategy: Overpriced" in csv_text
    assert "section,Meta" in csv_text
    assert "elasticity_measurement,arc_0.8x_to_1.2x" in csv_text


def test_csv_metadata_defaults_format_version_to_contract() -> None:
    csv_text = pricing_optimization_to_csv(
        _payload(),
        metadata={
            "generated_at": "2026-08-10T00:00:00Z",
            "user_id": 42,
        },
    )

    assert f"format_version,{FORMAT_VERSION}" in csv_text


def test_csv_empty_payload_still_renders_sections() -> None:
    csv_text = pricing_optimization_to_csv(
        PricingOptimizationOut(
            simulation_id=0,
            project_id=0,
            verdict="INSUFFICIENT_DATA",
        )
    )

    assert "section,Pricing Optimization Summary" in csv_text
    assert "section,Demand Curve" in csv_text
    assert "section,Cluster Price Profiles" in csv_text
    assert "section,Recommendations" in csv_text
    assert "section,Key Signals" in csv_text
    assert "price,market_conversion,market_revenue,demand_retained_pct" in csv_text
    assert "cluster_id,cluster_name,population_weight" in csv_text


def test_csv_handles_missing_optional_blocks() -> None:
    csv_text = pricing_optimization_to_csv(
        {
            "simulation_id": 7,
            "project_id": 8,
            "status": "COMPLETED",
            "price_points": [],
            "cluster_profiles": [],
            "recommendations": [],
            "key_signals": [],
        }
    )

    assert "simulation_id,7" in csv_text
    assert "section,Demand Curve" in csv_text
    assert "section,Cluster Price Profiles" in csv_text
    assert "section,Recommendations" in csv_text


@pytest.mark.parametrize(
    "malicious",
    ["=HYPERLINK('http://evil')", "+cmd", "-cmd", "@cmd", "\tcmd", "\rcmd"],
)
def test_csv_neutralises_formula_injection(malicious: str) -> None:
    payload = _payload()
    payload.cluster_profiles[0].cluster_name = malicious
    payload.recommendations = [malicious]

    csv_text = pricing_optimization_to_csv(payload)

    assert f"'{malicious}" in csv_text


def test_json_round_trips_payload() -> None:
    json_text = pricing_optimization_to_json(
        _payload(),
        metadata={"format_version": "1"},
    )
    parsed = json.loads(json_text)

    assert parsed["metadata"]["format_version"] == "1"
    assert parsed["pricing_optimization"]["simulation_id"] == 1
    assert parsed["pricing_optimization"]["project_id"] == 2
    assert parsed["pricing_optimization"]["verdict"] == VERDICT_OVERPRICED
    assert len(parsed["pricing_optimization"]["price_points"]) == 2
    assert len(parsed["pricing_optimization"]["cluster_profiles"]) == 1


def test_markdown_includes_summary_curve_and_recommendations() -> None:
    md = pricing_optimization_to_markdown(
        _payload(),
        simulation_id=1,
        project_id=2,
        project_name="Test Project",
        metadata={"generated_at": "2026-08-10T00:00:00Z"},
    )

    assert "# Test Project — Pricing Optimization" in md
    assert "## Summary" in md
    assert "## Demand Curve" in md
    assert "## Cluster Price Profiles" in md
    assert "## Recommendations" in md
    assert "## Key Signals" in md
    assert "Lowering price from 999.00" in md
    assert "Price strategy: Overpriced" in md
    assert "Simulation: 1" in md
    assert "Project: 2" in md


def test_markdown_escapes_pipe_characters() -> None:
    payload = _payload()
    payload.cluster_profiles[0].cluster_name = "Results | payload"
    payload.recommendations = ["Recommendation | pipe"]

    md = pricing_optimization_to_markdown(payload)

    assert "Results \\| payload" in md
    assert "Recommendation \\| pipe" in md


def test_markdown_handles_empty_items() -> None:
    md = pricing_optimization_to_markdown(
        {
            "simulation_id": 1,
            "project_id": 2,
            "price_points": [],
            "cluster_profiles": [],
            "recommendations": [],
            "key_signals": [],
        }
    )

    assert "## Demand Curve" in md
    assert "No demand-curve points are available." in md
    assert "No cluster price profiles are available." in md
    assert "No recommendations are currently available." in md
    assert "No key signals are currently available." in md


def test_csv_ignores_scalar_list_sections() -> None:
    csv_text = pricing_optimization_to_csv(
        {
            "simulation_id": 1,
            "project_id": 2,
            "price_points": "not-a-list",
            "cluster_profiles": None,
            "recommendations": "build now",
            "key_signals": 42,
        }
    )

    assert "demand_curve_points,0" in csv_text
    assert "cluster_profiles_count,0" in csv_text
    assert "recommendations_count,0" in csv_text
    assert "section,Demand Curve" in csv_text
    assert "section,Key Signals" in csv_text
    assert "b,build" not in csv_text
    assert "p,not-a-list" not in csv_text


def test_markdown_renders_zero_ids() -> None:
    md = pricing_optimization_to_markdown(
        {
            "simulation_id": 0,
            "project_id": 0,
            "price_points": [],
            "cluster_profiles": [],
            "recommendations": [],
            "key_signals": [],
        },
        simulation_id=0,
        project_id=0,
    )

    assert "- Simulation: 0" in md
    assert "- Project: 0" in md
    assert "- Simulation: —" not in md


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


async def _collect(resp: Any) -> bytes:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def _body(resp: Any) -> bytes:
    return asyncio.run(_collect(resp))


class _FakeProject:
    def __init__(self) -> None:
        self.id = 2
        self.title = "Test Project"


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else [_FakeProject()]

    def filter(self, *args: object, **kwargs: object) -> _FakeQuery:
        return self

    def first(self):
        return self.items[0] if self.items else None


class _FakeSession:
    def query(self, model: object, *args: object, **kwargs: object) -> _FakeQuery:
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery()
        return _FakeQuery([])


def _call_route(
    monkeypatch: pytest.MonkeyPatch,
    *,
    simulation_id: int = 1,
    format: str = "csv",
    payload: PricingOptimizationOut | None = None,
):
    sim_mod = _import_simulations_module()
    fake_payload = payload if payload is not None else _payload()

    def _fake_get_pricing_optimization(
        **kwargs: object,
    ) -> PricingOptimizationOut:
        return fake_payload

    monkeypatch.setattr(
        sim_mod,
        "get_pricing_optimization",
        _fake_get_pricing_optimization,
    )
    return sim_mod.export_pricing_optimization(
        simulation_id=simulation_id,
        format=format,
        db=_FakeSession(),  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )


def test_export_route_returns_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _call_route(monkeypatch)

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="pricing-optimization-1.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "section,Pricing Optimization Summary" in body
    assert "section,Demand Curve" in body
    assert "section,Cluster Price Profiles" in body
    assert "Lowering price from 999.00" in body


def test_export_route_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _call_route(monkeypatch, format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    assert 'filename="pricing-optimization-1.json"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert '"metadata"' in body
    assert '"pricing_optimization"' in body
    assert '"verdict": "OVERPRICED"' in body


def test_export_route_metadata_uses_format_version_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sim_mod = _import_simulations_module()
    monkeypatch.setattr(sim_mod, "FORMAT_VERSION", "9")

    resp = _call_route(monkeypatch, format="json")
    body = _body(resp).decode("utf-8")
    parsed = json.loads(body)

    assert parsed["metadata"]["format_version"] == "9"


def test_export_route_returns_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _call_route(monkeypatch, format="md")

    assert resp.media_type == "text/markdown; charset=utf-8"
    assert 'filename="pricing-optimization-1.md"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "## Demand Curve" in body
    assert "## Cluster Price Profiles" in body
    assert "## Recommendations" in body
    assert "## Key Signals" in body


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

    monkeypatch.setattr(sim_mod, "get_pricing_optimization", _forbidden_get)

    with pytest.raises(HTTPException) as exc_info:
        sim_mod.export_pricing_optimization(
            simulation_id=1,
            format="yaml",
            db=_FakeSession(),  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )

    assert exc_info.value.status_code == 400
    assert calls == []
