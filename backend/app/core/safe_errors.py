"""Sanitize exception details for anything crossing a trust boundary.

Exception *messages* routinely embed infrastructure internals — SQL
fragments, host names, broker URLs, file paths. Raw ``str(exc)`` must
never flow into an API response or client-facing payload; full detail
belongs in server-side logs, where diagnosis happens.

``safe_error_label`` therefore never derives its output from the
exception object's contents at all: an ``isinstance`` chain maps the
failure to one fixed literal from a curated vocabulary, so no
message text, traceback frame, or even class name can reach a client.
"""

from __future__ import annotations

import socket

from redis.exceptions import RedisError
from sqlalchemy.exc import OperationalError, SQLAlchemyError

# Ordered first-match: most specific failure classes first. Every label is
# a compile-time literal — adding signal means adding a row here, never
# interpolating anything from the exception itself.
_ERROR_LABELS: tuple[tuple[type[BaseException], str], ...] = (
    (TimeoutError, "timeout"),
    (socket.gaierror, "dns_failure"),
    (ConnectionError, "connection_failed"),
    (OperationalError, "database_unavailable"),
    (SQLAlchemyError, "database_error"),
    (RedisError, "cache_unavailable"),
)


def safe_error_label(exc: BaseException) -> str:
    """Return a fixed, message-free label describing the failure class.

    Keeps operator signal (``timeout`` vs ``database_unavailable`` vs
    ``cache_unavailable`` still distinguishes which dependency degraded)
    while leaking none of the message content: only literals from
    ``_ERROR_LABELS`` can ever be produced.
    """
    for exc_type, label in _ERROR_LABELS:
        if isinstance(exc, exc_type):
            return label
    return "internal_error"
