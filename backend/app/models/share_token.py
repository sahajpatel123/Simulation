from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ShareToken(Base):
    """A read-only public link to a completed simulation.

    The plaintext token is never stored — only its SHA-256 hash. Lookup
    hashes the incoming token and matches by ``token_hash``. Revocation
    is a soft-delete (``revoked_at`` set) so an audit trail of who shared
    what and when is preserved.
    """

    __tablename__ = "share_tokens"
    __table_args__ = (
        Index("idx_share_tokens_simulation_id", "simulation_id"),
        Index("idx_share_tokens_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    simulation_id: Mapped[int] = mapped_column(
        ForeignKey("simulations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scope: Mapped[str] = mapped_column(String(50), default="read_only", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    access_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships — keep loose so the model can be loaded without the
    # full project/simulation graph being eagerly fetched.
    simulation: Mapped["Simulation"] = relationship("Simulation", lazy="noload")  # type: ignore[name-defined]  # noqa: F821


__all__ = ["ShareToken"]
