"""Pure helpers for the per-project assumption digest.

Composes a per-project summary of all AI-extracted
assumptions so the dashboard can answer "what does TheCee
actually assume about my project, and which are the weakest
links?" in a single API call.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls the Assumption rows and hands them to
:func:`build_assumption_digest`.

What "weak link" means
----------------------
A weak-link assumption is one that:

* has ``sensitivity`` in (HIGH, CRITICAL), and
* has a low ``specificity_score`` (heuristic that prefers
  concrete numbers over vague claims).

If ``specificity_score`` is not provided by the caller,
we use a conservative default (0.5) so an unsorted call
still produces a sensible bucket.

Output shape
------------
::

    {
      "assumption_count": int,
      "sensitivity_breakdown": {"LOW": n, "MEDIUM": n, ...},
      "category_breakdown": {"pricing": n, "trust": n, ...},
      "high_impact_count": int,
      "weak_link_count": int,
      "weak_links": list[dict],            # capped
      "recent_assumptions": list[dict],    # capped
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

MAX_WEAK_LINKS: int = 5
MAX_RECENT_ASSUMPTIONS: int = 5
MAX_KEY_SIGNALS: int = 6

# Specificity below which an assumption is considered
# "vague" — combined with high sensitivity it becomes a
# weak link.
SPECIFICITY_WEAK_THRESHOLD: float = 0.5

# Sensitivity levels that count toward "high impact".
HIGH_SENSITIVITIES: frozenset[str] = frozenset(
    {"HIGH", "CRITICAL"},
)

# Signal severity buckets — keep aligned with the other
# dashboard tiles.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _iso(value: object) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _format_specificity(value: object) -> float:
    """Normalise a specificity score into [0.0, 1.0].
    Defaults to 0.5 when not provided so the bucket logic
    still works."""
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    return 0.5


def _specificity_severity(score: float) -> str:
    if score < 0.3:
        return SIGNAL_CRITICAL
    if score < 0.6:
        return SIGNAL_WATCH
    return SIGNAL_OK


def build_assumption_digest(
    assumptions: list[dict],
) -> dict:
    """Compose a per-project assumption digest.

    Args:
        assumptions: list of assumption-row dicts. Each
            must expose ``id``, ``text``, ``sensitivity``,
            ``category`` (optional), ``impact_score``
            (optional), ``is_hidden`` (optional), and
            ``created_at``. Optional:
            ``specificity_score``.

    Returns:
        A dict matching the output shape described in the
        module docstring.
    """
    visible = [
        a for a in assumptions
        if isinstance(a, dict) and not a.get("is_hidden")
    ]

    # ---- Breakdowns ---------------------------------------------------
    sensitivity_breakdown: dict[str, int] = {}
    category_breakdown: dict[str, int] = {}
    high_impact_count = 0
    impacts: list[float] = []
    weak_links: list[dict] = []

    for a in visible:
        sens = a.get("sensitivity") or "MEDIUM"
        sensitivity_breakdown[sens] = (
            sensitivity_breakdown.get(sens, 0) + 1
        )
        cat = a.get("category")
        if cat:
            category_breakdown[cat] = (
                category_breakdown.get(cat, 0) + 1
            )
        impact = a.get("impact_score")
        if isinstance(impact, (int, float)):
            impacts.append(float(impact))
        if sens in HIGH_SENSITIVITIES:
            high_impact_count += 1
        specificity = _format_specificity(
            a.get("specificity_score"),
        )
        if (
            sens in HIGH_SENSITIVITIES
            and specificity < SPECIFICITY_WEAK_THRESHOLD
        ):
            weak_links.append({
                "id": a.get("id"),
                "text": a.get("text"),
                "sensitivity": sens,
                "specificity_score": round(specificity, 3),
                "impact_score": (
                    float(impact) if isinstance(
                        impact, (int, float),
                    ) else None
                ),
                "category": cat,
            })

    # Sort weak links: CRITICAL first, then by impact DESC.
    sensitivity_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    weak_links.sort(
        key=lambda w: (
            sensitivity_rank.get(w.get("sensitivity"), 4),
            -(w.get("impact_score") or 0.0),
        ),
    )
    weak_links = weak_links[:MAX_WEAK_LINKS]
    weak_link_count = len(weak_links)

    # ---- Recent additions --------------------------------------------
    recent = sorted(
        visible,
        key=lambda a: _iso(a.get("created_at")),
        reverse=True,
    )[:MAX_RECENT_ASSUMPTIONS]
    recent_assumptions = [
        {
            "id": a.get("id"),
            "text": a.get("text"),
            "sensitivity": a.get("sensitivity") or "MEDIUM",
            "category": a.get("category"),
            "created_at": _iso(a.get("created_at")),
        }
        for a in recent
    ]

    # ---- Aggregates --------------------------------------------------
    avg_impact = sum(impacts) / len(impacts) if impacts else 0.0
    assumption_count = len(visible)

    # ---- Key signals ------------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "assumption_count",
        "value": assumption_count,
        "severity": (
            SIGNAL_WATCH if assumption_count == 0 else SIGNAL_OK
        ),
        "display": f"{assumption_count} assumption(s) on file",
    })
    if weak_link_count > 0:
        key_signals.append({
            "label": "weak_link_count",
            "value": weak_link_count,
            "severity": (
                SIGNAL_CRITICAL
                if weak_link_count >= 3 else SIGNAL_WATCH
            ),
            "display": (
                f"{weak_link_count} vague high-impact "
                f"assumption(s) flagged"
            ),
        })
    if high_impact_count:
        key_signals.append({
            "label": "high_impact_count",
            "value": high_impact_count,
            "severity": SIGNAL_WATCH,
            "display": (
                f"{high_impact_count} high-impact assumption(s)"
            ),
        })
    if avg_impact > 0:
        key_signals.append({
            "label": "avg_impact_score",
            "value": round(avg_impact, 3),
            "severity": (
                SIGNAL_WATCH if avg_impact >= 7 else SIGNAL_OK
            ),
            "display": (
                f"Average impact score {avg_impact:.1f}"
            ),
        })
    key_signals = key_signals[:MAX_KEY_SIGNALS]

    # ---- Narrative --------------------------------------------------
    sentences: list[str] = []
    if assumption_count == 0:
        sentences.append(
            "No assumptions have been extracted for this "
            "project yet."
        )
    else:
        sentences.append(
            f"{assumption_count} assumption(s) extracted; "
            f"{high_impact_count} are high-impact."
        )
    if weak_link_count:
        worst = weak_links[0]
        sentences.append(
            f"Weakest link: \"{worst.get('text', '')}\" "
            f"({worst.get('sensitivity')} sensitivity, "
            f"specificity "
            f"{worst.get('specificity_score', 0):.2f})."
        )
    if avg_impact > 0:
        sentences.append(
            f"Average impact score: {avg_impact:.1f}."
        )
    narrative = " ".join(sentences)

    return {
        "assumption_count": assumption_count,
        "sensitivity_breakdown": sensitivity_breakdown,
        "category_breakdown": category_breakdown,
        "high_impact_count": high_impact_count,
        "weak_link_count": weak_link_count,
        "weak_links": weak_links,
        "recent_assumptions": recent_assumptions,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "MAX_WEAK_LINKS",
    "MAX_RECENT_ASSUMPTIONS",
    "MAX_KEY_SIGNALS",
    "SPECIFICITY_WEAK_THRESHOLD",
    "HIGH_SENSITIVITIES",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_assumption_digest",
]  # noqa: E501
