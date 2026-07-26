"""
Pure helpers for the architect leaderboard endpoint.

The architect-accuracy bridge computes per-architect
calibration stats across the batch, but the founder wants a
single ranked list of "which architect should I investigate
first?" without iterating the 21 architects.

The leaderboard synthesises the bridge's ``by_architect``
output into a single composite score:

    score = |calibration_variance| × finding_count

The score weights bias magnitude by finding frequency — an
architect that flagged 10 findings AND over-predicted by
5pp ranks higher than one that flagged 1 finding with the
same bias. Architects with no calibrated data
(INSUFFICIENT_DATA) get score 0.0 (handled via the
calibration_variance=None branch) so they don't crowd out
real signals.

The output also surfaces ``priority_label`` (HIGH / MEDIUM /
LOW / NONE) bucketed from the score so the dashboard can
render "X architects need HIGH priority review" without
re-bucketing on the client.

Pure-Python (no SQL, no I/O) — the route layer invokes
:func:`bridge_architect_accuracy` and passes ``by_architect``
through.
"""
from __future__ import annotations

# Priority thresholds on the composite score. Below 0.005 →
# NONE (effectively no actionable signal). Below 0.02 → LOW.
# Below 0.05 → MEDIUM. Above → HIGH.
HIGH_PRIORITY_THRESHOLD: float = 0.05
LOW_PRIORITY_THRESHOLD: float = 0.02
NONE_PRIORITY_THRESHOLD: float = 0.005

VALID_PRIORITY_LABELS: frozenset[str] = frozenset({
    "HIGH",
    "MEDIUM",
    "LOW",
    "NONE",
})

# Cap on the leaderboard list — keeps the dashboard tile
# readable. 21 architects fit easily; the cap exists so the
# helper is robust to a future expansion to 50+.
MAX_LEADERS: int = 50


def _safe_float(raw: object) -> float | None:
    """Coerce to a finite float or return None."""
    import math
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
    return value


def _priority_label(score: float) -> str:
    """Bucket the composite score into a priority label."""
    if score >= HIGH_PRIORITY_THRESHOLD:
        return "HIGH"
    if score >= LOW_PRIORITY_THRESHOLD:
        return "MEDIUM"
    if score >= NONE_PRIORITY_THRESHOLD:
        return "LOW"
    return "NONE"


def build_architect_leaderboard(
    by_architect: list[dict] | None,
    *,
    top_n: int | None = None,
) -> dict:
    """Rank architects across the batch by composite score.

    Args:
        by_architect: list of dicts as produced by
            :func:`bridge_architect_accuracy`'s ``by_architect``
            field. Each row carries at least
            ``architect_name``, ``finding_count``,
            ``calibration_variance``, ``calibration_direction``,
            ``recommendation``.
        top_n: optional cap on the returned leaderboard.
            Defaults to all architects (capped at
            :data:`MAX_LEADERS`).

    Returns:
        A dict matching :class:`ArchitectLeaderboardOut`:

        * ``leaderboard`` — list of ranked rows sorted by
          ``score`` DESC. Each row: ``architect_name``,
          ``finding_count``, ``calibration_variance``,
          ``calibration_direction``, ``recommendation``,
          ``score``, ``priority_label``.
        * ``priority_counts`` — ``{HIGH, MEDIUM, LOW, NONE}``
          histogram so the dashboard has a summary tile.
        * ``total_architects`` — how many architects were
          considered (including uncalibrated ones with
          score 0).
        * ``top_n`` — echoed (the cap actually applied).
    """
    by_architect = by_architect or []
    cap = MAX_LEADERS if top_n is None else max(1, int(top_n))

    rows: list[dict] = []
    priority_counts: dict[str, int] = {
        "HIGH": 0,
        "MEDIUM": 0,
        "LOW": 0,
        "NONE": 0,
    }
    for entry in by_architect:
        name = str(entry.get("architect_name", "")).strip()
        if not name:
            continue
        finding_count = _safe_float(entry.get("finding_count"))
        calibration_variance = _safe_float(
            entry.get("calibration_variance")
        )
        # Composite score: |calibration_variance| ×
        # finding_count. Architects with no calibrated data
        # (calibration_variance=None) → score 0.0.
        if calibration_variance is None or finding_count is None:
            score = 0.0
        else:
            score = abs(calibration_variance) * finding_count
        label = _priority_label(score)
        priority_counts[label] += 1
        rows.append({
            "architect_name": name,
            "finding_count": int(finding_count or 0),
            "calibration_variance": (
                calibration_variance
            ),
            "calibration_direction": str(
                entry.get(
                    "calibration_direction", "INSUFFICIENT_DATA"
                )
            ),
            "recommendation": str(
                entry.get(
                    "recommendation",
                    "Continue — architect is calibrated",
                )
            ),
            "score": round(score, 6),
            "priority_label": label,
        })

    # Sort by score DESC, then finding_count DESC (more data
    # wins on ties), then architect_name ASC (stable).
    rows.sort(
        key=lambda r: (
            -r["score"],
            -r["finding_count"],
            r["architect_name"],
        ),
    )
    leaderboard = rows[:cap]

    # Most common recommendation label across the top-N
    # entries — the dashboard's one-word action hint.
    rec_counts: dict[str, int] = {}
    for row in leaderboard:
        rec = row["recommendation"]
        rec_counts[rec] = rec_counts.get(rec, 0) + 1
    if rec_counts:
        # Tiebreaker: alphabetical so the label is deterministic
        # when multiple recommendations share the max count.
        top_recommendation = max(
            rec_counts.keys(),
            key=lambda k: (rec_counts[k], ""),
        )
    else:
        top_recommendation = (
            "Continue — architect is calibrated"
        )

    # Score distribution — count of leaderboard rows in each
    # score band. Useful for the dashboard's "where does the
    # leaderboard cluster?" histogram.
    score_distribution = {
        "score_zero": 0,         # score == 0.0
        "score_low": 0,          # 0 < score < 0.01
        "score_moderate": 0,     # 0.01 ≤ score < 0.05
        "score_high": 0,         # score ≥ 0.05
    }
    for row in leaderboard:
        score = row["score"]
        if score <= 0.0:
            score_distribution["score_zero"] += 1
        elif score < 0.01:
            score_distribution["score_low"] += 1
        elif score < 0.05:
            score_distribution["score_moderate"] += 1
        else:
            score_distribution["score_high"] += 1

    return {
        "leaderboard": leaderboard,
        "priority_counts": priority_counts,
        "top_recommendation": top_recommendation,
        "score_distribution": score_distribution,
        "total_architects": len(rows),
        "top_n": cap,
    }


__all__ = [
    "HIGH_PRIORITY_THRESHOLD",
    "LOW_PRIORITY_THRESHOLD",
    "NONE_PRIORITY_THRESHOLD",
    "VALID_PRIORITY_LABELS",
    "MAX_LEADERS",
    "build_architect_leaderboard",
]