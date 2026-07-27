"""Pure helpers for the per-project health score.

Different from /me/account-health (user-level across
all projects): this answers "is THIS specific project in
good shape?" — a 0-100 score + 3-bucket verdict for one
project, composed from its latest sim confidence,
critical-finding count, pending-decision count,
outcome-recording status, and assumption weak-link count.

The helper is pure-Python. The route layer pulls the
underlying data and hands it to
:func:`build_project_health`.

Score composition
-----------------
* + Sim confidence (0-1)  × 30   → "we trust the prediction"
* + Zero critical findings → +20
* + Zero pending decisions → +10
* + Has recorded outcome  → +10
* + Zero assumption weak links → +15
* − Penalty per critical finding beyond 0
* − Penalty per pending decision beyond 0
* − Penalty per weak link beyond 0

Output shape
------------
::

    {
      "project_health_score": int,    # 0..100
      "verdict": "HEALTHY" | "NEEDS_ATTENTION" | "AT_RISK",
      "score_breakdown": dict,
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

MAX_SCORE: int = 100

# Sub-score weights (sum ≤ MAX_SCORE under ideal conditions).
SIM_CONFIDENCE_MAX: int = 30
ZERO_CRITICAL_FINDINGS_BONUS: int = 20
ZERO_PENDING_DECISIONS_BONUS: int = 10
HAS_OUTCOME_BONUS: int = 10
ZERO_WEAK_LINKS_BONUS: int = 15

# Penalties (subtract from cap).
PENALTY_PER_CRITICAL_FINDING: int = 4
PENALTY_PER_PENDING_DECISION: int = 2
PENALTY_PER_WEAK_LINK: int = 1

# Verdict thresholds.
VERDICT_HEALTHY: str = "HEALTHY"
VERDICT_NEEDS_ATTENTION: str = "NEEDS_ATTENTION"
VERDICT_AT_RISK: str = "AT_RISK"
VERDICT_HEALTHY_MIN: int = 70
VERDICT_AT_RISK_MAX: int = 40

# Signal severity buckets.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    return default


def _safe_float(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(
        value, bool,
    ):
        return float(value)
    return None


def _classify_verdict(score: int) -> str:
    if score >= VERDICT_HEALTHY_MIN:
        return VERDICT_HEALTHY
    if score <= VERDICT_AT_RISK_MAX:
        return VERDICT_AT_RISK
    return VERDICT_NEEDS_ATTENTION


def _verdict_severity(verdict: str) -> str:
    if verdict == VERDICT_HEALTHY:
        return SIGNAL_OK
    if verdict == VERDICT_AT_RISK:
        return SIGNAL_CRITICAL
    return SIGNAL_WATCH


def build_project_health(
    sim_confidence: float | None = None,
    critical_finding_count: int = 0,
    pending_decision_count: int = 0,
    weak_link_count: int = 0,
    has_outcome: bool = False,
) -> dict:
    """Compose the per-project health score.

    Args:
        sim_confidence: the latest sim's confidence score
            (0..1) — multiplied by 30 for the sub-score.
            ``None`` when the project has no completed
            sims (treated as 0).
        critical_finding_count: count of CRITICAL findings
            from the latest sim.
        pending_decision_count: count of PENDING/RUNNING
            decisions for the project.
        weak_link_count: count of weak-link assumptions
            (from the assumption digest).
        has_outcome: ``True`` when the project has at
            least one recorded Outcome row.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    confidence_points = 0
    if sim_confidence is not None:
        confidence_points = round(
            max(0.0, min(1.0, sim_confidence))
            * SIM_CONFIDENCE_MAX,
        )

    score_breakdown: dict[str, int] = {
        "sim_confidence": confidence_points,
        "zero_critical_findings": (
            ZERO_CRITICAL_FINDINGS_BONUS
            if critical_finding_count == 0 else 0
        ),
        "zero_pending_decisions": (
            ZERO_PENDING_DECISIONS_BONUS
            if pending_decision_count == 0 else 0
        ),
        "has_outcome": HAS_OUTCOME_BONUS if has_outcome else 0,
        "zero_weak_links": (
            ZERO_WEAK_LINKS_BONUS
            if weak_link_count == 0 else 0
        ),
    }

    raw_total = sum(score_breakdown.values())
    penalties = (
        _safe_int(critical_finding_count)
        * PENALTY_PER_CRITICAL_FINDING
        + _safe_int(pending_decision_count)
        * PENALTY_PER_PENDING_DECISION
        + _safe_int(weak_link_count)
        * PENALTY_PER_WEAK_LINK
    )
    if penalties:
        score_breakdown["penalties"] = -penalties

    score = max(0, min(MAX_SCORE, raw_total - penalties))
    verdict = _classify_verdict(score)
    severity = _verdict_severity(verdict)

    # ---- Key signals -----------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "project_health_score",
        "value": score,
        "severity": severity,
        "display": f"Project health: {score}/{MAX_SCORE}",
    })
    if critical_finding_count:
        key_signals.append({
            "label": "critical_finding_count",
            "value": critical_finding_count,
            "severity": (
                SIGNAL_CRITICAL
                if critical_finding_count >= 3 else SIGNAL_WATCH
            ),
            "display": (
                f"{critical_finding_count} critical finding(s)"
            ),
        })
    if pending_decision_count:
        key_signals.append({
            "label": "pending_decision_count",
            "value": pending_decision_count,
            "severity": (
                SIGNAL_CRITICAL
                if pending_decision_count >= 3 else SIGNAL_WATCH
            ),
            "display": (
                f"{pending_decision_count} decision(s) pending"
            ),
        })

    # ---- Narrative -------------------------------------------------
    sentences: list[str] = []
    sentences.append(
        f"Project health is {score}/{MAX_SCORE} "
        f"({verdict.replace('_', ' ').lower()})."
    )
    contributing = [
        f"{label.replace('_', ' ')} +{points}"
        for label, points in score_breakdown.items()
        if points > 0 and label != "penalties"
    ]
    if contributing:
        sentences.append(
            "Contributions: " + ", ".join(contributing) + "."
        )
    if penalties:
        sentences.append(f"Penalties: -{penalties}.")
    narrative = " ".join(sentences)

    return {
        "project_health_score": score,
        "verdict": verdict,
        "score_breakdown": score_breakdown,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "MAX_SCORE",
    "SIM_CONFIDENCE_MAX",
    "ZERO_CRITICAL_FINDINGS_BONUS",
    "ZERO_PENDING_DECISIONS_BONUS",
    "HAS_OUTCOME_BONUS",
    "ZERO_WEAK_LINKS_BONUS",
    "PENALTY_PER_CRITICAL_FINDING",
    "PENALTY_PER_PENDING_DECISION",
    "PENALTY_PER_WEAK_LINK",
    "VERDICT_HEALTHY",
    "VERDICT_NEEDS_ATTENTION",
    "VERDICT_AT_RISK",
    "VERDICT_HEALTHY_MIN",
    "VERDICT_AT_RISK_MAX",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_project_health",
]  # noqa: E501
