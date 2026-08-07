"""Tests for the pure tag-suggestion helper."""
from __future__ import annotations

from app.simulation.project_tags import normalise_tags
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


def test_suggest_tags_accepts_none_and_non_strings() -> None:
    assert suggest_tags(None, None) == []
    assert suggest_tags(42, None) == []
    assert suggest_tags(None, "AI Sim engine") == ["engine", "sim"]


def test_suggest_tags_keeps_hyphens_and_underscores() -> None:
    tags = suggest_tags(
        None,
        "A-B and C_D for realtime-collab sessions",
    )

    assert "realtime-collab" in tags
    assert "c_d" in tags
    # Every suggestion must satisfy the persisted tag contract.
    for tag in tags:
        assert len(normalise_tags([tag])) == 1


def test_suggest_tags_bounds_max_tags() -> None:
    text = "alpha beta gamma delta epsilon zeta eta theta"

    assert len(suggest_tags(text, None, max_tags=-5)) == 0
    assert len(suggest_tags(text, None, max_tags=0)) == 0
    assert len(suggest_tags(text, None, max_tags=3)) == 3
    assert len(suggest_tags(text, None, max_tags=10_000)) <= 8


def test_suggest_tags_frequency_ranking() -> None:
    tags = suggest_tags(None, "pricing plan basic plan")

    assert tags[0] == "plan"
    assert tags[1] == "basic"
    assert tags[2] == "pricing"
