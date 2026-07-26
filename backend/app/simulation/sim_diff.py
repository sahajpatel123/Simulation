"""
Pure helpers for the sim-comparison endpoint.

Sibling to cluster_diff (iter 18): the founder picks two
sims and the dashboard renders a side-by-side comparison so
they can answer "are these two sims actually different?"
without iterating each one.

The helper takes two complete sim payloads (metadata +
findings + predicted/actual conversion) and emits a diff:
* findings_diff — per-severity count + totals + winner label.
* conversion_diff — predicted / actual / variance per side
  + delta between the two.
* aggregate_diff — per-metric rows (predicted, actual,
  variance, |gap|, winner).
* summary — one-line headline.

Pure-Python (no SQL, no I/O) — the route layer validates
the two sim ids against the owned set, fetches the data,
and passes two dicts through.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

# Severity ordering — higher rank = more severe.
_SEVERITY_RANK: dict[str, int] = {
    "INFO": 1,
    "WARNING": 2,
    "CRITICAL": 3,
}


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


def _safe_str_id(raw: object) -> str:
    """Coerce an id-like value to a string. ``None`` → ``''``."""
    if raw is None:
        return ""
    return str(raw)


def _iso(ts: object) -> str | None:
    """Coerce a created_at value to ISO 8601 string. ``None`` →
    ``None``."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        return ts.isoformat()
    return str(ts)


def _winner(a: float | None, b: float | None) -> str:
    """Pick the higher side. ``TIE`` on near-equal (within
    1e-6), ``B`` if a is None, ``A`` if b is None."""
    if a is None and b is None:
        return "TIE"
    if a is None:
        return "SIM_B"
    if b is None:
        return "SIM_A"
    delta = a - b
    if abs(delta) < 1e-6:
        return "TIE"
    return "SIM_A" if delta > 0 else "SIM_B"


def _winner_lower(a: float | None, b: float | None) -> str:
    """Pick the LOWER side — used for |variance| (the better-
    calibrated side wins). ``TIE`` on near-equal, ``B`` if a is
    None, ``A`` if b is None."""
    if a is None and b is None:
        return "TIE"
    if a is None:
        return "SIM_B"
    if b is None:
        return "SIM_A"
    delta = a - b
    if abs(delta) < 1e-6:
        return "TIE"
    return "SIM_A" if delta < 0 else "SIM_B"


def _severity_counts(findings: list[dict] | None) -> dict[str, int]:
    """Count findings by severity. Non-list / missing severity
    falls into the INFO bucket (defensive)."""
    findings = findings or []
    counts = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}
    for f in findings:
        if not isinstance(f, dict):
            continue
        severity = str(f.get("severity", "INFO")).upper()
        if severity not in counts:
            severity = "INFO"
        counts[severity] += 1
    return counts


def _meta(sim_id: object, sim_data: dict | None) -> dict:
    """Pull the per-sim metadata block echoed back to the
    dashboard."""
    sim_data = sim_data or {}
    return {
        "sim_id": int(sim_id) if sim_id is not None else None,
        "project_id": sim_data.get("project_id"),
        "status": sim_data.get("status"),
        "created_at": _iso(sim_data.get("created_at")),
        "predicted_conversion_rate": _safe_float(
            sim_data.get("predicted_conversion_rate")
        ),
        "actual_conversion_rate": _safe_float(
            sim_data.get("actual_conversion_rate")
        ),
    }


def _variance(pred: float | None, act: float | None) -> float | None:
    if pred is None or act is None:
        return None
    return round(pred - act, 6)


