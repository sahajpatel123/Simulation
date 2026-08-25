from __future__ import annotations

import logging
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.database import SessionLocal
from app.core.request_id_middleware import _normalise_request_id

logger = logging.getLogger("thecee.audit")


# HTTP methods that actually mutate state. Everything else (GET, HEAD,
# OPTIONS) is a read or a CORS handshake; logging them would inflate
# the table ten-thousandfold without giving the user anything useful.
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Routes the audit middleware must skip.
#
#  * ``/metrics``, ``/health``, ``/readyz`` — probes that fire on a
#    fixed cadence. Even though they're GETs and would already be
#    filtered by ``_MUTATING_METHODS``, listing them here documents the
#    intent and protects us if someone later adds a POST health check.
#  * ``/api/v1/share/{token}`` — the public, unauthenticated read
#    endpoint for share tokens. Recording it would let anyone enumerate
#    every shared link a user has created by hitting that path with a
#    leaked token.
_AUDIT_EXEMPT_PATHS = frozenset(
    {"/metrics", "/health", "/readyz", "/api/v1/share"}
)


def _normalise_route(request: Request) -> str:
    """Return the matched route template (or ``"unmatched"``).

    See ``timing_middleware._normalise_path`` for the same logic. We
    duplicate it here rather than importing because the two modules
    are independent — metrics and audit have different concerns and
    neither should be a hard dependency of the other.
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None) if route is not None else None
    return template or "unmatched"


def _resolve_user_id(request: Request) -> int | None:
    """Best-effort extract of the user id from JWT or a personal API token.

    The middleware can't run Depends(get_current_user) (the request is
    already streaming out by the time the middleware fires the wrap-up), so
    it resolves the Authorization header directly: JWT decode first, then a
    hashed lookup for ``thecee_``-prefixed API tokens (the same fallback the
    auth dependency uses). A failure here is silent — we just return
    ``None`` and the row is logged as anonymous.
    """
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    try:
        # Imported lazily so a startup failure in auth (e.g. a missing
        # SECRET_KEY in a test environment) can't break the middleware.
        from app.core.deps import lookup_api_token_row
        from app.core.security import (
            API_TOKEN_PREFIX,
            api_token_is_expired,
            decode_token,
        )

        sub = decode_token(token, token_type="access")
        if sub is None:
            if not token.startswith(API_TOKEN_PREFIX):
                return None
            db = SessionLocal()
            try:
                row = lookup_api_token_row(db, token)
                if (
                    row is not None
                    and row.revoked_at is None
                    and not api_token_is_expired(row.expires_at)
                ):
                    return row.user_id
            finally:
                db.close()
            return None
        return int(sub)
    except Exception:
        return None


def _resolve_request_id(request: Request) -> str | None:
    """Return the correlation ID for this request, if one exists.

    ``RequestIdMiddleware`` (added outside this middleware) stores the
    generated or client-supplied ID on ``request.state.request_id``.
    Prefer that state — it is guaranteed safe and bounded — and fall
    back to the raw header only for paths where the outer middleware
    did not run (unit-test stubs, unusual embedded deployments). The
    fallback is still normalised with the same rules as the middleware
    so an over-long or header-smuggling value can never overflow the
    ``String(64)`` audit column or be stored verbatim.
    """
    state = request.scope.get("state") or {}
    state_id = state.get("request_id")
    if state_id:
        return str(state_id)
    return _normalise_request_id(request.headers.get("x-request-id"))


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Persist one row per mutating request to ``api_audit_log``.

    The write is intentionally inline (not BackgroundTasks, not a queue):
    an audit row must survive a process crash, which BackgroundTasks
    doesn't guarantee. The insert is a single-row write against a tiny
    table with a covering index — measured cost on the request path is
    sub-millisecond on a warm connection. Errors are caught and logged
    so an audit-write failure can never break the user's response.
    """

    async def dispatch(self, request: Request, call_next):
        if (
            request.method not in _MUTATING_METHODS
            or request.url.path in _AUDIT_EXEMPT_PATHS
        ):
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        try:
            self._persist(
                user_id=_resolve_user_id(request),
                method=request.method,
                route=_normalise_route(request),
                status=response.status_code,
                duration_ms=elapsed_ms,
                ip_address=request.client.host if request.client else None,
                request_id=_resolve_request_id(request),
            )
        except Exception as exc:  # noqa: BLE001 — audit must never break the response.
            logger.warning("audit log write failed: %s", exc)

        return response

    @staticmethod
    def _persist(
        user_id: int | None,
        method: str,
        route: str,
        status: int,
        duration_ms: int,
        ip_address: str | None,
        request_id: str | None,
    ) -> None:
        """Single-row INSERT against ``api_audit_log``.

        Uses a fresh SessionLocal — middleware runs outside the per-
        request Depends(get_db) lifecycle, and reusing the request
        session would risk committing a half-written transaction when
        the endpoint had already raised.
        """

        from app.models.audit_log import ApiAuditLog

        db = SessionLocal()
        try:
            row = ApiAuditLog(
                user_id=user_id,
                method=method,
                route=route,
                status=status,
                duration_ms=duration_ms,
                ip_address=ip_address,
                request_id=request_id,
            )
            db.add(row)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


__all__ = ["AuditLogMiddleware"]
