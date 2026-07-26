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
"""
from __future__ import annotations

MAX_BATCH_SIZE: int = 100
MIN_ID: int = 1


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


__all__ = ["MAX_BATCH_SIZE", "MIN_ID", "parse_id_list"]