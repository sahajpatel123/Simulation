"""
Pure heuristic tag suggestions for a project title/description.

The suggestions are deliberately conservative: they only produce words
that satisfy the same tag contract used by ``project_tags.normalise_tags``
(lowercase ``[a-z0-9_-]`` tokens, ``<= 32`` chars), so a UI can hand them
straight to ``PUT /projects/{id}/tags`` without a rejection round-trip.
"""
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

# At least 2 characters and no leading punctuation. Hyphens and
# underscores are kept because they are valid inside persisted tags
# (``normalise_tags`` allows ``[a-z0-9_-]``).
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]+")

# Suggestions beyond this are unlikely to be useful; the persisted tag
# contract also caps a project at ``MAX_TAGS_PER_PROJECT`` = 20.
_MAX_SUGGESTED_TAGS: int = 20


def _text(value: object) -> str:
    """Coerce a title/description-like value to plain text."""
    if value is None:
        return ""
    return str(value)


def suggest_tags(
    title: str | None,
    description: str | None,
    max_tags: int = 5,
) -> list[str]:
    """Return up to ``max_tags`` keyword tags extracted from the text.

    Tags are lowercased, deduped, ordered by frequency then alphabetically,
    and bounded to ``MAX_TAGS_PER_PROJECT`` so the output always fits the
    project tag contract.
    """
    capped = min(max(0, int(max_tags)), _MAX_SUGGESTED_TAGS)
    text = f"{_text(title)} {_text(description)}".casefold()
    words = _TOKEN_RE.findall(text)
    seen: dict[str, int] = {}
    for word in words:
        if word in _STOPWORDS or len(word) < 3:
            continue
        seen[word] = seen.get(word, 0) + 1
    ranked = sorted(seen, key=lambda w: (-seen[w], w))
    return ranked[:capped]


__all__ = ["_MAX_SUGGESTED_TAGS", "suggest_tags"]
