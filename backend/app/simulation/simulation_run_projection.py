"""Shared JSONB projection for lightweight simulation-run reads.

Both ``/simulation-history`` and ``/simulation-trend`` used to load the full
multi-MB ``results_json`` column just to read one or two conversion keys.
This module owns the single projected SQL read so the two routes cannot
drift apart.

The projection is defensive: ``jsonb_typeof`` guards mean a row whose
``results_json`` is a scalar/array (or whose conversion keys hold
non-numeric JSON like booleans, objects, or arrays) degrades to
``conversion_rate = NULL`` instead of raising a Postgres cast error and
500ing every read for the project. Numeric text (e.g. ``"0.05"``) is parsed
by the pure helpers downstream; non-numeric text also degrades to 0.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# Named-parameter SQL only (AGENTS.md): the project id is bound as ``:pid``.
SIMULATION_RUN_PROJECTION_SQL = text(
    """
    SELECT
        s.id,
        s.status,
        s.signal_quality,
        s.created_at,
        CASE
            WHEN jsonb_typeof(s.results_json) = 'object'
                 AND jsonb_typeof(s.results_json->'population_weighted_conversion')
                     IN ('number', 'string')
            THEN NULLIF(s.results_json->>'population_weighted_conversion', '')
            WHEN jsonb_typeof(s.results_json) = 'object'
                 AND jsonb_typeof(s.results_json->'conversion_rate')
                     IN ('number', 'string')
            THEN NULLIF(s.results_json->>'conversion_rate', '')
        END AS conversion_rate
    FROM simulations s
    WHERE s.project_id = :pid
    ORDER BY s.created_at ASC, s.id ASC
    """
)


def fetch_projected_run_rows(
    db: Session,
    project_id: int,
) -> list[dict[str, Any]]:
    """Return lightweight per-run projection rows for a project.

    Rows are ordered by ``created_at`` ascending with ``id`` as a stable
    tiebreaker, so history deltas and best/latest-run selection stay
    deterministic even when multiple runs share a timestamp.
    """
    rows = db.execute(
        SIMULATION_RUN_PROJECTION_SQL,
        {"pid": project_id},
    ).mappings().all()
    return [dict(row) for row in rows]


__all__ = ["SIMULATION_RUN_PROJECTION_SQL", "fetch_projected_run_rows"]
