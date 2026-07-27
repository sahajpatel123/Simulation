"""Pure helpers for the user-level account-health digest.

Composes a single qualitative verdict ("how healthy is this
account?") out of the slices that /me/dashboard surfaces
quantitatively. Different from /me/dashboard — that's a
count snapshot, this is a 0-100 health score with a
3-bucket verdict the home screen can show as a single
big number + traffic-light colour.

The helper is pure-Python. The route layer pulls the
underlying rows and hands them to
:func:`build_account_health`.

What contributes to the score
-----------------------------
Each dimension contributes 0..N points; the total is
clamped to ``[0, MAX_SCORE]``. Penalties subtract from
the cap directly.

* + calibration: low MAE (≥ +25), OK MAE (+15),
  watch (+5), critical (0).
* + blindspots: 0 blindspots → +20; 1-2 → +10;
  3+ → 0.
* + sim success: COMPLETED sims / total sims ≥ 80%
  gets +15; ≥ 50% gets +10; ≥ 20% gets +5; below → 0.
* + decision success: COMPLETED decisions /
  total decisions ≥ 80% → +10; ≥ 50% → +5; below → 0.
* + account age: established (>90d) → +5; otherwise → 0.
* − penalties: each FAILED outcome contributes
  PENALTY_PER_FAILED_OUTCOME points off the cap
  (default 2).
* − penalties: each CRITICAL signal in the calibration
  health contributes PENALTY_PER_CRITICAL_SIGNAL points
  off (default 1).

Output shape
------------
::

    {
      "health_score": int,    # 0..100
      "verdict": "HEALTHY" | "NEEDS_ATTENTION" | "AT_RISK",
      "score_breakdown": {label: points, ...},
      "calibration_health": dict | None,
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

# Bounded so the dashboard can show a percentage easily.
MAX_SCORE: int = 100

# Sub-scores (sum ≤ MAX_SCORE under ideal conditions).
CALIBRATION_SCORE_GOOD: int = 25
CALIBRATION_SCORE_OK: int = 15
CALIBRATION_SCORE_WATCH: int = 5

BLINDSPOTS_SCORE_CLEAN: int = 20
BLINDSPOTS_SCORE_FEW: int = 10
BLINDSPOTS_SCORE_THRESHOLD_FEW: int = 2
BLINDSPOTS_CRITICAL_THRESHOLD: int = 3

SIM_SUCCESS_SCORE_HIGH: int = 15
SIM_SUCCESS_SCORE_MID: int = 10
SIM_SUCCESS_SCORE_LOW: int = 5
SIM_SUCCESS_RATIO_HIGH: float = 0.80
SIM_SUCCESS_RATIO_MID: float = 0.50
SIM_SUCCESS_RATIO_LOW: float = 0.20

DECISION_SUCCESS_SCORE_HIGH: int = 10
DECISION_SUCCESS_SCORE_MID: int = 5
DECISION_SUCCESS_RATIO_HIGH: float = 0.80
DECISION_SUCCESS_RATIO_MID: float = 0.50

ACCOUNT_AGE_ESTABLISHED_DAYS: int = 90
ACCOUNT_AGE_SCORE_BONUS: int = 5

# Penalties (subtract from cap).
PENALTY_PER_FAILED_OUTCOME: int = 2
PENALTY_PER_CRITICAL_SIGNAL: int = 1

# Verdict buckets.
VERDICT_HEALTHY: str = "HEALTHY"
VERDICT_NEEDS_ATTENTION: str = "NEEDS_ATTENTION"
VERDICT_AT_RISK: str = "AT_RISK"

VERDICT_HEALTHY_MIN: int = 70
VERDICT_AT_RISK_MAX: int = 40

# Signal severity buckets — keep aligned with the other
# dashboard tiles.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    return default


def _compute_calibration_points(mae: float | None) -> int:
    if mae is None:
        return CALIBRATION_SCORE_WATCH
    if mae < 0.02:
        return CALIBRATION_SCORE_GOOD
    if mae < 0.05:
        return CALIBRATION_SCORE_OK
    return 0  # critical → no points


def _compute_blindspot_points(blindspot_count: int) -> int:
    if blindspot_count <= 0:
        return BLINDSPOTS_SCORE_CLEAN
    if blindspot_count <= BLINDSPOTS_SCORE_THRESHOLD_FEW:
        return BLINDSPOTS_SCORE_FEW
    return 0  # critical


def _compute_success_points(
    completed: int, total: int, high: int, mid: int,
) -> int:
    if total <= 0:
        return 0
    ratio = completed / total
    if ratio >= high / max(high, 1) * (high / 100.0):
        # The /max() guard above kept the signature simple
        # but we want the literal ratio thresholds — fall
        # through to explicit checks below.
        pass
    if ratio >= SIM_SUCCESS_RATIO_HIGH:
        return SIM_SUCCESS_SCORE_HIGH
    if ratio >= SIM_SUCCESS_RATIO_MID:
        return SIM_SUCCESS_SCORE_MID
    if ratio >= SIM_SUCCESS_RATIO_LOW:
        return SIM_SUCCESS_SCORE_LOW
    return 0


def _compute_sim_success_points(completed: int, total: int) -> int:
    if total <= 0:
        return 0
    ratio = completed / total
    if ratio >= SIM_SUCCESS_RATIO_HIGH:
        return SIM_SUCCESS_SCORE_HIGH
    if ratio >= SIM_SUCCESS_RATIO_MID:
        return SIM_SUCCESS_SCORE_MID
    if ratio >= SIM_SUCCESS_RATIO_LOW:
        return SIM_SUCCESS_SCORE_LOW
    return 0


def _compute_decision_success_points(
    completed: int, total: int,
) -> int:
    if total <= 0:
        return 0
    ratio = completed / total
    if ratio >= DECISION_SUCCESS_RATIO_HIGH:
        return DECISION_SUCCESS_SCORE_HIGH
    if ratio >= DECISION_SUCCESS_RATIO_MID:
        return DECISION_SUCCESS_SCORE_MID
    return 0


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


def build_account_health(
    mae: float | None = None,
    blindspot_count: int = 0,
    simulation_completed: int = 0,
    simulation_total: int = 0,
    decision_completed: int = 0,
    decision_total: int = 0,
    account_age_days: int = 0,
    failed_outcome_count: int = 0,
    critical_signal_count: int = 0,
) -> dict:
    """Compose the per-account health verdict.

    Args:
        mae: mean |variance| across the user's recorded
            outcomes (``None`` when no usable outcomes
            exist — treated as "watch").
        blindspot_count: recent-window blindspot count.
        simulation_completed / simulation_total: numerators
            and denominators for the sim success ratio.
        decision_completed / decision_total: numerators
            and denominators for the decision success ratio.
        account_age_days: days since signup.
        failed_outcome_count: count of FAILED outcomes
            (penalty input).
        critical_signal_count: number of CRITICAL items in
            the calibration health signals (penalty input).

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    score_breakdown: dict[str, int] = {}

    score_breakdown["calibration"] = _compute_calibration_points(mae)
    score_breakdown["blindspots"] = _compute_blindspot_points(
        blindspot_count,
    )
    score_breakdown["sim_success"] = _compute_sim_success_points(
        simulation_completed, simulation_total,
    )
    score_breakdown["decision_success"] = (
        _compute_decision_success_points(
            decision_completed, decision_total,
        )
    )
    score_breakdown["account_age"] = (
        ACCOUNT_AGE_SCORE_BONUS
        if account_age_days >= ACCOUNT_AGE_ESTABLISHED_DAYS
        else 0
    )

    raw_total = sum(score_breakdown.values())
    penalties = (
        _safe_int(failed_outcome_count) * PENALTY_PER_FAILED_OUTCOME
        + _safe_int(critical_signal_count)
        * PENALTY_PER_CRITICAL_SIGNAL
    )
    if penalties:
        score_breakdown["penalties"] = -penalties

    score = max(
        0,
        min(MAX_SCORE, raw_total - penalties),
    )
    verdict = _classify_verdict(score)
    severity = _verdict_severity(verdict)

    # ---- Key signals -----------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "health_score",
        "value": score,
        "severity": severity,
        "display": f"Account health score: {score}/{MAX_SCORE}",
    })
    if failed_outcome_count:
        key_signals.append({
            "label": "failed_outcome_count",
            "value": failed_outcome_count,
            "severity": (
                SIGNAL_CRITICAL
                if failed_outcome_count >= 3 else SIGNAL_WATCH
            ),
            "display": (
                f"{failed_outcome_count} failed outcome(s)"
            ),
        })

    # ---- Narrative -------------------------------------------------
    sentences: list[str] = []
    sentences.append(
        f"Account health score is {score}/{MAX_SCORE} "
        f"({verdict.replace('_', ' ').lower()})."
    )
    contributing = [
        f"{label} +{points}"
        for label, points in score_breakdown.items()
        if points > 0 and label != "penalties"
    ]
    if contributing:
        sentences.append(
            "Contributions: " + ", ".join(contributing) + "."
        )
    if penalties:
        sentences.append(
            f"Penalties: -{penalties}."
        )
    narrative = " ".join(sentences)

    return {
        "health_score": score,
        "verdict": verdict,
        "score_breakdown": score_breakdown,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "MAX_SCORE",
    "CALIBRATION_SCORE_GOOD",
    "CALIBRATION_SCORE_OK",
    "CALIBRATION_SCORE_WATCH",
    "BLINDSPOTS_SCORE_CLEAN",
    "BLINDSPOTS_SCORE_FEW",
    "BLINDSPOTS_SCORE_THRESHOLD_FEW",
    "BLINDSPOTS_CRITICAL_THRESHOLD",
    "SIM_SUCCESS_SCORE_HIGH",
    "SIM_SUCCESS_SCORE_MID",
    "SIM_SUCCESS_SCORE_LOW",
    "SIM_SUCCESS_RATIO_HIGH",
    "SIM_SUCCESS_RATIO_MID",
    "SIM_SUCCESS_RATIO_LOW",
    "DECISION_SUCCESS_SCORE_HIGH",
    "DECISION_SUCCESS_SCORE_MID",
    "DECISION_SUCCESS_RATIO_HIGH",
    "DECISION_SUCCESS_RATIO_MID",
    "ACCOUNT_AGE_ESTABLISHED_DAYS",
    "ACCOUNT_AGE_SCORE_BONUS",
    "PENALTY_PER_FAILED_OUTCOME",
    "PENALTY_PER_CRITICAL_SIGNAL",
    "VERDICT_HEALTHY",
    "VERDICT_NEEDS_ATTENTION",
    "VERDICT_AT_RISK",
    "VERDICT_HEALTHY_MIN",
    "VERDICT_AT_RISK_MAX",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_account_health",
]  # noqa: E501
