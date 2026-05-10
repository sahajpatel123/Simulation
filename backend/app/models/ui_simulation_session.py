from __future__ import annotations

from datetime import datetime

from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UISimulationSession(Base):
    __tablename__ = "ui_simulation_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    generated_ui_id: Mapped[int] = mapped_column(
        ForeignKey("generated_uis.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_cluster_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    agent_profile_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    events_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(50), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pages_visited: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    converted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
