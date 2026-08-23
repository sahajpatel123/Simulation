"""Route-level tests for bulk assumption import.

The import creates new assumptions idempotently: exact-duplicate texts
are skipped both against the project's existing assumptions and within
the batch. Covers JSON + CSV routes, dedupe behaviour, per-row skip
reasons, caps, and route registration.
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


class _FakeProject:
    def __init__(self, project_id: int = 10) -> None:
        self.id = project_id
        self.user_id = 42


class _FakeAssumption:
    def __init__(self, assumption_id: int, text: str) -> None:
        self.id = assumption_id
        self.project_id = 10
        self.text = text


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
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
        # Assumptions already stored for this project.
        self.existing = (
            assumptions if assumptions is not None else []
        )
        self.added_rows: list = []
        self.commit_count = 0

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery([] if self.project is None else [self.project])
        if name in ("Assumption", "Assumption.text"):
            return _FakeQuery(list(self.existing))
        return _FakeQuery()

    def add_all(self, rows: list) -> None:
        self.added_rows.extend(rows)

    def commit(self) -> None:
        self.commit_count += 1


class _FakeCsvRequest:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def body(self) -> bytes:
        return self._body


def _row(text: str, **overrides) -> dict:
    base = {"text": text}
    base.update(overrides)
    return base


def _call_json_import(session: _ImportSession, rows: list[dict]):
    from app.api.v1 import assumption_evidence as ev_mod

    payload = ev_mod.AssumptionImportRequest.model_validate({"rows": rows})
    return ev_mod.import_assumptions(
        project_id=10,
        payload=payload,
        db=session,  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )


def _call_csv_import(session: _ImportSession, csv_text: str):
    from app.api.v1 import assumption_evidence as ev_mod

    return asyncio.run(
        ev_mod.import_assumptions_csv(
            project_id=10,
            request=_FakeCsvRequest(csv_text.encode("utf-8")),
            db=session,  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
    )


_CSV_HEADER = "text,category,sensitivity,impact_score\n"


def test_assumption_import_routes_registered() -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in ev_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    assert "POST" in methods_by_path.get(
        "/projects/{project_id}/assumptions/import", set()
    )
    assert "POST" in methods_by_path.get(
        "/projects/{project_id}/assumptions/import/csv", set()
    )


def test_json_import_inserts_valid_rows_in_one_commit() -> None:
    session = _ImportSession()

    out = _call_json_import(
        session,
        [
            _row("Users will pay ₹999 monthly", sensitivity="HIGH"),
            _row("Onboarding completes in under 2 minutes"),
        ],
    )

    assert out.project_id == 10
    assert out.imported_count == 2
    assert out.skipped_count == 0
    assert len(session.added_rows) == 2
    assert session.commit_count == 1
    first = session.added_rows[0]
    assert first.sensitivity == "HIGH"
    assert first.category == "Market"
    assert first.impact_score == 5.0


def test_json_import_skips_duplicates_within_batch() -> None:
    session = _ImportSession()

    out = _call_json_import(
        session,
        [
            _row("Users will pay ₹999 monthly"),
            _row("users will pay ₹999 monthly"),  # same text, other case
            _row("Users will pay ₹999 monthly"),  # exact repeat
        ],
    )

    assert out.imported_count == 1
    assert out.skipped_count == 2
    assert all("already exists" in s.reason for s in out.skipped_rows)
    assert [s.index for s in out.skipped_rows] == [1, 2]


def test_json_import_is_idempotent_against_existing_rows() -> None:
    session = _ImportSession(
        assumptions=[_FakeAssumption(50, "Users will pay ₹999 monthly")],
    )

    out = _call_json_import(
        session,
        [
            _row("Users will pay ₹999 monthly"),
            _row("A brand-new assumption"),
        ],
    )

    assert out.imported_count == 1
    assert out.skipped_count == 1
    assert out.skipped_rows[0].index == 0
    assert len(session.added_rows) == 1
    assert session.commit_count == 1


def test_json_import_missing_project_raises_404() -> None:
    session = _ImportSession(project_missing=True)
    with pytest.raises(HTTPException) as exc:
        _call_json_import(session, [_row("Something to validate")])

    assert exc.value.status_code == 404
    assert session.commit_count == 0


def test_request_rejects_empty_and_oversized_batches() -> None:
    from app.schemas.assumption_import import AssumptionImportRequest

    with pytest.raises(ValidationError):
        AssumptionImportRequest.model_validate({"rows": []})
    with pytest.raises(ValidationError):
        AssumptionImportRequest.model_validate(
            {"rows": [_row("x")] * 201}
        )


def test_csv_import_parses_defaults_and_normalises_case() -> None:
    session = _ImportSession()

    out = _call_csv_import(
        session,
        _CSV_HEADER
        + "Users will pay ₹999 monthly,Pricing,high,8\n"
        + "Signup needs no credit card,,,,\n",
    )

    assert out.imported_count == 2
    assert out.skipped_count == 0
    pricing_row = session.added_rows[0]
    assert pricing_row.sensitivity == "HIGH"
    assert pricing_row.category == "Pricing"
    assert pricing_row.impact_score == 8.0
    default_row = session.added_rows[1]
    assert default_row.category == "Market"
    assert default_row.sensitivity == "MEDIUM"
    assert default_row.impact_score == 5.0


def test_csv_import_skips_bad_cells_without_blocking_good_rows() -> None:
    session = _ImportSession()

    out = _call_csv_import(
        session,
        _CSV_HEADER
        + ",Demand,HIGH,5\n"  # empty text
        + "Valid assumption,Demand,EXTREME,5\n"  # bad sensitivity
        + "Another valid one,Demand,HIGH,not_a_number\n"  # bad metric
        + "Out of range,Demand,HIGH,42\n"  # impact outside 1..10
        + "Kept row,Demand,HIGH,\n",
    )

    assert out.imported_count == 1
    assert out.skipped_count == 4
    reasons = " | ".join(s.reason for s in out.skipped_rows)
    assert "text is empty" in reasons
    assert "LOW/MEDIUM/HIGH/CRITICAL" in reasons
    assert "not a number" in reasons
    assert "between 1.0 and 10.0" in reasons
    assert session.added_rows[0].text == "Kept row"


def test_csv_import_missing_text_column_returns_400() -> None:
    session = _ImportSession()
    with pytest.raises(HTTPException) as exc:
        _call_csv_import(session, "category,sensitivity\nDemand,HIGH\n")

    assert exc.value.status_code == 400
    assert "missing required column" in exc.value.detail
    assert session.commit_count == 0


def test_csv_import_over_cap_returns_400() -> None:
    session = _ImportSession()
    body = _CSV_HEADER + "Some assumption,,,\n" * 201

    with pytest.raises(HTTPException) as exc:
        _call_csv_import(session, body)

    assert exc.value.status_code == 400
    assert "200-row import limit" in exc.value.detail
    assert session.commit_count == 0


class _ExportAssumption:
    def __init__(
        self,
        assumption_id: int,
        text: str,
        *,
        category: str = "Demand",
        sensitivity: str = "HIGH",
        impact_score: float = 7.5,
        is_hidden: bool = False,
    ) -> None:
        self.id = assumption_id
        self.project_id = 10
        self.text = text
        self.category = category
        self.sensitivity = sensitivity
        self.impact_score = impact_score
        self.is_hidden = is_hidden


def _call_export(session: _ImportSession):
    from app.api.v1 import assumption_evidence as ev_mod

    return ev_mod.export_assumptions_csv(
        project_id=10,
        db=session,  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )


def test_export_route_registered() -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in ev_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    path = "/projects/{project_id}/assumptions/export"
    assert "GET" in methods_by_path.get(path, set())


def test_export_matches_import_csv_shape() -> None:
    """The export header equals the importer's required shape."""
    session = _ImportSession(
        assumptions=[
            _ExportAssumption(50, "Users will pay ₹999 monthly"),
            _ExportAssumption(
                51,
                "-60% churn after redesign",
                sensitivity="CRITICAL",
            ),
            # NOTE: hidden-assumption exclusion happens in SQL and cannot
            # be exercised through this filter-blind fake session.
        ],
    )

    response = _call_export(session)
    body = asyncio.run(_collect(response))

    assert response.media_type == "text/csv; charset=utf-8"
    assert (
        'filename="assumptions-10.csv"'
        in response.headers["Content-Disposition"]
    )
    text = body.decode("utf-8")
    lines = text.splitlines()
    # Leading assumption_id column plus exactly the importer's column list,
    # so one download carries both key forms for the evidence paste-back.
    # The importer tolerates the extra leading column and round-trips.
    assert lines[0] == "assumption_id,text,category,sensitivity,impact_score"
    assert len(lines) == 3
    assert lines[1].startswith("50,Users will pay ₹999 monthly,Demand,HIGH")
    # Formula-leading text is guarded so spreadsheets stay safe.
    assert (
        "51,'-60% churn after redesign,Demand,CRITICAL,7.5" in lines[2]
    )
    assert int(response.headers["Content-Length"]) == len(body)


