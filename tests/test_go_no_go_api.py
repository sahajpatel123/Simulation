"""Route-level tests for ``GET /projects/{id}/go-no-go``."""
from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta

import pytest

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


_MISSING = object()


def _results(**overrides) -> dict:
    payload = {
        "population_weighted_conversion": 0.04,
        "product_type_detected": "saas",
        "total_agents": 10000,
        "raw_funnel": {
            "ARRIVE": 1000,
            "BROWSE": 600,
            "CONSIDER": 300,
            "DECIDE": 120,
            "PURCHASE": 40,
        },
        "cluster_breakdown": {
            "metro_power_professional": 0.06,
            "tier3_first_time_app_user": 0.03,
            "anxiety_driven_researcher": 0.04,
        },
        "domain_findings": [
            {"id": "f1", "title": "Support burden", "severity": "CRITICAL"},
            {"id": "f2", "title": "Pricing confusion", "severity": "MAJOR"},
        ],
    }
    payload.update(overrides)
    return payload


class _FakeAssumption:
    def __init__(
        self,
        category: str,
        sensitivity: str = "HIGH",
        is_hidden: bool = False,
        created_at: datetime | None = None,
    ) -> None:
        self.category = category
        self.sensitivity = sensitivity
        self.is_hidden = is_hidden
        self.created_at = created_at or datetime.now(UTC)


class _FakeProject:
    def __init__(
        self,
        project_id: int,
        *,
        premortem_json: dict | None = None,
        competitive_json: dict | None = None,
    ) -> None:
        self.id = project_id
        self.user_id = 42
        self.premortem_json = premortem_json
        self.competitive_json = competitive_json


class _FakeSimulation:
    def __init__(
        self,
        sim_id: int = 1,
        *,
        status: str = "COMPLETED",
        results: dict | None = None,
    ) -> None:
        self.id = sim_id
        self.project_id = 10
        self.status = status
        self.signal_quality = 0.62
        self.results_json = results if results is not None else _results()
        self.created_at = datetime.now(UTC) - timedelta(days=1)


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
        *,
        sim: _FakeSimulation | object = _MISSING,
        assumptions: list[_FakeAssumption] | None = None,
    ) -> None:
        self.sim = (
            sim if sim is not _MISSING else _FakeSimulation()
        )
        self.assumptions = (
            assumptions
            if assumptions is not None
            else [
                _FakeAssumption("Pricing"),
                _FakeAssumption("Trust"),
                _FakeAssumption("Onboarding"),
            ]
        )

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Simulation":
            return _FakeQuery([self.sim] if self.sim is not None else [])
        if name == "Assumption":
            return _FakeQuery(self.assumptions)
        table = getattr(getattr(model, "table", None), "name", None)
        if table == "outcomes":
            return _FakeQuery([])
        return _FakeQuery([])


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
    owned = project or _FakeProject(
        project_id,
        premortem_json={
            "failure_modes": [
                {
                    "title": "Competitors copy",
                    "severity": "MEDIUM",
                    "impact": 6,
                },
            ]
        },
        competitive_json={
            "overall_competitive_position": "MODERATE",
            "competitors": [
                {"name": "BigCo", "threat_level": "HIGH"},
                {"name": "TinyCo", "threat_level": "LOW"},
            ],
        },
    )
    if monkeypatch is not None:
        monkeypatch.setattr(
            projects_mod,
            "get_owned_project",
            lambda db_, user_id, project_id_: owned,
        )
    return projects_mod.get_go_no_go(
        project_id=project_id,
        db=db,
        current_user=type("U", (), {"id": current_user_id})(),
    )


def test_go_no_go_returns_full_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _call_route(monkeypatch=monkeypatch)

    assert out.project_id == 10
    assert out.latest_simulation_id == 1
    assert out.verdict in {
        "GO",
        "CONDITIONAL_GO",
        "NO_GO",
        "INSUFFICIENT_DATA",
    }
    assert out.verdict_label
    assert len(out.pillars) == 6
    assert {p.key for p in out.pillars} == {
        "readiness",
        "premortem",
        "competitive",
        "trust",
        "freshness",
        "coverage",
    }
    assert len(out.gates) == 5
    assert out.meta["total_pillars"] == 6
    assert out.narrative

    readiness = next(p for p in out.pillars if p.key == "readiness")
    assert readiness.score is not None
    assert readiness.evidence
    premortem = next(p for p in out.pillars if p.key == "premortem")
    assert premortem.summary
    competitive = next(p for p in out.pillars if p.key == "competitive")
    assert any("high-threat" in line for line in competitive.evidence)


def test_go_no_go_without_simulation_is_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(sim=None, assumptions=[])
    out = _call_route(session=session, monkeypatch=monkeypatch)

    assert out.latest_simulation_id is None
    assert out.go_no_go_score is None
    assert out.verdict == "INSUFFICIENT_DATA"
    readiness_gate = next(g for g in out.gates if g.id == "readiness_gate")
    assert readiness_gate.evaluated is False


def test_go_no_go_missing_project_raises_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    from app.api.v1 import projects as projects_mod

    def _not_found(db, user_id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")

    monkeypatch.setattr(projects_mod, "get_owned_project", _not_found)
    with pytest.raises(HTTPException) as exc:
        projects_mod.get_go_no_go(
            project_id=10,
            db=_FakeSession(),
            current_user=type("U", (), {"id": 42})(),
        )
    assert exc.value.status_code == 404


def test_go_no_go_uses_latest_completed_simulation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(
        sim=_FakeSimulation(sim_id=7, results=None),
    )
    out = _call_route(session=session, monkeypatch=monkeypatch)

    assert out.latest_simulation_id == 7
    # Empty results still produce evaluated readiness/trust pillars
    # (both score 0), so the digest must not crash on malformed rows.
    assert out.verdict in {
        "GO",
        "CONDITIONAL_GO",
        "NO_GO",
        "INSUFFICIENT_DATA",
    }
