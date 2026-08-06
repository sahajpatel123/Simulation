"""Pure helpers for the per-project next-best-action.

Composes the single most actionable next step the founder
should take right now, drawn from:

* the latest simulation's top CRITICAL finding
* the oldest pending decision in the project's queue
* the calibration-health verdict when an outcome is
  available
* a fallback "run your first simulation" nudge when the
  project is brand-new

The helper is pure-Python (no SQL, no I/O). The route
layer pulls the data and hands it to
:func:`build_next_best_action`.

Output shape
------------
A single dict::

    {
      "title": "...",
      "action": "TIGHTEN PricingArchitect",
      "reason": "...",
      "severity": "critical" | "watch" | "ok",
      "category": "miscalibration" | "pending_decision"
                    | "calibration_health" | "first_sim"
                    | "no_signal",
      "source": {
        "kind": "...",
        "ref_id": 123,
        "ref_label": "..."
      },
      "fallback": False
    }

The dashboard renders the title + action as a primary CTA
and the reason + severity as supporting context.
"""
from __future__ import annotations

# Severity buckets — match the convention used by
# portfolio_narrative / decision_digest so the dashboard's
# tile-color mapping is consistent.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"

# Category tags drive the dashboard icon + the
# "why this action?" tooltip string.
CATEGORY_MISCALIBRATION: str = "miscalibration"
CATEGORY_PENDING_DECISION: str = "pending_decision"
CATEGORY_CALIBRATION_HEALTH: str = "calibration_health"
CATEGORY_FIRST_SIM: str = "first_sim"
CATEGORY_NO_SIGNAL: str = "no_signal"


def _format_architect_action(architect: str, recommendation: str) -> str:
    """Combine architect + recommendation into a single
    imperative CTA. ``recommendation`` is the
    leaderboard's term (e.g. "TIGHTEN", "INVESTIGATE_BIAS")."""
    if not architect:
        return recommendation or "Investigate"
    if not recommendation:
        return f"Investigate {architect}"
    return f"{recommendation} {architect}"


def _pick_top_critical_finding(
    recent_findings: list[dict] | None,
) -> tuple[str | None, str | None, str | None]:
    """Walk the recent findings (newest first) and pick the
    first CRITICAL architect flag. Returns
    ``(architect, recommendation, title)`` or three Nones."""
    if not recent_findings:
        return None, None, None
    for sim_findings in recent_findings:
        if not isinstance(sim_findings, dict):
            continue
        for finding in sim_findings.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            if finding.get("severity") == "CRITICAL":
                return (
                    finding.get("architect"),
                    finding.get("recommendation"),
                    finding.get("title")
                    or finding.get("description"),
                )
    return None, None, None


