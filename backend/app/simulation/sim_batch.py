"""
Pure helpers for the bulk simulation-status endpoint.

The contract is intentionally narrow and predictable so the route
handler can splat the parsed kwargs into a single SQLAlchemy query:

* ``raw_ids`` is any iterable of ints (the route accepts either a
  repeated query param ``?ids=1&ids=2`` or a comma-separated string).
  Strings parse strictly — non-numeric tokens raise.
* IDs are deduplicated and order-preserved (first occurrence wins).
  The DB query uses ``IN`` so dedup also avoids pointless work.
* The batch is capped at :data:`MAX_BATCH_SIZE`; the route passes
  this through to the SQL ``.limit()`` call so the worker can't be
  asked to return more rows than the cap.
* The result is two parallel lists — ``ids`` (the canonical list to
  pass to the DB) and ``original_order`` (the user's first-seen
  order, used to re-order the DB results so the API response matches
  the URL's intent).
* ``sort`` / ``order`` allow the dashboard to pick its preferred
  ordering (id ASC for stable polling, updated_at DESC for
  "recently changed first").
* ``since`` lets the dashboard do incremental polling — only return
  rows whose ``updated_at`` is at or after the supplied ISO
  timestamp. The route layer filters the DB by ``updated_at >=``.
"""
from __future__ import annotations

from datetime import UTC, datetime

MAX_BATCH_SIZE: int = 100
MIN_ID: int = 1

# Allowlist of sortable columns for the batch endpoint. Each tuple is
# (caller-facing name, SQLAlchemy attribute name). Anything outside
# the allowlist raises so a typo can't slip into the SQL ``ORDER BY``.
VALID_BATCH_SORT_FIELDS: dict[str, str] = {
    "id": "id",
    "updated_at": "updated_at",
}
DEFAULT_BATCH_SORT: str = "id"
VALID_BATCH_ORDERS: frozenset[str] = frozenset({"asc", "desc"})
DEFAULT_BATCH_ORDER: str = "asc"


def parse_id_list(raw_ids: list[str] | None) -> list[int]:
    """Parse, validate, dedupe, and cap an ID list.

    Accepts a list of strings (from the URL's repeated query param)
    or ``None`` (empty input). Non-numeric tokens raise
    ``ValueError`` so the route handler returns 400 rather than
    silently dropping the bad ID. Negative or zero IDs raise too —
    simulation IDs are always positive autoincrement.

    Empty / None input returns ``[]`` so the caller treats it as a
    no-op rather than a malformed request.
    """
    if not raw_ids:
        return []
    # Flatten any joined strings (the route receives one token per
    # ``?ids=N`` repeat). The route can also accept comma-separated
    # values by splitting on "," before passing in — keep this
    # helper simple by handling one level of nesting.
    flat: list[str] = []
    for tok in raw_ids:
        if tok is None:
            continue
        # Allow comma-separated tokens for convenience (``?ids=1,2,3``).
        if "," in tok:
            for piece in tok.split(","):
                piece = piece.strip()
                if piece:
                    flat.append(piece)
        else:
            stripped = tok.strip()
            if stripped:
                flat.append(stripped)
    if not flat:
        return []
    parsed: list[int] = []
    seen: set[int] = set()
    for tok in flat:
        try:
            value = int(tok)
        except (TypeError, ValueError):
            raise ValueError(f"invalid simulation id token {tok!r}")
        if value < MIN_ID:
            raise ValueError(
                f"simulation id {value} below minimum {MIN_ID}"
            )
        if value in seen:
            continue
        seen.add(value)
        parsed.append(value)
    if len(parsed) > MAX_BATCH_SIZE:
        # Don't silently truncate — the UI sent too many ids and we
        # want to surface that, not invent a result set.
        raise ValueError(
            f"too many ids ({len(parsed)}); max is {MAX_BATCH_SIZE}"
        )
    return parsed


def _normalise_sort(raw: str | None) -> str:
    """Return a valid sort key from the allowlist, or the default.

    Unknown keys raise ``ValueError`` so the route handler returns
    400 rather than silently using the default (a typo like
    ``?sort=update_at`` would otherwise be invisibly ignored).
    """
    if raw is None:
        return DEFAULT_BATCH_SORT
    candidate = raw.strip().lower()
    if not candidate:
        return DEFAULT_BATCH_SORT
    if candidate not in VALID_BATCH_SORT_FIELDS:
        allowed = ", ".join(sorted(VALID_BATCH_SORT_FIELDS.keys()))
        raise ValueError(f"invalid sort {raw!r}; allowed: {allowed}")
    return candidate


def _normalise_order(raw: str | None) -> str:
    """Return ``asc`` / ``desc`` or the default."""
    if raw is None:
        return DEFAULT_BATCH_ORDER
    candidate = raw.strip().lower()
    if not candidate:
        return DEFAULT_BATCH_ORDER
    if candidate not in VALID_BATCH_ORDERS:
        allowed = ", ".join(sorted(VALID_BATCH_ORDERS))
        raise ValueError(f"invalid order {raw!r}; allowed: {allowed}")
    return candidate


def parse_since(raw: str | None) -> datetime | None:
    """Parse an ISO 8601 ``since`` timestamp.

    Empty / None input returns ``None`` (no filter). Invalid input
    raises ``ValueError`` so the route handler returns 400. Naive
    timestamps are rejected (force the caller to be timezone-aware)
    so the comparison doesn't silently mismatch across regions.
    """
    if raw is None:
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    # ``fromisoformat`` accepts the ``+00:00`` suffix but not the ``Z``
    # shorthand in some Python versions; normalise Z to +00:00 first.
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"invalid since timestamp {raw!r}: {exc}")
    if parsed.tzinfo is None:
        raise ValueError(
            f"since timestamp {raw!r} is timezone-naive; "
            "include a UTC offset (e.g. '...Z' or '+00:00')"
        )
    # Coerce to UTC for consistent DB comparison regardless of source tz.
    return parsed.astimezone(UTC)


def summarise_statuses(statuses: list[str]) -> dict[str, int]:
    """Return a ``{status: count}`` dict for the supplied statuses.

    Iterates in input order but counts in O(n); the caller doesn't
    care about insertion order — dicts are JSON-serialised and the
    dashboard keys off the names.

    Empty input returns an empty dict (no items == no summary).
    """
    out: dict[str, int] = {}
    for s in statuses:
        # Skip non-string entries defensively — the DB column is
        # ``String(50)`` so this shouldn't happen, but the helper
        # is pure and may be called with foreign data.
        if not isinstance(s, str) or not s:
            continue
        out[s] = out.get(s, 0) + 1
    return out


__all__ = [
    "MAX_BATCH_SIZE",
    "MIN_ID",
    "VALID_BATCH_SORT_FIELDS",
    "VALID_BATCH_ORDERS",
    "DEFAULT_BATCH_SORT",
    "DEFAULT_BATCH_ORDER",
    "parse_id_list",
    "parse_since",
    "summarise_statuses",
    "_normalise_sort",
    "_normalise_order",
]
