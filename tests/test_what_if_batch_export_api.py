"""Route-level tests for the batch what-if scenario export endpoint."""
from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest
from fastapi import HTTPException

from app.schemas.what_if import WhatIfAssumption
from app.schemas.what_if_batch import (
    WhatIfBatchRequest,
    WhatIfBatchScenarioInput,
)


if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _FakeEnvironment:
    def __init__(self) -> None:
        self.average_order_value = 999.0
        self.price_sensitivity = 0.5
        self.market_maturity = 0.3
        self.consumer_volume = 10000
        self.growth_rate_per_month = 5.0
        self.mode = "MANUAL"
        self.scenario_type = None
        self.manual_params_json = None


class _FakeSimulation:
    def __init__(
        self,
        sim_id: int = 1,
        *,
        status: str = "COMPLETED",
        results: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        self.id = sim_id
        self.project_id = 10
        self.environment_id = 5
        self.status = status
        self.error_message = error_message
        self.signal_quality = 0.62
        self.results_json = (
            results
            if results is not None
            else {
                "population_weighted_conversion": 0.05,
                "conversion_rate": 0.05,
                "mean_revenue": 999.0,
                "product_type_detected": "saas",
            }
        )


class _FakeAssumption:
    def __init__(self, text: str) -> None:
        self.project_id = 10
        self.is_hidden = False
        self.text = text
        self.sensitivity = "HIGH"
        self.impact_score = 8.0


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else [_FakeSimulation()]

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return self.items


class _FakeSession:
    def __init__(
        self,
        sim: _FakeSimulation | None = None,
        assumptions: list[_FakeAssumption] | None = None,
    ) -> None:
        self.sim = sim or _FakeSimulation()
        self.assumptions = assumptions or [_FakeAssumption("Existing demand is strong")]

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Simulation":
            return _FakeQuery([self.sim])
        if name == "Environment":
            return _FakeQuery([_FakeEnvironment()])
        if name == "Assumption":
            return _FakeQuery(self.assumptions)
        return _FakeQuery([])


def _payload() -> WhatIfBatchRequest:
    return WhatIfBatchRequest(
        scenarios=[
            WhatIfBatchScenarioInput(
                label="demand",
                assumptions=[
                    WhatIfAssumption(
                        text="Strong market demand for this product",
                        sensitivity="HIGH",
                        impact_score=8.0,
                    )
                ],
            ),
            WhatIfBatchScenarioInput(
                label="pricing",
                assumptions=[
                    WhatIfAssumption(
                        text="Pricing too expensive",
                        sensitivity="HIGH",
                        impact_score=8.0,
                    )
                ],
            ),
        ]
    )


def _call_route(
    *,
    simulation_id: int = 1,
    format: str = "csv",
    session: _FakeSession | None = None,
    payload: WhatIfBatchRequest | None = None,
):
    from app.api.v1 import simulations as sim_mod

    db = session or _FakeSession()
    return sim_mod.export_what_if_batch(
        payload=payload or _payload(),
        simulation_id=simulation_id,
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


def test_completed_simulation_returns_multi_section_csv() -> None:
    resp = _call_route()

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="what-if-batch-1.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "What-If Batch Summary" in body
    assert "Ranked Scenarios" in body
    assert "rank,label,simulation_id,project_id,base_conversion_rate" in body
    assert "demand" in body
    assert "pricing" in body


def test_format_json_returns_batch_payload() -> None:
    resp = _call_route(format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    body = _body(resp).decode("utf-8")
    parsed = json.loads(body)
    assert parsed["metadata"]["simulation_id"] == 1
    assert parsed["metadata"]["project_id"] == 10
    assert parsed["what_if_batch"]["summary"]["scenario_count"] == 2
    assert [item["label"] for item in parsed["what_if_batch"]["scenarios"]] == [
        "demand",
        "pricing",
    ]


def test_format_md_returns_markdown_brief() -> None:
    resp = _call_route(format="md")

    assert resp.media_type == "text/markdown; charset=utf-8"
    assert 'filename="what-if-batch-1.md"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert body.startswith("# What-If Batch — Simulation 1")
    assert "## Summary" in body
    assert "## Ranked Scenarios" in body
    assert "demand" in body
    assert "pricing" in body


def test_unsupported_format_raises_400() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_route(format="pdf")
    assert exc.value.status_code == 400
    assert "unsupported export format" in exc.value.detail


def test_failed_simulation_raises_422() -> None:
    session = _FakeSession(
        sim=_FakeSimulation(status="FAILED", error_message="boom")
    )
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422
    assert "boom" in exc.value.detail


def test_pending_simulation_raises_409() -> None:
    session = _FakeSession(sim=_FakeSimulation(status="PENDING"))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 409


def test_empty_results_raises_422() -> None:
    session = _FakeSession(sim=_FakeSimulation(results={}))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422
