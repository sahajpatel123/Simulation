"""Pure helpers for the per-project intervention digest.

Composes a per-project summary of the AI-generated
interventions (LOW/MEDIUM/HIGH difficulty; LOW/MEDIUM/HIGH
priority) into a single payload the dashboard can render
as a "what should I change next?" tile.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls ``project.interventions_json`` and hands the
embedded list to :func:`build_intervention_digest`.

What it answers
--------------
* "How many interventions has TheCee recommended?"
* "What is the difficulty/priority breakdown?"
* "Which quick wins should I tackle first?"
* "When were these recommendations generated?"

Output shape
------------
::

    {
      "intervention_count": int,
      "difficulty_breakdown": {"LOW": n, "MEDIUM": n, "HIGH": n},
      "priority_breakdown": {"LOW": n, "MEDIUM": n, "HIGH": n},
      "category_breakdown": {"pricing": n, ...},
      "quick_win_count": int,
      "top_interventions": list[dict],   # capped
      "generated_at": str | None,
      "stale": bool,
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

# Cap on top_interventions — dashboard tile stays readable.
MAX_TOP: int = 5

# Cap on category_breakdown so the narrative doesn't list
# every niche category.
MAX_KEY_SIGNALS: int = 6

# Threshold (in days) after which the intervention set is
# considered stale (the latest sim + assumptions have likely
# moved on since).
STALE_AFTER_DAYS: int = 14

# Quick wins = LOW difficulty + priority_score > 0.70.
QUICK_WIN_DIFFICULTY: str = "LOW"
QUICK_WIN_MIN_PRIORITY: float = 0.70

# Signal severity buckets.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _safe_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return default


def _is_quick_win(item: dict) -> bool:
    """Mirror the route's quick-wins definition:
    LOW difficulty + priority_score > 0.70."""
    if not isinstance(item, dict):
        return False
    diff = (item.get("difficulty") or "").upper()
    if diff != QUICK_WIN_DIFFICULTY:
        return False
    score = _safe_float(item.get("priority_score"))
    return score > QUICK_WIN_MIN_PRIORITY


def _format_stale_flag(generated_at: object | None, now: object) -> bool:
    if not generated_at:
        return True
    from datetime import datetime, timezone

    gen = generated_at
    if isinstance(gen, str):
        try:
            gen = datetime.fromisoformat(gen)
        except Exception:
            return True
    if not isinstance(gen, datetime):
        return True
    if gen.tzinfo is None:
        gen = gen.replace(tzinfo=timezone.utc)
    ref = now
    if isinstance(ref, str):
        try:
            ref = datetime.fromisoformat(ref)
        except Exception:
            ref = datetime.now(timezone.utc)
    if isinstance(ref, datetime) and ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    try:
        delta = ref - gen
    except Exception:
        return True
    return delta.days > STALE_AFTER_DAYS


def build_intervention_digest(
    interventions_data: dict | None,
    now: object | None = None,
) -> dict:
    """Compose the per-project intervention digest.

    Args:
        interventions_data: the value of
            ``project.interventions_json``. Expected
            shape::

                {
                    "interventions": [...],   # required list
                    "quick_wins":     [...],   # optional pre-filtered
                    "generated_at":   "...",   # optional ISO timestamp
                    "context_used":   {...},
                    "simulation_id":  int,
                }

            When ``interventions_data`` is None (no
            interventions generated yet), the digest is
            the canonical empty state.
        now: optional override for the current time
            (for testability). When provided, used by the
            stale flag check.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    interventions_data = interventions_data or {}
    raw_interventions = interventions_data.get("interventions") or []
    if not isinstance(raw_interventions, list):
        raw_interventions = []

    intervention_count = 0
    difficulty_breakdown: dict[str, int] = {}
    priority_breakdown: dict[str, int] = {}
    category_breakdown: dict[str, int] = {}
    quick_win_count = 0
    enriched: list[dict] = []

    for raw in raw_interventions:
        if not isinstance(raw, dict):
            continue
        intervention_count += 1
        diff = (raw.get("difficulty") or "").upper()
        if diff:
            difficulty_breakdown[diff] = (
                difficulty_breakdown.get(diff, 0) + 1
            )
        priority = (raw.get("priority") or "").upper()
        if priority:
            priority_breakdown[priority] = (
                priority_breakdown.get(priority, 0) + 1
            )
        cat = raw.get("category")
        if cat:
            category_breakdown[cat] = (
                category_breakdown.get(cat, 0) + 1
            )
        score = _safe_float(raw.get("priority_score"))
        if _is_quick_win(raw):
            quick_win_count += 1
        enriched.append({
            "id": raw.get("id"),
            "title": raw.get("title"),
            "description": raw.get("description") or "",
            "category": cat,
            "difficulty": diff,
            "priority": priority,
            "priority_score": score,
        })

    # Sort by priority_score DESC for the top list.
    enriched.sort(
        key=lambda x: (x.get("priority_score") or 0.0),
        reverse=True,
    )
    top_interventions = enriched[:MAX_TOP]

    generated_at = interventions_data.get("generated_at")
    stale = _format_stale_flag(generated_at, now)

    # ---- Key signals ------------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "intervention_count",
        "value": intervention_count,
        "severity": (
            SIGNAL_WATCH if intervention_count == 0
            else SIGNAL_OK
        ),
        "display": (
            f"{intervention_count} intervention(s) on file"
        ),
    })
    if quick_win_count:
        key_signals.append({
            "label": "quick_win_count",
            "value": quick_win_count,
            "severity": (
                SIGNAL_OK if quick_win_count >= 2
                else SIGNAL_WATCH
            ),
            "display": (
                f"{quick_win_count} quick win(s) ready"
            ),
        })
    if stale:
        key_signals.append({
            "label": "stale",
            "value": True,
            "severity": SIGNAL_WATCH,
            "display": (
                f"Recommendations older than "
                f"{STALE_AFTER_DAYS} days — re-run analysis"
            ),
        })
    key_signals = key_signals[:MAX_KEY_SIGNALS]

    # ---- Narrative --------------------------------------------------
    sentences: list[str] = []
    if intervention_count == 0:
        sentences.append(
            "No interventions have been generated yet for "
            "this project."
        )
    else:
        sentences.append(
            f"{intervention_count} intervention(s) "
            f"generated; {quick_win_count} are quick wins "
            f"({QUICK_WIN_DIFFICULTY} difficulty + "
            f"priority > "
            f"{QUICK_WIN_MIN_PRIORITY:.2f})."
        )
    if stale and intervention_count > 0:
        sentences.append(
            "Recommendations are stale — re-run analysis "
            "after a sim or assumption update."
        )
    if top_interventions:
        best = top_interventions[0]
        sentences.append(
            f"Top recommendation: \"{best.get('title') or 'TBD'}\""
            f" (score {best.get('priority_score', 0):.2f})."
        )
    narrative = " ".join(sentences)

    return {
        "intervention_count": intervention_count,
        "difficulty_breakdown": difficulty_breakdown,
        "priority_breakdown": priority_breakdown,
        "category_breakdown": category_breakdown,
        "quick_win_count": quick_win_count,
        "top_interventions": top_interventions,
        "generated_at": _iso(generated_at),
        "stale": stale,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "MAX_TOP",
    "MAX_KEY_SIGNALS",
    "STALE_AFTER_DAYS",
    "QUICK_WIN_DIFFICULTY",
    "QUICK_WIN_MIN_PRIORITY",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_intervention_digest",
]  # noqa: E501