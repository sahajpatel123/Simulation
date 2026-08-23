from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    # codeql[py/unsafe-cyclic-import]: TYPE_CHECKING-guarded import — never executes at runtime, so no runtime cycle exists
    from app.models.user import User


class ApiToken(Base, TimestampMixin):
    """Long-lived, revocable bearer credential for programmatic API access.

    Only the SHA-256 hash of the plaintext token is stored, mirroring how
    refresh tokens are persisted. ``last_used_at`` is refreshed on a
    throttled basis so owners can audit which token is actually being used
    without turning every authenticated request into a write.
    """

    __tablename__ = "api_tokens"
    __table_args__ = (
        Index("ix_api_tokens_user_id", "user_id"),
        Index("uq_api_tokens_token_hash", "token_hash", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # "read" allows only safe methods; "read_write" allows the full surface.
    scope: Mapped[str] = mapped_column(String(32), default="read", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    user: Mapped[User] = relationship("User", back_populates="api_tokens")
