"""Pure helpers for the per-project decision digest.

Composes a per-project summary of all AI-generated
decisions so the founder can answer "what has the system
recommended for me, what's pending, and which is the
clearest winner?" in a single API call.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls the Decision rows, then hands them to
:func:`build_decision_digest`.

Output shape
------------
* ``decision_count`` — total decisions in scope.
* ``status_breakdown`` — ``{status: count}`` so the
  dashboard can render a tiny stacked bar.
* ``success_rate`` — fraction of COMPLETED decisions that
  produced a meaningful winner margin (>= 0.02). 0.0 when
  there are no COMPLETED decisions.
* ``pending_decisions`` — pending/running decisions sorted
  oldest-first (the founder's action queue).
* ``top_decisions`` — completed decisions sorted by winner
  margin DESC, capped at 5.
* ``avg_winner_margin`` — mean winner margin across
  completed decisions, 0.0 when none.
* ``narrative`` — one paragraph string the dashboard can
  render as plain text.
* ``key_signals`` — list of ``{label, value, severity,
  display}`` dicts for the dashboard tiles.
"""
from __future__ import annotations

# Cap on top_decisions so the dashboard tile stays
# readable. The founder can always drill into
# /projects/{id}/decisions for the full list.
MAX_TOP_DECISIONS: int = 5

# Cap on pending_decisions surfaced in the digest so the
# action queue tile doesn't spam. The remaining ones are
# still discoverable via the project decisions endpoint.
MAX_PENDING_DECISIONS: int = 10

# Cap on key_signals so the dashboard's "what's
# important" strip stays scannable.
MAX_KEY_SIGNALS: int = 6

# Winner's-margin threshold above which we consider a
# decision a "clear win". Below this the winner is
# considered marginal and surfaces in the narrative.
CLEAR_WIN_MARGIN: float = 0.02

# Statuses that block founder action — surfaced in
# ``pending_decisions``.
PENDING_STATUSES: frozenset[str] = frozenset({"PENDING", "RUNNING"})

# Signal severity buckets — re-used from the
# portfolio-narrative convention so the dashboard's
# tile-color mapping is consistent across endpoints.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _parse_iso_dt(value: object) -> str:
    """Normalise a created_at value to an ISO string. The
    SQLAlchemy column is a ``datetime`` but tests pass raw
    strings, so handle both."""
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _scenario_label(
    scenarios: list[dict],
    recommended: str | None,
) -> str | None:
    """Return the recommended scenario's display label
    (its name) or None if not derivable."""
    if not recommended or not isinstance(scenarios, list):
        return None
    for s in scenarios:
        if isinstance(s, dict) and s.get("scenario_name") == recommended:
            return s.get("scenario_name")
    return None


def _format_success_rate_severity(rate: float, n_completed: int) -> str:
    """Bucketed severity for the success-rate signal.

    No data → watch (we'd rather flag than hide). 0% →
    critical. <50% → watch. ≥50% → ok.
    """
    if n_completed == 0:
        return SIGNAL_WATCH
    if rate < 0.25:
        return SIGNAL_CRITICAL
    if rate < 0.5:
        return SIGNAL_WATCH
    return SIGNAL_OK


def _format_pending_severity(n_pending: int) -> str:
    if n_pending == 0:
        return SIGNAL_OK
    if n_pending >= 5:
        return SIGNAL_CRITICAL
    return SIGNAL_WATCH


