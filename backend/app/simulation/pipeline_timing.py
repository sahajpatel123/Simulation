"""Pure helpers for per-stage simulation pipeline timing.

The Celery worker already reports a single ``wall_time_seconds`` for the
conductor run and a coarse progress percentage, but nothing tells a founder
or operator *where* the wall clock actually goes. A 10k-agent run can spend
its time in agent-profile generation, the conductor, the accountability
pass, or result serialisation, and each has a different fix.

This module normalises the worker's raw ``time.perf_counter()`` deltas into
the persisted ``results_json["pipeline_timing"]`` payload:

* only finite, non-negative stage durations are kept (a single bad timer
  value must not poison the payload);
* durations are rounded to 4 decimal places so the JSONB payload stays
  compact and deterministic enough to read;
* ``total_seconds`` is the sum of the accounted stages, and
  ``per_agent_ms`` converts it into a scaling signal (ms per simulated
  agent) that stays comparable across 1k / 10k / 100k runs.

Pure module - no DB, no I/O. The task layer supplies the measured stage
dict and the worker persists the result payload.
"""

from __future__ import annotations

import math
from typing import Any


def _safe_seconds(value: object) -> float | None:
    """Coerce one stage duration to a finite, non-negative float."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0.0:
        return None
    return parsed


def build_pipeline_timing(
    stage_seconds: dict[str, object] | None,
    *,
    total_agents: int | None = None,
    end_to_end_seconds: float | None = None,
) -> dict[str, Any]:
    """Build the persisted ``pipeline_timing`` payload for a simulation run.

    Args:
        stage_seconds: mapping of stage name -> wall-clock duration. Names
            must be non-empty strings; durations must be finite, non-negative
            numbers or they are dropped.
        total_agents: simulated population size, used to derive
            ``per_agent_ms``. ``None`` or non-positive values yield ``None``.
        end_to_end_seconds: optional independently measured worker runtime
            (from the RUNNING status flip to result serialisation). Included
            only when finite and non-negative.

    Returns:
        A dict with one key per valid stage (seconds, rounded to 4 decimals),
        plus ``total_seconds``, ``stage_count``, ``per_agent_ms`` and, when
        provided, ``end_to_end_seconds``. Never raises: malformed input
        produces a zeroed summary rather than a failed simulation.
    """
    cleaned: dict[str, float] = {}
    for name, raw in (stage_seconds or {}).items():
        if not isinstance(name, str) or not name.strip():
            continue
        seconds = _safe_seconds(raw)
        if seconds is None:
            continue
        cleaned[name] = round(seconds, 4)

    total = round(sum(cleaned.values()), 4)
    agents = (
        int(total_agents)
        if isinstance(total_agents, int)
        and not isinstance(total_agents, bool)
        and total_agents > 0
        else None
    )

    payload: dict[str, Any] = {
        **cleaned,
        "total_seconds": total,
        "stage_count": len(cleaned),
        "per_agent_ms": (
            round(total * 1000.0 / agents, 6)
            if agents is not None
            else None
        ),
    }
    end_to_end = _safe_seconds(end_to_end_seconds)
    if end_to_end is not None:
        payload["end_to_end_seconds"] = round(end_to_end, 4)
    return payload


__all__ = ["build_pipeline_timing"]
