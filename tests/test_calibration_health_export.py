"""Tests for the calibration-health export helper and route."""
from __future__ import annotations

import asyncio
import sys
import types

import pytest

from app.simulation.calibration_health_export import calibration_health_to_csv


def _payload() -> dict:
    return {
        "overall_health": "WELL_CALIBRATED",
        "mean_abs_variance": 0.01,
        "observation_count": 2,
        "health_trajectory": "STABLE",
        "consecutive_well_calibrated_days": 3,
        "summary": "Calibration health: WELL_CALIBRATED (mean |variance|=0.01, 2 sim(s))",
        "top_miscalibrated_architect": {
            "architect_name": "PricingArchitect",
            "abs_calibration_variance": 0.02,
            "calibration_variance": 0.02,
            "calibration_direction": "OVER_PREDICTS",
            "recommendation": "TIGHTEN",
            "finding_count": 4,
        },
        "trend_buckets": [
            {
                "window": "7d",
                "days": 7,
                "observation_count": 2,
                "mean_abs_variance": 0.01,
            },
            {
                "window": "30d",
                "days": 30,
                "observation_count": 2,
                "mean_abs_variance": 0.01,
            },
        ],
        "architect_accuracy_counts": {
            "TIGHTEN": 1,
            "TRUSTED": 0,
        },
    }


def test_csv_renders_metadata_summary_trends_and_counts() -> None:
    csv_text = calibration_health_to_csv(
        _payload(),
        metadata={
            "generated_at": "now",
            "user_id": 42,
            "format_version": "1",
            "requested_ids": [1, 2],
        },
    )

    assert "generated_at,now" in csv_text
    assert "user_id,42" in csv_text
    assert 'requested_ids,"1,2"' in csv_text
    assert "section,Calibration Summary" in csv_text
    assert "overall_health,WELL_CALIBRATED" in csv_text
    assert "mean_abs_variance,0.01" in csv_text
    assert "top_miscalibrated_architect,PricingArchitect" in csv_text
    assert "top_miscalibrated_recommendation,TIGHTEN" in csv_text
    assert "section,Trend Buckets" in csv_text
    assert "7d,7,2,0.01" in csv_text
    assert "30d,30,2,0.01" in csv_text
    assert "section,Architect Accuracy Counts" in csv_text
    assert "TIGHTEN,1" in csv_text
    assert "TRUSTED,0" in csv_text


def test_csv_empty_payload_still_renders_sections() -> None:
    csv_text = calibration_health_to_csv({})

    assert "section,Calibration Summary" in csv_text
    assert "section,Trend Buckets" in csv_text
    assert "section,Architect Accuracy Counts" in csv_text
    assert "window,days,observation_count,mean_abs_variance" in csv_text
    assert "recommendation,count" in csv_text


def test_csv_handles_missing_optional_blocks() -> None:
    csv_text = calibration_health_to_csv(
        {
            "overall_health": "INSUFFICIENT_DATA",
            "mean_abs_variance": None,
            "observation_count": 0,
            "health_trajectory": "INSUFFICIENT_DATA",
            "consecutive_well_calibrated_days": 0,
            "summary": "No data — calibration health unknown.",
        }
    )

    assert "overall_health,INSUFFICIENT_DATA" in csv_text
    assert "mean_abs_variance," in csv_text
    assert "summary,No data — calibration health unknown." in csv_text
    assert "top_miscalibrated_architect" not in csv_text


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------


class _FakeCalibrationRow:
    def __init__(
        self,
        *,
        sim_id: int = 1,
        created_at: str = "2026-08-01T00:00:00+00:00",
        predicted: float = 0.10,
        actual: float = 0.05,
    ) -> None:
        self.id = sim_id
        self.created_at = created_at
        self.predicted_conversion_rate = predicted
        self.actual_conversion_rate = actual
        self.results_json = {"domain_findings": []}


class _FakeQuery:
    def __init__(self, rows: list | None = None) -> None:
        self.rows = rows if rows is not None else [_FakeCalibrationRow()]

    def outerjoin(self, *args, **kwargs):
        return self

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self.rows


class _FakeSession:
    def __init__(self, rows: list | None = None) -> None:
        self.rows = rows

    def query(self, model, *args, **kwargs):
        return _FakeQuery(self.rows)


def _import_simulations_module():
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub
    from app.api.v1 import simulations as sim_mod

    return sim_mod


def _call_route(
    *,
    ids: list[str] | None = None,
    format: str = "csv",
    session: _FakeSession | None = None,
):
    sim_mod = _import_simulations_module()
    db = session if session is not None else _FakeSession()
    return sim_mod.export_calibration_health(
        ids=ids,
        format=format,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


async def _collect(resp) -> bytes:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def _body(resp) -> bytes:
    return asyncio.run(_collect(resp))


def test_export_route_returns_csv() -> None:
    resp = _call_route(ids=["1"])

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="calibration-health.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "section,Calibration Summary" in body
    assert "observation_count,1" in body
    assert "Calibration health:" in body


def test_export_route_returns_json() -> None:
    resp = _call_route(ids=["1"], format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    assert 'filename="calibration-health.json"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert '"calibration_health"' in body
    assert '"overall_health"' in body
    assert '"requested_ids"' in body
    assert "1" in body


def test_export_route_without_ids_returns_empty_health() -> None:
    resp = _call_route(ids=None)

    body = _body(resp).decode("utf-8")
    assert "overall_health,INSUFFICIENT_DATA" in body
    assert "observation_count,0" in body


def test_export_route_registered_before_dynamic_export() -> None:
    """The static export route must win over ``/{simulation_id}/export``."""
    sim_mod = _import_simulations_module()

    paths = [r.path for r in sim_mod.router.routes]
    static_index = paths.index("/simulations/calibration-health/export")
    dynamic_index = paths.index("/simulations/{simulation_id}/export")
    assert static_index < dynamic_index
