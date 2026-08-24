"""Tests for the CSV launch-outcome backfill feature.

Covers the pure CSV parser (``app.simulation.outcomes_csv_import``) and the
route layer (``POST /projects/{id}/outcomes/batch/csv``). Route tests drive
the route function directly with a fake session, matching the pattern in
``test_outcomes_batch_api.py`` so no Postgres or Redis is required.
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.schemas.outcome import OutcomeCsvImportOut
from app.simulation import outcomes_csv_import as csv_mod
from app.simulation.outcomes_csv_import import (
    MAX_ROWS,
    CsvRowError,
    parse_outcomes_csv,
)

CSV_HEADER = (
    "actual_conversion_rate,actual_mrr,actual_cac,actual_churn_rate,"
    "days_since_launch,actual_dau,actual_nps,notes,client_request_id,"
    "simulation_id"
)


def _csv(*rows: str) -> bytes:
    return "\n".join([CSV_HEADER, *rows]).encode("utf-8")


# ---------------------------------------------------------------------------
# Parser: public surface
# ---------------------------------------------------------------------------


def test_parser_public_allowlist_matches_callers() -> None:

    assert set(csv_mod.__all__) == {
        "REQUIRED_COLUMNS",
        "OPTIONAL_COLUMNS",
        "READ_ONLY_COLUMNS",
        "MAX_ROWS",
        "CsvRowError",
        "CsvParseResult",
        "parse_outcomes_csv",
    }


# ---------------------------------------------------------------------------
# Parser: header handling
# ---------------------------------------------------------------------------


def test_parse_empty_csv_reports_header_required() -> None:
    result = parse_outcomes_csv("")
    assert result.items == []
    assert result.data_row_count == 0
    assert result.errors == [
        CsvRowError(row=1, column=None, error="CSV is empty — a header row is required")
    ]


def test_parse_header_only_reports_no_data_rows() -> None:
    result = parse_outcomes_csv(CSV_HEADER + "\n")
    assert result.items == []
    assert result.data_row_count == 0
    assert result.errors == [
        CsvRowError(
            row=1,
            column=None,
            error="CSV contains a header but no data rows",
        )
    ]


def test_parse_header_accepts_case_insensitive_and_bom() -> None:
    text = (
        "\ufeffACTUAL_CONVERSION_RATE,Actual_MRR,actual_cac,actual_churn_rate\n0.05,1000,50,0.03\n"
    )
    result = parse_outcomes_csv(text)
    assert result.errors == []
    assert len(result.items) == 1
    assert result.items[0]["actual_conversion_rate"] == 0.05
    assert result.items[0]["actual_mrr"] == 1000.0


def test_parse_header_missing_required_column() -> None:
    result = parse_outcomes_csv(
        "actual_conversion_rate,actual_mrr,actual_churn_rate\n0.05,1000,0.03\n"
    )
    assert result.items == []
    assert any(
        error.column == "actual_cac" and "missing required" in error.error and error.row == 1
        for error in result.errors
    )


def test_parse_header_rejects_unknown_column() -> None:
    result = parse_outcomes_csv(
        "actual_conversion_rate,actual_mrr,actual_cac,actual_churn_rate,revenue\n"
        "0.05,1000,50,0.03,999\n"
    )
    assert result.items == []
    assert any(
        error.column == "revenue" and "unknown column" in error.error for error in result.errors
    )


def test_parse_header_rejects_read_only_column() -> None:
    result = parse_outcomes_csv(
        "actual_conversion_rate,actual_mrr,actual_cac,actual_churn_rate,"
        "predicted_conversion_rate\n0.05,1000,50,0.03,0.04\n"
    )
    assert result.items == []
    assert any(
        error.column == "predicted_conversion_rate" and "read-only" in error.error
        for error in result.errors
    )


def test_parse_header_rejects_duplicate_column() -> None:
    result = parse_outcomes_csv(
        "actual_conversion_rate,actual_mrr,actual_cac,actual_churn_rate,"
        "actual_mrr\n0.05,1000,50,0.03,2000\n"
    )
    assert result.items == []
    assert any(
        error.column == "actual_mrr" and "duplicate column" in error.error
        for error in result.errors
    )


# ---------------------------------------------------------------------------
# Parser: cell coercion
# ---------------------------------------------------------------------------


def test_parse_rate_accepts_fraction_and_percentage() -> None:
    result = parse_outcomes_csv(
        "actual_conversion_rate,actual_mrr,actual_cac,actual_churn_rate\n5%,1000,50,12.5%\n"
    )
    assert result.errors == []
    assert result.items[0]["actual_conversion_rate"] == 0.05
    assert result.items[0]["actual_churn_rate"] == 0.125


def test_parse_rate_rejects_bare_whole_number_with_hint() -> None:
    result = parse_outcomes_csv(
        "actual_conversion_rate,actual_mrr,actual_cac,actual_churn_rate\n5,1000,50,0.03\n"
    )
    assert result.items == []
    error = next(e for e in result.errors if e.column == "actual_conversion_rate")
    assert error.row == 2
    assert "use 0.05 or 5%" in error.error


def test_parse_rejects_invalid_number() -> None:
    result = parse_outcomes_csv(
        "actual_conversion_rate,actual_mrr,actual_cac,actual_churn_rate\n"
        "0.05,not-a-number,50,0.03\n"
    )
    assert result.items == []
    assert any(
        error.column == "actual_mrr" and "invalid number" in error.error for error in result.errors
    )


def test_parse_optional_blanks_become_omitted_fields() -> None:
    result = parse_outcomes_csv(
        "actual_conversion_rate,actual_mrr,actual_cac,actual_churn_rate,"
        "days_since_launch,actual_dau,actual_nps,notes,client_request_id,"
        "simulation_id\n0.05,1000,50,0.03,,,,,,\n"
    )
    assert result.errors == []
    row = result.items[0]
    assert "days_since_launch" not in row
    assert "notes" not in row
    assert "simulation_id" not in row


def test_parse_integer_columns() -> None:
    result = parse_outcomes_csv(
        "actual_conversion_rate,actual_mrr,actual_cac,actual_churn_rate,"
        "days_since_launch,simulation_id\n0.05,1000,50,0.03,60,7\n"
    )
    assert result.errors == []
    assert result.items[0]["days_since_launch"] == 60
    assert result.items[0]["simulation_id"] == 7


def test_parse_rejects_invalid_integer() -> None:
    result = parse_outcomes_csv(
        "actual_conversion_rate,actual_mrr,actual_cac,actual_churn_rate,"
        "days_since_launch\n0.05,1000,50,0.03,thirty\n"
    )
    assert result.items == []
    assert any(
        error.column == "days_since_launch" and "invalid integer" in error.error
        for error in result.errors
    )


def test_parse_missing_required_value_reports_row_and_column() -> None:
    result = parse_outcomes_csv(
        "actual_conversion_rate,actual_mrr,actual_cac,actual_churn_rate\n"
        "0.05,1000,50,0.03\n"
        "0.06,,50,0.03\n"
    )
    # The clean first row is still parsed; the route rejects the whole
    # import because any error is present.
    assert len(result.items) == 1
    assert len(result.errors) == 1
    assert result.errors[0].row == 3
    assert result.errors[0].column == "actual_mrr"
    assert "missing required value" in result.errors[0].error


def test_parse_skips_blank_lines_and_keeps_spreadsheet_row_numbers() -> None:
    text = (
        "actual_conversion_rate,actual_mrr,actual_cac,actual_churn_rate\n"
        "\n"
        "0.05,1000,50,0.03\n"
        "\n"
        "0.06,2000,60,0.04\n"
    )
    result = parse_outcomes_csv(text)
    assert result.errors == []
    assert result.data_row_count == 2
    assert len(result.items) == 2


def test_parse_handles_quoted_commas_and_newlines_in_notes() -> None:
    text = (
        "actual_conversion_rate,actual_mrr,actual_cac,actual_churn_rate,notes\n"
        '0.05,1000,50,0.03,"launch, then paused\nresumed in June"\n'
    )
    result = parse_outcomes_csv(text)
    assert result.errors == []
    assert result.items[0]["notes"] == "launch, then paused\nresumed in June"


def test_parse_rejects_too_many_columns() -> None:
    result = parse_outcomes_csv(
        "actual_conversion_rate,actual_mrr,actual_cac,actual_churn_rate\n0.05,1000,50,0.03,999\n"
    )
    assert result.items == []
    assert result.errors[0].row == 2
    assert "row has 5 columns" in result.errors[0].error


def test_parse_rejects_duplicate_client_request_id() -> None:
    result = parse_outcomes_csv(
        "actual_conversion_rate,actual_mrr,actual_cac,actual_churn_rate,"
        "client_request_id\n"
        "0.05,1000,50,0.03,key-1\n"
        "0.06,2000,60,0.04,key-1\n"
    )
    assert len(result.items) == 1
    assert any(
        error.row == 3
        and error.column == "client_request_id"
        and "duplicate client_request_id" in error.error
        for error in result.errors
    )


def test_parse_caps_rows_at_100() -> None:
    rows = [f"0.0{i % 9 + 1},1000,50,0.03" for i in range(101)]
    result = parse_outcomes_csv("\n".join([CSV_HEADER, *rows]))
    assert result.data_row_count == 101
    assert len(result.items) == MAX_ROWS
    assert len(result.errors) == 1
    assert result.errors[0].row == 102
    assert "exceeds 100" in result.errors[0].error


def test_parse_reports_oversized_field_as_row_error() -> None:
    huge_notes = "x" * 200_000
    text = (
        "actual_conversion_rate,actual_mrr,actual_cac,actual_churn_rate,notes\n"
        f'0.05,1000,50,0.03,"{huge_notes}"\n'
    )
    result = parse_outcomes_csv(text)
    assert result.items == []
    assert result.data_row_count == 0
    assert len(result.errors) == 1
    assert result.errors[0].row == 2
    assert result.errors[0].column is None
    assert "too large to parse safely" in result.errors[0].error


# ---------------------------------------------------------------------------
# Route layer
# ---------------------------------------------------------------------------


class _Project:
    def __init__(self, project_id: int = 10) -> None:
        self.id = project_id
        self.status = "ACTIVE"


class _Simulation:
    def __init__(
        self,
        sim_id: int,
        status: str = "COMPLETED",
        results: dict | None = None,
        *,
        created_at: datetime | None = None,
    ) -> None:
        self.id = sim_id
        self.project_id = 10
        self.status = status
        self.results_json = (
            results
            if results is not None
            else {"mean_conversion_rate": 0.04, "mean_revenue": 900.0}
        )
        self.created_at = created_at or datetime(2026, 8, 1, tzinfo=UTC)


class _FakeQuery:
    def __init__(self, items: list) -> None:
        self._items = list(items)

    def filter(self, *args, **kwargs) -> _FakeQuery:
        return self

    def order_by(self, *args, **kwargs) -> _FakeQuery:
        return self

    def first(self) -> object | None:
        return self._items[0] if self._items else None

    def all(self) -> list:
        return list(self._items)


class _FakeSession:
    def __init__(
        self,
        *,
        project: _Project | None = None,
        simulations: list[_Simulation] | None = None,
    ) -> None:
        self.project = project or _Project()
        self.simulations = simulations if simulations is not None else []
        self.added: list = []
        self.committed = False
        self._next_id = 100

    def query(self, model, *args, **kwargs) -> _FakeQuery:
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery([self.project])
        if name == "Simulation":
            return _FakeQuery(self.simulations)
        return _FakeQuery([])

    def add(self, obj) -> None:
        self.added.append(obj)

    def add_all(self, objs) -> None:
        self.added.extend(objs)

    def commit(self) -> None:
        self.committed = True
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime(2026, 8, 10, tzinfo=UTC)

    def refresh(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = self._next_id
            self._next_id += 1
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime(2026, 8, 10, tzinfo=UTC)


class _FakeStream:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            return self._data
        return self._data[:size]


class _FakeUpload:
    def __init__(self, data: bytes) -> None:
        self.file = _FakeStream(data)


def _call_csv_import(
    data: bytes,
    session: _FakeSession | None = None,
) -> OutcomeCsvImportOut:
    from app.api.v1 import outcomes as out_mod

    db = session if session is not None else _FakeSession()
    return out_mod.import_outcomes_csv(
        project_id=10,
        file=_FakeUpload(data),
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


def test_csv_import_records_all_rows_with_latest_sim() -> None:
    latest = _Simulation(9, created_at=datetime(2026, 8, 5, tzinfo=UTC))
    session = _FakeSession(simulations=[latest])

    resp = _call_csv_import(
        _csv("0.05,1000,50,0.03", "3%,800,40,4%"),
        session=session,
    )

    assert resp.rows_scanned == 2
    assert resp.rows_rejected == 0
    assert resp.errors == []
    assert resp.created_count == 2
    assert resp.replayed_count == 0
    assert session.committed is True
    assert session.project.status == "OUTCOME_RECORDED"

    assert resp.outcomes[0].simulation_id == 9
    assert resp.outcomes[0].predicted_conversion_rate == 0.04
    assert resp.outcomes[0].predicted_mrr == 900.0
    assert resp.outcomes[0].variance.conversion == 25.0
    assert resp.outcomes[1].actual_conversion_rate == 0.03
    assert resp.outcomes[1].actual_churn_rate == 0.04


def test_csv_import_binds_explicit_simulation() -> None:
    sim = _Simulation(
        7,
        results={"mean_conversion_rate": 0.02, "mean_revenue": 400.0},
    )
    session = _FakeSession(simulations=[sim])

    resp = _call_csv_import(
        _csv("0.025,1000,50,0.03,,,,,,7"),
        session=session,
    )

    assert resp.created_count == 1
    assert resp.outcomes[0].simulation_id == 7
    assert resp.outcomes[0].predicted_conversion_rate == 0.02
    assert resp.outcomes[0].variance.conversion == 25.0


def test_csv_import_rejects_whole_file_on_row_error() -> None:
    session = _FakeSession(simulations=[_Simulation(7)])

    with pytest.raises(HTTPException) as exc:
        _call_csv_import(
            _csv("0.05,1000,50,0.03", "0.06,,50,0.03"),
            session=session,
        )

    assert exc.value.status_code == 422
    detail = exc.value.detail
    assert detail["rows_scanned"] == 2
    assert detail["rows_rejected"] == 1
    assert detail["errors"][0]["row"] == 3
    assert detail["errors"][0]["column"] == "actual_mrr"
    assert session.added == []
    assert session.committed is False


def test_csv_import_rejects_header_only_file() -> None:
    session = _FakeSession(simulations=[_Simulation(7)])

    with pytest.raises(HTTPException) as exc:
        _call_csv_import(CSV_HEADER.encode("utf-8"), session=session)

    assert exc.value.status_code == 422
    detail = exc.value.detail
    assert detail["rows_scanned"] == 0
    assert detail["rows_rejected"] == 1
    assert detail["errors"][0]["row"] == 1
    assert "no data rows" in detail["errors"][0]["error"]
    assert session.added == []


def test_csv_import_rejects_oversized_field_without_500() -> None:
    session = _FakeSession(simulations=[_Simulation(7)])
    huge_notes = "x" * 200_000
    body = (
        CSV_HEADER.encode("utf-8") + b'\n0.05,1000,50,0.03,"' + huge_notes.encode("utf-8") + b'"\n'
    )

    with pytest.raises(HTTPException) as exc:
        _call_csv_import(body, session=session)

    assert exc.value.status_code == 422
    detail = exc.value.detail
    assert detail["rows_scanned"] == 0
    assert detail["rows_rejected"] == 1
    assert detail["errors"][0]["row"] == 2
    assert "too large to parse safely" in detail["errors"][0]["error"]
    assert session.added == []


def test_csv_import_rejects_read_only_export_column() -> None:
    session = _FakeSession(simulations=[_Simulation(7)])

    with pytest.raises(HTTPException) as exc:
        _call_csv_import(
            b"actual_conversion_rate,actual_mrr,actual_cac,"
            b"actual_churn_rate,predicted_conversion_rate\n"
            b"0.05,1000,50,0.03,0.04\n",
            session=session,
        )

    assert exc.value.status_code == 422
    detail = exc.value.detail
    assert detail["rows_rejected"] == 1
    assert detail["errors"][0]["row"] == 1
    assert detail["errors"][0]["column"] == "predicted_conversion_rate"
    assert session.added == []


def test_csv_import_rejects_duplicate_client_request_id() -> None:
    session = _FakeSession(simulations=[_Simulation(7)])

    with pytest.raises(HTTPException) as exc:
        _call_csv_import(
            _csv(
                "0.05,1000,50,0.03,,,,,key-1",
                "0.06,2000,60,0.04,,,,,key-1",
            ),
            session=session,
        )

    assert exc.value.status_code == 422
    assert exc.value.detail["errors"][0]["column"] == "client_request_id"


def test_csv_import_maps_pydantic_errors_to_rows() -> None:
    session = _FakeSession(simulations=[_Simulation(7)])

    with pytest.raises(HTTPException) as exc:
        _call_csv_import(
            _csv("0.05,1000,50,0.03,,,200,,,"),
            session=session,
        )

    assert exc.value.status_code == 422
    detail = exc.value.detail
    assert detail["rows_rejected"] == 1
    assert detail["errors"][0]["row"] == 2
    assert detail["errors"][0]["column"] == "actual_nps"
    assert session.added == []


def test_csv_import_rejects_non_utf8() -> None:
    session = _FakeSession(simulations=[_Simulation(7)])

    with pytest.raises(HTTPException) as exc:
        _call_csv_import(b"\xff\xfe\x00invalid", session=session)

    assert exc.value.status_code == 400
    assert "UTF-8" in exc.value.detail


def test_csv_import_rejects_oversized_file(monkeypatch) -> None:
    from app.api.v1 import outcomes as out_mod

    monkeypatch.setattr(out_mod, "MAX_CSV_BYTES", 16)
    session = _FakeSession(simulations=[_Simulation(7)])

    with pytest.raises(HTTPException) as exc:
        _call_csv_import(b"a" * 17, session=session)

    assert exc.value.status_code == 400
    assert "exceeds" in exc.value.detail


def test_csv_import_handles_bom_and_blank_lines() -> None:
    latest = _Simulation(9)
    session = _FakeSession(simulations=[latest])
    text = "\ufeff" + CSV_HEADER + "\n\n0.05,1000,50,0.03\n"

    resp = _call_csv_import(text.encode("utf-8"), session=session)

    assert resp.rows_scanned == 1
    assert resp.created_count == 1


def test_csv_import_schema_validates_counts() -> None:
    out = OutcomeCsvImportOut(
        project_id=10,
        created_count=1,
        replayed_count=0,
        outcomes=[],
        rows_scanned=1,
        rows_rejected=0,
    )
    assert out.rows_scanned == 1
    assert out.errors == []

    with pytest.raises(ValidationError):
        OutcomeCsvImportOut(
            project_id=10,
            created_count=1,
            replayed_count=0,
            outcomes=[],
            rows_scanned=-1,
            rows_rejected=0,
        )
