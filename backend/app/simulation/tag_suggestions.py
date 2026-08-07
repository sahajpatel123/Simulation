"""Pure heuristic tag suggestions for a project title/description."""
from __future__ import annotations

import re

_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "for",
        "with",
        "to",
        "of",
        "in",
        "on",
        "is",
        "are",
        "it",
        "we",
        "our",
        "that",
        "this",
        "app",
        "tool",
        "platform",
        "solution",
    }
)


def suggest_tags(
    title: str | None,
    description: str | None,
    max_tags: int = 5,
) -> list[str]:
    """Return up to ``max_tags`` simple lowercase keyword tags."""
    text = f"{title or ''} {description or ''}".lower()
    words = re.findall(r"[a-z0-9][a-z0-9\-]{1,}", text)
    seen: dict[str, int] = {}
    for word in words:
        if word in _STOPWORDS or len(word) < 3:
            continue
        seen[word] = seen.get(word, 0) + 1
    ranked = sorted(seen, key=lambda w: (-seen[w], w))
    return ranked[: max(0, max_tags)]


__all__ = ["suggest_tags"]
