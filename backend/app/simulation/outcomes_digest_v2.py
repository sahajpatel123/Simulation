"""Pure helpers for the per-project outcomes digest.

Composes a per-project summary of how accurate the
predictions have been so the dashboard can answer "how
trustable are my numbers?" in a single API call.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls the (predicted, actual) pairs and hands them
to :func:`build_outcomes_digest`.

Source values
-------------
* ``prediction_pairs`` — list of ``(predicted, actual)``
  tuples from the project's outcomes (one per
  recorded outcome).
* ``architect_accuracy`` — output of
  :func:`build_architect_leaderboard` keyed by architect
  name. Used to surface the worst / best calibrating
  architect without re-querying.
* ``calibration_health`` — output of
  :func:`build_calibration_health` (optional). Used for
  the headline verdict when present.

Output shape
------------
::

    {
      "outcome_count": int,
      "usable_count": int,
      "mean_abs_variance": float,
      "bias_direction": "OVER-PREDICTING" | "UNDER-PREDICTING" | "BALANCED",
      "accuracy_trend": "IMPROVING" | "STABLE" | "DEGRADING" | "INSUFFICIENT_DATA",
      "best_architect": {...} | None,
      "worst_architect": {...} | None,
      "calibration_health": {...} | None,
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

# Cap on (predicted, actual) pairs we average. Anything
# beyond this is informational only — recent predictions
# are what matters.
MAX_PAIRS: int = 25

# |variance| bands (in absolute terms, fraction of 1.0).
# e.g. variance of 0.05 means 5 percentage points.
MAE_OK_THRESHOLD: float = 0.02
MAE_WATCH_THRESHOLD: float = 0.05

# Trend threshold: how much the recent MAE must change vs
# the prior MAE before we call it improving / degrading.
TREND_DELTA_THRESHOLD: float = 0.005

# Architect leaderboard bin labels we trust as
# "calibrated" — the others we surface.
ARCHITECT_BIN_TRUSTED: frozenset[str] = frozenset({
    "TRUSTED", "Continue — architect is calibrated",
})

# Signal severity buckets — keep aligned with the other
# dashboard tiles.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _safe_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _format_mae_severity(mae: float | None) -> str:
    if mae is None:
        return SIGNAL_WATCH
    if mae < MAE_OK_THRESHOLD:
        return SIGNAL_OK
    if mae < MAE_WATCH_THRESHOLD:
        return SIGNAL_WATCH
    return SIGNAL_CRITICAL


def _format_bias_direction(
    pairs: list[tuple[float, float]],
) -> str:
    """Return OVER-PREDICTING / UNDER-PREDICTING / BALANCED
    based on the mean signed bias."""
    if not pairs:
        return "INSUFFICIENT_DATA"
    diffs = [actual - pred for pred, actual in pairs]
    mean_diff = sum(diffs) / len(diffs)
    if abs(mean_diff) < 0.005:
        return "BALANCED"
    if mean_diff > 0:
        return "UNDER-PREDICTING"
    return "OVER-PREDICTING"


def _format_accuracy_trend(
    pairs: list[tuple[float, float]],
) -> str:
    """Compare recent MAE vs prior MAE."""
    if len(pairs) < 4:
        return "INSUFFICIENT_DATA"
    half = len(pairs) // 2
    # pairs come in newest-first from the route layer.
    recent = pairs[:half]
    older = pairs[half:]
    recent_mae = sum(
        abs(a - p) for p, a in recent
    ) / len(recent)
    older_mae = sum(
        abs(a - p) for p, a in older
    ) / len(older)
    delta = recent_mae - older_mae
    if delta < -TREND_DELTA_THRESHOLD:
        return "IMPROVING"
    if delta > TREND_DELTA_THRESHOLD:
        return "DEGRADING"
    return "STABLE"


def _pick_extreme_architect(
    leaderboard: list[dict] | None,
    worst: bool,
) -> dict | None:
    """Return the worst-calibrating (or best-calibrating)
    architect with a non-TRUSTED recommendation, or None.

    The leaderboard already sorts by priority+score, so
    for "best" we walk from the end picking the first
    entry whose priority is "NONE" (i.e. calibrated).
    For "worst" we walk from the front picking the
    first entry with a TIGHTEN / INVESTIGATE_BIAS
    recommendation.
    """
    if not leaderboard:
        return None
    if worst:
        for entry in leaderboard:
            rec = (entry.get("recommendation") or "").upper()
            if rec in {"TIGHTEN", "INVESTIGATE_BIAS"}:
                return entry
    else:
        # Walk from the end for the "calibrated" pick.
        for entry in reversed(leaderboard):
            rec = (entry.get("recommendation") or "").strip()
            if rec in ARCHITECT_BIN_TRUSTED:
                return entry
            if (entry.get("priority_label") or "").upper() == "NONE":
                return entry
    return None


def build_outcomes_digest(
    prediction_pairs: list[tuple[float | None, float | None]],
    architect_leaderboard: list[dict] | None = None,
    calibration_health: dict | None = None,
) -> dict:
    """Compose the per-project outcomes digest.

    Args:
        prediction_pairs: list of ``(predicted, actual)``
            tuples ordered newest-first. ``None`` values
            are filtered out before any statistics are
            computed.
        architect_leaderboard: output of
            :func:`build_architect_leaderboard` (list of
            entry dicts). Optional.
        calibration_health: output of
            :func:`build_calibration_health` (dict).
            Optional but recommended for the headline
            verdict.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    # ---- Filter + cap pairs ------------------------------------------
    pairs: list[tuple[float, float]] = []
    for pair in (prediction_pairs or [])[:MAX_PAIRS]:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        pred = _safe_float(pair[0])
        actual = _safe_float(pair[1])
        if pred is None or actual is None:
            continue
        pairs.append((pred, actual))

    usable_count = len(pairs)
    outcome_count = len(prediction_pairs or [])

    # ---- Statistics --------------------------------------------------
    if usable_count == 0:
        mae: float | None = None
        bias = "INSUFFICIENT_DATA"
        trend = "INSUFFICIENT_DATA"
    else:
        mae = sum(
            abs(actual - pred) for pred, actual in pairs
        ) / usable_count
        bias = _format_bias_direction(pairs)
        trend = _format_accuracy_trend(pairs)

    mae_severity = _format_mae_severity(mae)
    worst_arch = _pick_extreme_architect(
        architect_leaderboard, worst=True,
    )
    best_arch = _pick_extreme_architect(
        architect_leaderboard, worst=False,
    )

    # ---- Key signals ------------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "outcome_count",
        "value": outcome_count,
        "severity": (
            SIGNAL_WATCH if outcome_count == 0 else SIGNAL_OK
        ),
        "display": f"{outcome_count} outcome(s) recorded",
    })
    if mae is not None:
        key_signals.append({
            "label": "mean_abs_variance",
            "value": round(mae, 6),
            "severity": mae_severity,
            "display": f"Mean |variance|: {mae * 100:.2f}%",
        })
    if bias != "INSUFFICIENT_DATA":
        key_signals.append({
            "label": "bias_direction",
            "value": bias,
            "severity": (
                SIGNAL_WATCH
                if bias != "BALANCED" else SIGNAL_OK
            ),
            "display": f"Calibration bias: {bias.replace('-', ' ')}",
        })
    if trend != "INSUFFICIENT_DATA":
        key_signals.append({
            "label": "accuracy_trend",
            "value": trend,
            "severity": (
                SIGNAL_OK if trend == "IMPROVING"
                else SIGNAL_CRITICAL if trend == "DEGRADING"
                else SIGNAL_WATCH
            ),
            "display": f"Accuracy is {trend.lower()}",
        })

    # ---- Narrative -------------------------------------------------
    sentences: list[str] = []
    if outcome_count == 0:
        sentences.append(
            "No outcomes have been recorded yet — calibration "
            "is advisory only."
        )
    elif usable_count == 0:
        sentences.append(
            f"{outcome_count} outcome(s) recorded but none "
            f"have both a predicted and actual value."
        )
    else:
        sentences.append(
            f"Across {usable_count} usable outcome(s), "
            f"mean |variance| is {mae * 100:.2f}%."
        )
    if bias == "OVER-PREDICTING":
        sentences.append(
            "Predictions systematically overshoot — tighten "
            "the highest-impact architects."
        )
    elif bias == "UNDER-PREDICTING":
        sentences.append(
            "Predictions systematically undershoot — you may "
            "be leaving uplift on the table."
        )
    if worst_arch and isinstance(worst_arch, dict):
        sentences.append(
            f"Worst calibrating: "
            f"{worst_arch.get('architect_name')} "
            f"({worst_arch.get('recommendation')})."
        )
    if best_arch and isinstance(best_arch, dict):
        sentences.append(
            f"Best calibrating: "
            f"{best_arch.get('architect_name')} "
            f"({best_arch.get('recommendation')})."
        )
    narrative = " ".join(sentences)

    return {
        "outcome_count": outcome_count,
        "usable_count": usable_count,
        "mean_abs_variance": (
            round(mae, 6) if mae is not None else None
        ),
        "bias_direction": bias,
        "accuracy_trend": trend,
        "best_architect": best_arch,
        "worst_architect": worst_arch,
        "calibration_health": calibration_health,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "MAX_PAIRS",
    "MAE_OK_THRESHOLD",
    "MAE_WATCH_THRESHOLD",
    "TREND_DELTA_THRESHOLD",
    "ARCHITECT_BIN_TRUSTED",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_outcomes_digest",
]  # noqa: E501