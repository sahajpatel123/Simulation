"""Pure helper for detecting projects with the same title."""
from __future__ import annotations

from typing import Any


def find_duplicate_titles(
    title: str | None,
    candidates: list[dict[str, Any]],
    project_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return candidate projects whose title matches (case-insensitive)."""
    normalized = (title or "").strip().casefold()
    if not normalized:
        return []
    return [
        {
            "project_id": candidate.get("id"),
            "title": candidate.get("title"),
        }
        for candidate in candidates
        if candidate.get("id") != project_id
        and (candidate.get("title") or "").strip().casefold() == normalized
    ]


__all__ = ["find_duplicate_titles"]
