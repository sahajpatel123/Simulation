from __future__ import annotations

import re
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

# Header name used for inbound correlation IDs (lowercase, as read from
# request headers) and for the outbound response header (conventional
# casing, as written back to clients).
REQUEST_ID_HEADER = "x-request-id"
REQUEST_ID_RESPONSE_HEADER = "X-Request-ID"

# Accepted inbound request-ID shape. Client-supplied IDs are preserved so a
# frontend / proxy / tracing system can seed the correlation chain, but they
# must stay bounded (the audit table column is String(64)) and free of
# characters that could smuggle header values or pollute logs (control
# characters, whitespace, HTML, path separators, etc.).
_VALID_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def _normalise_request_id(value: str | None) -> str | None:
    """Return a safe inbound request ID, or ``None`` when unusable.

    ``None`` / empty values and values with invalid characters or an
    over-long length are rejected so a hostile header can never be
    echoed back verbatim (header injection) or stored unbounded in the
    audit log.
    """
    if not value:
        return None
    candidate = value.strip()
    if not candidate or not _VALID_REQUEST_ID_RE.match(candidate):
        return None
    return candidate


def _generate_request_id() -> str:
    """Create a fresh 32-char correlation ID (UUID v4 hex, no hyphens)."""
    return uuid.uuid4().hex


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Ensure every HTTP request carries a stable correlation ID.

    A client-supplied ``X-Request-ID`` is preserved when it is a safe,
    bounded value; otherwise a fresh UUID is generated. The ID is stored
    on ``request.state.request_id`` so downstream middleware (audit
    logging, timing metrics) and route handlers can correlate work for
    one request, and it is written back as the ``X-Request-ID`` response
    header so the caller can reference it in support tickets.

    This middleware must sit outside the audit / timing middleware: it
    sets the state before either of them runs on the request path.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = (
            _normalise_request_id(request.headers.get(REQUEST_ID_HEADER))
            or _generate_request_id()
        )
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[REQUEST_ID_RESPONSE_HEADER] = request_id
        return response


__all__ = [
    "REQUEST_ID_HEADER",
    "REQUEST_ID_RESPONSE_HEADER",
    "RequestIdMiddleware",
    "_generate_request_id",
    "_normalise_request_id",
]
