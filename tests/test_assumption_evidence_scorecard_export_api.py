"""Route-level tests for ``GET /projects/{project_id}/assumptions/{assumption_id}/evidence-scorecard/export``."""
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

from app.schemas.assumption_evidence import (
    AssumptionEvidenceScorecardOut,
)


class _FakeSimulation:
    def __init__(self) -> None:
        self.id = 1
        self.project_id = 10
        self.environment_id = 5
        self.status = "COMPLETED"
        self.results_json = {
            "mean_conversion_rate": 0.04,
            "total_agents": 10000,
            "converted": 400,
        }
        self.signal_quality = 0.62
        self.error_message = None


class _FakeEnvironment:
    def __init__(self) -> None:
        self.id = 5
        self.average_order_value = 999.0
        self.price_sensitivity = 0.5
        self.market_maturity = 0.3
        self.consumer_volume = 10000
        self.growth_rate_per_month = 5.0


class _FakeAssumption:
    def __init__(
        self,
        assumption_id: int = 100,
        text: str = "We believe pricing will be 999 rupees per month",
        category: str = "PricingArchitect",
        sensitivity: str = "CRITICAL",
    ) -> None:
        self.id = assumption_id
        self.project_id = 10
        self.text = text
        self.category = category
        self.sensitivity = sensitivity
        self.impact_score = 9.0
        self.claim_confidence = None
        self.is_hidden = False


class _FakeEvidence:
    def __init__(
        self,
        evidence_id: int = 1,
        result: str = "PASS",
    ) -> None:
        self.id = evidence_id
        self.project_id = 10
        self.assumption_id = 100
        self.method = "WILLINGNESS_TO_PAY_SURVEY"
        self.result = result
        self.observed_metric = 0.42
        self.notes = "35 responses"
        from datetime import UTC, datetime

        self.created_at = datetime(2026, 1, 5, tzinfo=UTC)


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return list(self.items)


class _FakeProject:
    def __init__(self, project_id: int = 10, user_id: int = 42) -> None:
        self.id = project_id
        self.user_id = user_id


class _FakeSession:
    def __init__(
        self,
        *,
        sim: _FakeSimulation | None = None,
        assumptions: list | None = None,
        evidence: list | None = None,
    ) -> None:
        self.sim = sim
        self.project = _FakeProject()
        self.assumptions = assumptions if assumptions is not None else [_FakeAssumption(100)]
        self.evidence = evidence if evidence is not None else []

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery([self.project])
        if name == "Simulation":
            return _FakeQuery([self.sim] if self.sim is not None else [])
        if name == "Environment":
            return _FakeQuery([_FakeEnvironment()])
        if name == "Assumption":
            return _FakeQuery(self.assumptions)
        if name == "AssumptionEvidence":
            return _FakeQuery(self.evidence)
        return _FakeQuery()


