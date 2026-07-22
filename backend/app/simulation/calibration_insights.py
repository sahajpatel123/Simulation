"""
Pure helpers for the calibration-status diagnostics view.

The ``GET /analytics/calibration/status`` endpoint issues a few SQL queries
and threads the rows through these helpers. Keeping them pure means the
edge cases (empty tables, single row, all-1.0 scalars) are testable
without a database.
"""
from __future__ import annotations

import statistics
from typing import Any


# Architect names must have effective_sample_count >= this to be considered
# "calibrated" — matches the layer-2 threshold used by the calibration engine.
_CALIBRATED_SAMPLE_THRESHOLD: float = 10.0


def build_outcome_coverage(
    total: int | None,
    validated: int | None,
    rejected: int | None,
    pending: int | None = None,
) -> dict[str, Any]:
    """
    Aggregate founder outcome rows into a coverage rollup.

    ``pending`` is the optional leftover (total - validated - rejected).
    If omitted it's computed as ``max(0, total - validated - rejected)`` so
    the math always balances even with stale count data.
    """
    total_n = int(total or 0)
    val_n = int(validated or 0)
    rej_n = int(rejected or 0)
    if pending is None:
        pending_n = max(0, total_n - val_n - rej_n)
    else:
        pending_n = int(pending or 0)

    rate = round((val_n / total_n) * 100.0, 2) if total_n > 0 else 0.0
    return {
        "total": total_n,
        "validated": val_n,
        "rejected": rej_n,
        "pending": pending_n,
        "validation_rate_pct": rate,
    }


def build_architect_health(
    corrections: list[dict[str, Any]] | None,
    known_architect_names: list[str],
) -> list[dict[str, Any]]:
    """
    Aggregate the ``architect_corrections`` rows into a per-architect
    health summary. Architects with no corrections still appear so the
    caller can flag them as ``under_calibrated``.

    Each input row dict must contain at minimum:
      ``architect_name``, ``correction_scalar``, ``confidence_weight``,
      ``effective_sample_count``. Extra fields are ignored.
    """
    by_arch: dict[str, list[dict[str, Any]]] = {n: [] for n in known_architect_names}
    for row in corrections or []:
        name = row.get("architect_name")
        if not name:
            continue
        bucket = by_arch.setdefault(str(name), [])
        bucket.append(row)

    out: list[dict[str, Any]] = []
    for name in sorted(by_arch.keys()):
        rows = by_arch[name]
        if not rows:
            out.append(
                {
                    "architect_name": name,
                    "correction_count": 0,
                    "avg_scalar": 1.0,
                    "max_abs_drift": 0.0,
                    "confidence_avg": 0.0,
                    "effective_sample_count": 0.0,
                    "is_calibrated": False,
                }
            )
            continue

        scalars = [
            float(r.get("correction_scalar", 1.0) or 1.0) for r in rows
        ]
        confs = [
            float(r.get("confidence_weight", 0.0) or 0.0) for r in rows
        ]
        samples = [
            float(r.get("effective_sample_count", 0.0) or 0.0) for r in rows
        ]
        max_abs_drift = max((abs(s - 1.0) for s in scalars), default=0.0)
        out.append(
            {
                "architect_name": name,
                "correction_count": len(rows),
                "avg_scalar": round(statistics.fmean(scalars), 4),
                "max_abs_drift": round(max_abs_drift, 4),
                "confidence_avg": round(statistics.fmean(confs), 4),
                "effective_sample_count": round(sum(samples), 2),
                "is_calibrated": sum(samples) >= _CALIBRATED_SAMPLE_THRESHOLD,
            }
        )
    return out


def summarise_calibration(
    health_rows: list[dict[str, Any]],
    corrections: list[dict[str, Any]] | None = None,
    threshold: float = _CALIBRATED_SAMPLE_THRESHOLD,
) -> dict[str, Any]:
    """
    Roll up the per-architect health into the dashboard summary numbers.

    Returns::

        {
          "total_correction_rows": int,
          "calibrated_architects": int,
          "under_calibrated_architects": int,
          "under_calibrated_list": [name, ...],
        }
    """
    total_rows = len(corrections or [])
    calibrated = [h for h in health_rows if h.get("is_calibrated")]
    under = [
        h["architect_name"]
        for h in health_rows
        if not h.get("is_calibrated")
    ]
    return {
        "total_correction_rows": total_rows,
        "calibrated_architects": len(calibrated),
        "under_calibrated_architects": len(under),
        "under_calibrated_list": under,
        "_threshold": threshold,  # for diagnostics, not surfaced
    }


