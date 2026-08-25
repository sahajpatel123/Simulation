"""Route-level tests for bulk evidence import.

The import endpoint is the write-side complement to the CSV exports:
founders fill a downloaded spreadsheet offline and paste outcomes back.
These tests verify atomic batch insertion, per-row skip reporting for
unknown assumptions, and that an all-invalid batch writes nothing.
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.api.v1 import assumption_evidence as ev_mod  # noqa: E402


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
            None if project_missing else (project if project is not None else _FakeProject())
        )
        self.assumptions = assumptions if assumptions is not None else [_FakeAssumption(100)]
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

    payload = ev_mod.EvidenceImportRequest.model_validate({"rows": rows})
    return ev_mod.import_assumption_evidence(
        project_id=10,
        payload=payload,
        db=session,  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )


def test_import_route_registered() -> None:

    methods_by_path: dict[str, set[str]] = {}
    for route in ev_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(route.methods or set())
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
    assert all("does not exist in this project" in s.reason for s in out.skipped_rows)
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

    with pytest.raises(ValidationError):
        ev_mod.EvidenceImportRequest.model_validate({"rows": []})


def test_import_request_rejects_oversized_batch() -> None:

    with pytest.raises(ValidationError):
        ev_mod.EvidenceImportRequest.model_validate({"rows": [_row(100)] * 201})


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


class _FakeCsvRequest:
    """Minimal stand-in for starlette Request with a preloaded body."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    async def body(self) -> bytes:
        return self._body


