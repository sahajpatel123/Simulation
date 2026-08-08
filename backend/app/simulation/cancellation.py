"""Cooperative cancellation primitives for the simulation pipeline.

The conductor runs 52 clusters × the product's architect stack — the
longest stretch of a simulation. A user-initiated cancel flips the
simulation row to ``CANCELLED``; the worker checks that state at each
cluster boundary through :func:`Conductor.run`'s ``cancel_check``
callback and raises :class:`SimulationCancelled` to unwind cleanly
instead of killing the worker or persisting partial results.
"""

from __future__ import annotations


class SimulationCancelled(Exception):
    """Raised when a running simulation is cancelled by its owner.

    Deliberately separate from ``Exception`` handling in the Celery
    task: a cancellation is a terminal outcome, not a failure, so it
    must not retry, increment failure metrics, or persist a FAILED row.
    """
