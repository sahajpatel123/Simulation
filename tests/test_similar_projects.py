"""Tests for the pure similar-projects helper."""
from __future__ import annotations

from app.simulation.similar_projects import find_similar_projects


def test_find_similar_projects_returns_overlaps() -> None:
    results = find_similar_projects(
        {"id": 1, "tags": ["saas", "india"]},
        [
            {"id": 2, "tags": ["saas", "india", "billing"]},
            {"id": 3, "tags": ["hardware"]},
        ],
    )

    assert len(results) == 1
    assert results[0]["project_id"] == 2
    assert results[0]["shared_tag_count"] == 2


def test_find_similar_projects_excludes_self() -> None:
    results = find_similar_projects(
        {"id": 1, "tags": ["saas"]},
        [{"id": 1, "tags": ["saas"]}, {"id": 2, "tags": ["saas"]}],
    )

    assert len(results) == 1
    assert results[0]["project_id"] == 2