def build_decision_digest(decisions: list[dict]) -> dict:
    """Compose a per-project decision digest.

    Args:
        decisions: list of decision-row dicts. Each must
            expose at least ``id``, ``title``, ``status``,
            ``created_at``. ``results_json`` (when
            present) is expected to be a dict with
            ``scenarios`` / ``recommended_scenario`` /
            ``winner_margin`` keys. Extra fields are
            ignored.

    Returns:
        A dict matching :class:`DecisionDigestOut` (see
        the route layer).
    """
    # ---- Status breakdown -------------------------------------------
    status_breakdown: dict[str, int] = {}
    pending: list[dict] = []
    completed: list[dict] = []
    for d in decisions:
        if not isinstance(d, dict):
            continue
        status = d.get("status") or "UNKNOWN"
        status_breakdown[status] = status_breakdown.get(status, 0) + 1
        if status in PENDING_STATUSES:
            pending.append(d)
        elif status == "COMPLETED":
            completed.append(d)

    decision_count = len(decisions)
    n_pending = len(pending)
    n_completed = len(completed)
    n_failed = status_breakdown.get("FAILED", 0)
    n_running = status_breakdown.get("RUNNING", 0)

    # ---- Top completed (sorted by winner margin) ---------------------
    top_decisions: list[dict] = []
    margins: list[float] = []
    clear_win_count = 0
    for d in completed:
        results = d.get("results_json") or {}
        if not isinstance(results, dict):
            results = {}
        margin = float(results.get("winner_margin", 0.0) or 0.0)
        margins.append(margin)
        if margin >= CLEAR_WIN_MARGIN:
            clear_win_count += 1
        top_decisions.append({
            "id": d.get("id"),
            "title": d.get("title"),
            "status": "COMPLETED",
            "recommended_scenario": results.get("recommended_scenario"),
            "winner_margin": margin,
            "key_insights": results.get("key_insights", []) or [],
            "created_at": _parse_iso_dt(d.get("created_at")),
        })
    # Highest margin first; tiebreak on recency (newer wins).
    top_decisions.sort(
        key=lambda x: (
            -(x.get("winner_margin") or 0.0),
            -(0 if not x.get("created_at") else 1),
            x.get("created_at") or "",
        ),
    )
    top_decisions = top_decisions[:MAX_TOP_DECISIONS]

    # ---- Pending (oldest first) -------------------------------------
    pending_decisions: list[dict] = []
    for d in sorted(
        pending,
        key=lambda x: _parse_iso_dt(x.get("created_at")) or "",
    )[:MAX_PENDING_DECISIONS]:
        pending_decisions.append({
            "id": d.get("id"),
            "title": d.get("title"),
            "status": d.get("status"),
            "created_at": _parse_iso_dt(d.get("created_at")),
        })

    # ---- Aggregates --------------------------------------------------
    avg_winner_margin = (
        sum(margins) / len(margins) if margins else 0.0
    )
    success_rate = (
        clear_win_count / n_completed if n_completed else 0.0
    )

    # ---- Key signals -------------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "decision_count",
        "value": decision_count,
        "severity": (
            SIGNAL_WATCH if decision_count == 0 else SIGNAL_OK
        ),
        "display": f"{decision_count} decision(s) generated",
    })
    key_signals.append({
        "label": "pending_count",
        "value": n_pending,
        "severity": _format_pending_severity(n_pending),
        "display": (
            f"{n_pending} pending" if n_pending
            else "No pending decisions"
        ),
    })
    if n_completed > 0:
        key_signals.append({
            "label": "success_rate",
            "value": round(success_rate, 4),
            "severity": _format_success_rate_severity(
                success_rate, n_completed,
            ),
            "display": (
                f"{success_rate:.0%} of completed decisions "
                f"have a clear winner"
            ),
        })
    if n_failed > 0:
        key_signals.append({
            "label": "failed_count",
            "value": n_failed,
            "severity": (
                SIGNAL_CRITICAL if n_failed >= 2 else SIGNAL_WATCH
            ),
            "display": f"{n_failed} decision(s) failed",
        })
    if n_running > 0:
        key_signals.append({
            "label": "running_count",
            "value": n_running,
            "severity": SIGNAL_WATCH,
            "display": f"{n_running} decision(s) running",
        })
    key_signals = key_signals[:MAX_KEY_SIGNALS]

    # ---- Narrative ---------------------------------------------------
    sentences: list[str] = []
    if decision_count == 0:
        sentences.append(
            "No AI-generated decisions for this project yet — "
            "the digest is empty."
        )
    else:
        sentences.append(
            f"{decision_count} decision(s) generated: "
            f"{n_completed} completed, {n_pending} pending, "
            f"{n_failed} failed."
        )
    if n_completed > 0:
        sentences.append(
            f"Success rate is {success_rate:.0%} with an "
            f"average winner margin of {avg_winner_margin:.1%}."
        )
    if clear_win_count == 0 and n_completed > 0:
        sentences.append(
            "No decisions show a clear winner yet — consider "
            "tightening the scenario inputs."
        )
    if pending_decisions:
        oldest = pending_decisions[0]
        sentences.append(
            f"Oldest pending: \"{oldest.get('title')}\"."
        )
    if top_decisions:
        best = top_decisions[0]
        if best.get("recommended_scenario"):
            sentences.append(
                f"Strongest recommendation: "
                f"{best.get('recommended_scenario')} "
                f"(margin {best.get('winner_margin', 0):.1%})."
            )
    narrative = " ".join(sentences)

    return {
        "decision_count": decision_count,
        "status_breakdown": status_breakdown,
        "success_rate": round(success_rate, 4),
        "avg_winner_margin": round(avg_winner_margin, 6),
        "pending_decisions": pending_decisions,
        "top_decisions": top_decisions,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "MAX_TOP_DECISIONS",
    "MAX_PENDING_DECISIONS",
    "MAX_KEY_SIGNALS",
    "CLEAR_WIN_MARGIN",
    "PENDING_STATUSES",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_decision_digest",
]
