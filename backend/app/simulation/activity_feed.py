"""Pure helpers for the per-project activity feed.

Composes a chronological feed of "what just happened"
events from the project's recent rows so the dashboard
can render a timeline without five separate API calls.

Event types emitted
--------------------
* ``sim_created``        — Simulation row inserted
  (status PENDING / RUNNING / FAILED / COMPLETED at
  creation time).
* ``sim_completed``      — Simulation transitioned to
  COMPLETED. ``ref_id`` carries the sim id, ``summary``
  carries the predicted conversion rate.
* ``decision_created``   — Decision row inserted (status
  PENDING / RUNNING / FAILED at creation time).
* ``decision_completed`` — Decision transitioned to
  COMPLETED. ``summary`` carries the recommended scenario
  + winner margin.
* ``outcome_submitted``  — Outcome row inserted.
  ``summary`` carries the actual conversion rate.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls the rows and hands them to
:func:`build_activity_feed`.

Output shape
------------
::

    {
      "event_count": int,
      "events": [
        {
          "type": "sim_completed",
          "occurred_at": "2026-01-04T...",
          "ref_id": 123,
          "title": "Run #3 completed",
          "summary": "Predicted 4.2% conversion",
          "severity": "ok" | "watch" | "critical"
        },
        ...
      ],
      "narrative": "...",
      "key_signals": [...]
    }
"""
from __future__ import annotations

# Cap so the dashboard timeline tile stays readable;
# the founder can always paginate via filter params.
MAX_EVENTS: int = 50

