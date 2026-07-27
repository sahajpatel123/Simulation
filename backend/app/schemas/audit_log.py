"""
Pydantic schemas for the user-facing audit-log endpoints.

Powers ``GET /me/audit-log``: a reverse-chronological timeline of every
mutating request the user has made (and every mutating request anyone
has made on their behalf, e.g. via a share link).

The endpoint exists for two reasons:

1. **Self-service support** — "what did I just do?" when a user is
   surprised by a project state change and didn't have a tab open.
2. **Security review** — the user can spot writes they don't recognise
   and use it as a starting point for investigating compromised
   sessions.

GETs are not logged (deliberately — see ``AuditLogMiddleware``) so the
table stays small and every entry is meaningful.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AuditLogOut(BaseModel):
    """One row from the audit log, shaped for the response payload.

    ``route`` is the matched FastAPI route template (e.g.
    ``/projects/{project_id}/simulate``), never the raw URL — a leaked
    row therefore cannot be used to discover internal numeric IDs by
    counting occurrences.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    method: str
    route: str
    status: int
    duration_ms: int
    ip_address: str | None = None
    request_id: str | None = None
    created_at: datetime


class AuditLogListOut(BaseModel):
    """Paginated list of audit entries for the current user.

    Cursor pagination via ``before_id``: pass the smallest ``id`` from
    the previous page as ``before_id`` on the next request to get the
    page before it. ``has_more`` is ``True`` when the page returned was
    exactly ``limit`` rows (suggesting more exist), but is approximate —
    the next call is the source of truth.
    """

    items: list[AuditLogOut]
    has_more: bool
    next_before_id: int | None = Field(
        default=None,
        description="Use as ``before_id`` on the next request to fetch the previous page.",
    )


__all__ = ["AuditLogOut", "AuditLogListOut"]