def _call_csv_import(session: _ImportSession, csv_text: str):

    return asyncio.run(
        ev_mod.import_assumption_evidence_csv(
            project_id=10,
            request=_FakeCsvRequest(csv_text.encode("utf-8")),
            db=session,  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
    )


_CSV_HEADER = "assumption_id,method,result,observed_metric,notes\n"


def test_csv_import_route_registered() -> None:

    methods_by_path: dict[str, set[str]] = {}
    for route in ev_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(route.methods or set())
    path = "/projects/{project_id}/assumptions/evidence/import/csv"
    assert "POST" in methods_by_path.get(path, set())


def test_csv_import_parses_valid_rows_and_normalises_case() -> None:
    session = _ImportSession(assumptions=[_FakeAssumption(100)])

    out = _call_csv_import(
        session,
        _CSV_HEADER + "100,USER_INTERVIEWS,pass,0.42,35 responses\n",
    )

    assert out.imported_count == 1
    assert out.skipped_count == 0
    assert out.assumption_ids_touched == [100]
    inserted = session.added_rows[0]
    assert inserted.result == "PASS"
    assert inserted.observed_metric == 0.42
    assert inserted.notes == "35 responses"
    assert session.commit_count == 1


def test_csv_import_skips_bad_cells_without_blocking_good_rows() -> None:
    session = _ImportSession(assumptions=[_FakeAssumption(100)])

    out = _call_csv_import(
        session,
        _CSV_HEADER
        + "999,WILLINGNESS_TO_PAY_SURVEY,FAIL,,unknown assumption\n"
        + "bad_id,USER_INTERVIEWS,FAIL,,\n"
        + "100,NOT_A_METHOD,FAIL,,\n"
        + "100,USER_INTERVIEWS,maybe,,\n"
        + "100,USER_INTERVIEWS,FAIL,not_a_number,\n"
        + "100,PRE_ORDER_WAITLIST,FAIL,,kept\n",
    )

    assert out.imported_count == 1
    assert out.skipped_count == 5
    reasons = [s.reason for s in out.skipped_rows]
    assert any("does not exist" in reason for reason in reasons)
    assert any("not a whole number" in reason for reason in reasons)
    assert any("not a known experiment method" in reason for reason in reasons)
    assert any("PASS/FAIL/INCONCLUSIVE" in reason for reason in reasons)
    assert any("not a number" in reason for reason in reasons)
    # The good row still landed.
    assert session.added_rows[0].notes == "kept"
    assert session.commit_count == 1


def test_csv_import_missing_required_column_returns_400() -> None:
    from fastapi import HTTPException

    session = _ImportSession()
    with pytest.raises(HTTPException) as exc:
        _call_csv_import(session, "assumption_id,method\n100,USER_INTERVIEWS\n")

    assert exc.value.status_code == 400
    assert "missing required column" in exc.value.detail
    assert "result" in exc.value.detail
    assert session.commit_count == 0


def test_csv_import_skips_blank_lines_without_shifting_indices() -> None:
    session = _ImportSession(assumptions=[_FakeAssumption(100)])

    out = _call_csv_import(
        session,
        _CSV_HEADER + "\n" + "100,USER_INTERVIEWS,FAIL,,\n" + "\n" + "100,USER_INTERVIEWS,FAIL,,\n",
    )

    assert out.imported_count == 2
    assert out.skipped_count == 0


def test_csv_import_handles_utf8_bom() -> None:

    session = _ImportSession(assumptions=[_FakeAssumption(100)])
    body = (
        "﻿"  # UTF-8 BOM
        + _CSV_HEADER
        + "100,USER_INTERVIEWS,FAIL,,\n"
    ).encode("utf-8")

    out = asyncio.run(
        ev_mod.import_assumption_evidence_csv(
            project_id=10,
            request=_FakeCsvRequest(body),
            db=session,  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
    )

    assert out.imported_count == 1
    assert out.skipped_count == 0


def test_csv_import_over_cap_returns_400() -> None:
    from fastapi import HTTPException

    session = _ImportSession()
    body = _CSV_HEADER + "100,USER_INTERVIEWS,FAIL,,\n" * 201

    with pytest.raises(HTTPException) as exc:
        _call_csv_import(session, body)

    assert exc.value.status_code == 400
    assert "200-row import limit" in exc.value.detail
    assert session.commit_count == 0


def test_csv_import_all_invalid_writes_nothing() -> None:
    session = _ImportSession(assumptions=[_FakeAssumption(100)])

    out = _call_csv_import(
        session,
        _CSV_HEADER + "100,USER_INTERVIEWS,maybe,,\n",
    )

    assert out.imported_count == 0
    assert out.skipped_count == 1
    assert session.added_rows == []
    assert session.commit_count == 0


class _TextAssumption:
    """Assumption fixture carrying realistic text for text-resolution."""

    def __init__(self, assumption_id: int, text: str) -> None:
        self.id = assumption_id
        self.project_id = 10
        self.text = text
        self.is_hidden = False


def test_json_import_resolves_rows_by_assumption_text() -> None:

    session = _ImportSession(
        assumptions=[
            _TextAssumption(100, "Users will pay ₹999 monthly"),
            _TextAssumption(101, "Onboarding completes in two minutes"),
        ]
    )

    payload = ev_mod.EvidenceImportRequest.model_validate(
        {
            "rows": [
                {
                    "assumption_text": "users will pay ₹999 MONTHLY ",
                    "method": "USER_INTERVIEWS",
                    "result": "PASS",
                },
                {
                    "assumption_text": "Nobody wants this",
                    "method": "USER_INTERVIEWS",
                    "result": "FAIL",
                },
            ]
        }
    )
    out = ev_mod.import_assumption_evidence(
        project_id=10,
        payload=payload,
        db=session,  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )

    assert out.imported_count == 1
    assert out.skipped_count == 1
    assert out.assumption_ids_touched == [100]
    inserted = session.added_rows[0]
    assert inserted.assumption_id == 100
    reason = out.skipped_rows[0].reason
    assert "no assumption matches text" in reason
    assert session.commit_count == 1


def test_json_import_row_without_id_or_text_is_rejected() -> None:

    with pytest.raises(ValidationError) as exc:
        ev_mod.EvidenceImportRequest.model_validate(
            {
                "rows": [
                    {"method": "USER_INTERVIEWS", "result": "PASS"},
                ]
            }
        )
    assert "assumption_id or assumption_text" in str(exc.value)


def test_json_import_prefers_id_when_both_given() -> None:

    session = _ImportSession(
        assumptions=[
            _TextAssumption(100, "Users will pay ₹999 monthly"),
            _TextAssumption(200, "A different claim entirely"),
        ]
    )

    payload = ev_mod.EvidenceImportRequest.model_validate(
        {
            "rows": [
                {
                    # ID wins even though the text points elsewhere.
                    "assumption_id": 200,
                    "assumption_text": "Users will pay ₹999 monthly",
                    "method": "USER_INTERVIEWS",
                    "result": "PASS",
                }
            ]
        }
    )
    out = ev_mod.import_assumption_evidence(
        project_id=10,
        payload=payload,
        db=session,  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )

    assert out.imported_count == 1
    assert out.assumption_ids_touched == [200]


def test_csv_import_resolves_blank_ids_by_text_column() -> None:

    session = _ImportSession(assumptions=[_TextAssumption(100, "Users will pay ₹999 monthly")])

    body = (
        "assumption_text,method,result,observed_metric,notes\n"
        "users will pay ₹999 monthly,USER_INTERVIEWS,PASS,0.4,text match\n"
        "Missing claim,LANDING_PAGE_SMOKE_TEST,FAIL,,not found\n"
    )
    out = asyncio.run(
        ev_mod.import_assumption_evidence_csv(
            project_id=10,
            request=_FakeCsvRequest(body.encode("utf-8")),
            db=session,  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
    )

    assert out.imported_count == 1
    assert out.skipped_count == 1
    assert session.added_rows[0].assumption_id == 100
    assert session.added_rows[0].notes == "text match"
    assert "no assumption matches text" in out.skipped_rows[0].reason


def test_csv_import_requires_method_and_result_headers_only() -> None:
    """The id column is optional now; method/result stay mandatory."""

    session = _ImportSession()

    # assumption_text alone satisfies the per-row key requirement.
    body = "assumption_text,method,result\nSome claim,USER_INTERVIEWS,FAIL\n"
    out = asyncio.run(
        ev_mod.import_assumption_evidence_csv(
            project_id=10,
            request=_FakeCsvRequest(body.encode("utf-8")),
            db=session,  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
    )
    assert out.skipped_count == 1  # no matching assumption — skip, not crash

    # Neither key column on a data row → that row skips with a reason
    # naming both accepted keys; the batch itself still parses.
    out = asyncio.run(
        ev_mod.import_assumption_evidence_csv(
            project_id=10,
            request=_FakeCsvRequest(b"method,result\nUSER_INTERVIEWS,PASS\n"),
            db=session,  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
    )
    assert out.imported_count == 0
    assert out.skipped_count == 1
    assert "assumption_id or assumption_text" in out.skipped_rows[0].reason
