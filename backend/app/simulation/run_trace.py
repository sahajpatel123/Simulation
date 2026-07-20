"""Structured per-stage timing for the conductor pipeline.

Provides a fail-open ``RunTrace`` recorder that captures elapsed wall time
and item counts for each named stage of a simulation run. Stages are
opened with ``begin(name)`` and closed with ``end(items=...)``. The
resulting payload is JSON-serializable and safe to stash in the
``simulations.run_trace`` JSONB column for later inspection.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class StageRecord:
    """One recorded stage. ``elapsed_ms`` is wall time, ``items`` is an
    optional count of work units processed during the stage (clusters,
    architects, domain reports, etc.)."""

    name: str
    elapsed_ms: float
    items: int | None = None
    status: str = "ok"


@dataclass
class RunTrace:
    """Lightweight, fail-open timer for nested pipeline stages.

    Usage::

        trace = RunTrace()
        trace.begin("cluster_weights")
        # ... work ...
        trace.end(items=52)

        trace.begin("architect_loop")
        # ... work, possibly raising ...
        try:
            ...
            trace.end(items=architect_count)
        except Exception:
            trace.end(status="error")
            raise

        payload = trace.to_dict()
    """

    started_at: float = field(default_factory=time.perf_counter)
    stages: list[StageRecord] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    _stage_start: float | None = None
    _current_name: str = ""

    def begin(self, name: str) -> None:
        """Open a new stage. Closes any prior open stage defensively so
        a forgotten ``end()`` does not skew later stages."""
        if self._stage_start is not None:
            self.end(status="orphaned")
        self._current_name = name
        self._stage_start = time.perf_counter()

    def end(self, items: int | None = None, status: str = "ok") -> None:
        """Close the current stage. Safe to call when no stage is open."""
        if self._stage_start is None:
            return
        elapsed_ms = (time.perf_counter() - self._stage_start) * 1000.0
        self.stages.append(
            StageRecord(
                name=self._current_name or "unnamed",
                elapsed_ms=round(elapsed_ms, 2),
                items=items,
                status=status,
            )
        )
        self._stage_start = None

    def fail(self) -> None:
        """Mark the current stage as failed without recording elapsed
        time since it raised mid-flight."""
        self.end(status="error")

    def add_summary(self, **kwargs: Any) -> None:
        """Attach extra scalar fields to the trace (counters, totals).
        These appear at the top level of ``to_dict()`` so dashboards can
        query them without walking the ``stages`` array."""
        self.summary.update(kwargs)

    def to_dict(self) -> dict:
        total_ms = (time.perf_counter() - self.started_at) * 1000.0
        return {
            "total_ms": round(total_ms, 2),
            "stage_count": len(self.stages),
            **self.summary,
            "stages": [asdict(s) for s in self.stages],
        }
