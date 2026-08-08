"""Stable result fingerprinting and identical-input comparison helpers.

The seeded-run feature lets founders re-run a simulation with the same RNG
seed and frozen environment snapshot, but nothing automatically told them
whether the re-run actually matched. This module fingerprints a completed
simulation's result payload (canonical JSON, volatile timing/timestamp
fields excluded) so the API can compare identical-input runs and surface
drift caused by non-seed factors.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

FINGERPRINT_ALGORITHM = "sha256-canonical-json-v1"

# Fields that legitimately differ between two runs of the same simulation
# (wall-clock timing, completion timestamps) and must not influence the
# reproducibility fingerprint.
VOLATILE_RESULT_KEYS: frozenset[str] = frozenset(
    {
        "agents_per_second",
        "completed_at",
        "generated_at",
        "wall_time_seconds",
    }
)


def _canonicalise(value: Any) -> Any:
    """Recursively normalise a JSON value for byte-stable serialisation."""
    if isinstance(value, dict):
        return {
            str(key): _canonicalise(item)
            for key, item in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalise(item) for item in value]
    if isinstance(value, float) and value == 0.0:
        # JSONB round-trips -0.0 as 0.0 on some drivers; treat them as the
        # same number so a sign-only difference never flags a mismatch.
        return 0.0
    return value


def _strip_volatile(value: Any) -> Any:
    """Recursively drop keys whose values change between identical runs."""
    if isinstance(value, dict):
        return {
            key: _strip_volatile(item)
            for key, item in value.items()
            if key not in VOLATILE_RESULT_KEYS
        }
    if isinstance(value, list):
        return [_strip_volatile(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _canonicalise(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def stable_result_fingerprint(results: dict[str, Any] | None) -> str | None:
    """Return a stable SHA-256 fingerprint of a simulation result payload.

    ``None`` or an empty payload returns ``None`` (nothing to verify).
    Volatile timing/timestamp fields are excluded before canonicalisation,
    so an exact replay and its source produce the same fingerprint while
    any real result change produces a different one.
    """
    if not isinstance(results, dict) or not results:
        return None
    payload = _canonical_json(_strip_volatile(results)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def canonical_env_snapshot(snapshot: dict[str, Any] | None) -> str:
    """Return a canonical serialisation of an environment snapshot.

    ``None`` serialises to the JSON literal ``"null"`` so legacy runs
    without a frozen snapshot compare equal to each other but never equal
    to a frozen snapshot dict.
    """
    return _canonical_json(snapshot)


def inputs_are_identical(
    *,
    consumer_volume_a: int,
    seed_used_a: int,
    env_snapshot_a: dict[str, Any] | None,
    consumer_volume_b: int,
    seed_used_b: int,
    env_snapshot_b: dict[str, Any] | None,
) -> bool:
    """Return True when two runs used identical recorded inputs.

    Compares consumer volume, the resolved RNG seed actually used by the
    worker, and the canonical environment snapshot. Two legacy runs with
    no snapshot only match when their resolved seeds also match.
    """
    return (
        consumer_volume_a == consumer_volume_b
        and seed_used_a == seed_used_b
        and canonical_env_snapshot(env_snapshot_a)
        == canonical_env_snapshot(env_snapshot_b)
    )
