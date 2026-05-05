from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class HardwareProduct(Base):
    __tablename__ = "hardware_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    product_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_price_inr: Mapped[float | None] = mapped_column(Float, nullable=True)
    material_spec: Mapped[str | None] = mapped_column(Text, nullable=True)
    dimensions_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    weight_grams: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Hardware3DModel(Base):
    __tablename__ = "hardware_3d_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hardware_product_id: Mapped[int] = mapped_column(
        ForeignKey("hardware_products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_type: Mapped[str] = mapped_column(String(20), nullable=False)
    model_data_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    polygon_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
