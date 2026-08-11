"""Route-level tests for ``GET /projects/{id}/risk-register/export``."""

from __future__ import annotations

import asyncio
import sys
import types

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _FakeProject:
    def __init__(
        self,
        project_id: int = 10,
        *,
        premortem_json: dict | None = None,
    ) -> None:
        self.id = project_id
        self.user_id = 42
        self.premortem_json = premortem_json
        self.stress_test_json = None
        self.competitive_json = None


class _FakeSimulation:
    def __init__(self, results: dict | None = None) -> None:
        self.id = 1
        self.project_id = 10
        self.status = "COMPLETED"
        self.results_json = results or {
            "mean_conversion_rate": 0.04,
            "domain_findings": [
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


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None


class _FakeSession:
    def __init__(self, sim: _FakeSimulation | None = None) -> None:
        self.sim = sim if sim is not None else _FakeSimulation()

    def query(self, model, *args, **kwargs):
        if getattr(model, "__name__", "") == "Simulation":
            return _FakeQuery([self.sim])
        return _FakeQuery([])


def _call_route(
    *,
    project_id: int = 10,
    format: str = "csv",
    session: _FakeSession | None = None,
    monkeypatch: pytest.MonkeyPatch,
    project: _FakeProject | None = None,
):
    from app.api.v1 import projects as projects_mod

    db = session if session is not None else _FakeSession()
    owned = project or _FakeProject(project_id)
    monkeypatch.setattr(
        projects_mod,
        "get_owned_project",
        lambda db_, user_id, project_id_: owned,
    )
    return projects_mod.export_risk_register(
        project_id=project_id,
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


def test_export_risk_register_returns_csv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resp = _call_route(monkeypatch=monkeypatch)

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="risk-register-10.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "user_id,42" in body
    assert "section,Risk Register Summary" in body
    assert "section,Severity Breakdown" in body
    assert "section,Source Breakdown" in body
    assert "section,Risks" in body
    assert "Price exceeds willingness to pay" in body


def test_export_risk_register_format_json_returns_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resp = _call_route(format="json", monkeypatch=monkeypatch)

    assert resp.media_type == "application/json; charset=utf-8"
    assert 'filename="risk-register-10.json"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert '"risk_register"' in body
    assert '"project_id": 10' in body
    assert '"total_risks"' in body
    assert '"Price exceeds willingness to pay"' in body


def test_export_risk_register_missing_project_raises_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import projects as projects_mod

    def _not_found(db, user_id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")

    monkeypatch.setattr(projects_mod, "get_owned_project", _not_found)

    with pytest.raises(HTTPException) as exc:
        projects_mod.export_risk_register(
            project_id=10,
            format="csv",
            db=_FakeSession(),
            current_user=type("U", (), {"id": 42})(),
        )
    assert exc.value.status_code == 404


def test_export_risk_register_csv_neutralizes_formula_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _FakeProject(
        10,
        premortem_json={
            "failure_modes": [
                {
                    "title": '=HYPERLINK("http://evil")',
                    "severity": "CRITICAL",
                    "probability": 0.5,
                    "impact": 0.9,
                    "intervention": "=NOW()",
                }
            ]
        },
    )

    resp = _call_route(
        session=_FakeSession(sim=None),
        project=project,
        monkeypatch=monkeypatch,
    )
    body = _body(resp).decode("utf-8")

    assert "'=HYPERLINK(" in body
    assert "'=NOW()" in body


def test_export_risk_register_route_registered() -> None:
    from app.api.v1 import projects as proj_mod

    paths = {r.path for r in proj_mod.router.routes}
    assert "/projects/{project_id}/risk-register/export" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in proj_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(r.methods or set())
    assert "GET" in methods_by_path["/projects/{project_id}/risk-register/export"]


def test_export_risk_register_invalid_format_rejected_with_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import projects as proj_mod
    from app.core.deps import get_current_user, get_db

    monkeypatch.setattr(
        proj_mod,
        "get_owned_project",
        lambda db, user_id, project_id: _FakeProject(project_id),
    )

    mini_app = FastAPI()
    mini_app.include_router(proj_mod.router)
    mini_app.dependency_overrides[get_db] = lambda: _FakeSession()
    mini_app.dependency_overrides[get_current_user] = lambda: type("U", (), {"id": 42})()

    with TestClient(mini_app) as client:
        resp = client.get(
            "/projects/10/risk-register/export",
            params={"format": "xlsx"},
        )

    assert resp.status_code == 422