def _call_export(
    *,
    project_id: int = 10,
    assumption_id: int = 100,
    format: str = "csv",
    session: _FakeSession | None = None,
):
    from app.api.v1 import assumption_evidence as ev_mod

    db = session or _FakeSession()
    return ev_mod.export_assumption_evidence_scorecard(
        project_id=project_id,
        assumption_id=assumption_id,
        format=format,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


def _fake_scorecard(*, evidence_count: int = 1, latest_result: str = "PASS") -> dict:
    """Build a realistic scorecard dict to inject via monkeypatch."""
    return {
        "project_id": 10,
        "assumption_id": 100,
        "assumption_text": "We believe pricing will be 999 rupees per month",
        "category": "PricingArchitect",
        "sensitivity": "CRITICAL",
        "evidence_count": evidence_count,
        "latest_result": latest_result,
        "derived_confidence": "VALIDATED_INTERNAL",
        "confidence_before": "ASPIRATIONAL",
        "confidence_after": "VALIDATED_INTERNAL",
        "validation_roi_before": 0.75,
        "validation_roi_after": 0.45,
        "roi_tier_before": "HIGH_VALUE",
        "roi_tier_after": "VALIDATE_FIRST",
        "roi_delta": -0.30,
        "tier_upgraded": True,
        "recommendation": "PASS confirmed — confidence upgraded to VALIDATED_INTERNAL.",
        "history": [
            {
                "id": 1,
                "project_id": 10,
                "assumption_id": 100,
                "method": "WILLINGNESS_TO_PAY_SURVEY",
                "method_label": "Willingness-to-pay survey",
                "result": "PASS",
                "observed_metric": 0.42,
                "created_at": "2026-08-05T00:00:00+00:00",
                "derived_confidence": "VALIDATED_INTERNAL",
                "notes": "35 responses",
            }
        ],
        "meta": {"model": "evidence_scorecard_v1"},
    }


def _monkeypatch_scorecard(
    monkeypatch: pytest.MonkeyPatch,
    *,
    payload: dict | None = None,
):
    from app.api.v1 import assumption_evidence as ev_mod

    fake_payload = payload if payload is not None else _fake_scorecard()

    def _fake_get_scorecard(**kwargs):
        return AssumptionEvidenceScorecardOut(**fake_payload)

    monkeypatch.setattr(ev_mod, "get_assumption_evidence_scorecard", _fake_get_scorecard)


async def _collect(response: Any) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def _body(response: Any) -> bytes:
    return asyncio.run(_collect(response))


def test_route_registered() -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    paths = {r.path for r in ev_mod.router.routes}
    assert (
        "/projects/{project_id}/assumptions/{assumption_id}/evidence-scorecard/export"
        in paths
    )


def test_route_returns_csv_export(monkeypatch: pytest.MonkeyPatch) -> None:
    _monkeypatch_scorecard(monkeypatch)
    response = _call_export(format="csv")

    assert response.media_type == "text/csv; charset=utf-8"
    assert "evidence-scorecard-10-100.csv" in response.headers["Content-Disposition"]
    assert response.headers["Cache-Control"] == "no-store"
    body = _body(response).decode("utf-8")
    assert body.startswith("﻿")
    assert "section,Evidence Scorecard Summary" in body
    assert "section,Evidence History" in body
    assert "assumption_text" in body
    assert "VALIDATED_INTERNAL" in body
    assert int(response.headers["Content-Length"]) == len(body.encode("utf-8"))


def test_route_returns_json_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    _monkeypatch_scorecard(monkeypatch)
    response = _call_export(format="json")

    assert response.media_type == "application/json; charset=utf-8"
    assert "evidence-scorecard-10-100.json" in response.headers["Content-Disposition"]
    parsed = json.loads(_body(response).decode("utf-8"))
    assert parsed["metadata"]["assumption_id"] == 100
    assert parsed["metadata"]["format_version"] == "1"
    scorecard = parsed["evidence_scorecard"]
    assert scorecard["assumption_id"] == 100
    assert scorecard["validation_roi_before"] == 0.75
    assert scorecard["validation_roi_after"] == 0.45
    assert scorecard["roi_delta"] == -0.30


def test_route_returns_markdown_brief(monkeypatch: pytest.MonkeyPatch) -> None:
    _monkeypatch_scorecard(monkeypatch)
    response = _call_export(format="md")

    assert response.media_type == "text/markdown; charset=utf-8"
    assert "evidence-scorecard-10-100.md" in response.headers["Content-Disposition"]
    assert response.headers["Cache-Control"] == "no-store"
    body = _body(response).decode("utf-8")
    assert body.startswith("# Evidence Scorecard")
    assert "## Summary" in body
    assert "We believe pricing will be 999 rupees per month" in body
    assert "75.0%" in body  # validation_roi_before as percentage
    assert "45.0%" in body  # validation_roi_after as percentage
    assert "## Evidence History" in body
    assert "## Recommendation" in body
    assert int(response.headers["Content-Length"]) == len(body.encode("utf-8"))


def test_route_markdown_empty_history_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _monkeypatch_scorecard(monkeypatch, payload=_fake_scorecard())
    # Override history to empty
    from app.api.v1 import assumption_evidence as ev_mod

    payload = _fake_scorecard()
    payload["history"] = []
    payload["evidence_count"] = 0
    payload["latest_result"] = None

    def _fake_get_scorecard(**kwargs):
        return AssumptionEvidenceScorecardOut(**payload)

    monkeypatch.setattr(ev_mod, "get_assumption_evidence_scorecard", _fake_get_scorecard)

    response = _call_export(format="md")
    body = _body(response).decode("utf-8")
    assert "No validation experiments logged yet." in body


def test_route_accepts_uppercase_format(monkeypatch: pytest.MonkeyPatch) -> None:
    _monkeypatch_scorecard(monkeypatch)
    response = _call_export(format="JSON")

    body = json.loads(_body(response).decode("utf-8"))
    assert body["evidence_scorecard"]["assumption_id"] == 100


def test_route_rejects_unsupported_format(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    calls: list = []

    def forbidden(**kwargs):
        calls.append(kwargs)
        raise AssertionError("scorecard should not build for invalid format")

    monkeypatch.setattr(ev_mod, "get_assumption_evidence_scorecard", forbidden)

    with pytest.raises(HTTPException) as exc:
        _call_export(format="yaml")
    assert exc.value.status_code == 400
    assert "yaml" in exc.value.detail
    assert calls == []


def test_route_rejects_non_completed_simulation() -> None:

    sim = _FakeSimulation()
    sim.status = "PENDING"
    session = _FakeSession(sim=sim)
    with pytest.raises(HTTPException) as exc:
        _call_export(session=session)
    assert exc.value.status_code == 409


def test_route_returns_404_when_assumption_missing() -> None:

    # _assumption_or_404 returns None for empty query
    session = _FakeSession(sim=_FakeSimulation(), assumptions=[])
    with pytest.raises(HTTPException) as exc:
        _call_export(session=session, assumption_id=999)
    assert exc.value.status_code == 404
