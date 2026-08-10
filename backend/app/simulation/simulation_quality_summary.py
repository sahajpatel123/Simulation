"""Pure project-level simulation quality digest.

The per-run quality gate (``app.simulation.simulation_quality``) answers
"how trustworthy is this one run?" This module answers the portfolio
question on top of it: *"how trustworthy is this project's simulation
history?"* The route layer supplies the project's simulation rows and this
helper runs the same deterministic gate on each completed run, then rolls
the results into:

* per-run trust scores, verdicts, and headline conversion (pending / failed
  rows are listed without a score);
* PASS / REVIEW / FAIL verdict counts;
* mean / min / max trust scores across evaluated runs;
* an overall verdict derived from the mean trust score using the same
  thresholds as the per-run gate.

Pure-Python — no SQL, no I/O — so the aggregation is verifiable without
FastAPI or PostgreSQL.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from app.simulation.simulation_quality import (
    PASS_THRESHOLD,
    REVIEW_THRESHOLD,
    VERDICT_FAIL,
    VERDICT_PASS,
    VERDICT_REVIEW,
    build_simulation_quality,
)

LABEL_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"


def _created_at_text(raw: Any) -> str | None:
    """Coerce a datetime / ISO string to a string; ``None`` stays ``None``."""
    if raw is None:
        return None
    if hasattr(raw, "isoformat"):
        return raw.isoformat()
    return str(raw)


def _safe_signal_quality(raw: Any) -> float | None:
    """Coerce a persisted signal quality to a finite 0..1 float or ``None``."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or not (0.0 <= value <= 1.0):
        return None
    return round(value, 4)


def _overall_verdict(trust_scores: list[float]) -> str:
    """Bucket the mean trust score into the digest's overall verdict."""
    if not trust_scores:
        return LABEL_INSUFFICIENT_DATA
    mean = sum(trust_scores) / len(trust_scores)
    if mean >= PASS_THRESHOLD:
        return VERDICT_PASS
    if mean >= REVIEW_THRESHOLD:
        return VERDICT_REVIEW
    return VERDICT_FAIL


def build_project_simulation_quality(
    rows: list[dict[str, Any]] | None,
    *,
    project_id: int,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the project simulation quality digest from simulation rows.

    Each row should contain ``id``, ``status``, ``created_at``,
    ``signal_quality`` and ``results_json``. Rows may arrive in any order;
    the helper preserves input order in ``runs``. Completed rows are passed
    through the per-run quality gate; other statuses are listed with a
    ``None`` trust score so the digest always reflects the full history.
    """
    if generated_at is None:
        generated_at = datetime.now(UTC).isoformat()

    total_runs = len(rows or [])
    completed_runs = 0
    evaluated_runs = 0
    trust_scores: list[float] = []
    verdict_counts: dict[str, int] = {
        VERDICT_PASS: 0,
        VERDICT_REVIEW: 0,
        VERDICT_FAIL: 0,
    }
    run_rows: list[dict[str, Any]] = []

    for raw in rows or []:
        row = raw if isinstance(raw, dict) else {}
        simulation_id = int(row.get("id") or 0)
        status = str(row.get("status") or "UNKNOWN").strip().upper()
        created_at = _created_at_text(row.get("created_at"))

        trust_score: float | None = None
        verdict: str | None = None
        headline_conversion: float | None = None
        signal_quality: float | None = None
        failed_checks = 0
        skipped_checks = 0

        if status == "COMPLETED":
            completed_runs += 1
            evaluated_runs += 1
            quality = build_simulation_quality(
                simulation_id=simulation_id,
                project_id=project_id,
                base_results=row.get("results_json"),
                status=status,
                signal_quality=row.get("signal_quality"),
            )
            trust_score = quality.trust_score
            verdict = quality.verdict
            headline_conversion = quality.headline_conversion
            signal_quality = quality.signal_quality
            failed_checks = int(quality.summary.failed_checks)
            skipped_checks = int(quality.summary.skipped_checks)
            trust_scores.append(trust_score)
            verdict_counts[str(verdict)] = verdict_counts.get(str(verdict), 0) + 1
        else:
            signal_quality = _safe_signal_quality(row.get("signal_quality"))

        run_rows.append(
            {
                "simulation_id": simulation_id,
                "status": status,
                "created_at": created_at,
                "trust_score": trust_score,
                "verdict": verdict,
                "headline_conversion": headline_conversion,
                "signal_quality": signal_quality,
                "failed_checks": failed_checks,
                "skipped_checks": skipped_checks,
            }
        )

    return {
        "project_id": project_id,
        "total_runs": total_runs,
        "completed_runs": completed_runs,
        "evaluated_runs": evaluated_runs,
        "pass_count": verdict_counts[VERDICT_PASS],
        "review_count": verdict_counts[VERDICT_REVIEW],
        "fail_count": verdict_counts[VERDICT_FAIL],
        "overall_verdict": _overall_verdict(trust_scores),
        "mean_trust_score": (
            round(sum(trust_scores) / len(trust_scores), 4)
            if trust_scores
            else None
        ),
        "min_trust_score": min(trust_scores) if trust_scores else None,
        "max_trust_score": max(trust_scores) if trust_scores else None,
        "generated_at": generated_at,
        "runs": run_rows,
    }


__all__ = [
    "LABEL_INSUFFICIENT_DATA",
    "build_project_simulation_quality",
]