def build_sim_diff(
    sim_a_id: int,
    sim_a_data: dict | None,
    sim_b_id: int,
    sim_b_data: dict | None,
) -> dict:
    """Build the sim-comparison payload.

    Args:
        sim_a_id / sim_b_id: canonical sim ids (echoed back).
        sim_a_data / sim_b_data: dicts carrying at least
            ``project_id``, ``status``, ``created_at``,
            ``predicted_conversion_rate``,
            ``actual_conversion_rate``, and
            ``domain_findings``.

    Returns:
        A dict matching :class:`SimDiffOut`:

        * ``sim_a_meta`` / ``sim_b_meta`` — echoed metadata.
        * ``findings_diff`` — dict with per-side
          ``critical_count``, ``warning_count``,
          ``info_count``, ``total_count``, ``winner``
          (the side with the most findings).
        * ``conversion_diff`` — per-side
          ``predicted_conversion``,
          ``actual_conversion``, ``variance``, plus
          ``predicted_delta``, ``actual_delta`` (SIM_A −
          SIM_B).
        * ``aggregate_diff`` — list of per-metric rows
          (predicted / actual / variance / winner).
        * ``summary`` — one-line headline.
    """
    a_meta = _meta(sim_a_id, sim_a_data)
    b_meta = _meta(sim_b_id, sim_b_data)

    a_findings = (
        (sim_a_data or {}).get("domain_findings") if sim_a_data
        else None
    )
    b_findings = (
        (sim_b_data or {}).get("domain_findings") if sim_b_data
        else None
    )
    a_counts = _severity_counts(a_findings)
    b_counts = _severity_counts(b_findings)

    a_total = sum(a_counts.values())
    b_total = sum(b_counts.values())

    # Each finding-severity count's winner.
    findings_diff = {
        "sim_a": a_counts,
        "sim_b": b_counts,
        "critical_count_winner": _winner(
            a_counts["CRITICAL"], b_counts["CRITICAL"]
        ),
        "warning_count_winner": _winner(
            a_counts["WARNING"], b_counts["WARNING"]
        ),
        "info_count_winner": _winner(
            a_counts["INFO"], b_counts["INFO"]
        ),
        "total_count_winner": _winner(
            float(a_total), float(b_total)
        ),
        "sim_a_total_count": a_total,
        "sim_b_total_count": b_total,
    }

    # Conversion deltas.
    a_pred = a_meta["predicted_conversion_rate"]
    a_act = a_meta["actual_conversion_rate"]
    b_pred = b_meta["predicted_conversion_rate"]
    b_act = b_meta["actual_conversion_rate"]
    a_var = _variance(a_pred, a_act)
    b_var = _variance(b_pred, b_act)
    conversion_diff = {
        "sim_a": {
            "predicted_conversion": a_pred,
            "actual_conversion": a_act,
            "variance": a_var,
        },
        "sim_b": {
            "predicted_conversion": b_pred,
            "actual_conversion": b_act,
            "variance": b_var,
        },
        "predicted_delta": (
            round(a_pred - b_pred, 6)
            if a_pred is not None and b_pred is not None
            else None
        ),
        "actual_delta": (
            round(a_act - b_act, 6)
            if a_act is not None and b_act is not None
            else None
        ),
        "variance_delta": (
            round((a_var or 0.0) - (b_var or 0.0), 6)
            if a_var is not None and b_var is not None
            else None
        ),
        "variance_winner": _winner_lower(
            abs(a_var) if a_var is not None else None,
            abs(b_var) if b_var is not None else None,
        ),
    }

    # Per-metric rows for the dashboard's table.
    aggregate_diff = [
        {
            "metric": "predicted_conversion_rate",
            "sim_a": a_pred,
            "sim_b": b_pred,
            "delta": conversion_diff["predicted_delta"],
            "winner": _winner(a_pred, b_pred),
        },
        {
            "metric": "actual_conversion_rate",
            "sim_a": a_act,
            "sim_b": b_act,
            "delta": conversion_diff["actual_delta"],
            "winner": _winner(a_act, b_act),
        },
        {
            "metric": "variance",
            "sim_a": a_var,
            "sim_b": b_var,
            "delta": conversion_diff["variance_delta"],
            "winner": conversion_diff["variance_winner"],
        },
        {
            "metric": "total_finding_count",
            "sim_a": float(a_total),
            "sim_b": float(b_total),
            "delta": float(a_total - b_total),
            "winner": findings_diff["total_count_winner"],
        },
    ]

    # One-line headline summarising the comparison.
    summary = (
        f"Sim {sim_a_id} vs Sim {sim_b_id}: "
        f"{a_total} findings / {a_pred or '?'}→{a_act or '?'} "
        f"vs {b_total} findings / {b_pred or '?'}→{b_act or '?'}"
    )

    return {
        "sim_a_meta": a_meta,
        "sim_b_meta": b_meta,
        "findings_diff": findings_diff,
        "conversion_diff": conversion_diff,
        "aggregate_diff": aggregate_diff,
        "summary": summary,
    }


__all__ = [
    "build_sim_diff",
]  # the internal helpers (_winner, _severity_counts, _safe_float)
# are intentionally NOT exported — they're implementation
# details and could be renamed without breaking consumers.