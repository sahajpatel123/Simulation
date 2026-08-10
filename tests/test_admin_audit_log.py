"""Tests for the admin platform audit log (list + CSV/JSON export).

The per-user endpoint (``GET /users/me/audit-log``) is covered by
``test_audit_log_endpoint_contract.py``; this file pins the admin
counterpart added to ``app/api/v1/analytics.py``:

* admin-only gating (403 for non-admins)
* filter construction (user / method / status / route / time window)
* cursor pagination with limit+1 ``has_more`` detection
* CSV/JSON export parity with the same filters, formula-injection guard,
  and explicit rejection of unsupported formats / inverted windows
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import sys
import types
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.models.audit_log import ApiAuditLog
from app.schemas.audit_log import AuditLogListOut
from app.simulation.admin_audit_log import (
    MUTATING_METHODS,
    admin_audit_log_to_csv,
    admin_audit_log_to_json,
    apply_admin_audit_filters,
)


def _audit_dict(
    *,
    id: int,
    user_id: int | None = 5,
    method: str = "POST",
    route: str = "/projects/10/simulate",
    status: int = 200,
    duration_ms: int = 12,
    ip_address: str | None = "1.2.3.4",
    request_id: str | None = None,
    created_at: datetime | None = None,
) -> dict:
    return {
        "id": id,
        "user_id": user_id,
        "method": method,
        "route": route,
        "status": status,
        "duration_ms": duration_ms,
        "ip_address": ip_address,
        "request_id": request_id or f"req-{id}",
        "created_at": created_at or datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    }


class _Row:
    def __init__(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []
        self.filters: list[tuple] = []
        self.order_by_calls = 0
        self.limit_calls: list[int] = []

    def filter(self, *args):
        self.filters.append(args)
        return self

    def order_by(self, *args):
        self.order_by_calls += 1
        return self

    def limit(self, count: int):
        self.limit_calls.append(count)
        return self

    def all(self):
        return self.items


class _FakeSession:
    def __init__(self, rows: list | None = None) -> None:
        self.rows = rows if rows is not None else []
        self.fake_query = _FakeQuery(self.rows)
        self.last_model: object | None = None

    def query(self, model):
        self.last_model = model
        return self.fake_query


def _admin_user(*, is_admin: bool = True, email: str = "admin@example.com"):
    return type("U", (), {"id": 1, "email": email, "is_admin": is_admin})()


def _analytics():
    from app.api.v1 import analytics as analytics_mod

    return analytics_mod


def _call_list(session: _FakeSession, current_user=None, **kwargs):
    """Call the list route with every optional FastAPI param made explicit."""
    analytics = _analytics()
    defaults = {
        "user_id": None,
        "method": None,
        "status": None,
        "route": None,
        "since": None,
        "until": None,
        "before_id": None,
        "limit": 50,
    }
    defaults.update(kwargs)
    return analytics.get_admin_audit_log(
        db=session,
        current_user=current_user or _admin_user(),
        **defaults,
    )


def _call_export(session: _FakeSession, current_user=None, **kwargs):
    """Call the export route with every optional FastAPI param made explicit."""
    analytics = _analytics()
    defaults = {
        "format": "csv",
        "user_id": None,
        "method": None,
        "status": None,
        "route": None,
        "since": None,
        "until": None,
        "limit": 1000,
    }
    defaults.update(kwargs)
    return analytics.export_admin_audit_log(
        db=session,
        current_user=current_user or _admin_user(),
        **defaults,
    )


async def _collect(resp) -> bytes:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def _body(resp) -> bytes:
    return asyncio.run(_collect(resp))


# ---------------------------------------------------------------------------
# Pure filter builder
# ---------------------------------------------------------------------------


def test_filters_empty_when_nothing_supplied() -> None:
    assert apply_admin_audit_filters() == []


def test_user_id_filter_binds_exact_id() -> None:
    clauses = apply_admin_audit_filters(user_id=7)
    assert len(clauses) == 1
    assert clauses[0].left.key == "user_id"
    assert clauses[0].right.value == 7


def test_method_filter_normalizes_case() -> None:
    clauses = apply_admin_audit_filters(method="post")
    assert len(clauses) == 1
    assert clauses[0].left.key == "method"
    assert clauses[0].right.value == "POST"


def test_method_filter_rejects_non_audited_method() -> None:
    # GET/HEAD/OPTIONS are never written by the middleware, so filtering on
    # them is a caller bug and must fail loudly rather than match nothing.
    assert "GET" not in MUTATING_METHODS
    with pytest.raises(ValueError):
        apply_admin_audit_filters(method="GET")


def test_status_filter_binds_exact_status() -> None:
    clauses = apply_admin_audit_filters(status=500)
    assert len(clauses) == 1
    assert clauses[0].left.key == "status"
    assert clauses[0].right.value == 500


def test_route_filter_is_escaped_case_insensitive_substring() -> None:
    clauses = apply_admin_audit_filters(route="/projects/%")
    assert len(clauses) == 1
    rendered = str(clauses[0])
    assert "lower" in rendered
    assert "LIKE" in rendered
    # The literal % must be escaped so it can never act as a wildcard.
    assert "ESCAPE" in rendered
    params = clauses[0].compile().params
    assert list(params.values())[0] == "//projects///%"


def test_since_until_are_normalized_to_utc() -> None:
    naive = datetime(2026, 1, 1, 9, 30)
    aware = datetime(2026, 1, 2, 9, 30, tzinfo=UTC)
    clauses = apply_admin_audit_filters(since=naive, until=aware)
    assert len(clauses) == 2
    assert clauses[0].left.key == "created_at"
    assert clauses[0].right.value == naive.replace(tzinfo=UTC)
    assert clauses[0].right.value.tzinfo is not None
    assert clauses[1].left.key == "created_at"
    assert clauses[1].right.value == aware


def test_blank_route_is_skipped() -> None:
    assert apply_admin_audit_filters(route="   ") == []


# ---------------------------------------------------------------------------
# Serializers (row dicts, matching the route's model_dump(mode="json"))
# ---------------------------------------------------------------------------


def test_csv_renders_metadata_header_and_rows() -> None:
    older = _audit_dict(id=1)
    newer = _audit_dict(id=2, method="DELETE", status=204)
    csv_text = admin_audit_log_to_csv(
        [newer, older],
        metadata={
            "generated_at": "2026-01-02T00:00:00+00:00",
            "requested_by_user_id": 42,
            "filter_user_id": 7,
            "limit": 50,
            "total": 2,
            "format_version": "1",
        },
    )
    assert csv_text.startswith("generated_at,")
    assert "requested_by_user_id,42" in csv_text
    assert "filter_user_id,7" in csv_text
    assert (
        "id,user_id,method,route,status,duration_ms,ip_address,request_id,created_at"
        in csv_text
    )
    lines = csv_text.strip().splitlines()
    assert lines[-2].startswith("2,")
    assert lines[-1].startswith("1,")
    assert ",DELETE,/projects/10/simulate,204," in csv_text


def test_csv_neutralizes_spreadsheet_formula_injection() -> None:
    row = _audit_dict(
        id=9,
        route='=HYPERLINK("http://evil")',
        ip_address="@attacker",
    )
    csv_text = admin_audit_log_to_csv([row])
    rows = list(csv.reader(io.StringIO(csv_text)))
    data = rows[-1]
    assert data[3] == "'=HYPERLINK(\"http://evil\")"
    assert data[6] == "'@attacker"


def test_csv_renders_datetimes_and_missing_fields_safely() -> None:
    row = _audit_dict(id=3, user_id=None, ip_address=None, request_id=None)
    csv_text = admin_audit_log_to_csv([row])
    assert (
        "3,,POST,/projects/10/simulate,200,12,,req-3,2026-01-01T12:00:00+00:00"
        in csv_text
    )


def test_json_renders_metadata_and_items() -> None:
    payload = json.loads(
        admin_audit_log_to_json(
            [{"id": 1, "method": "POST", "route": "/projects/1/simulate"}],
            metadata={"total": 1, "format_version": "1"},
        )
    )
    assert payload["metadata"]["total"] == 1
    assert payload["items"][0]["route"] == "/projects/1/simulate"


# ---------------------------------------------------------------------------
# Route behavior (direct calls with fake session / user)
# ---------------------------------------------------------------------------


def test_list_requires_admin() -> None:
    with patch("app.core.deps.settings.ADMIN_EMAILS", ""):
        with pytest.raises(HTTPException) as exc:
            _call_list(
                _FakeSession([]),
                current_user=_admin_user(is_admin=False, email="user@example.com"),
            )
    assert exc.value.status_code == 403


def test_export_requires_admin() -> None:
    with patch("app.core.deps.settings.ADMIN_EMAILS", ""):
        with pytest.raises(HTTPException) as exc:
            _call_export(
                _FakeSession([]),
                current_user=_admin_user(is_admin=False, email="user@example.com"),
            )
    assert exc.value.status_code == 403


def test_list_returns_items_newest_first_without_pagination_hint() -> None:
    session = _FakeSession(
        [
            _Row(**_audit_dict(id=2, method="DELETE", status=204)),
            _Row(**_audit_dict(id=1)),
        ]
    )
    resp = _call_list(session)
    assert isinstance(resp, AuditLogListOut)
    assert [item.id for item in resp.items] == [2, 1]
    assert resp.items[0].method == "DELETE"
    assert resp.has_more is False
    assert resp.next_before_id is None
    assert session.last_model is ApiAuditLog
    assert session.fake_query.order_by_calls == 1
    # limit+1 so has_more can be detected without a COUNT(*).
    assert session.fake_query.limit_calls == [51]


def test_list_reports_has_more_and_next_cursor() -> None:
    rows = [_Row(**_audit_dict(id=i)) for i in range(51, 0, -1)]
    session = _FakeSession(rows)
    resp = _call_list(session)
    assert resp.has_more is True
    assert [item.id for item in resp.items] == list(range(51, 1, -1))
    assert resp.next_before_id == 2


def test_list_applies_all_filters_and_cursor() -> None:
    session = _FakeSession([])
    _call_list(
        session,
        user_id=7,
        method="POST",
        status=500,
        route="/projects/",
        since=datetime(2026, 1, 1, tzinfo=UTC),
        until=datetime(2026, 1, 31, tzinfo=UTC),
        before_id=100,
        limit=20,
    )
    # One filter call for the six user filters, one for the cursor.
    assert len(session.fake_query.filters) == 2
    assert len(session.fake_query.filters[0]) == 6
    assert session.fake_query.filters[1][0].left.key == "id"
    assert session.fake_query.limit_calls == [21]


def test_list_rejects_inverted_time_window() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_list(
            _FakeSession([]),
            since=datetime(2026, 2, 1, tzinfo=UTC),
            until=datetime(2026, 1, 1, tzinfo=UTC),
        )
    assert exc.value.status_code == 400


def test_list_accepts_mixed_naive_and_aware_window() -> None:
    session = _FakeSession([])
    resp = _call_list(
        session,
        since=datetime(2026, 1, 1),  # naive is treated as UTC
        until=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert resp.items == []
    assert len(session.fake_query.filters) == 1
    assert len(session.fake_query.filters[0]) == 2
    since_value = session.fake_query.filters[0][0].right.value
    until_value = session.fake_query.filters[0][1].right.value
    assert since_value == datetime(2026, 1, 1, tzinfo=UTC)
    assert until_value == datetime(2026, 1, 2, tzinfo=UTC)


def test_list_rejects_inverted_mixed_naive_and_aware_window() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_list(
            _FakeSession([]),
            since=datetime(2026, 1, 2),  # naive is treated as UTC
            until=datetime(2026, 1, 1, tzinfo=UTC),
        )
    assert exc.value.status_code == 400


def test_export_csv_matches_list_filters_and_metadata() -> None:
    session = _FakeSession([_Row(**_audit_dict(id=1, user_id=7, status=404))])
    resp = _call_export(
        session,
        user_id=7,
        method="POST",
        status=404,
        route="/projects/",
        since=datetime(2026, 1, 1, tzinfo=UTC),
        until=datetime(2026, 1, 31, tzinfo=UTC),
        limit=10,
    )
    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="admin-audit-log.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "generated_at," in body
    assert "requested_by_user_id,1" in body
    assert "filter_user_id,7" in body
    assert "filter_method,POST" in body
    assert "filter_status,404" in body
    assert "filter_route,/projects/" in body
    assert "filter_since,2026-01-01T00:00:00+00:00" in body
    assert "filter_until,2026-01-31T00:00:00+00:00" in body
    assert "limit,10" in body
    assert "total,1" in body
    assert (
        "id,user_id,method,route,status,duration_ms,ip_address,request_id,created_at"
        in body
    )
    assert (
        "1,7,POST,/projects/10/simulate,404,12,1.2.3.4,req-1,"
        "2026-01-01T12:00:00Z" in body
    )
    assert len(session.fake_query.filters) == 1
    assert len(session.fake_query.filters[0]) == 6
    assert session.fake_query.limit_calls == [10]


def test_export_json_returns_raw_rows() -> None:
    session = _FakeSession([_Row(**_audit_dict(id=2, method="PATCH", status=422))])
    resp = _call_export(session, format="json")
    assert resp.media_type == "application/json; charset=utf-8"
    assert 'filename="admin-audit-log.json"' in resp.headers["Content-Disposition"]
    payload = json.loads(_body(resp).decode("utf-8"))
    assert payload["metadata"]["requested_by_user_id"] == 1
    assert payload["metadata"]["format_version"] == "1"
    assert payload["items"][0]["method"] == "PATCH"
    assert payload["items"][0]["status"] == 422


def test_export_rejects_unsupported_format() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_export(_FakeSession([]), format="xml")
    assert exc.value.status_code == 400
    assert "unsupported export format" in exc.value.detail


def test_export_rejects_inverted_time_window() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_export(
            _FakeSession([]),
            since=datetime(2026, 2, 1, tzinfo=UTC),
            until=datetime(2026, 1, 1, tzinfo=UTC),
        )
    assert exc.value.status_code == 400


def test_admin_audit_routes_registered() -> None:
    analytics = _analytics()
    paths = {route.path for route in analytics.router.routes}
    assert "/analytics/audit-log" in paths
    assert "/analytics/audit-log/export" in paths
