"""Tests for the pure tag-suggestion helper."""
from __future__ import annotations

from app.simulation.tag_suggestions import suggest_tags


def test_suggest_tags_returns_keywords() -> None:
    tags = suggest_tags("AI Sim", "A simulation engine for founders")

    assert "sim" in tags
    assert "founders" in tags
    assert len(tags) <= 5


def test_suggest_tags_excludes_stopwords() -> None:
    tags = suggest_tags("Tool", "A platform for the app tool")

    assert "tool" not in tags
    assert "platform" not in tags
