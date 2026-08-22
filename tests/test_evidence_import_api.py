"""Route-level tests for bulk evidence import.

The import endpoint is the write-side complement to the CSV exports:
founders fill a downloaded spreadsheet offline and paste outcomes back.
These tests verify atomic batch insertion, per-row skip reporting for
unknown assumptions, and that an all-invalid batch writes nothing.
"""

from __future__ import annotations

import sys
import types

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _FakeProject:
    def __init__(self, project_id: int = 10) -> None:
        self.id = project_id
        self.user_id = 42


class _FakeAssumption:
    def __init__(self, assumption_id: int) -> None:
        self.id = assumption_id
        self.project_id = 10
        self.text = f"Assumption about {assumption_id}"
        self.is_hidden = False


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return list(self.items)


class _ImportSession:
    """Fake session tracking batch inserts and commit count."""

    def __init__(
        self,
        *,
        project: _FakeProject | None = None,
        project_missing: bool = False,
        assumptions: list | None = None,
    ) -> None:
        self.project = (
            None
            if project_missing
            else (project if project is not None else _FakeProject())
        )
        self.assumptions = (
            assumptions if assumptions is not None else [_FakeAssumption(100)]
        )
        self.added_rows: list = []
        self.commit_count = 0

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery([] if self.project is None else [self.project])
        if name == "Assumption":
            return _FakeQuery(list(self.assumptions))
        return _FakeQuery()

    def add_all(self, rows: list) -> None:
        self.added_rows.extend(rows)

    def commit(self) -> None:
        self.commit_count += 1


def _row(
    assumption_id: int,
    *,
    result: str = "PASS",
    method: str = "USER_INTERVIEWS",
) -> dict:
    return {
        "assumption_id": assumption_id,
        "method": method,
        "result": result,
    }


def _call_import(session: _ImportSession, rows: list[dict]):
    from app.api.v1 import assumption_evidence as ev_mod

    payload = ev_mod.EvidenceImportRequest.model_validate({"rows": rows})
    return ev_mod.import_assumption_evidence(
        project_id=10,
        payload=payload,
        db=session,  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )


def test_import_route_registered() -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in ev_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    path = "/projects/{project_id}/assumptions/evidence/import"
    assert "POST" in methods_by_path.get(path, set())


def test_import_inserts_valid_rows_in_one_commit() -> None:
    session = _ImportSession(
        assumptions=[_FakeAssumption(100), _FakeAssumption(101)],
    )

    out = _call_import(
        session,
        [
            _row(100),
            _row(101, result="FAIL", method="LANDING_PAGE_SMOKE_TEST"),
            _row(100, result="INCONCLUSIVE"),
        ],
    )

    assert out.project_id == 10
    assert out.imported_count == 3
    assert out.skipped_count == 0
    assert out.skipped_rows == []
    # Touched IDs are deduplicated and keep first-seen order.
    assert out.assumption_ids_touched == [100, 101]
    assert len(session.added_rows) == 3
    assert session.commit_count == 1
    inserted = session.added_rows[0]
    assert inserted.project_id == 10
    assert inserted.assumption_id == 100
    assert inserted.result == "PASS"


def test_import_skips_unknown_assumptions_with_reasons() -> None:
    session = _ImportSession(assumptions=[_FakeAssumption(100)])

    out = _call_import(
        session,
        [
            _row(999),
            _row(100, result="FAIL"),
            _row(555),
        ],
    )

    assert out.imported_count == 1
    assert out.skipped_count == 2
    assert [(s.index, s.assumption_id) for s in out.skipped_rows] == [
        (0, 999),
        (2, 555),
    ]
    assert all(
        "does not exist in this project" in s.reason
        for s in out.skipped_rows
    )
    assert len(session.added_rows) == 1
    assert session.commit_count == 1


def test_import_with_all_invalid_rows_writes_nothing() -> None:
    session = _ImportSession(assumptions=[_FakeAssumption(100)])

    out = _call_import(session, [_row(404), _row(500)])

    assert out.imported_count == 0
    assert out.skipped_count == 2
    assert session.added_rows == []
    # No valid rows means no commit at all.
    assert session.commit_count == 0


def test_import_missing_project_raises_404() -> None:
    session = _ImportSession(project_missing=True)
    with pytest.raises(HTTPException) as exc:
        _call_import(session, [_row(100)])

    assert exc.value.status_code == 404
    assert session.commit_count == 0


def test_import_request_rejects_empty_batch() -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    with pytest.raises(ValidationError):
        ev_mod.EvidenceImportRequest.model_validate({"rows": []})


def test_import_request_rejects_oversized_batch() -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    with pytest.raises(ValidationError):
        ev_mod.EvidenceImportRequest.model_validate(
            {"rows": [_row(100)] * 201}
        )


def test_import_request_rejects_unknown_fields_and_results() -> None:
    from app.schemas.assumption_evidence import EvidenceImportRow

    with pytest.raises(ValidationError):
        EvidenceImportRow.model_validate({**_row(100), "surprise": True})
    with pytest.raises(ValidationError):
        EvidenceImportRow.model_validate(
            {
                "assumption_id": 100,
                "method": "USER_INTERVIEWS",
                "result": "MAYBE",
            }
        )
