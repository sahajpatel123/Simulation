from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ApiAuditLog(Base):
    """One row per mutating HTTP request handled by the API.

    Populated by ``AuditLogMiddleware`` in the request path. The
    ``route`` column stores the matched FastAPI route template
    (e.g. ``/projects/{project_id}/simulate``), not the raw URL —
    dynamic IDs are folded into the template so the table size and
    the per-user index both stay bounded.
    """

    __tablename__ = "api_audit_log"
    __table_args__ = (
        # Reverse-chronological lookup for ``GET /me/audit-log`` — the
        # composite covers both the user filter and the (id, DESC) sort
        # used by cursor pagination.
        Index("idx_api_audit_log_user_id", "user_id", "id"),
        # Catch-all time index for ops queries ("all writes in the last
        # hour") that don't filter by user.
        Index("idx_api_audit_log_created_at", "created_at"),
    )

    # BIGSERIAL in the migration; BigInteger here so SQLAlchemy reads it
    # back as Python ``int`` instead of choking on overflow.
    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )

    # ``user_id`` is nullable + ``ON DELETE SET NULL`` so a deleted user
    # doesn't cascade-delete their write history — audit logs survive
    # the actor, which is the whole point of an audit log.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    method: Mapped[str] = mapped_column(String(10), nullable=False)
    route: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # Network / trace metadata. All nullable — a malformed request that
    # never reaches the FastAPI stack still gets logged without these.
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = ["ApiAuditLog"]
