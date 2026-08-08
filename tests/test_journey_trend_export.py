"""Tests for the journey-trend export helpers and route.

Covers the multi-section CSV rendering, the JSON envelope, spreadsheet
formula-injection guarding, malformed-payload resilience, and the
``GET /api/v1/simulations/{id}/journey/trend/export`` route gates.
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

from app.schemas.journey_trend import JourneyTrendOut  # noqa: E402
from app.simulation.journey_analytics import summarise_journey_matrices  # noqa: E402
from app.simulation.journey_trend import build_journey_trend  # noqa: E402
from app.simulation.journey_trend_export import (  # noqa: E402
    FORMAT_VERSION,
    journey_trend_to_csv,
    journey_trend_to_json,
)


def _results() -> dict:
    return {
        "cluster_weights": {"c0": 0.6, "c1": 0.4},
        "per_cluster_matrices": {
            "c0": {
                "ARRIVE->BROWSE": 0.95,
                "BROWSE->CONSIDER": 0.80,
                "CONSIDER->DECIDE": 0.70,
                "DECIDE->PURCHASE": 0.50,
            },
            "c1": {},
        },
    }


def _strong_results() -> dict:
    results = _results()
    results["per_cluster_matrices"]["c0"]["DECIDE->PURCHASE"] = 0.95
    return results


def _weak_results() -> dict:
    results = _results()
    results["per_cluster_matrices"]["c0"]["DECIDE->PURCHASE"] = 0.10
    return results


def _summary(results: dict) -> dict:
    built = summarise_journey_matrices(
        results["per_cluster_matrices"],
        results["cluster_weights"],
    )
    assert built is not None
    return built


def _row(
    sim_id: int,
    results: dict,
    *,
    project_id: int = 10,
    created_at: str | None = None,
) -> dict:
    return {
        "simulation_id": sim_id,
        "project_id": project_id,
        "created_at": created_at,
        "journey_summary": _summary(results),
    }


def _payload() -> dict:
    rows = [
        _row(1, _weak_results(), created_at="2026-01-01T00:00:00Z"),
        _row(2, _results(), created_at="2026-02-01T00:00:00Z"),
        _row(3, _strong_results(), created_at="2026-03-01T00:00:00Z"),
    ]
    payload = build_journey_trend(
        rows,
        anchor_simulation_id=3,
        project_id=10,
    )
    payload["generated_at"] = "2026-08-08T12:00:00+00:00"
    return payload


def _trend_model() -> JourneyTrendOut:
    return JourneyTrendOut.model_validate(_payload())


# ---------------------------------------------------------------------------
# CSV rendering
# ---------------------------------------------------------------------------


def test_csv_renders_metadata_and_headline_section() -> None:
    csv_text = journey_trend_to_csv(
        _trend_model(),
        metadata={
            "generated_at": "2026-08-08T12:00:00+00:00",
            "user_id": 42,
            "simulation_id": 3,
            "project_id": 10,
            "format_version": FORMAT_VERSION,
        },
    )

    assert csv_text.startswith("generated_at,")
    assert "user_id,42" in csv_text
    assert "simulation_id,3" in csv_text
    assert "project_id,10" in csv_text
    assert "format_version,1" in csv_text
    assert "section,Headline" in csv_text
    assert "status,COMPLETED" in csv_text
    assert "included_count,3" in csv_text
    assert "raw_count,3" in csv_text
    assert "skipped_count,0" in csv_text
    assert "trend_slope," in csv_text
    assert "stability_score," in csv_text
    assert "anchor_percentile_rank,100.0" in csv_text


def test_csv_renders_purchase_stats_and_momentum() -> None:
    csv_text = journey_trend_to_csv(_payload())

    assert "section,Purchase Statistics" in csv_text
    assert "metric,value" in csv_text
    assert "count,3" in csv_text
    assert "min," in csv_text
    assert "max," in csv_text
    assert "mean," in csv_text
    assert "median," in csv_text
    assert "std," in csv_text
    assert "section,Momentum" in csv_text
    assert "improved_count,2" in csv_text
    assert "declined_count,0" in csv_text
    assert "flat_count,0" in csv_text
    assert "improvement_share_pct,100.0" in csv_text
    assert "latest_delta," in csv_text


def test_csv_renders_key_runs_and_point_series() -> None:
    csv_text = journey_trend_to_csv(_payload())

    assert "section,Key Runs" in csv_text
    assert "best_point,3" in csv_text
    assert "worst_point,1" in csv_text
    assert "section,Journey Points" in csv_text
    assert "simulation_id,project_id,created_at" in csv_text
    assert "1,10,2026-01-01T00:00:00Z" in csv_text
    assert "2,10,2026-02-01T00:00:00Z" in csv_text
    assert "3,10,2026-03-01T00:00:00Z" in csv_text
    anchor_line = next(
        line
        for line in csv_text.splitlines()
        if line.startswith("3,10,2026-03-01T00:00:00Z")
    )
    assert anchor_line.endswith(",true")


def test_csv_renders_leak_tables_and_insights() -> None:
    csv_text = journey_trend_to_csv(_payload())

    assert "section,Stage Leak Medians" in csv_text
    assert "stage,median_probability" in csv_text
    assert "ARRIVE," in csv_text
    assert "BROWSE," in csv_text
    assert "CONSIDER," in csv_text
    assert "DECIDE," in csv_text
    assert "section,Latest Stage Leaks" in csv_text
    assert "stage,probability" in csv_text
    assert "section,Insights" in csv_text
    assert "rank,insight" in csv_text
    assert "above your" in csv_text


def test_csv_guards_spreadsheet_formula_injection() -> None:
    payload = _payload()
    payload["insights"] = ['=HYPERLINK("https://evil.example")']
    payload["points"][0]["primary_exit_stage"] = " \t+SUM(A1:A2)"
    payload["summary"]["most_common_primary_exit_stage"] = "@SUM(A1:A2)"

    csv_text = journey_trend_to_csv(payload)

    assert "'=HYPERLINK" in csv_text
    assert "' \t+SUM(A1:A2)" in csv_text
    assert "'@SUM(A1:A2)" in csv_text


def test_csv_guards_control_character_formula_injection() -> None:
    """OWASP-style leading tab/CR/LF cells are neutralised too."""
    payload = _payload()
    payload["insights"] = [
        '\t=HYPERLINK("https://evil.example")',
        "\r=2+2",
        "\n@EVAL",
    ]
    payload["points"][0]["primary_exit_stage"] = "\tCMD"

    csv_text = journey_trend_to_csv(payload)

    assert "'\t=HYPERLINK" in csv_text
    assert "'\r=2+2" in csv_text
    assert "'\n@EVAL" in csv_text
    assert "'\tCMD" in csv_text


def test_csv_falls_back_to_payload_generated_at_without_metadata() -> None:
    """Provenance is preserved when the caller omits metadata."""
    csv_text = journey_trend_to_csv(_payload())

    assert csv_text.startswith("generated_at,2026-08-08T12:00:00+00:00\n")
    assert "\nsection,Headline" in csv_text


def test_csv_handles_malformed_payload_without_raising() -> None:
    csv_text = journey_trend_to_csv(
        {
            "summary": {
                "included_count": float("inf"),
                "raw_count": 1e999,
                "skipped_count": None,
                "purchase_stats": {
                    "count": 2,
                    "min": float("nan"),
                    "mean": "n/a",
                },
                "momentum": {
                    "improved_count": float("inf"),
                    "improvement_share_pct": None,
                    "latest_delta": "junk",
                },
                "best_point": "junk",
                "worst_point": None,
                "stage_leak_medians": "junk",
                "latest_stage_leaks": None,
            },
            "points": ["not-a-dict"],
            "insights": None,
        },
        metadata=["not", "a", "dict"],
    )

    assert csv_text.startswith("section,Headline")
    assert "included_count,0" in csv_text
    assert "raw_count,0" in csv_text
    assert "skipped_count,0" in csv_text
    assert "section,Purchase Statistics" in csv_text
    assert "min,0.0" in csv_text
    assert "mean,0.0" in csv_text
    assert "section,Momentum" in csv_text
    assert "improved_count,0" in csv_text
    assert "improvement_share_pct," in csv_text
    assert "latest_delta,0.0" in csv_text
    assert "section,Key Runs" in csv_text
    assert "section,Journey Points" in csv_text
    assert "section,Stage Leak Medians" in csv_text
    assert "section,Latest Stage Leaks" in csv_text
    assert "section,Insights" in csv_text


# ---------------------------------------------------------------------------
# JSON rendering
# ---------------------------------------------------------------------------


def test_json_renders_envelope_with_payload() -> None:
    text = journey_trend_to_json(
        _trend_model(),
        metadata={"format_version": FORMAT_VERSION, "user_id": 42},
    )
    data = json.loads(text)

    assert data["metadata"]["format_version"] == "1"
    assert data["metadata"]["user_id"] == 42
    assert data["journey_trend"]["simulation_id"] == 3
    assert data["journey_trend"]["summary"]["included_count"] == 3
    assert [p["simulation_id"] for p in data["journey_trend"]["points"]] == [
        1,
        2,
        3,
    ]
    assert data["journey_trend"]["anchor_percentile_rank"] == pytest.approx(100.0)
    assert text.endswith("\n")


def test_json_falls_back_to_payload_generated_at_without_metadata() -> None:
    text = journey_trend_to_json(_payload())
    data = json.loads(text)

    assert data["metadata"]["generated_at"] == "2026-08-08T12:00:00+00:00"
    assert data["metadata"] == {
        "generated_at": "2026-08-08T12:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


def _user() -> object:
    return type("U", (), {"id": 42})()


async def _body_bytes(response: object) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def _call_export(
    *,
    simulation_id: int = 3,
    format: str = "csv",
    db: object | None = None,
    current_user: object | None = None,
):
    from app.api.v1 import simulations as sim_mod

    return sim_mod.export_simulation_journey_trend(
        simulation_id=simulation_id,
        format=format,
        db=db,
        current_user=current_user or _user(),
    )


def test_export_route_returns_csv_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import simulations as sim_mod

    calls: dict = {}

    def fake_trend(**kwargs):
        calls.update(kwargs)
        return _trend_model()

    monkeypatch.setattr(sim_mod, "get_simulation_journey_trend", fake_trend)

    response = _call_export()
    body = asyncio.run(_body_bytes(response)).decode()

    assert response.media_type == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="journey-trend.csv"'
    )
    assert calls["simulation_id"] == 3
    assert "section,Headline" in body
    assert "section,Purchase Statistics" in body
    assert "section,Journey Points" in body
    assert "section,Insights" in body


def test_export_route_returns_json_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import simulations as sim_mod

    monkeypatch.setattr(
        sim_mod,
        "get_simulation_journey_trend",
        lambda **kwargs: _trend_model(),
    )

    response = _call_export(format="json")
    body = asyncio.run(_body_bytes(response)).decode()
    data = json.loads(body)

    assert response.media_type == "application/json; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="journey-trend.json"'
    )
    assert data["metadata"]["user_id"] == 42
    assert data["metadata"]["simulation_id"] == 3
    assert data["metadata"]["project_id"] == 10
    assert data["metadata"]["format_version"] == "1"
    assert data["journey_trend"]["summary"]["included_count"] == 3


def test_export_route_rejects_unsupported_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import simulations as sim_mod

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("trend builder must not run for bad format")

    monkeypatch.setattr(sim_mod, "get_simulation_journey_trend", _must_not_be_called)

    with pytest.raises(HTTPException) as exc:
        _call_export(format="xml")
    assert exc.value.status_code == 400
    assert "expected 'csv' or 'json'" in exc.value.detail


def test_export_route_accepts_whitespace_and_case_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import simulations as sim_mod

    monkeypatch.setattr(
        sim_mod,
        "get_simulation_journey_trend",
        lambda **kwargs: _trend_model(),
    )

    response = _call_export(format=" JSON ")
    body = asyncio.run(_body_bytes(response)).decode()
    data = json.loads(body)

    assert response.media_type == "application/json; charset=utf-8"
    assert data["metadata"]["simulation_id"] == 3
    assert data["metadata"]["format_version"] == "1"


def test_export_route_propagates_endpoint_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import simulations as sim_mod

    def fake_trend(**kwargs):
        raise HTTPException(status_code=404, detail="Simulation not found")

    monkeypatch.setattr(sim_mod, "get_simulation_journey_trend", fake_trend)

    with pytest.raises(HTTPException) as exc:
        _call_export(simulation_id=999)
    assert exc.value.status_code == 404
    assert "Simulation not found" in exc.value.detail
