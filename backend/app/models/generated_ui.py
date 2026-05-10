from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class GeneratedUI(Base, TimestampMixin):
    __tablename__ = "generated_uis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    html_content: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    product_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pages_generated: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    preview_token: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
