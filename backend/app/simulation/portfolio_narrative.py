"""
Pure helpers for the portfolio narrative endpoint.

Composes the existing helper outputs (portfolio_summary,
calibration_health, architect_leaderboard, outlier_detection)
into a single founder-readable narrative so the home-screen
tile can render one paragraph instead of forcing the
dashboard to merge four payloads.

The helper is pure-Python (no SQL, no I/O). The route layer
calls the four sub-helpers in sequence and passes the
results through.

Output:
* ``narrative`` — one paragraph string the dashboard renders
  as plain text.
* ``key_signals`` — list of ``{label, value, severity}`` dicts
  for any structured highlights (e.g. "MAE = 0.04" →
  ``{"label": "mae", "value": 0.04, "severity": "watch"}``).
* ``recommended_actions`` — list of dicts with ``architect``
  + ``action`` for the most-misaligned architects (capped).
"""
from __future__ import annotations

# Cap on the recommended_actions list so the dashboard's
# "what to do next" tile stays readable.
MAX_RECOMMENDED_ACTIONS: int = 5

# Severity buckets for key_signals — used by the dashboard
# to colour-code the "what's important" tiles.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"

VALID_SIGNAL_SEVERITIES: frozenset[str] = frozenset({
    SIGNAL_OK,
    SIGNAL_WATCH,
    SIGNAL_CRITICAL,
})


def _format_mae_severity(mae: float | None) -> str:
    """Buckets a mean |variance| into a dashboard severity.

    0.0–0.02 → ok. 0.02–0.05 → watch. ≥0.05 → critical.
    None → watch (defensive).
    """
    if mae is None:
        return SIGNAL_WATCH
    if mae < 0.02:
        return SIGNAL_OK
    if mae < 0.05:
        return SIGNAL_WATCH
    return SIGNAL_CRITICAL


def _format_trajectory_text(trajectory: str | None) -> str | None:
    """Translate the trajectory label into a short adverb
    ('and trending up' / 'and stable' / 'and trending down')
    for the narrative."""
    if not trajectory:
        return None
    if trajectory == "IMPROVING":
        return "and trending up"
    if trajectory == "STABLE":
        return "and stable"
    if trajectory == "DEGRADING":
        return "and trending down"
    return None


