"""Unit tests for ``app.core.request_id_middleware`` and its error-handler
integration.

The middleware is the observability glue of the API: it guarantees every
request carries a bounded correlation ID, surfaces it back to the caller
via ``X-Request-ID``, and exposes it on ``request.state`` so audit rows,
timing logs and error responses can be joined to the same trace. These
tests pin the validation rules (client IDs must be safe and bounded) and
the header/state contract without needing a database.
"""
from __future__ import annotations

import asyncio
import json
import re

from starlette.applications import Starlette
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.core.errors import generic_error_handler
from app.core.request_id_middleware import (
    REQUEST_ID_RESPONSE_HEADER,
    RequestIdMiddleware,
    _generate_request_id,
    _normalise_request_id,
)

_GENERATED_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _make_app() -> Starlette:
    """Minimal app exercising the middleware without the full API stack."""
    app = Starlette()
    app.add_middleware(RequestIdMiddleware)

    async def echo(request: Request) -> JSONResponse:
        return JSONResponse({"request_id": request.state.request_id})

    async def missing(request: Request) -> JSONResponse:
        raise StarletteHTTPException(status_code=404, detail="not here")

    app.add_route("/echo", echo)
    app.add_route("/missing", missing)
    return app


def _request_with_id(request_id: str | None) -> Request:
    scope: dict[str, object] = {
        "type": "http",
        "method": "GET",
        "path": "/x",
        "headers": [],
        "query_string": b"",
    }
    if request_id is not None:
        scope["state"] = {"request_id": request_id}
    return Request(scope)


# ── ID normalisation ─────────────────────────────────────────────────


def test_normalise_accepts_valid_client_ids() -> None:
    assert _normalise_request_id("abc-123_DEF.xyz") == "abc-123_DEF.xyz"
    assert (
        _normalise_request_id("550e8400-e29b-41d4-a716-446655440000")
        == "550e8400-e29b-41d4-a716-446655440000"
    )
    assert _normalise_request_id("a" * 64) == "a" * 64
    assert _normalise_request_id("  trimmed-id  ") == "trimmed-id"


def test_normalise_rejects_missing_or_invalid_client_ids() -> None:
    assert _normalise_request_id(None) is None
    assert _normalise_request_id("") is None
    assert _normalise_request_id("   ") is None
    # Over-long values would overflow the audit table column (String(64)).
    assert _normalise_request_id("a" * 65) is None
    # Header smuggling / log-injection shapes are rejected, not echoed back.
    assert _normalise_request_id("bad\nid") is None
    assert _normalise_request_id("<script>alert(1)</script>") is None
    assert _normalise_request_id("/etc/passwd") is None
    assert _normalise_request_id("id with spaces") is None


def test_generated_id_is_bounded_uuid_hex() -> None:
    rid = _generate_request_id()
    assert len(rid) == 32
    assert _GENERATED_ID_RE.match(rid) is not None


# ── Middleware contract ──────────────────────────────────────────────


def test_middleware_generates_id_and_stamps_response() -> None:
    client = TestClient(_make_app())
    resp = client.get("/echo")
    rid = resp.json()["request_id"]
    assert _GENERATED_ID_RE.match(rid) is not None
    assert resp.headers[REQUEST_ID_RESPONSE_HEADER] == rid


def test_middleware_preserves_valid_client_id() -> None:
    client = TestClient(_make_app())
    resp = client.get("/echo", headers={"X-Request-ID": "client-trace-42"})
    assert resp.json()["request_id"] == "client-trace-42"
    assert resp.headers[REQUEST_ID_RESPONSE_HEADER] == "client-trace-42"


def test_middleware_replaces_invalid_client_id() -> None:
    client = TestClient(_make_app())
    bad = "x" * 100
    resp = client.get("/echo", headers={"X-Request-ID": bad})
    rid = resp.json()["request_id"]
    assert rid != bad
    assert _GENERATED_ID_RE.match(rid) is not None
    assert resp.headers[REQUEST_ID_RESPONSE_HEADER] == rid


def test_middleware_stamps_http_error_responses() -> None:
    client = TestClient(_make_app())
    resp = client.get("/missing")
    assert resp.status_code == 404
    assert _GENERATED_ID_RE.match(resp.headers[REQUEST_ID_RESPONSE_HEADER]) is not None


# ── Error-handler integration ────────────────────────────────────────


def test_generic_error_handler_includes_request_id() -> None:
    resp = asyncio.run(
        generic_error_handler(
            _request_with_id("trace-abc"),
            StarletteHTTPException(status_code=404, detail="gone"),
        )
    )
    assert resp.headers[REQUEST_ID_RESPONSE_HEADER] == "trace-abc"
    body = json.loads(resp.body)
    assert body["request_id"] == "trace-abc"
    assert body["code"] == "HTTP_ERROR"


def test_generic_error_handler_omits_header_without_request_id() -> None:
    resp = asyncio.run(
        generic_error_handler(
            _request_with_id(None),
            StarletteHTTPException(status_code=404, detail="gone"),
        )
    )
    assert REQUEST_ID_RESPONSE_HEADER not in resp.headers
    assert json.loads(resp.body)["request_id"] is None