def build_next_best_action(
    latest_findings: list[dict] | None,
    pending_decisions: list[dict] | None,
    calibration_health: dict | None,
    has_any_simulation: bool,
) -> dict:
    """Return the single highest-priority next-best-action.

    Args:
        latest_findings: list of ``domain_findings`` payloads
            ordered newest-first. Each entry may carry a
            ``findings`` list with severity-coded entries
            (architect / recommendation / title).
        pending_decisions: list of pending-decision dicts
            (from the digest endpoint). Oldest-first.
        calibration_health: output of
            :func:`build_calibration_health` for the
            project — optional.
        has_any_simulation: whether the project has at least
            one simulation. Drives the fallback nudge.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    # ---- Priority 1: top CRITICAL architect finding --------------
    arch, rec, title = _pick_top_critical_finding(latest_findings)
    if arch is not None:
        return {
            "title": (
                title or f"{arch} flagged something critical"
            ),
            "action": _format_architect_action(arch, rec),
            "reason": (
                f"The latest simulation flagged {arch} as "
                f"CRITICAL with recommendation {rec}. Address "
                f"this before the next run."
            ),
            "severity": SIGNAL_CRITICAL,
            "category": CATEGORY_MISCALIBRATION,
            "source": {
                "kind": "architect_finding",
                "ref_id": None,
                "ref_label": arch,
            },
            "fallback": False,
        }

    # ---- Priority 2: oldest pending decision ----------------------
    # Pick the decision with the earliest created_at so the
    # founder tackles the item that has been waiting longest.
    # ISO-8601 strings compare lexicographically, so a raw
    # string comparison is safe for the API's timestamps;
    # rows missing a timestamp sort last (kept as fallback).
    oldest_pending = None
    if pending_decisions:
        for d in pending_decisions:
            if not isinstance(d, dict):
                continue
            if oldest_pending is None:
                oldest_pending = d
                continue
            d_ts = d.get("created_at")
            best_ts = oldest_pending.get("created_at")
            if d_ts and (not best_ts or d_ts < best_ts):
                oldest_pending = d
    if oldest_pending:
        return {
            "title": (
                oldest_pending.get("title")
                or "Review pending decision"
            ),
            "action": "Review & decide",
            "reason": (
                f"This decision has been in {oldest_pending.get('status', 'PENDING')} "
                f"since {oldest_pending.get('created_at') or 'an unknown date'} — "
                f"address it to unblock your action queue."
            ),
            "severity": SIGNAL_WATCH,
            "category": CATEGORY_PENDING_DECISION,
            "source": {
                "kind": "decision",
                "ref_id": oldest_pending.get("id"),
                "ref_label": oldest_pending.get("title"),
            },
            "fallback": False,
        }

    # ---- Priority 3: miscalibration health verdict ---------------
    if calibration_health:
        verdict = calibration_health.get("overall_health")
        if verdict == "POORLY_CALIBRATED":
            top = calibration_health.get("top_miscalibrated_architect") or {}
            return {
                "title": (
                    f"Calibration is {verdict}"
                ),
                "action": _format_architect_action(
                    top.get("architect_name"),
                    top.get("recommendation"),
                ),
                "reason": (
                    f"Mean |variance| is "
                    f"{calibration_health.get('mean_abs_variance', 0):.4f}. "
                    f"Recommendations are off — tighten "
                    f"{top.get('architect_name') or 'the weakest architect'} "
                    f"so future predictions are trustworthy."
                ),
                "severity": SIGNAL_CRITICAL,
                "category": CATEGORY_CALIBRATION_HEALTH,
                "source": {
                    "kind": "calibration",
                    "ref_id": None,
                    "ref_label": top.get("architect_name"),
                },
                "fallback": False,
            }

    # ---- Fallback: brand-new project, no signal yet --------------
    if not has_any_simulation:
        return {
            "title": "Run your first simulation",
            "action": "Start a simulation",
            "reason": (
                "No simulations have been run yet — start one "
                "to generate a baseline prediction."
            ),
            "severity": SIGNAL_WATCH,
            "category": CATEGORY_FIRST_SIM,
            "source": {
                "kind": "project",
                "ref_id": None,
                "ref_label": "first_simulation",
            },
            "fallback": True,
        }

    # ---- Empty-state when nothing is actionable -------------------
    return {
        "title": "All clear",
        "action": "Run another simulation",
        "reason": (
            "No critical findings, no pending decisions, "
            "and calibration is healthy — run another "
            "simulation to refresh the picture."
        ),
        "severity": SIGNAL_OK,
        "category": CATEGORY_NO_SIGNAL,
        "source": {
            "kind": "system",
            "ref_id": None,
            "ref_label": "all_clear",
        },
        "fallback": True,
    }


__all__ = [
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "CATEGORY_MISCALIBRATION",
    "CATEGORY_PENDING_DECISION",
    "CATEGORY_CALIBRATION_HEALTH",
    "CATEGORY_FIRST_SIM",
    "CATEGORY_NO_SIGNAL",
    "build_next_best_action",
]  # noqa: E501
