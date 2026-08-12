"""Route-level tests for ``GET /projects/{id}/prediction-range-coverage/export``."""

from __future__ import annotations

import asyncio
import json
import sys
import types
from typing import Any

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.schemas.prediction_range_coverage import (
    PredictionRangeCoverageOut,
    PredictionRangeCoverageRow,
)


def _payload() -> PredictionRangeCoverageOut:
    return PredictionRangeCoverageOut(
        project_id=7,
        generated_at="2026-08-12T00:00:00+00:00",
        total_project_outcomes=6,
        evaluated_runs=2,
        within_range_count=1,
        coverage_rate=0.5,
        mean_margin=0.25,
        worst_miss={
            "simulation_id": 4,
            "margin": 0.25,
            "actual_conversion_rate": 0.40,
            "low": 0.05,
            "high": 0.15,
        },
        verdict="NEEDS_ATTENTION",
        narrative=(
            "Across 2 out-of-sample run(s), the prediction band contained "
            "actual conversion in 1 (50%)."
        ),
        key_signals=[
            {
                "label": "coverage_rate",
                "value": 0.5,
                "severity": "watch",
                "display": "Band contained actual conversion in 1/2 (50%)",
            }
        ],
        rows=[
            PredictionRangeCoverageRow(
                simulation_id=1,
                project_id=7,
                predicted_conversion_rate=0.10,
                actual_conversion_rate=0.09,
                low=0.05,
                high=0.15,
                history_count=3,
                calibration_source="project",
                confidence_label="WELL_CALIBRATED",
                within=True,
                margin=0.0,
                evaluated=True,
                created_at="2026-01-04T00:00:00+00:00",
            )
        ],
    )


def _import_projects_module() -> Any:
    from app.api.v1 import projects as projects_mod

    return projects_mod


async def _collect(response: Any) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def _body(response: Any) -> bytes:
    return asyncio.run(_collect(response))


def _call_route(
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_id: int = 7,
    format: str = "csv",
    payload: PredictionRangeCoverageOut | None = None,
) -> Any:
    projects_mod = _import_projects_module()
    fake_payload = payload if payload is not None else _payload()

    monkeypatch.setattr(
        projects_mod,
        "get_prediction_range_coverage",
        lambda **kwargs: fake_payload,
    )
    return projects_mod.export_prediction_range_coverage(
        project_id=project_id,
        format=format,
        db=object(),  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )


def test_export_route_registered() -> None:
    projects_mod = _import_projects_module()

    paths = {route.path for route in projects_mod.router.routes}
    assert (
        "/projects/{project_id}/prediction-range-coverage/export" in paths
    )

    methods_by_path: dict[str, set[str]] = {}
    for route in projects_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    assert "GET" in methods_by_path[
        "/projects/{project_id}/prediction-range-coverage/export"
    ]


def test_export_route_returns_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _call_route(monkeypatch=monkeypatch)

    assert response.media_type == "text/csv; charset=utf-8"
    assert (
        'filename="prediction-range-coverage-7.csv"'
        in response.headers["Content-Disposition"]
    )
    assert response.headers["Cache-Control"] == "no-store"
    body = _body(response)
    text = body.decode("utf-8")
    assert "section,Prediction Range Coverage Summary" in text
    assert "section,Key Signals" in text
    assert "section,Out-of-Sample Band Checks" in text
    assert "simulation_id,project_id,predicted_conversion_rate" in text
    assert "1,7,0.1,0.09,0.05,0.15,3,project" in text
    assert int(response.headers["Content-Length"]) == len(body)


def test_export_route_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _call_route(monkeypatch=monkeypatch, format="json")

    assert response.media_type == "application/json; charset=utf-8"
    assert (
        'filename="prediction-range-coverage-7.json"'
        in response.headers["Content-Disposition"]
    )
    parsed = json.loads(_body(response).decode("utf-8"))
    assert parsed["metadata"]["project_id"] == 7
    assert parsed["metadata"]["format_version"] == "1"
    coverage = parsed["prediction_range_coverage"]
    assert coverage["project_id"] == 7
    assert coverage["verdict"] == "NEEDS_ATTENTION"
    assert len(coverage["rows"]) == 1


def test_export_route_returns_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _call_route(monkeypatch=monkeypatch, format="md")

    assert response.media_type == "text/markdown; charset=utf-8"
    assert (
        'filename="prediction-range-coverage-7.md"'
        in response.headers["Content-Disposition"]
    )
    body = _body(response).decode("utf-8")
    assert body.startswith("# Prediction Range Coverage")
    assert "## Verdict" in body
    assert "## Summary" in body
    assert "## Out-of-Sample Band Checks" in body
    assert "## Key Signals" in body


def test_export_route_filename_includes_project_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_response = _call_route(monkeypatch=monkeypatch, project_id=42)
    assert (
        'filename="prediction-range-coverage-42.csv"'
        in csv_response.headers["Content-Disposition"]
    )

    json_response = _call_route(
        monkeypatch=monkeypatch,
        project_id=42,
        format="json",
    )
    assert (
        'filename="prediction-range-coverage-42.json"'
        in json_response.headers["Content-Disposition"]
    )


def test_export_route_accepts_uppercase_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(monkeypatch=monkeypatch, format="JSON")
    parsed = json.loads(_body(response).decode("utf-8"))
    assert parsed["prediction_range_coverage"]["verdict"] == "NEEDS_ATTENTION"


def test_export_route_rejects_unknown_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _call_route(monkeypatch=monkeypatch, format="pdf")

    assert exc_info.value.status_code == 400
    assert "unsupported export format" in exc_info.value.detail


def test_export_route_unknown_format_fails_before_payload_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unsupported format must not pay for the coverage aggregation."""
    projects_mod = _import_projects_module()
    calls: list[dict[str, Any]] = []

    def _forbidden_get(**kwargs: Any) -> Any:
        calls.append(kwargs)
        raise AssertionError(
            "payload builder should not run for bad format"
        )

    monkeypatch.setattr(
        projects_mod,
        "get_prediction_range_coverage",
        _forbidden_get,
    )

    with pytest.raises(HTTPException) as exc_info:
        projects_mod.export_prediction_range_coverage(
            project_id=7,
            format="yaml",
            db=object(),  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )

    assert exc_info.value.status_code == 400
    assert calls == []


def test_export_route_forwards_missing_project_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_mod = _import_projects_module()

    def _not_found(**kwargs: Any) -> Any:
        raise HTTPException(status_code=404, detail="Project not found")

    monkeypatch.setattr(
        projects_mod,
        "get_prediction_range_coverage",
        _not_found,
    )

    with pytest.raises(HTTPException) as exc_info:
        projects_mod.export_prediction_range_coverage(
            project_id=999,
            format="csv",
            db=object(),  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )

    assert exc_info.value.status_code == 404
    assert "Project not found" in exc_info.value.detail