def build_portfolio_narrative(
    portfolio_summary: dict | None,
    calibration_health: dict | None,
    architect_leaderboard: dict | None,
    outlier_detection: dict | None,
) -> dict:
    """Compose a single founder-readable narrative.

    Args:
        portfolio_summary: output of
            :func:`build_portfolio_summary`. May be None when
            no sims were supplied.
        calibration_health: output of
            :func:`build_calibration_health`. May be None.
        architect_leaderboard: output of
            :func:`build_architect_leaderboard`. May be None.
        outlier_detection: output of
            :func:`build_outlier_detection`. May be None.

    Returns:
        A dict matching :class:`PortfolioNarrativeOut`:

        * ``narrative`` — composed paragraph.
        * ``key_signals`` — list of dicts
          ``{label, value, severity}``.
        * ``recommended_actions`` — list of dicts
          ``{architect, action}``.
    """
    # All inputs literally None (truly not provided) → no
    # narrative, no signals, no actions. Empty dicts ({})
    # are treated as legitimate "the sub-helper was called
    # with no data" so we still emit the canonical sim-count
    # + overall-health signals for the dashboard.
    if (
        portfolio_summary is None
        and calibration_health is None
        and architect_leaderboard is None
        and outlier_detection is None
    ):
        return {
            "narrative": "",
            "key_signals": [],
            "recommended_actions": [],
        }

    portfolio_summary = portfolio_summary or {}
    calibration_health = calibration_health or {}
    architect_leaderboard = architect_leaderboard or {}
    outlier_detection = outlier_detection or {}

    # ---- Key signals -------------------------------------------------

    key_signals: list[dict] = []

    # MAE + health from calibration_health.
    mae = calibration_health.get("mean_abs_variance")
    health = calibration_health.get("overall_health", "INSUFFICIENT_DATA")
    mae_severity = _format_mae_severity(mae)
    if mae is not None:
        key_signals.append({
            "label": "mae",
            "value": round(mae, 6),
            "severity": mae_severity,
            "display": f"Mean |variance| = {round(mae, 4)}",
        })
    key_signals.append({
        "label": "overall_health",
        "value": health,
        "severity": (
            SIGNAL_OK
            if health == "WELL_CALIBRATED"
            else SIGNAL_WATCH
            if health == "NEEDS_ATTENTION"
            else SIGNAL_CRITICAL
        ),
        "display": f"Overall health: {health}",
    })
    sim_count = portfolio_summary.get("simulation_count", 0)
    key_signals.append({
        "label": "simulation_count",
        "value": sim_count,
        "severity": (
            SIGNAL_CRITICAL if sim_count == 0 else SIGNAL_OK
        ),
        "display": f"{sim_count} sim(s) in the batch",
    })
    trajectory = calibration_health.get("health_trajectory")
    if trajectory:
        key_signals.append({
            "label": "health_trajectory",
            "value": trajectory,
            "severity": (
                SIGNAL_OK
                if trajectory == "IMPROVING"
                else SIGNAL_WATCH
                if trajectory == "STABLE"
                else SIGNAL_CRITICAL
            ),
            "display": f"Trajectory: {trajectory}",
        })
    streak = calibration_health.get(
        "consecutive_well_calibrated_days"
    )
    if streak is not None and streak > 0:
        key_signals.append({
            "label": "well_calibrated_streak_days",
            "value": streak,
            "severity": SIGNAL_OK,
            "display": f"{streak}-day well-calibrated streak",
        })

    # Outliers from outlier_detection.
    outlier_count = outlier_detection.get("outlier_count", 0)
    if outlier_count > 0:
        key_signals.append({
            "label": "outlier_count",
            "value": outlier_count,
            "severity": (
                SIGNAL_CRITICAL
                if outlier_count >= 3
                else SIGNAL_WATCH
            ),
            "display": (
                f"{outlier_count} outlier sim(s) flagged"
            ),
        })
    top_outlier = (
        outlier_detection.get("top_deviation_summary") or {}
    )
    if top_outlier:
        top_severity = top_outlier.get("deviation_severity", "MILD")
        key_signals.append({
            "label": "top_outlier",
            "value": top_outlier.get("sim_id"),
            "severity": (
                SIGNAL_CRITICAL
                if top_severity == "EXTREME"
                else SIGNAL_WATCH
            ),
            "display": (
                f"Top outlier: sim {top_outlier.get('sim_id')} "
                f"({top_severity})"
            ),
        })

    # Top miscalibrated architect from calibration_health.
    top_arch = calibration_health.get("top_miscalibrated_architect")
    if top_arch:
        key_signals.append({
            "label": "top_miscalibrated_architect",
            "value": top_arch.get("architect_name"),
            "severity": (
                SIGNAL_CRITICAL
                if top_arch.get("recommendation")
                in (
                    "TIGHTEN", "INVESTIGATE_BIAS",
                )
                else SIGNAL_WATCH
            ),
            "display": (
                f"Top miscalibrated: "
                f"{top_arch.get('architect_name')}"
            ),
        })

    # ---- Recommended actions -----------------------------------------

    recommended_actions: list[dict] = []
    for entry in architect_leaderboard.get("leaderboard", []):
        if not isinstance(entry, dict):
            continue
        rec = entry.get("recommendation")
        if not rec or rec in ("TRUSTED", "Continue — architect is calibrated"):
            continue
        recommended_actions.append({
            "architect": entry.get("architect_name"),
            "action": rec,
            "score": entry.get("score"),
            "priority_label": entry.get("priority_label"),
        })
        if len(recommended_actions) >= MAX_RECOMMENDED_ACTIONS:
            break

    # Outlier-driven actions.
    for outlier in outlier_detection.get("outliers", [])[
        :MAX_RECOMMENDED_ACTIONS
    ]:
        if not isinstance(outlier, dict):
            continue
        recommended_actions.append({
            "architect": None,
            "action": (
                f"Investigate sim {outlier.get('sim_id')} "
                f"(z={outlier.get('z_score', 0):.2f})"
            ),
            "score": outlier.get("z_score"),
            "priority_label": outlier.get("deviation_severity"),
        })

    # Sort: critical first, then by score DESC.
    severity_rank = {
        SIGNAL_CRITICAL: 0,
        SIGNAL_WATCH: 1,
        SIGNAL_OK: 2,
    }
    recommended_actions.sort(
        key=lambda a: (
            severity_rank.get(a.get("priority_label"), 3) or 3,
            -(a.get("score") or 0.0),
        )
    )
    recommended_actions = recommended_actions[:MAX_RECOMMENDED_ACTIONS]

    # ---- Narrative composition ---------------------------------------

    sentences: list[str] = []

    # Opening sentence: sim count + overall health.
    if sim_count == 0:
        sentences.append(
            "No simulations were supplied — the portfolio "
            "narrative is empty."
        )
    else:
        sentences.append(
            f"Across {sim_count} simulation(s), the batch is "
            f"{health}."
        )

    # Trajectory sentence.
    trajectory_text = _format_trajectory_text(trajectory)
    if trajectory_text and mae is not None:
        sentences.append(
            f"Calibration is {trajectory_text} with mean "
            f"|variance| at {round(mae, 4)}."
        )
    elif mae is not None:
        sentences.append(
            f"Mean |variance| is {round(mae, 4)}."
        )

    # Streak sentence.
    if streak and streak > 0:
        sentences.append(
            f"You have a {streak}-day well-calibrated streak."
        )

    # Top architect sentence.
    if top_arch:
        sentences.append(
            f"Top miscalibrated architect: "
            f"{top_arch.get('architect_name')} "
            f"({top_arch.get('recommendation')})."
        )

    # Outliers sentence.
    if outlier_count == 1:
        top_o = outlier_detection.get("outliers", [{}])[0]
        sentences.append(
            f"{outlier_count} outlier sim flagged — sim "
            f"{top_o.get('sim_id')} with z={top_o.get('z_score', 0):.2f}."
        )
    elif outlier_count > 1:
        sentences.append(
            f"{outlier_count} outlier sims flagged across the batch."
        )

    # Recommendations summary.
    if recommended_actions:
        sentences.append(
            f"{len(recommended_actions)} recommended action(s) to "
            f"investigate."
        )

    narrative = " ".join(sentences)
    return {
        "narrative": narrative,
        "key_signals": key_signals,
        "recommended_actions": recommended_actions,
    }


__all__ = [
    "MAX_RECOMMENDED_ACTIONS",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "VALID_SIGNAL_SEVERITIES",
    "build_portfolio_narrative",
]
