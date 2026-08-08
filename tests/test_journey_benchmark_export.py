"""Tests for the journey-benchmark export helpers and route.

Covers the multi-section CSV rendering, the JSON envelope, spreadsheet
formula-injection guarding, malformed-payload resilience, and the
``GET /api/v1/simulations/{id}/journey/benchmark/export`` route gates.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest
from fastapi import HTTPException

# ``app.api.v1`` eagerly imports the billing router, which imports the
# razorpay SDK. Stub it the same way the existing route-level tests do so we
# can import the simulations module in environments without the package.
if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.schemas.journey_benchmark import (  # noqa: E402
    JourneyBenchmarkOut,
    JourneyCategoryBenchmarkOut,
)
from app.simulation.journey_benchmark_export import (  # noqa: E402
    FORMAT_VERSION,
    journey_benchmark_to_csv,
    journey_benchmark_to_json,
)


def _payload(*, category: str | None = None) -> dict:
    payload = {
        "simulation_id": 1,
        "project_id": 10,
        "cohort_size": 2,
        "current": {
            "purchase_probability": 0.060933,
            "abandon_probability": 0.939067,
            "expected_steps_to_absorb": 2.7798,
            "expected_revisits": 0.12,
            "primary_exit_stage": "BROWSE",
            "exit_stage_distribution": {
                "ARRIVE": 0.1,
                "BROWSE": 0.5,
                "CONSIDER": 0.25,
                "DECIDE": 0.089,
            },
        },
        "distribution": {
            "median_purchase_probability": 0.051,
            "mean_purchase_probability": 0.055,
            "p25_purchase_probability": 0.031,
            "p75_purchase_probability": 0.078,
            "min_purchase_probability": 0.012,
            "max_purchase_probability": 0.095,
            "median_expected_steps": 3.1,
            "median_expected_revisits": 0.18,
            "most_common_primary_exit_stage": "BROWSE",
            "stage_leak_medians": {
                "ARRIVE": 0.08,
                "BROWSE": 0.35,
                "CONSIDER": 0.2,
                "DECIDE": 0.09,
            },
        },
        "percentile_rank": 50.0,
        "insights": [
            "Ranks above 50.0% of previous journey-capable simulations.",
            "The funnel leaks most heavily at BROWSE.",
        ],
        "meta": {
            "raw_completed_count": 3,
            "skipped_without_journey_data": 1,
        },
    }
    if category is not None:
        payload["category"] = category
    return payload


def _portfolio_model() -> JourneyBenchmarkOut:
    return JourneyBenchmarkOut.model_validate(_payload())


def _category_model() -> JourneyCategoryBenchmarkOut:
    return JourneyCategoryBenchmarkOut.model_validate(_payload(category="saas"))


# ---------------------------------------------------------------------------
# CSV rendering
# ---------------------------------------------------------------------------


def test_csv_renders_metadata_and_current_section() -> None:
    csv_text = journey_benchmark_to_csv(
        _portfolio_model(),
        metadata={
            "generated_at": "2026-08-08T12:00:00+00:00",
            "user_id": 42,
            "simulation_id": 1,
            "project_id": 10,
            "scope": "portfolio",
            "category": None,
        },
    )

    assert csv_text.startswith("generated_at,")
    assert "simulation_id,1" in csv_text
    assert "project_id,10" in csv_text
    assert "scope,portfolio" in csv_text
    assert "section,Current Funnel" in csv_text
    assert "purchase_probability,0.060933" in csv_text
    assert "abandon_probability,0.939067" in csv_text
    assert "primary_exit_stage,BROWSE" in csv_text


def test_csv_renders_distribution_and_stage_leak_comparison() -> None:
    csv_text = journey_benchmark_to_csv(_portfolio_model())

    assert "section,Cohort Distribution" in csv_text
    assert "median_purchase_probability,0.051" in csv_text
    assert "max_purchase_probability,0.095" in csv_text
    assert "cohort_size,2" in csv_text
    assert "percentile_rank,50.0" in csv_text
    assert "section,Stage Leak Comparison" in csv_text
    assert "BROWSE,0.5,0.35,0.15" in csv_text
    assert "DECIDE,0.089,0.09,-0.001" in csv_text


def test_csv_renders_insights_and_meta() -> None:
    csv_text = journey_benchmark_to_csv(_portfolio_model())

    assert "section,Insights" in csv_text
    assert "Ranks above 50.0%" in csv_text
    assert "section,Meta" in csv_text
    assert "raw_completed_count,3" in csv_text
    assert "skipped_without_journey_data,1" in csv_text


def test_csv_guards_spreadsheet_formula_injection() -> None:
    payload = _payload()
    payload["insights"] = ['=HYPERLINK("https://evil.example")']
    payload["current"]["primary_exit_stage"] = " \t+SUM(A1:A2)"
    payload["distribution"]["most_common_primary_exit_stage"] = "@SUM(A1:A2)"

    csv_text = journey_benchmark_to_csv(payload)

    assert "'=HYPERLINK" in csv_text
    assert "' \t+SUM(A1:A2)" in csv_text
    assert "'@SUM(A1:A2)" in csv_text


def test_csv_handles_malformed_payload_without_raising() -> None:
    csv_text = journey_benchmark_to_csv(
        {
            "current": "junk",
            "distribution": None,
            "percentile_rank": float("nan"),
            "cohort_size": float("inf"),
            "insights": None,
            "meta": {
                "raw_completed_count": float("inf"),
                "skipped_without_journey_data": 1e999,
                "sample_limit": "n/a",
            },
        }
    )

    assert "section,Current Funnel" in csv_text
    assert "purchase_probability,0.0" in csv_text
    assert "section,Cohort Distribution" in csv_text
    assert "cohort_size,0" in csv_text
    assert "section,Stage Leak Comparison" in csv_text
    assert "section,Insights" in csv_text
    assert "section,Meta" in csv_text
    assert "raw_completed_count,0" in csv_text
    assert "skipped_without_journey_data,0" in csv_text
    assert "sample_limit,0" in csv_text


def test_csv_ignores_non_dict_metadata_without_raising() -> None:
    csv_text = journey_benchmark_to_csv(_payload(), metadata=["not", "a", "dict"])

    assert not csv_text.startswith("generated_at,")
    assert "section,Current Funnel" in csv_text

    no_metadata = journey_benchmark_to_csv(_payload(), metadata=None)
    assert no_metadata.startswith("section,Current Funnel")


# ---------------------------------------------------------------------------
# JSON rendering
# ---------------------------------------------------------------------------


def test_json_renders_envelope_with_payload() -> None:
    text = journey_benchmark_to_json(
        _portfolio_model(),
        metadata={"format_version": FORMAT_VERSION, "scope": "portfolio"},
    )
    data = json.loads(text)

    assert data["metadata"]["format_version"] == "1"
    assert data["metadata"]["scope"] == "portfolio"
    assert data["journey_benchmark"]["simulation_id"] == 1
    assert data["journey_benchmark"]["current"]["purchase_probability"] == pytest.approx(
        0.060933
    )
    assert data["journey_benchmark"]["distribution"]["median_purchase_probability"] == (
        pytest.approx(0.051)
    )
    assert text.endswith("\n")


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


def _user() -> object:
    return type("U", (), {"id": 42})()


async def _body_bytes(response: object) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def _call_export(
    *,
    simulation_id: int = 1,
    format: str = "csv",
    scope: str = "portfolio",
    limit: int = 200,
    db: object | None = None,
    current_user: object | None = None,
):
    from app.api.v1 import simulations as sim_mod

    return sim_mod.export_simulation_journey_benchmark(
        simulation_id=simulation_id,
        format=format,
        scope=scope,
        limit=limit,
        db=db,
        current_user=current_user or _user(),
    )


def test_export_route_returns_csv_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import simulations as sim_mod

    calls: dict = {}

    def fake_portfolio(**kwargs):
        calls.update(kwargs)
        return _portfolio_model()

    monkeypatch.setattr(sim_mod, "get_simulation_journey_benchmark", fake_portfolio)

    response = _call_export()
    body = asyncio.run(_body_bytes(response)).decode()

    assert response.media_type == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="journey-benchmark.csv"'
    )
    assert calls["simulation_id"] == 1
    assert "section,Current Funnel" in body
    assert "section,Cohort Distribution" in body
    assert "section,Stage Leak Comparison" in body
    assert "Ranks above 50.0%" in body


def test_export_route_returns_json_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import simulations as sim_mod

    monkeypatch.setattr(
        sim_mod,
        "get_simulation_journey_benchmark",
        lambda **kwargs: _portfolio_model(),
    )

    response = _call_export(format="json")
    body = asyncio.run(_body_bytes(response)).decode()
    data = json.loads(body)

    assert response.media_type == "application/json; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="journey-benchmark.json"'
    )
    assert data["metadata"]["scope"] == "portfolio"
    assert data["metadata"]["user_id"] == 42
    assert data["journey_benchmark"]["percentile_rank"] == pytest.approx(50.0)


def test_export_route_uses_category_scope_and_passes_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import simulations as sim_mod

    calls: dict = {}

    def fake_category(**kwargs):
        calls.update(kwargs)
        return _category_model()

    monkeypatch.setattr(
        sim_mod,
        "get_simulation_journey_category_benchmark",
        fake_category,
    )

    response = _call_export(scope="category", limit=50, format="json")
    body = asyncio.run(_body_bytes(response)).decode()
    data = json.loads(body)

    assert calls["limit"] == 50
    assert calls["simulation_id"] == 1
    assert data["metadata"]["scope"] == "category"
    assert data["metadata"]["category"] == "saas"
    assert data["journey_benchmark"]["category"] == "saas"


def test_export_route_rejects_unsupported_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import simulations as sim_mod

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("benchmark builder must not run for bad format")

    monkeypatch.setattr(sim_mod, "get_simulation_journey_benchmark", _must_not_be_called)

    with pytest.raises(HTTPException) as exc:
        _call_export(format="xml")
    assert exc.value.status_code == 400
    assert "expected 'csv' or 'json'" in exc.value.detail


def test_export_route_rejects_unsupported_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import simulations as sim_mod

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("benchmark builder must not run for bad scope")

    monkeypatch.setattr(sim_mod, "get_simulation_journey_benchmark", _must_not_be_called)

    with pytest.raises(HTTPException) as exc:
        _call_export(scope="industry")
    assert exc.value.status_code == 400
    assert "expected 'portfolio' or 'category'" in exc.value.detail


def test_export_route_propagates_endpoint_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import simulations as sim_mod

    def fake_portfolio(**kwargs):
        raise HTTPException(status_code=404, detail="Simulation not found")

    monkeypatch.setattr(sim_mod, "get_simulation_journey_benchmark", fake_portfolio)

    with pytest.raises(HTTPException) as exc:
        _call_export()
    assert exc.value.status_code == 404
    assert "Simulation not found" in exc.value.detail
