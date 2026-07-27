"""Pure helpers for the per-project premortem digest.

Composes ``project.premortem_json`` (the JSONB field
populated by the Claude premortem analysis) into a
single founder-readable payload so the dashboard can
render a "what could go wrong?" tile without fanning
out to the generator.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls the field and hands it to
:func:`build_premortem_digest`.

Output shape
------------
::

    {
      "premortem_count": int,
      "severity_breakdown": {"CRITICAL": n, ...},
      "top_failure_modes": list[dict],   # capped
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

MAX_TOP: int = 5

SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _safe_float(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(
        value, bool,
    ):
        return float(value)
    return None


def build_premortem_digest(
    premortem_data: dict | None,
    now: object | None = None,
) -> dict:
    """Compose the per-project premortem digest.

    Args:
        premortem_data: the value of
            ``project.premortem_json``. Expected shape::

                {
                    "failure_modes": [
                        {"title", "description", "severity",
                         "probability", "impact", ...},
                        ...
                    ],
                    "generated_at": "...",
                    "context_used": {...},
                }

            Accepts alternate shapes — anything with a
            ``failure_modes`` (or fallback
            ``modes``/``findings``) list works.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    premortem_data = premortem_data or {}
    raw_modes = (
        premortem_data.get("failure_modes")
        or premortem_data.get("modes")
        or premortem_data.get("findings")
        or []
    )
    if not isinstance(raw_modes, list):
        raw_modes = []

    severity_breakdown: dict[str, int] = {}
    enriched: list[dict] = []
    for raw in raw_modes:
        if not isinstance(raw, dict):
            continue
        sev = (raw.get("severity") or "MEDIUM").upper()
        severity_breakdown[sev] = (
            severity_breakdown.get(sev, 0) + 1
        )
        # Highest impact first when we sort; fall back
        # to 0 for missing or non-numeric impacts.
        impact = _safe_float(raw.get("impact"))
        prob = _safe_float(raw.get("probability"))
        enriched.append({
            "title": raw.get("title"),
            "description": raw.get("description") or "",
            "severity": sev,
            "impact": impact,
            "probability": prob,
        })

    # Sort by impact DESC (most likely fatal first).
    enriched.sort(
        key=lambda m: (m.get("impact") or 0.0),
        reverse=True,
    )
    top_failure_modes = enriched[:MAX_TOP]
    premortem_count = len(enriched)

    # ---- Key signals ------------------------------------------------
    key_signals: list[dict] = []
    critical_count = severity_breakdown.get("CRITICAL", 0)
    if premortem_count == 0:
        key_signals.append({
            "label": "premortem_count",
            "value": 0,
            "severity": SIGNAL_WATCH,
            "display": "No premortem generated yet",
        })
    else:
        key_signals.append({
            "label": "premortem_count",
            "value": premortem_count,
            "severity": (
                SIGNAL_CRITICAL
                if critical_count >= 2 else SIGNAL_OK
            ),
            "display": f"{premortem_count} failure mode(s) identified",
        })

    # ---- Narrative -------------------------------------------------
    sentences: list[str] = []
    if premortem_count == 0:
        sentences.append(
            "No premortem has been generated for this project "
            "yet — run the premortem analysis to surface "
            "failure modes before they happen."
        )
    else:
        sentences.append(
            f"{premortem_count} failure mode(s) identified; "
            f"{critical_count} are CRITICAL."
        )
        if top_failure_modes:
            worst = top_failure_modes[0]
            sentences.append(
                f"Most fatal: \"{worst.get('title') or 'TBD'}\" "
                f"(impact "
                f"{worst.get('impact', 0) if worst.get('impact') is not None else 0:.0f}"
                f")."
            )
    narrative = " ".join(sentences)

    return {
        "premortem_count": premortem_count,
        "severity_breakdown": severity_breakdown,
        "top_failure_modes": top_failure_modes,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "MAX_TOP",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_premortem_digest",
]  # noqa: E501