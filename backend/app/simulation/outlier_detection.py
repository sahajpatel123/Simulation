"""
Pure helpers for the outlier-detection endpoint.

Miscalibration (the outcomes-digest) measures whether the
batch is calibrated; outlier detection measures whether
specific sims are *anomalous* relative to their peers.
A sim is flagged when |predicted − actual| is more than
``z_threshold`` standard deviations from the batch mean
of |variance|.

Pure-Python (no SQL, no I/O) — the route layer joins
simulations + outcomes, builds (sim_id, predicted, actual)
tuples, and passes them through.

The helper returns the full batch stats + the outliers so
the dashboard has the headline ("we flagged 2 of 12 sims
as outliers, mean |variance| = 0.04") without recomputing.
"""
from __future__ import annotations

import math

# Default z-score threshold — 3σ is the textbook "anomaly"
# boundary (≈0.3% of a normal distribution). Exposed as a
# route query param so the dashboard can dial it down to
# 2σ for a wider net.
DEFAULT_Z_THRESHOLD: float = 3.0
MIN_Z_THRESHOLD: float = 0.5
MAX_Z_THRESHOLD: float = 10.0

# Floor on batch std — when all sims have the same
# |variance|, std is 0.0 and any nonzero |variance| is
# "infinitely many sigmas" away. We cap the z-score at a
# generous 9999.99 to keep the JSON serialisable.
Z_FLOOR_DENOMINATOR: float = 1e-6
Z_CAP: float = 9999.99


def _safe_float(raw: object) -> float | None:
    """Coerce to a finite float in [0.0, 1.0] or return None."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
    if not math.isfinite(value):
        return None
    if value < 0.0 or value > 1.0:
        return None
    return value


def normalise_z_threshold(raw: float | None) -> float:
    """Clamp the z-score query param into the allowed range.

    Empty / None → default 3.0. Negative / over-10 → clamped
    so a UI typo ('3' instead of '3.0') doesn't silently widen
    the outlier definition.
    """
    if raw is None:
        return DEFAULT_Z_THRESHOLD
    if raw < MIN_Z_THRESHOLD:
        return MIN_Z_THRESHOLD
    if raw > MAX_Z_THRESHOLD:
        return MAX_Z_THRESHOLD
    return raw


def build_outlier_detection(
    rows: list[tuple[object, object, object]],
    *,
    z_threshold: float = DEFAULT_Z_THRESHOLD,
) -> dict:
    """Build the outlier-detection payload.

    Args:
        rows: list of ``(sim_id, predicted, actual)`` tuples.
            ``sim_id`` is echoed back. ``predicted`` / ``actual``
            are coerced defensively (None / non-numeric / out-
            of-range rows are skipped so they don't poison
            the mean).
        z_threshold: |variance| z-score cutoff. Sim is
            flagged when its z-score ≥ threshold.

    Returns:
        A dict matching :class:`OutlierDetectionOut`:

        * ``outliers`` — list of dicts sorted by z_score DESC.
          Each row: ``sim_id``, ``predicted``,
          ``actual_conversion``, ``variance``
          (predicted − actual), ``abs_variance``,
          ``z_score``.
        * ``observation_count`` — sims that contributed
          to the batch mean / std.
        * ``outlier_count`` — how many sims are flagged.
        * ``batch_mean_abs_variance`` — mean of |variance|
          across the batch.
        * ``batch_std_abs_variance`` — sample std-dev of
          |variance| across the batch.
        * ``z_threshold`` — echoed.
        * ``summary`` — one-line headline.
    """
    threshold = normalise_z_threshold(z_threshold)

    abs_variances: list[float] = []
    per_row: list[dict] = []
    sim_to_data: dict[int, dict] = {}

    for sim_id, predicted, actual in rows:
        if sim_id is None:
            continue
        p = _safe_float(predicted)
        a = _safe_float(actual)
        if p is None or a is None:
            continue
        variance = p - a
        abs_var = abs(variance)
        abs_variances.append(abs_var)
        sim_to_data[int(sim_id)] = {
            "sim_id": int(sim_id),
            "predicted": round(p, 6),
            "actual_conversion": round(a, 6),
            "variance": round(variance, 6),
            "abs_variance": round(abs_var, 6),
        }

    observation_count = len(abs_variances)
    if observation_count == 0:
        return {
            "outliers": [],
            "observation_count": 0,
            "outlier_count": 0,
            "batch_mean_abs_variance": 0.0,
            "batch_std_abs_variance": 0.0,
            "z_threshold": threshold,
            "summary": "No data — outlier detection skipped.",
        }

    batch_mean = sum(abs_variances) / observation_count
    if observation_count >= 2:
        # Sample std-dev (1/n-1).
        mean_sq = sum(v * v for v in abs_variances) / observation_count
        variance = max(0.0, mean_sq - batch_mean * batch_mean)
        batch_std = (
            variance * observation_count / (observation_count - 1)
        ) ** 0.5
    else:
        batch_std = 0.0

    # Z-score each sim.
    for sim_id, payload in sim_to_data.items():
        denom = max(batch_std, Z_FLOOR_DENOMINATOR)
        z = (payload["abs_variance"] - batch_mean) / denom
        if z > Z_CAP:
            z = Z_CAP
        sim_to_data[sim_id]["z_score"] = round(z, 6)

    # Outliers = z ≥ threshold.
    outliers: list[dict] = []
    for sim_id, payload in sim_to_data.items():
        if payload["z_score"] >= threshold:
            outliers.append(payload)
    outliers.sort(key=lambda r: -r["z_score"])

    summary = (
        f"Outlier detection: {len(outliers)} of "
        f"{observation_count} sim(s) flagged at z≥{threshold} "
        f"(mean |variance|={round(batch_mean, 4)})"
    )

    return {
        "outliers": outliers,
        "observation_count": observation_count,
        "outlier_count": len(outliers),
        "batch_mean_abs_variance": round(batch_mean, 6),
        "batch_std_abs_variance": round(batch_std, 6),
        "z_threshold": threshold,
        "summary": summary,
    }


__all__ = [
    "DEFAULT_Z_THRESHOLD",
    "MIN_Z_THRESHOLD",
    "MAX_Z_THRESHOLD",
    "normalise_z_threshold",
    "build_outlier_detection",
]