"""Route-level tests for ``GET /api/v1/projects/{id}/outcome-benchmark/export``.

Covers CSV/JSON attachment rendering, delegation to the same benchmark
builder as the JSON endpoint, unsupported-format rejection, and propagation
of the ownership/benchmark gates.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.schemas.outcome_benchmark import OutcomeBenchmarkOut  # noqa: E402


def _payload() -> dict:
    return {
        "has_data": True,
        "category": "saas",
        "current": {
            "outcome_id": 1,
            "simulation_id": 7,
            "project_id": 10,
            "days_since_launch": 30,
            "actual_conversion_rate": 0.06,
            "predicted_conversion_rate": 0.04,
            "data_confidence": "ESTIMATED",
            "launched": True,
            "recorded_at": "2026-08-01T00:00:00+00:00",
        },
        "distribution": {
            "peer_count": 5,
            "min": 0.01,
            "p25": 0.02,
            "median": 0.03,
            "p75": 0.04,
            "max": 0.05,
            "mean": 0.03,
        },
        "percentile_rank": 100.0,
        "verdict": "TOP_QUARTILE",
        "median_comparison": "Above the peer median (0.03)",
        "narrative": "Ranks at 100.0% of comparable launched outcomes.",
        "insights": [
            "Ranks above 100.0% of comparable launched outcomes.",
            "Actual conversion is 1.5x the simulated prediction.",
        ],
        "key_signals": [
            {
                "label": "outcome_benchmark",
                "value": "TOP_QUARTILE",
                "severity": "ok",
                "display": "Real-world conversion verdict: Top Quartile",
            }
        ],
        "meta": {
            "benchmark_scope": (
                "other launched projects in the same product category "
                "across TheCee"
            ),
            "peers_scanned": 5,
            "peers_usable": 5,
            "peers_skipped_invalid": 0,
            "peers_skipped_product_changed": 0,
            "data_sufficient": True,
        },
    }


def _user() -> object:
    return type("U", (), {"id": 42})()


async def _body_bytes(response: object) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def _call_export(
    *,
    project_id: int = 10,
    format: str = "csv",
    db: object | None = None,
    current_user: object | None = None,
):
    from app.api.v1 import outcomes as out_mod

    return out_mod.export_outcome_benchmark(
        project_id=project_id,
        format=format,
        db=db,
        current_user=current_user or _user(),
    )


def test_export_route_returns_csv_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import outcomes as out_mod

    calls: dict = {}

    def fake_benchmark(**kwargs):
        calls.update(kwargs)
        return OutcomeBenchmarkOut.model_validate(_payload())

    monkeypatch.setattr(out_mod, "get_outcome_benchmark", fake_benchmark)

    response = _call_export()
    body = asyncio.run(_body_bytes(response)).decode()

    assert response.media_type == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="outcome-benchmark.csv"'
    )
    assert calls["project_id"] == 10
    assert "section,Current Outcome" in body
    assert "actual_conversion_rate,0.06" in body
    assert "section,Peer Distribution" in body
    assert "section,Ranking" in body
    assert "verdict,TOP_QUARTILE" in body
    assert "Ranks above 100.0%" in body


def test_export_route_returns_json_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import outcomes as out_mod

    monkeypatch.setattr(
        out_mod,
        "get_outcome_benchmark",
        lambda **kwargs: OutcomeBenchmarkOut.model_validate(_payload()),
    )

    response = _call_export(format="json")
    body = asyncio.run(_body_bytes(response)).decode()
    data = json.loads(body)

    assert response.media_type == "application/json; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="outcome-benchmark.json"'
    )
    assert data["metadata"]["user_id"] == 42
    assert data["metadata"]["project_id"] == 10
    assert data["metadata"]["category"] == "saas"
    assert data["outcome_benchmark"]["percentile_rank"] == pytest.approx(100.0)
    assert data["outcome_benchmark"]["verdict"] == "TOP_QUARTILE"


def test_export_route_rejects_unsupported_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import outcomes as out_mod

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("benchmark builder must not run for bad format")

    monkeypatch.setattr(out_mod, "get_outcome_benchmark", _must_not_be_called)

    with pytest.raises(HTTPException) as exc:
        _call_export(format="xml")
    assert exc.value.status_code == 400
    assert "expected 'csv' or 'json'" in exc.value.detail


def test_export_route_propagates_endpoint_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import outcomes as out_mod

    def fake_benchmark(**kwargs):
        raise HTTPException(status_code=404, detail="Project not found")

    monkeypatch.setattr(out_mod, "get_outcome_benchmark", fake_benchmark)

    with pytest.raises(HTTPException) as exc:
        _call_export()
    assert exc.value.status_code == 404
    assert "Project not found" in exc.value.detail