def build_product_type_breakdown(
    corrections: list[dict[str, Any]] | None,
) -> dict[str, int]:
    """
    Counts correction rows grouped by product_type (default ``"ALL"`` when
    missing). Used by the dashboard so admins can see which product types
    have the most calibration data.
    """
    out: dict[str, int] = {}
    for row in corrections or []:
        pt = (row.get("product_type") or "ALL").upper()
        out[pt] = out.get(pt, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def build_weighted_drift(
    corrections: list[dict[str, Any]] | None,
    known_architect_names: list[str],
) -> dict[str, Any]:
    """
    Confidence-weighted bias rollup across the architect corrections.

    ``drift_i = correction_scalar_i - 1.0`` so a scalar of ``0.92`` counts
    as ``-0.08`` (downward bias) and ``1.07`` as ``+0.07`` (upward bias).

    For each architect we report:

      * ``weighted_drift`` -- Σ drift_i * confidence_weight_i
      * ``confidence_sum`` -- Σ confidence_weight_i
      * ``sample_sum``     -- Σ effective_sample_count_i
      * ``direction``      -- ``"BIASED_UP"`` / ``"BIASED_DOWN"`` /
                             ``"STABLE"`` (when |weighted_drift| <= 1e-6).

    Unknown / empty architects are surfaced with zeroed values and
    ``direction="STABLE"`` so the dashboard never has to special-case them.
    """
    by_arch: dict[str, list[dict[str, Any]]] = {
        n: [] for n in known_architect_names
    }
    for row in corrections or []:
        name = row.get("architect_name")
        if not name:
            continue
        bucket = by_arch.setdefault(str(name), [])
        bucket.append(row)

    out: list[dict[str, Any]] = []
    for name in sorted(by_arch.keys()):
        rows = by_arch[name]
        if not rows:
            out.append(
                {
                    "architect_name": name,
                    "weighted_drift": 0.0,
                    "confidence_sum": 0.0,
                    "sample_sum": 0.0,
                    "direction": "STABLE",
                }
            )
            continue

        weighted_drift = 0.0
        confidence_sum = 0.0
        sample_sum = 0.0
        for row in rows:
            try:
                scalar = float(row.get("correction_scalar", 1.0) or 1.0)
            except (TypeError, ValueError):
                scalar = 1.0
            try:
                conf = float(row.get("confidence_weight", 0.0) or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            try:
                samples = float(row.get("effective_sample_count", 0.0) or 0.0)
            except (TypeError, ValueError):
                samples = 0.0
            weighted_drift += (scalar - 1.0) * conf
            confidence_sum += conf
            sample_sum += samples

        if weighted_drift > 1e-6:
            direction = "BIASED_UP"
        elif weighted_drift < -1e-6:
            direction = "BIASED_DOWN"
        else:
            direction = "STABLE"

        out.append(
            {
                "architect_name": name,
                "weighted_drift": round(weighted_drift, 6),
                "confidence_sum": round(confidence_sum, 6),
                "sample_sum": round(sample_sum, 6),
                "direction": direction,
            }
        )

    return {
        "total_architects": len(out),
        "biased_up_count": sum(1 for r in out if r["direction"] == "BIASED_UP"),
        "biased_down_count": sum(
            1 for r in out if r["direction"] == "BIASED_DOWN"
        ),
        "stable_count": sum(1 for r in out if r["direction"] == "STABLE"),
        "by_architect": out,
    }


__all__ = [
    "_CALIBRATED_SAMPLE_THRESHOLD",
    "build_outcome_coverage",
    "build_architect_health",
    "summarise_calibration",
    "build_product_type_breakdown",
    "build_weighted_drift",
]
