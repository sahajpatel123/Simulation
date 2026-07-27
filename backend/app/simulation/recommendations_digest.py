"""Pure helpers for the per-project recommendations digest.

Composes the project's premortem + intervention
recommendations into a single "what does TheCee
recommend?" payload so the dashboard's recommendations
tile can render one paragraph + key signals without
fanning out to /premortem-digest and /intervention-digest.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls both source digests and hands them to
:func:`build_recommendations_digest`.

Output shape
------------
::

    {
      "recommendation_count": int,
      "critical_failure_count": int,
      "quick_win_count": int,
      "top_recommendations": list[dict],   # capped
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

MAX_TOP: int = 8

SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _safe_float(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(
        value, bool,
    ):
        return float(value)
    return None


def _format_recommendation(
    source: str,
    title: str,
    description: str,
    severity: str,
    impact_score: float | None,
    priority_score: float | None,
) -> dict:
    return {
        "source": source,
        "title": title or "Untitled",
        "description": description or "",
        "severity": severity,
        "impact_score": impact_score,
        "priority_score": priority_score,
    }


def _rank_combined(
    items: list[dict],
) -> list[dict]:
    """Sort mixed premortem + intervention items by
    impact / priority score, highest first. Missing
    scores are treated as 0 so the item still surfaces
    (sorted to the bottom of the feed)."""
    def _key(item: dict) -> float:
        return max(
            item.get("impact_score") or 0.0,
            item.get("priority_score") or 0.0,
        )
    return sorted(items, key=_key, reverse=True)


def build_recommendations_digest(
    premortem_digest: dict | None,
    intervention_digest: dict | None,
) -> dict:
    """Compose the per-project recommendations digest.

    Args:
        premortem_digest: the value of
            ``build_premortem_digest`` (or ``None``).
        intervention_digest: the value of
            ``build_intervention_digest`` (or ``None``).

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    premortem_digest = premortem_digest or {}
    intervention_digest = intervention_digest or {}

    # Pull the canonical "top failure modes" from
    # premortem + the canonical "top interventions" from
    # interventions, normalize the schema, then merge +
    # rank.
    enriched: list[dict] = []
    for mode in premortem_digest.get("top_failure_modes") or []:
        if not isinstance(mode, dict):
            continue
        enriched.append(_format_recommendation(
            source="premortem",
            title=mode.get("title"),
            description=mode.get("description"),
            severity=mode.get("severity") or "MEDIUM",
            impact_score=_safe_float(mode.get("impact")),
            priority_score=None,
        ))
    for iv in intervention_digest.get("top_interventions") or []:
        if not isinstance(iv, dict):
            continue
        # Quick-win labels propagate into the title so
        # the dashboard can promote them visually.
        title = iv.get("title") or "Untitled"
        if iv.get("priority_score") is not None:
            score = _safe_float(iv["priority_score"])
            if score is not None and score > 0.70:
                title = f"Quick win: {title}"
        enriched.append(_format_recommendation(
            source="intervention",
            title=title,
            description=iv.get("description"),
            severity=iv.get("difficulty") or "MEDIUM",
            impact_score=None,
            priority_score=_safe_float(iv.get("priority_score")),
        ))

    # Rank + cap.
    ranked = _rank_combined(enriched)
    top_recommendations = ranked[:MAX_TOP]

    # Counts.
    critical_failure_count = sum(
        1 for m in premortem_digest.get("top_failure_modes") or []
        if isinstance(m, dict)
        and (m.get("severity") or "").upper() == "CRITICAL"
    )
    quick_win_count = sum(
        1 for iv in intervention_digest.get("top_interventions") or []
        if isinstance(iv, dict)
        and (iv.get("difficulty") or "").upper() == "LOW"
        and _safe_float(iv.get("priority_score")) is not None
        and _safe_float(iv.get("priority_score")) > 0.70
    )
    recommendation_count = len(top_recommendations)

    # ---- Key signals ------------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "recommendation_count",
        "value": recommendation_count,
        "severity": (
            SIGNAL_WATCH if recommendation_count == 0
            else SIGNAL_OK
        ),
        "display": f"{recommendation_count} recommendation(s) "
        f"ready",
    })
    if critical_failure_count:
        key_signals.append({
            "label": "critical_failure_count",
            "value": critical_failure_count,
            "severity": (
                SIGNAL_CRITICAL
                if critical_failure_count >= 2 else SIGNAL_WATCH
            ),
            "display": (
                f"{critical_failure_count} critical failure(s) "
                f"flagged"
            ),
        })
    if quick_win_count:
        key_signals.append({
            "label": "quick_win_count",
            "value": quick_win_count,
            "severity": (
                SIGNAL_OK if quick_win_count >= 2 else SIGNAL_WATCH
            ),
            "display": (
                f"{quick_win_count} quick win(s) ready"
            ),
        })

    # ---- Narrative -------------------------------------------------
    sentences: list[str] = []
    if recommendation_count == 0:
        sentences.append(
            "No AI-generated recommendations yet — run the "
            "premortem + interventions analysis to populate."
        )
    else:
        sentences.append(
            f"{recommendation_count} recommendation(s) "
            f"composed from premortem + interventions."
        )
    if critical_failure_count and quick_win_count:
        sentences.append(
            f"{critical_failure_count} critical failure(s) and "
            f"{quick_win_count} quick win(s) surfaced."
        )
    elif critical_failure_count:
        sentences.append(
            f"{critical_failure_count} critical failure(s) "
            f"need attention."
        )
    elif quick_win_count:
        sentences.append(
            f"{quick_win_count} quick win(s) ready to act on."
        )
    narrative = " ".join(sentences)

    return {
        "recommendation_count": recommendation_count,
        "critical_failure_count": critical_failure_count,
        "quick_win_count": quick_win_count,
        "top_recommendations": top_recommendations,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "MAX_TOP",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_recommendations_digest",
]  # noqa: E501