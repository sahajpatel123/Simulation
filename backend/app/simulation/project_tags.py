"""
Tag normalisation + validation helpers for projects.

Tags are short, lowercase, URL-safe labels users attach to projects
to organise them (e.g. ``"saas"``, ``"v2"``, ``"ab-test"``). The API
exposes three mutating routes that funnel every write through
:func:`normalise_tags` so the persisted shape is always:

* a list of unique strings
* lowercase, stripped, with internal whitespace collapsed
* max ``_MAX_TAG_LEN`` characters each
* bounded to ``_MAX_TAGS_PER_PROJECT`` entries per project
* only contains ``[a-z0-9_-]`` characters (no punctuation, no spaces,
  no unicode) — this lets the tag appear in URLs, JSON filters, and
  future API tokens without escaping

Anything outside the contract is rejected, never silently coerced —
that way a UI typo doesn't quietly turn ``"Q3 Launch"`` into ``"q3"``.

The route layer accepts ``None``/empty inputs as "clear all" so the
UI can reset a project's tags in one request without enumerating
the current set.
"""
from __future__ import annotations

import re

# Caps — kept module-level so tests can import them as constants
# rather than re-deriving them from the validator logic.
MAX_TAG_LEN: int = 32
MAX_TAGS_PER_PROJECT: int = 20

# Allowed character set: lowercase ASCII alnum, dash, underscore.
# Dots, slashes, spaces, and unicode are *not* allowed so the tag
# is safe to embed in URLs (``/projects?tag=v2``) and future token
# schemes (``share:project:v2``). Dashes and underscores let users
# mimic common conventions (``"ab-test"``, ``"hero_v1"``).
_TAG_CHARS_RE = re.compile(r"^[a-z0-9_-]+$")

# Internal whitespace run inside a tag is collapsed to a single dash
# before the lowercase + strip pass. A tag like ``"Q3   Launch"``
# becomes ``"q3-launch"`` rather than triggering an error.
_INTERNAL_WS_RE = re.compile(r"\s+")


def _coerce_one(raw: str) -> str:
    """Return the canonical form of a single tag or raise ``ValueError``.

    Contract:
        * must be a string (non-None)
        * non-empty after strip + whitespace-collapse
        * length ``<= MAX_TAG_LEN``
        * only contains ``[a-z0-9_-]``

    The case fold happens *after* whitespace collapse so a tag like
    ``"  Q3  "`` → ``"q3"`` deterministically (not ``"  q3"``).
    """
    if not isinstance(raw, str):
        raise ValueError(f"tag must be a string, got {type(raw).__name__}")
    # Collapse any internal whitespace run to a single dash first;
    # case-fold + strip next; then enforce length + char set.
    collapsed = _INTERNAL_WS_RE.sub("-", raw.strip())
    folded = collapsed.casefold()
    # After casefold, ``.strip()`` removes any leading/trailing dashes
    # that the whitespace-collapse pass may have introduced.
    folded = folded.strip("-").strip()
    if not folded:
        raise ValueError("tag cannot be empty or whitespace-only")
    if len(folded) > MAX_TAG_LEN:
        raise ValueError(
            f"tag {folded!r} exceeds max length {MAX_TAG_LEN} chars"
        )
    if not _TAG_CHARS_RE.fullmatch(folded):
        raise ValueError(
            f"tag {folded!r} contains disallowed characters; "
            "use lowercase letters, digits, '-', or '_'"
        )
    return folded


def normalise_tags(raw_tags: list[str] | None) -> list[str]:
    """Return the canonical, deduped, order-preserved tag list.

    * ``None`` or ``[]`` → ``[]``
    * duplicates are dropped (case-insensitively — handled by the
      casefold step in :func:`_coerce_one`)
    * order is preserved: first occurrence wins
    * over-cap entries raise ``ValueError`` so the caller returns
      a 400 rather than silently truncating the user's intent

    The list cap is enforced *after* dedupe so the limit reflects
    the persisted shape, not the raw user input.
    """
    if not raw_tags:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for t in raw_tags:
        normalised = _coerce_one(t)
        if normalised in seen:
            continue
        seen.add(normalised)
        out.append(normalised)
    if len(out) > MAX_TAGS_PER_PROJECT:
        raise ValueError(
            f"too many tags ({len(out)}); max is {MAX_TAGS_PER_PROJECT}"
        )
    return out


__all__ = [
    "MAX_TAG_LEN",
    "MAX_TAGS_PER_PROJECT",
    "normalise_tags",
    "rename_tag_in_list",
    "remove_tag_from_list",
]


def rename_tag_in_list(tags: list[str] | None, old: str, new: str) -> list[str]:
    """Return a new list with ``old`` replaced by ``new`` wherever it appears.

    Preserves order, deduplicates the result (in case the new tag was
    already present alongside the old — the merged list is then
    capped against :data:`MAX_TAGS_PER_PROJECT` so a rename can never
    blow the per-project cap).

    * ``None``/empty input → ``[]``
    * if ``old`` is absent, the input is returned unchanged
    * if the rename would push the list over the cap, a ``ValueError``
      is raised so the caller can return a 400
    """
    if not tags:
        return []
    seen: set[str] = set()
    out: list[str] = []
    replaced = False
    for t in tags:
        if t == old:
            candidate = new
            replaced = True
        else:
            candidate = t
        if candidate in seen:
            continue
        seen.add(candidate)
        out.append(candidate)
    if not replaced:
        return list(tags)
    if len(out) > MAX_TAGS_PER_PROJECT:
        raise ValueError(
            f"rename would push tag count to {len(out)}; max is {MAX_TAGS_PER_PROJECT}"
        )
    return out


def remove_tag_from_list(tags: list[str] | None, target: str) -> list[str]:
    """Return a new list with ``target`` removed.

    Order is preserved. Idempotent — calling with a tag that isn't
    present is a no-op.
    """
    if not tags:
        return []
    return [t for t in tags if t != target]