async def _collect(response) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def test_round_trip_export_then_reimport_is_noop() -> None:
    """Re-importing your own export skips every row as a duplicate."""
    rows = [
        _ExportAssumption(50, "Users will pay ₹999 monthly"),
        _ExportAssumption(51, "Onboarding under two minutes"),
    ]
    session = _ImportSession(assumptions=rows)

    # Export the project's assumptions…
    exported = asyncio.run(_collect(_call_export(session))).decode("utf-8")

    # …then feed the same bytes straight back through the CSV importer.
    out = _call_csv_import(session, exported)

    assert out.imported_count == 0
    assert out.skipped_count == 2
    assert all("already exists" in s.reason for s in out.skipped_rows)
    assert session.added_rows == []
    assert session.commit_count == 0


def test_exported_ids_feed_evidence_paste_back() -> None:
    """The export's assumption_id column plugs straight into evidence CSV."""
    from app.api.v1 import assumption_evidence as ev_mod

    rows = [_ExportAssumption(50, "Users will pay ₹999 monthly")]
    session = _ImportSession(assumptions=rows)

    exported = asyncio.run(_collect(_call_export(session))).decode("utf-8")
    assumption_id = exported.splitlines()[1].split(",", 1)[0]
    assert assumption_id == "50"

    evidence_out = asyncio.run(
        ev_mod.import_assumption_evidence_csv(
            project_id=10,
            request=_FakeCsvRequest(
                (
                    "assumption_id,method,result,observed_metric,notes\n"
                    f"{assumption_id},USER_INTERVIEWS,PASS,0.6,called 12 users\n"
                ).encode()
            ),
            db=session,  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
    )

    assert evidence_out.imported_count == 1
    assert evidence_out.skipped_count == 0
    assert evidence_out.assumption_ids_touched == [50]
    assert session.commit_count == 1
