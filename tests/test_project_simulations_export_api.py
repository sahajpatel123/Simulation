"""Route-level tests for the /projects/{id}/simulations/export endpoint."""
from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _Simulation:
    def __init__(self, simulation_id: int = 1) -> None:
        self.id = simulation_id
        self.project_id = 10
        self.status = "COMPLETED"
        self.created_at = "2026-08-07T20:00:00+00:00"
        self.signal_quality = 0.62
        self.results_json = {
            "product_type_detected": "saas",
            "population_weighted_conversion": 0.042,
        }


class _Project:
    def __init__(self) -> None:
        self.id = 10
        self.tags = ["saas", "india"]
        self.mvp_feature_list = ["Auth"]


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def count(self):
        return len(self.items)

    def all(self):
        return list(self.items)


class _FakeSession:
    def __init__(self, simulations: list | None = None) -> None:
        self.simulations = simulations if simulations is not None else [_Simulation()]

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery([_Project()])
        if name == "Simulation":
            return _FakeQuery(self.simulations)
        return _FakeQuery([])


def _call_route(
    *,
    project_id: int = 10,
    format: str = "csv",
    session: _FakeSession | None = None,
):
    from app.api.v1 import projects as proj_mod

    db = session if session is not None else _FakeSession()
    return proj_mod.export_project_simulations(
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


def test_export_project_simulations_returns_csv() -> None:
    resp = _call_route()

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="simulations-10.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "simulation_id,project_id,status,created_at" in body
    assert "1,10,COMPLETED,2026-08-07T20:00:00+00:00,0.6200,saas,0.0420" in body


def test_export_project_simulations_format_json_returns_payload() -> None:
    resp = _call_route(format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert '"project_id": 10' in body
    assert '"population_weighted_conversion": 0.042' in body


def test_export_project_simulations_empty_returns_header_only() -> None:
    session = _FakeSession(simulations=[])
    resp = _call_route(session=session)

    body = _body(resp).decode("utf-8")
    assert "simulation_id,project_id,status,created_at" in body
    assert "1,10,COMPLETED" not in body


def test_export_project_simulations_missing_project_raises_404() -> None:
    class NoProjectSession(_FakeSession):
        def query(self, model, *args, **kwargs):
            name = getattr(model, "__name__", "")
            if name == "Project":
                return _FakeQuery([])
            return _FakeQuery(self.simulations)

    with pytest.raises(HTTPException) as exc:
        _call_route(session=NoProjectSession())
    assert exc.value.status_code == 404


def test_export_simulation_count_returns_csv() -> None:
    from app.api.v1 import projects as proj_mod

    db = _FakeSession(simulations=[_Simulation(), _Simulation()])
    resp = proj_mod.export_simulation_count(
        project_id=10,
        format="csv",
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )

    assert resp.media_type == "text/csv; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert "project_id,simulation_count" in body
    assert "10,2" in body


def test_export_simulation_count_format_json_returns_payload() -> None:
    from app.api.v1 import projects as proj_mod

    db = _FakeSession(simulations=[_Simulation(), _Simulation()])
    resp = proj_mod.export_simulation_count(
        project_id=10,
        format="json",
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )

    assert resp.media_type == "application/json; charset=utf-8"
    assert 'filename="simulation-count-10.json"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    payload = json.loads(body)
    assert payload["project_id"] == 10
    assert payload["simulation_count"] == 2
    assert isinstance(payload["simulation_count"], int)
    assert set(payload) == {"generated_at", "project_id", "simulation_count"}


def test_export_simulation_count_zero_counts_in_both_formats() -> None:
    from app.api.v1 import projects as proj_mod

    db = _FakeSession(simulations=[])
    user = type("U", (), {"id": 42})()

    csv_resp = proj_mod.export_simulation_count(
        project_id=10,
        format="csv",
        db=db,
        current_user=user,
    )
    assert "10,0" in _body(csv_resp).decode("utf-8")

    json_resp = proj_mod.export_simulation_count(
        project_id=10,
        format="json",
        db=db,
        current_user=user,
    )
    payload = json.loads(_body(json_resp).decode("utf-8"))
    assert payload["project_id"] == 10
    assert payload["simulation_count"] == 0


def test_export_simulation_count_invalid_format_rejected_with_422() -> None:
    from app.api.v1 import projects as proj_mod
    from app.core.deps import get_current_user, get_db

    mini_app = FastAPI()
    mini_app.include_router(proj_mod.router)
    mini_app.dependency_overrides[get_db] = lambda: _FakeSession(
        simulations=[_Simulation()]
    )
    mini_app.dependency_overrides[get_current_user] = lambda: type(
        "U", (), {"id": 42}
    )()

    with TestClient(mini_app) as client:
        resp = client.get(
            "/projects/10/simulation-count/export",
            params={"format": "xlsx"},
        )

    assert resp.status_code == 422


def test_export_decision_count_returns_csv() -> None:
    from app.api.v1 import projects as proj_mod

    db = _FakeSession(simulations=[])
    resp = proj_mod.export_decision_count(
        project_id=10,
        format="csv",
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )

    assert resp.media_type == "text/csv; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert "project_id,decision_count" in body
    assert "10,0" in body


def test_export_decision_count_invalid_format_rejected_with_422() -> None:
    from app.api.v1 import projects as proj_mod
    from app.core.deps import get_current_user, get_db

    mini_app = FastAPI()
    mini_app.include_router(proj_mod.router)
    mini_app.dependency_overrides[get_db] = lambda: _FakeSession(simulations=[])
    mini_app.dependency_overrides[get_current_user] = lambda: type(
        "U", (), {"id": 42}
    )()

    with TestClient(mini_app) as client:
        resp = client.get(
            "/projects/10/decision-count/export",
            params={"format": "xlsx"},
        )

    assert resp.status_code == 422


def test_export_outcome_count_returns_csv() -> None:
    from app.api.v1 import projects as proj_mod

    db = _FakeSession(simulations=[])
    resp = proj_mod.export_outcome_count(
        project_id=10,
        format="csv",
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )

    assert resp.media_type == "text/csv; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert "project_id,outcome_count" in body
    assert "10,0" in body


def test_export_outcome_count_invalid_format_rejected_with_422() -> None:
    from app.api.v1 import projects as proj_mod
    from app.core.deps import get_current_user, get_db

    mini_app = FastAPI()
    mini_app.include_router(proj_mod.router)
    mini_app.dependency_overrides[get_db] = lambda: _FakeSession(simulations=[])
    mini_app.dependency_overrides[get_current_user] = lambda: type(
        "U", (), {"id": 42}
    )()

    with TestClient(mini_app) as client:
        resp = client.get(
            "/projects/10/outcome-count/export",
            params={"format": "xlsx"},
        )

    assert resp.status_code == 422


def test_export_assumption_count_returns_csv() -> None:
    from app.api.v1 import projects as proj_mod

    db = _FakeSession(simulations=[])
    resp = proj_mod.export_assumption_count(
        project_id=10,
        format="csv",
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )

    assert resp.media_type == "text/csv; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert "project_id,assumption_count" in body
    assert "10,0" in body


def test_export_assumption_count_invalid_format_rejected_with_422() -> None:
    from app.api.v1 import projects as proj_mod
    from app.core.deps import get_current_user, get_db

    mini_app = FastAPI()
    mini_app.include_router(proj_mod.router)
    mini_app.dependency_overrides[get_db] = lambda: _FakeSession(simulations=[])
    mini_app.dependency_overrides[get_current_user] = lambda: type(
        "U", (), {"id": 42}
    )()

    with TestClient(mini_app) as client:
        resp = client.get(
            "/projects/10/assumption-count/export",
            params={"format": "xlsx"},
        )

    assert resp.status_code == 422


def test_export_tag_count_returns_csv() -> None:
    from app.api.v1 import projects as proj_mod

    db = _FakeSession(simulations=[])
    resp = proj_mod.export_tag_count(
        project_id=10,
        format="csv",
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )

    assert resp.media_type == "text/csv; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert "project_id,tag_count" in body
    assert "10,2" in body


def test_export_tag_count_invalid_format_rejected_with_422() -> None:
    from app.api.v1 import projects as proj_mod
    from app.core.deps import get_current_user, get_db

    mini_app = FastAPI()
    mini_app.include_router(proj_mod.router)
    mini_app.dependency_overrides[get_db] = lambda: _FakeSession(simulations=[])
    mini_app.dependency_overrides[get_current_user] = lambda: type(
        "U", (), {"id": 42}
    )()

    with TestClient(mini_app) as client:
        resp = client.get(
            "/projects/10/tag-count/export",
            params={"format": "xlsx"},
        )

    assert resp.status_code == 422


def test_export_prototype_count_returns_csv() -> None:
    from app.api.v1 import projects as proj_mod

    db = _FakeSession(simulations=[])
    resp = proj_mod.export_prototype_count(
        project_id=10,
        format="csv",
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )

    assert resp.media_type == "text/csv; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert "project_id,prototype_count" in body
    assert "10,0" in body


def test_export_prototype_count_invalid_format_rejected_with_422() -> None:
    from app.api.v1 import projects as proj_mod
    from app.core.deps import get_current_user, get_db

    mini_app = FastAPI()
    mini_app.include_router(proj_mod.router)
    mini_app.dependency_overrides[get_db] = lambda: _FakeSession(simulations=[])
    mini_app.dependency_overrides[get_current_user] = lambda: type(
        "U", (), {"id": 42}
    )()

    with TestClient(mini_app) as client:
        resp = client.get(
            "/projects/10/prototype-count/export",
            params={"format": "xlsx"},
        )

    assert resp.status_code == 422


def test_export_evidence_count_returns_csv() -> None:
    from app.api.v1 import projects as proj_mod

    db = _FakeSession(simulations=[])
    resp = proj_mod.export_evidence_count(
        project_id=10,
        format="csv",
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )

    assert resp.media_type == "text/csv; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert "project_id,evidence_count" in body
    assert "10,0" in body


def test_export_evidence_count_invalid_format_rejected_with_422() -> None:
    from app.api.v1 import projects as proj_mod
    from app.core.deps import get_current_user, get_db

    mini_app = FastAPI()
    mini_app.include_router(proj_mod.router)
    mini_app.dependency_overrides[get_db] = lambda: _FakeSession(simulations=[])
    mini_app.dependency_overrides[get_current_user] = lambda: type(
        "U", (), {"id": 42}
    )()

    with TestClient(mini_app) as client:
        resp = client.get(
            "/projects/10/evidence-count/export",
            params={"format": "xlsx"},
        )

    assert resp.status_code == 422


def test_export_outcome_tracker_count_returns_csv() -> None:
    from app.api.v1 import projects as proj_mod

    db = _FakeSession(simulations=[])
    resp = proj_mod.export_outcome_tracker_count(
        project_id=10,
        format="csv",
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )

    assert resp.media_type == "text/csv; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert "project_id,outcome_tracker_count" in body
    assert "10,0" in body


def test_export_outcome_tracker_count_invalid_format_rejected_with_422() -> None:
    from app.api.v1 import projects as proj_mod
    from app.core.deps import get_current_user, get_db

    mini_app = FastAPI()
    mini_app.include_router(proj_mod.router)
    mini_app.dependency_overrides[get_db] = lambda: _FakeSession(simulations=[])
    mini_app.dependency_overrides[get_current_user] = lambda: type(
        "U", (), {"id": 42}
    )()

    with TestClient(mini_app) as client:
        resp = client.get(
            "/projects/10/outcome-tracker-count/export",
            params={"format": "xlsx"},
        )

    assert resp.status_code == 422


def test_export_premortem_count_returns_csv() -> None:
    from app.api.v1 import projects as proj_mod

    db = _FakeSession(simulations=[])
    resp = proj_mod.export_premortem_count(
        project_id=10,
        format="csv",
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )

    assert resp.media_type == "text/csv; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert "project_id,premortem_count" in body
    assert "10,0" in body


def test_export_premortem_count_invalid_format_rejected_with_422() -> None:
    from app.api.v1 import projects as proj_mod
    from app.core.deps import get_current_user, get_db

    mini_app = FastAPI()
    mini_app.include_router(proj_mod.router)
    mini_app.dependency_overrides[get_db] = lambda: _FakeSession(simulations=[])
    mini_app.dependency_overrides[get_current_user] = lambda: type(
        "U", (), {"id": 42}
    )()

    with TestClient(mini_app) as client:
        resp = client.get(
            "/projects/10/premortem-count/export",
            params={"format": "xlsx"},
        )

    assert resp.status_code == 422


def test_export_intervention_count_returns_csv() -> None:
    from app.api.v1 import projects as proj_mod

    db = _FakeSession(simulations=[])
    resp = proj_mod.export_intervention_count(
        project_id=10,
        format="csv",
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )

    assert resp.media_type == "text/csv; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert "project_id,intervention_count" in body
    assert "10,0" in body


def test_export_intervention_count_invalid_format_rejected_with_422() -> None:
    from app.api.v1 import projects as proj_mod
    from app.core.deps import get_current_user, get_db

    mini_app = FastAPI()
    mini_app.include_router(proj_mod.router)
    mini_app.dependency_overrides[get_db] = lambda: _FakeSession(simulations=[])
    mini_app.dependency_overrides[get_current_user] = lambda: type(
        "U", (), {"id": 42}
    )()

    with TestClient(mini_app) as client:
        resp = client.get(
            "/projects/10/intervention-count/export",
            params={"format": "xlsx"},
        )

    assert resp.status_code == 422


def test_export_competitive_count_returns_csv() -> None:
    from app.api.v1 import projects as proj_mod

    db = _FakeSession(simulations=[])
    resp = proj_mod.export_competitive_count(
        project_id=10,
        format="csv",
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )

    assert resp.media_type == "text/csv; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert "project_id,competitive_count" in body
    assert "10,0" in body


def test_export_competitive_count_invalid_format_rejected_with_422() -> None:
    from app.api.v1 import projects as proj_mod
    from app.core.deps import get_current_user, get_db

    mini_app = FastAPI()
    mini_app.include_router(proj_mod.router)
    mini_app.dependency_overrides[get_db] = lambda: _FakeSession(simulations=[])
    mini_app.dependency_overrides[get_current_user] = lambda: type(
        "U", (), {"id": 42}
    )()

    with TestClient(mini_app) as client:
        resp = client.get(
            "/projects/10/competitive-count/export",
            params={"format": "xlsx"},
        )

    assert resp.status_code == 422


def test_export_mvp_feature_count_returns_csv() -> None:
    from app.api.v1 import projects as proj_mod

    db = _FakeSession(simulations=[])
    resp = proj_mod.export_mvp_feature_count(
        project_id=10,
        format="csv",
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )

    assert resp.media_type == "text/csv; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert "project_id,mvp_feature_count" in body
    assert "10,1" in body


def test_export_mvp_feature_count_invalid_format_rejected_with_422() -> None:
    from app.api.v1 import projects as proj_mod
    from app.core.deps import get_current_user, get_db

    mini_app = FastAPI()
    mini_app.include_router(proj_mod.router)
    mini_app.dependency_overrides[get_db] = lambda: _FakeSession(simulations=[])
    mini_app.dependency_overrides[get_current_user] = lambda: type(
        "U", (), {"id": 42}
    )()

    with TestClient(mini_app) as client:
        resp = client.get(
            "/projects/10/mvp-feature-count/export",
            params={"format": "xlsx"},
        )

    assert resp.status_code == 422


def test_export_readings_count_returns_csv() -> None:
    from app.api.v1 import projects as proj_mod

    db = _FakeSession(simulations=[])
    resp = proj_mod.export_readings_count(
        project_id=10,
        format="csv",
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )

    assert resp.media_type == "text/csv; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert "project_id,readings_count" in body
    assert "10,0" in body


def test_export_readings_count_invalid_format_rejected_with_422() -> None:
    from app.api.v1 import projects as proj_mod
    from app.core.deps import get_current_user, get_db

    mini_app = FastAPI()
    mini_app.include_router(proj_mod.router)
    mini_app.dependency_overrides[get_db] = lambda: _FakeSession(simulations=[])
    mini_app.dependency_overrides[get_current_user] = lambda: type(
        "U", (), {"id": 42}
    )()

    with TestClient(mini_app) as client:
        resp = client.get(
            "/projects/10/readings-count/export",
            params={"format": "xlsx"},
        )

    assert resp.status_code == 422
