"""Pure helpers for the per-user tag-taxonomy endpoint.

Composes a single tag + project_count map so the
dashboard's tag-filter dropdowns can render without
fanning out to the projects list endpoint.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls the (tag, count) tuples and hands them to
:func:`build_tag_taxonomy`.

Output shape
------------
::

    {
      "tag_count": int,
      "tags": [
        {"tag": "pricing", "project_count": 3},
        {"tag": "tier-3", "project_count": 2},
        ...
      ],
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

# Signal severity buckets.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"


def _safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    return default


def build_tag_taxonomy(
    tag_counts: list[tuple[str, int]] | None = None,
) -> dict:
    """Compose the per-user tag-taxonomy digest.

    Args:
        tag_counts: list of ``(tag, project_count)`` tuples
            from the route layer. The route is expected to
            pre-flatten ``Project.tags`` (which is a list)
            into one row per (project_id, tag) pair.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    rows: list[dict] = []
    seen: set[str] = set()
    for entry in tag_counts or []:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        tag = entry[0]
        count = _safe_int(entry[1])
        if not isinstance(tag, str) or not tag:
            continue
        if tag in seen:
            continue
        seen.add(tag)
        rows.append({"tag": tag, "project_count": count})

    # Sort by project_count DESC, then by tag name (alpha).
    rows.sort(
        key=lambda r: (-r["project_count"], r["tag"]),
    )
    tag_count = len(rows)

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "tag_count",
        "value": tag_count,
        "severity": (
            SIGNAL_WATCH if tag_count == 0 else SIGNAL_OK
        ),
        "display": f"{tag_count} tag(s) on file",
    })

    # ---- Narrative ------------------------------------------------
    sentences: list[str] = []
    if tag_count == 0:
        sentences.append("No tags on file yet.")
    else:
        most_used = rows[0]
        sentences.append(
            f"{tag_count} tag(s) in use; "
            f"'{most_used['tag']}' is the most common "
            f"({most_used['project_count']} project(s))."
        )
    narrative = " ".join(sentences)

    return {
        "tag_count": tag_count,
        "tags": rows,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "build_tag_taxonomy",
]  # noqa: E501
