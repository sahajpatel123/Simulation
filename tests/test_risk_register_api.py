"""Route-level tests for ``GET /projects/{id}/risk-register``."""
from __future__ import annotations

import sys
import types

import pytest
from fastapi import HTTPException

from app.schemas.risk_register import RiskRegisterOut
from app.simulation.risk_register import (
    SOURCE_COMPETITIVE,
    SOURCE_PREMORTEM,
    SOURCE_SIMULATION,
    SOURCE_STRESS_TEST,
)

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


_MISSING = object()


def _results(findings: list[dict] | None = None) -> dict:
    return {
        "mean_conversion_rate": 0.04,
        "domain_findings": findings
        if findings is not None
        else [
            {
                "architect_name": "PricingArchitect",
                "cluster_id": "a",
                "cluster_name": "Cluster A",
                "finding": "Price exceeds willingness to pay",
                "metric_affected": "will_pay_probability",
                "actual_value": 0.10,
                "healthy_benchmark": 0.40,
                "conversion_impact": 0.08,
                "recommended_action": "Add a starter tier",
                "severity": "CRITICAL",
            }
        ],
    }


class _FakeProject:
    def __init__(
        self,
        project_id: int,
        *,
        premortem_json: dict | None = None,
        stress_test_json: dict | None = None,
        competitive_json: dict | None = None,
    ) -> None:
        self.id = project_id
        self.user_id = 42
        self.premortem_json = premortem_json
        self.stress_test_json = stress_test_json
        self.competitive_json = competitive_json


class _FakeSimulation:
    def __init__(
        self,
        sim_id: int = 1,
        *,
        results: dict | None = None,
    ) -> None:
        self.id = sim_id
        self.project_id = 10
        self.status = "COMPLETED"
        self.results_json = results if results is not None else _results()


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return list(self.items)


class _FakeSession:
    def __init__(
        self,
        sim: _FakeSimulation | None | object = _MISSING,
    ) -> None:
        self.sim = (
            sim
            if sim is not _MISSING
            else _FakeSimulation()
        )

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Simulation":
            return _FakeQuery([self.sim] if self.sim is not None else [])
        return _FakeQuery([])


def _full_project(project_id: int = 10) -> _FakeProject:
    return _FakeProject(
        project_id,
        premortem_json={
            "failure_modes": [
                {
                    "title": "Certification delay",
                    "description": "Approval takes months",
                    "severity": "CRITICAL",
                    "probability": 0.5,
                    "impact": 0.9,
                    "intervention": "Start certification early",
                }
            ]
        },
        stress_test_json={
            "sensitivity_matrix": [
                {
                    "assumption_text": "Users will pay for premium",
                    "sensitivity": "HIGH",
                    "delta": -0.025,
                    "delta_pct": -62.5,
                    "kill_shot": True,
                    "kill_shot_prob": 0.7,
                    "recommendation": "A/B test the price",
                }
            ]
        },
        competitive_json={
            "overall_competitive_position": "MODERATE",
            "competitors": [
                {"name": "BigCo", "threat_level": "HIGH"},
            ],
            "gap_analysis": {
                "recommended_counter_moves": ["Ship the integration"],
            },
        },
    )


def _call_route(
    *,
    project_id: int = 10,
    current_user_id: int = 42,
    session: _FakeSession | None = None,
    project: _FakeProject | None = None,
    monkeypatch: pytest.MonkeyPatch | None = None,
):
    from app.api.v1 import projects as projects_mod

    db = session or _FakeSession()
    owned = project or _full_project(project_id)
    if monkeypatch is not None:
        monkeypatch.setattr(
            projects_mod,
            "get_owned_project",
            lambda db_, user_id, project_id_: owned,
        )
    return projects_mod.get_project_risk_register(
        project_id=project_id,
        db=db,
        current_user=type("U", (), {"id": current_user_id})(),
    )


def test_risk_register_combines_all_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = _call_route(monkeypatch=monkeypatch)

    assert out.project_id == 10
    assert out.total_risks == 4
    assert out.source_breakdown == {
        SOURCE_PREMORTEM: 1,
        SOURCE_STRESS_TEST: 1,
        SOURCE_COMPETITIVE: 1,
        SOURCE_SIMULATION: 1,
    }
    assert out.top_risk_count == 4
    assert out.top_risk_score is not None
    assert out.overall_risk_level in {"LOW", "MODERATE", "HIGH", "SEVERE"}
    assert out.narrative
    # Ranked descending.
    scores = [item.risk_score for item in out.risks]
    assert scores == sorted(scores, reverse=True)
    # Kill shot (0.7 prob x 0.9 impact = 0.63) is the top risk.
    assert out.risks[0].source == SOURCE_STRESS_TEST
    assert out.risks[0].severity == "CRITICAL"


def test_risk_register_without_data_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _FakeProject(10)
    session = _FakeSession(sim=None)
    out = _call_route(
        session=session,
        project=project,
        monkeypatch=monkeypatch,
    )
    assert out.total_risks == 0
    assert out.risks == []
    assert out.overall_risk_level == "LOW"
    assert out.top_risk_score is None


def test_risk_register_includes_latest_simulation_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(sim=_FakeSimulation(sim_id=7))
    out = _call_route(session=session, monkeypatch=monkeypatch)
    assert out.total_risks == 4
    assert out.source_breakdown[SOURCE_SIMULATION] == 1


def test_risk_register_missing_project_raises_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import projects as projects_mod

    def _not_found(db, user_id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")

    monkeypatch.setattr(projects_mod, "get_owned_project", _not_found)
    with pytest.raises(HTTPException) as exc:
        projects_mod.get_project_risk_register(
            project_id=10,
            db=_FakeSession(),
            current_user=type("U", (), {"id": 42})(),
        )
    assert exc.value.status_code == 404


def test_risk_register_serialises_via_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = _call_route(monkeypatch=monkeypatch)
    payload = RiskRegisterOut.model_validate(out)
    assert payload.total_risks == 4
    assert payload.risks[0].id.startswith("stress-")
    assert payload.key_signals
