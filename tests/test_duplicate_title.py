"""Tests for the pure duplicate-title helper."""
from __future__ import annotations

from app.simulation.duplicate_title import find_duplicate_titles


def test_find_duplicate_titles_matches_case_insensitive() -> None:
    results = find_duplicate_titles(
        "TheCee",
        [{"id": 2, "title": "thecee"}, {"id": 3, "title": "Other"}],
        project_id=1,
    )

    assert len(results) == 1
    assert results[0]["project_id"] == 2


def test_find_duplicate_titles_excludes_self() -> None:
    results = find_duplicate_titles(
        "TheCee",
        [{"id": 1, "title": "TheCee"}, {"id": 2, "title": "TheCee"}],
        project_id=1,
    )

    assert len(results) == 1
    assert results[0]["project_id"] == 2