# Severity buckets used in event payloads — re-use the
# convention from portfolio_narrative / decision_digest
# so the dashboard tile-colour mapping is consistent.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _iso(value: object) -> str:
    """Normalise a datetime (or a string) to an ISO
    timestamp string the JSON layer can render."""
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _safe_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def build_activity_feed(
    sims: list[dict] | None = None,
    decisions: list[dict] | None = None,
    outcomes: list[dict] | None = None,
    now: object | None = None,
) -> dict:
    """Compose the per-project activity feed.

    Args:
        sims: list of simulation row dicts; expected keys
            ``id``, ``status``, ``created_at``,
            ``updated_at`` or ``completed_at``, plus
            ``mean_conversion_rate`` or
            ``conversion_rate`` from results_json.
        decisions: list of decision row dicts; expected
            keys ``id``, ``status``, ``created_at``,
            ``updated_at``, ``title``, plus
            ``results_json`` when available.
        outcomes: list of outcome row dicts; expected
            keys ``id``, ``created_at``,
            ``actual_conversion_rate``.
        now: optional override for the current time (for
            testability). When provided, ``now`` is used
            to mark "X days ago" phrasing in the narrative.

    Returns:
        Dict matching the schema described in the module
        docstring.
    """
    events: list[dict] = []

    # ---- Simulations ---------------------------------------------------
    for sim in sims or []:
        if not isinstance(sim, dict):
            continue
        sim_id = sim.get("id")
        created = _iso(sim.get("created_at"))
        status = sim.get("status")
        # Each sim contributes a "created" event.
        events.append({
            "type": "sim_created",
            "occurred_at": created,
            "ref_id": sim_id,
            "title": f"Simulation #{sim_id} enqueued",
            "summary": f"Status: {status}" if status else "",
            "severity": SIGNAL_WATCH,
        })
        # When status == COMPLETED, also emit a completion
        # event keyed off updated_at (best available proxy
        # for the completion timestamp).
        if status == "COMPLETED":
            results = sim.get("results_json") or {}
            if not isinstance(results, dict):
                results = {}
            cr = _safe_float(
                results.get("mean_conversion_rate")
                or results.get("conversion_rate"),
            )
            summary = (
                f"Predicted {cr:.2%} conversion"
                if cr is not None else "Completed"
            )
            events.append({
                "type": "sim_completed",
                "occurred_at": _iso(sim.get("updated_at"))
                or created,
                "ref_id": sim_id,
                "title": f"Simulation #{sim_id} completed",
                "summary": summary,
                "severity": SIGNAL_OK,
            })
        elif status == "FAILED":
            events.append({
                "type": "sim_failed",
                "occurred_at": _iso(sim.get("updated_at"))
                or created,
                "ref_id": sim_id,
                "title": f"Simulation #{sim_id} failed",
                "summary": (
                    sim.get("error_message")
                    or "Worker reported a failure"
                ),
                "severity": SIGNAL_CRITICAL,
            })

    # ---- Decisions -----------------------------------------------------
    for d in decisions or []:
        if not isinstance(d, dict):
            continue
        d_id = d.get("id")
        created = _iso(d.get("created_at"))
        title = d.get("title") or f"Decision #{d_id}"
        status = d.get("status")
        events.append({
            "type": "decision_created",
            "occurred_at": created,
            "ref_id": d_id,
            "title": f"Decision enqueued: {title}",
            "summary": f"Status: {status}" if status else "",
            "severity": SIGNAL_WATCH,
        })
        if status == "COMPLETED":
            results = d.get("results_json") or {}
            if not isinstance(results, dict):
                results = {}
            rec = results.get("recommended_scenario")
            margin = _safe_float(results.get("winner_margin"))
            summary_parts: list[str] = []
            if rec:
                summary_parts.append(f"Recommended: {rec}")
            if margin is not None:
                summary_parts.append(f"Margin {margin:.1%}")
            summary = (
                " · ".join(summary_parts)
                if summary_parts else "Completed"
            )
            events.append({
                "type": "decision_completed",
                "occurred_at": _iso(d.get("updated_at"))
                or created,
                "ref_id": d_id,
                "title": f"Decision completed: {title}",
                "summary": summary,
                "severity": SIGNAL_OK,
            })
        elif status == "FAILED":
            events.append({
                "type": "decision_failed",
                "occurred_at": _iso(d.get("updated_at"))
                or created,
                "ref_id": d_id,
                "title": f"Decision failed: {title}",
                "summary": (
                    d.get("error_message")
                    or "Worker reported a failure"
                ),
                "severity": SIGNAL_CRITICAL,
            })

    # ---- Outcomes ------------------------------------------------------
    for o in outcomes or []:
        if not isinstance(o, dict):
            continue
        o_id = o.get("id")
        cr = _safe_float(o.get("actual_conversion_rate"))
        summary = (
            f"Actual: {cr:.2%} conversion"
            if cr is not None else "Outcome recorded"
        )
        events.append({
            "type": "outcome_submitted",
            "occurred_at": _iso(o.get("created_at")),
            "ref_id": o_id,
            "title": "Outcome recorded",
            "summary": summary,
            "severity": SIGNAL_OK,
        })

    # ---- Sort + cap ---------------------------------------------------
    # Newest first — the dashboard renders a top-down feed.
    events.sort(key=lambda e: e.get("occurred_at") or "", reverse=True)
    capped = events[:MAX_EVENTS]
    event_count = len(events)

    # ---- Narrative ---------------------------------------------------
    sentences: list[str] = []
    if event_count == 0:
        sentences.append(
            "No recent activity — the timeline is empty."
        )
    else:
        # Categorise for the headline.
        sim_count = sum(
            1 for e in events if str(e.get("type", "")).startswith(
                "sim_",
            )
        )
        dec_count = sum(
            1 for e in events
            if str(e.get("type", "")).startswith("decision_")
        )
        out_count = sum(
            1 for e in events
            if e.get("type") == "outcome_submitted"
        )
        crit_count = sum(
            1 for e in events
            if e.get("severity") == SIGNAL_CRITICAL
        )
        sentences.append(
            f"{event_count} recent event(s) — "
            f"{sim_count} simulation(s), "
            f"{dec_count} decision(s), "
            f"{out_count} outcome(s)."
        )
        if crit_count:
            sentences.append(
                f"{crit_count} failure(s) in the window."
            )
        newest = capped[0]
        sentences.append(
            f"Latest: {newest.get('title', 'event')} "
            f"— {newest.get('summary', '')}."
        )
    narrative = " ".join(sentences)

    # ---- Key signals --------------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "event_count",
        "value": event_count,
        "severity": (
            SIGNAL_WATCH if event_count == 0 else SIGNAL_OK
        ),
        "display": f"{event_count} event(s) in the feed",
    })
    recent_failures = sum(
        1 for e in events
        if e.get("severity") == SIGNAL_CRITICAL
    )
    if recent_failures:
        key_signals.append({
            "label": "recent_failures",
            "value": recent_failures,
            "severity": (
                SIGNAL_CRITICAL
                if recent_failures >= 2 else SIGNAL_WATCH
            ),
            "display": f"{recent_failures} failure(s) recent",
        })
    recent_sims = sum(
        1 for e in events
        if e.get("type") == "sim_completed"
    )
    if recent_sims:
        key_signals.append({
            "label": "recent_sim_completions",
            "value": recent_sims,
            "severity": SIGNAL_OK,
            "display": f"{recent_sims} simulation(s) completed",
        })

    return {
        "event_count": event_count,
        "events": capped,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "MAX_EVENTS",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_activity_feed",
]  # noqa: E501
