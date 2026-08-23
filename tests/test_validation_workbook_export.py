"""Tests for the validation-workbook ZIP export.

The workbook bundles the project's CSV validation exports into one
download. Builders are stubbed so these tests pin the bundling contract:
entry names come from each sheet's Content-Disposition, the manifest
lists what shipped, and a failing sheet lands in errors.txt instead of
sinking the bundle.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import types
import zipfile

from fastapi import HTTPException
from starlette.responses import StreamingResponse

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def _sheet_response(filename: str, body: bytes) -> StreamingResponse:
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class _FakeProject:
    def __init__(self, project_id: int = 10) -> None:
        self.id = project_id
        self.user_id = 42


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None


class _WorkbookSession:
    """Fake session that only needs to resolve the owned project."""

    def __init__(self) -> None:
        self.project = _FakeProject()

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery([self.project])
        return _FakeQuery()

    def commit(self) -> None:  # pragma: no cover - builders are stubbed
        raise AssertionError("workbook route must not write")


_SHEET_BODIES = {
    "assumptions.csv": b"assumption_id,text,category\n50,Pricing,HIGH\n",
    "validation-timeline-10.csv": b"section,Events\n",
    "validation-momentum-10.csv": b"section,Momentum Counts\n",
    "evidence-freshness-10.csv": b"section,Freshness\n",
    "validation-dashboard-10.csv": b"section,Dashboard\n",
    "validation-momentum-10.md": b"# Validation Momentum\n",
    "validation-dashboard-10.md": b"# Validation Dashboard\n",
}


def _install_builders(monkeypatch, *, fail_label: str | None = None) -> dict:
    from app.api.v1 import assumption_evidence as ev_mod

    calls: dict[str, tuple] = {}

    def make(label, filename):
        def _builder(**kwargs):
            calls[label] = dict(kwargs)
            if label == fail_label:
                raise HTTPException(status_code=409, detail="not ready")
            return _sheet_response(filename, _SHEET_BODIES[filename])

        return _builder

    monkeypatch.setattr(
        ev_mod, "export_assumptions_csv", make("assumptions", "assumptions.csv")
    )
    monkeypatch.setattr(
        ev_mod,
        "export_assumption_validation_timeline",
        make("validation-timeline", "validation-timeline-10.csv"),
    )
    monkeypatch.setattr(
        ev_mod,
        "export_validation_momentum",
        make("validation-momentum", "validation-momentum-10.csv"),
    )
    monkeypatch.setattr(
        ev_mod,
        "export_evidence_freshness",
        make("evidence-freshness", "evidence-freshness-10.csv"),
    )
    monkeypatch.setattr(
        ev_mod,
        "export_validation_dashboard",
        make("validation-dashboard", "validation-dashboard-10.csv"),
    )
    # Markdown briefs reuse the momentum/dashboard builders with format=md;
    # the same stub serves both by matching on the requested format.
    def _momentum_any(**kwargs):
        if kwargs.get("format") == "md":
            calls.setdefault("momentum-brief", dict(kwargs))
            return _sheet_response(
                "validation-momentum-10.md", _SHEET_BODIES["validation-momentum-10.md"]
            )
        return _builder_momentum_csv(**kwargs)

    def _dashboard_any(**kwargs):
        if kwargs.get("format") == "md":
            calls.setdefault("dashboard-brief", dict(kwargs))
            return _sheet_response(
                "validation-dashboard-10.md",
                _SHEET_BODIES["validation-dashboard-10.md"],
            )
        return _builder_dashboard_csv(**kwargs)

    _builder_momentum_csv = ev_mod.export_validation_momentum
    _builder_dashboard_csv = ev_mod.export_validation_dashboard
    monkeypatch.setattr(ev_mod, "export_validation_momentum", _momentum_any)
    monkeypatch.setattr(
        ev_mod, "export_validation_dashboard", _dashboard_any
    )
    return calls


def _call_workbook(session):
    from app.api.v1 import assumption_evidence as ev_mod

    return asyncio.run(
        ev_mod.export_validation_workbook(
            project_id=10,
            db=session,  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
    )


async def _drain(response) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def test_workbook_route_registered() -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in ev_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    path = "/projects/{project_id}/validation-workbook/export"
    assert "GET" in methods_by_path.get(path, set())


def test_workbook_bundles_all_sheets_with_manifest(monkeypatch) -> None:
    _install_builders(monkeypatch)

    response = _call_workbook(_WorkbookSession())
    body = asyncio.run(_drain(response))

    assert response.media_type == "application/zip"
    assert 'filename="validation-workbook-10.zip"' in (
        response.headers["Content-Disposition"]
    )
    assert int(response.headers["Content-Length"]) == len(body)
    assert b"errors.txt" not in body

    archive = zipfile.ZipFile(io.BytesIO(body))
    names = set(archive.namelist())
    assert names == set(_SHEET_BODIES) | {"README.txt"}
    for filename, expected in _SHEET_BODIES.items():
        assert archive.read(filename) == expected

    readme = archive.read("README.txt").decode("utf-8")
    assert readme.startswith("TheCee Validation Workbook")
    assert "- assumptions.csv (" in readme
    assert "Project: 10" in readme
    # The manifest teaches the offline loop.
    assert "assumptions/import/csv" in readme
    assert "evidence/import/csv" in readme


def test_workbook_reports_failed_sheet_without_sinking_bundle(
    monkeypatch,
) -> None:
    _install_builders(monkeypatch, fail_label="evidence-freshness")

    response = _call_workbook(_WorkbookSession())
    body = asyncio.run(_drain(response))

    archive = zipfile.ZipFile(io.BytesIO(body))
    names = set(archive.namelist())
    assert "evidence-freshness-10.csv" not in names
    assert "errors.txt" in names
    assert "validation-momentum-10.csv" in names

    errors = archive.read("errors.txt").decode("utf-8")
    assert "evidence-freshness: 409 not ready" in errors

    readme = archive.read("README.txt").decode("utf-8")
    assert "errors.txt" in readme


def test_workbook_forwarded_builder_kwargs(monkeypatch) -> None:
    """Momentum/freshness/dashboard get explicit numeric windows."""
    calls = _install_builders(monkeypatch)

    _call_workbook(_WorkbookSession())

    momentum_kwargs = calls["validation-momentum"]
    assert momentum_kwargs["target_de_risked_pct"] == 1.0
    freshness_kwargs = calls["evidence-freshness"]
    assert isinstance(freshness_kwargs["fresh_days"], int)
    assert isinstance(freshness_kwargs["aging_days"], int)
    dashboard_kwargs = calls["validation-dashboard"]
    assert dashboard_kwargs["target_de_risked_pct"] == 1.0
    # Every call is scoped to the owned project.
    for label, kwargs in calls.items():
        assert kwargs["project_id"] == 10, label


def test_workbook_json_metadata_shape_untouched() -> None:
    """Sanity: envelope key used by sheets stays stable across refactor."""
    from app.simulation.validation_momentum_export import (
        validation_momentum_to_json,
    )

    parsed = json.loads(
        validation_momentum_to_json({"counts": {}}, metadata={"user_id": 1})
    )
    assert set(parsed) == {"metadata", "validation_momentum"}
