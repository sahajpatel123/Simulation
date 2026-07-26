"""
Pure helpers for the project search endpoint.

The search contract is intentionally narrow and predictable:

* ``q`` — a substring (case-insensitive) matched against the project
  title, description, and précis. Substring, not full-text — the
  dataset is per-user and our existing UI doesn't need stemming or
  ranking. Words are split on whitespace and the query must match
  *all* words (AND), so ``q="ai tutor"`` matches a project whose
  description contains both "ai" and "tutor" in any order.
* ``tags`` — a list of canonical tags. A project matches if its tag
  list contains *all* the requested tags (AND across tags). This
  composes with the existing ``?tag=`` filter exposed by the
  list endpoint: that one uses OR-of-single, this one uses
  AND-of-many.
* ``status`` — exact match on the ``status`` column.
* ``archived`` — defaults to *exclude archived* so the main UI shows
  only live projects. Pass ``True`` to include them.
* ``limit`` — 1..100, default 50.
* ``before_id`` — pagination cursor: return projects with
  ``id < before_id``, ordered by ``id DESC``. The ID cursor is more
  stable than a timestamp cursor because the simulation costs depend
  on row count, not clock time.

All constraints are enforced here so the route handler can pass the
resulting kwargs straight into the SQLAlchemy query builder.
"""
from __future__ import annotations

_MAX_LIMIT: int = 100
_MIN_LIMIT: int = 1
_DEFAULT_LIMIT: int = 50
_MAX_QUERY_WORDS: int = 10
_MAX_QUERY_WORD_LEN: int = 64


def _normalise_query_words(raw: str | None) -> list[str]:
    """Split ``q`` into AND-matched word tokens.

    Empty / whitespace-only input returns ``[]``. Each word is
    folded (case-insensitive search) and capped at
    :data:`_MAX_QUERY_WORD_LEN` chars. Stop-word filtering is
    deliberate — search engines handle stop-words well; a substring
    search must not, otherwise every search returns every project.
    """
    if not raw:
        return []
    # ``.split()`` collapses any whitespace run and discards empties.
    words = raw.split()
    if len(words) > _MAX_QUERY_WORDS:
        # Surface the cap as a ValueError so the route handler returns
        # 400 rather than silently truncating the user's query.
        raise ValueError(
            f"query has {len(words)} words; max is {_MAX_QUERY_WORDS}"
        )
    out: list[str] = []
    for w in words:
        if not isinstance(w, str):
            raise ValueError(f"query word must be a string, got {type(w).__name__}")
        folded = w.casefold().strip()
        if not folded:
            continue
        if len(folded) > _MAX_QUERY_WORD_LEN:
            raise ValueError(
                f"query word {folded!r} exceeds {_MAX_QUERY_WORD_LEN} chars"
            )
        out.append(folded)
    return out


def _normalise_limit(raw: int | None) -> int:
    """Coerce ``limit`` into the allowed range, with a default."""
    if raw is None:
        return _DEFAULT_LIMIT
    if raw < _MIN_LIMIT:
        return _MIN_LIMIT
    if raw > _MAX_LIMIT:
        return _MAX_LIMIT
    return raw


def _normalise_tags(raw_tags: list[str] | None) -> list[str]:
    """Canonicalise tag filters via the project_tags contract.

    Empty / None inputs return ``[]``. The caller decides whether
    empty means "no filter" (our default) or "match projects with no
    tags" — the route handler treats empty as no filter.
    """
    if not raw_tags:
        return []
    # Late import to avoid a circular import — project_tags is the
    # canonical source of the normalisation contract.
    from app.simulation.project_tags import normalise_tags

    return normalise_tags(raw_tags)


def build_search_filters(
    *,
    q: str | None = None,
    tags: list[str] | None = None,
    status: str | None = None,
    archived: bool | None = None,
    limit: int | None = None,
    before_id: int | None = None,
) -> dict:
    """Validate + coerce search inputs into a kwargs dict.

    The keys are stable so the route handler can splat them into a
    SQLAlchemy ``filter()`` chain. Returns:

    * ``query_words`` — list of AND-matched words (empty = no q filter)
    * ``tags`` — canonical list (empty = no tag filter)
    * ``status`` — uppercase string (empty = no status filter)
    * ``archived`` — bool (None = no filter)
    * ``limit`` — int in ``[_MIN_LIMIT, _MAX_LIMIT]``
    * ``before_id`` — int or None
    """
    query_words = _normalise_query_words(q)
    canonical_tags = _normalise_tags(tags)
    status_normalised = (status or "").strip().upper()
    if len(status_normalised) > 50:
        raise ValueError("status filter exceeds 50 chars")
    return {
        "query_words": query_words,
        "tags": canonical_tags,
        "status": status_normalised or None,
        "archived": archived,
        "limit": _normalise_limit(limit),
        "before_id": before_id,
    }


__all__ = [
    "build_search_filters",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "MIN_LIMIT",
    "MAX_QUERY_WORDS",
    "MAX_QUERY_WORD_LEN",
]


# Constants exposed via attributes so callers can import them by name
# rather than re-deriving from the function bodies.
DEFAULT_LIMIT = _DEFAULT_LIMIT
MAX_LIMIT = _MAX_LIMIT
MIN_LIMIT = _MIN_LIMIT
MAX_QUERY_WORDS = _MAX_QUERY_WORDS
MAX_QUERY_WORD_LEN = _MAX_QUERY_WORD_LEN
