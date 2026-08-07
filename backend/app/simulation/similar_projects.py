"""Pure helper for finding similarly tagged projects."""
from __future__ import annotations

from typing import Any


def find_similar_projects(
    project: dict[str, Any],
    candidates: list[dict[str, Any]],
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """Return candidate projects sharing tags with ``project``, best overlap first."""
    own_tags = set(project.get("tags") or [])
    results: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.get("id") == project.get("id"):
            continue
        other_tags = set(candidate.get("tags") or [])
        overlap = sorted(own_tags & other_tags)
        if not overlap:
            continue
        results.append(
            {
                "project_id": candidate.get("id"),
                "title": candidate.get("title"),
                "shared_tags": overlap,
                "shared_tag_count": len(overlap),
            }
        )
    results.sort(key=lambda r: (-r["shared_tag_count"], r["project_id"]))
    return results[: max(0, max_results)]


__all__ = ["find_similar_projects"]
