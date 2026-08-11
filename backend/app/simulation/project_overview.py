"""Pure composition helper for the one-call per-project overview.

Each per-project digest endpoint (status banner, latest snapshot, confidence
explainer, next action, stale check, convergence, health, outcomes digest)
already exists as its own API route. This module composes them into a single
lightweight dashboard payload so the frontend can render the project header
with one request instead of eight.

Every digest exposes ``key_signals`` with a ``severity`` bucket (``ok`` /
``watch`` / ``critical``). The overview normalises each panel into a
subsystem row (key, label, verdict, healthy, summary, headline) and rolls the
severities up: ``CRITICAL`` wins, then ``WATCH``, then ``HEALTHY``. A
completely empty payload (no panels at all) is ``EMPTY`` and counts as
healthy — there is nothing to judge yet, not something broken.

The composition is pure Python (no I/O): callers build the individual panel
payloads and pass them in.
"""

from __future__ import annotations

from typing import Any

# Overall verdicts.
VERDICT_HEALTHY: str = "HEALTHY"
VERDICT_WATCH: str = "WATCH"
VERDICT_CRITICAL: str = "CRITICAL"
VERDICT_EMPTY: str = "EMPTY"

# Severity buckets used by the panel key-signals.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"

_VALID_SEVERITIES: frozenset[str] = frozenset(
    {SIGNAL_OK, SIGNAL_WATCH, SIGNAL_CRITICAL}
)

_SEVERITY_RANK: dict[str, int] = {
    SIGNAL_OK: 0,
    SIGNAL_WATCH: 1,
    SIGNAL_CRITICAL: 2,
}

# Canonical panel order + labels for the project dashboard.
PANEL_ORDER: tuple[str, ...] = (
    "status_banner",
    "latest_snapshot",
    "confidence_explainer",
    "next_action",
    "stale_check",
    "convergence",
    "health",
    "outcomes_digest",
)

PANEL_LABELS: dict[str, str] = {
    "status_banner": "Project status",
    "latest_snapshot": "Latest activity",
    "confidence_explainer": "Prediction confidence",
    "next_action": "Next action",
    "stale_check": "Data freshness",
    "convergence": "Prediction convergence",
    "health": "Project health",
    "outcomes_digest": "Outcome accuracy",
}


def _safe_str(raw: Any, default: str = "") -> str:
    if raw is None or isinstance(raw, bool):
        return default
    text = str(raw).strip()
    return text if text else default


def _safe_int(raw: Any, default: int = 0) -> int:
    if raw is None or isinstance(raw, bool):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        parsed = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed == parsed else None


def _normalise_severity(raw: Any) -> str:
    candidate = str(raw or "").strip().lower()
    if candidate not in _VALID_SEVERITIES:
        return SIGNAL_OK
    return candidate


def _explicit_severity(raw: Any) -> str | None:
    """Return a valid severity only when one was explicitly supplied."""
    candidate = str(raw or "").strip().lower()
    if candidate in _VALID_SEVERITIES:
        return candidate
    return None


def _key_signal_severity(panel: dict[str, Any]) -> str | None:
    """Return the worst valid severity from a panel's key-signals.

    ``critical`` wins, then ``watch``, then ``ok``. Malformed or missing
    severities are ignored so they cannot mask the panel's direct
    ``severity`` / ``verdict`` fallbacks.
    """
    worst: str | None = None
    for signal in panel.get("key_signals") or []:
        if not isinstance(signal, dict):
            continue
        severity = _explicit_severity(signal.get("severity"))
        if severity is None:
            continue
        if (
            worst is None
            or _SEVERITY_RANK[severity] > _SEVERITY_RANK[worst]
        ):
            worst = severity
    return worst


def _panel_severity(key: str, panel: dict[str, Any] | None) -> str:
    """Derive one panel's severity bucket, falling back to known fields."""
    if panel is None:
        return SIGNAL_OK

    from_signals = _key_signal_severity(panel)
    if from_signals is not None:
        return from_signals

    # Field-level fallbacks for digests that expose a direct severity or
    # verdict rather than (or in addition to) key-signals.
    direct = _explicit_severity(panel.get("severity"))
    if direct is not None:
        return direct

    verdict = str(panel.get("verdict") or "").upper()
    if key == "health":
        if verdict == "AT_RISK":
            return SIGNAL_CRITICAL
        if verdict == "NEEDS_ATTENTION":
            return SIGNAL_WATCH
        if verdict == "HEALTHY":
            return SIGNAL_OK
    if key == "convergence":
        if verdict == "DIVERGED":
            return SIGNAL_CRITICAL
        if verdict in {"MILDLY_VARIANT", "INSUFFICIENT_DATA"}:
            return SIGNAL_WATCH
        if verdict == "CONVERGED":
            return SIGNAL_OK

    return SIGNAL_OK


def _panel_summary(key: str, panel: dict[str, Any] | None) -> str:
    """One-line human summary for a panel row."""
    if panel is None:
        return "Not available"

    narrative = _safe_str(panel.get("narrative"))
    if narrative:
        return narrative[:240]

    if key == "status_banner":
        return f"Status: {_safe_str(panel.get('status'), 'Unknown')}"
    if key == "next_action":
        title = _safe_str(panel.get("title"))
        action = _safe_str(panel.get("action"))
        if action:
            return f"{action}: {title}" if title else action
        return title or "No next action yet"
    if key == "health":
        score = _safe_int(panel.get("project_health_score"))
        return f"Score {score}/100 ({_safe_str(panel.get('verdict'), 'UNKNOWN')})"
    if key == "convergence":
        return f"Verdict: {_safe_str(panel.get('verdict'), 'INSUFFICIENT_DATA')}"
    if key == "stale_check":
        stale = _safe_int(panel.get("stale_count"))
        checked = _safe_int(panel.get("sources_checked"))
        return f"{stale} of {checked} data source(s) stale"
    if key == "outcomes_digest":
        mae = _safe_float(panel.get("mean_abs_variance"))
        bias = _safe_str(panel.get("bias_direction"), "INSUFFICIENT_DATA")
        if mae is not None:
            return f"Mean |variance| {mae:.1%}, {bias}"
        return f"Calibration: {bias}"
    if key == "confidence_explainer":
        score = _safe_float(panel.get("confidence_score"))
        return (
            f"Confidence {score:.0%}"
            if score is not None
            else "No confidence score"
        )

    return "No data"


def _panel_headline(key: str, panel: dict[str, Any] | None) -> dict[str, Any]:
    """Key metrics for one panel row (compact, defensive)."""
    if panel is None:
        return {}

    if key == "status_banner":
        return {
            "status": _safe_str(panel.get("status")),
            "severity": _normalise_severity(panel.get("severity")),
        }
    if key == "latest_snapshot":
        return {
            "brief_completed": bool(panel.get("brief_completed")),
            "has_simulation": panel.get("latest_simulation") is not None,
            "has_outcome": panel.get("latest_outcome") is not None,
            "has_decision": panel.get("latest_decision") is not None,
        }
    if key == "confidence_explainer":
        return {
            "confidence_score": _safe_float(panel.get("confidence_score")),
        }
    if key == "next_action":
        return {
            "title": _safe_str(panel.get("title")),
            "action": _safe_str(panel.get("action")),
            "category": _safe_str(panel.get("category")),
            "severity": _normalise_severity(panel.get("severity")),
            "fallback": bool(panel.get("fallback")),
        }
    if key == "stale_check":
        return {
            "stale_count": _safe_int(panel.get("stale_count")),
            "sources_checked": _safe_int(panel.get("sources_checked")),
        }
    if key == "convergence":
        return {
            "sim_count": _safe_int(panel.get("sim_count")),
            "mean_pcr": _safe_float(panel.get("mean_pcr")),
            "cv": _safe_float(panel.get("cv")),
            "verdict": _safe_str(panel.get("verdict")),
        }
    if key == "health":
        return {
            "project_health_score": _safe_int(
                panel.get("project_health_score")
            ),
            "verdict": _safe_str(panel.get("verdict")),
        }
    if key == "outcomes_digest":
        return {
            "outcome_count": _safe_int(panel.get("outcome_count")),
            "usable_count": _safe_int(panel.get("usable_count")),
            "mean_abs_variance": _safe_float(
                panel.get("mean_abs_variance")
            ),
            "accuracy_trend": _safe_str(panel.get("accuracy_trend")),
        }
    return {}


def _overall_verdict(
    panels: dict[str, dict[str, Any] | None],
    subsystems: list[dict[str, Any]],
) -> tuple[str, bool, list[str]]:
    """Roll panel severities up into the overall verdict."""
    if not panels:
        return VERDICT_EMPTY, True, []

    verdicts = [
        str(row["verdict"]).upper() for row in subsystems
    ]
    unhealthy = [
        row["key"]
        for row in subsystems
        if not bool(row["healthy"])
    ]
    if VERDICT_CRITICAL in verdicts:
        return VERDICT_CRITICAL, False, unhealthy
    if VERDICT_WATCH in verdicts:
        return VERDICT_WATCH, False, unhealthy
    return VERDICT_HEALTHY, True, []


def _headline(
    panels: dict[str, dict[str, Any] | None],
    subsystems: list[dict[str, Any]],
    verdict: str,
) -> str:
    """Compose a single dashboard headline from the strongest panel."""
    next_action = panels.get("next_action")
    if next_action:
        title = _safe_str(next_action.get("title"))
        if title:
            return title

    health = panels.get("health")
    if health:
        narrative = _safe_str(health.get("narrative"))
        if narrative:
            return narrative

    status = panels.get("status_banner")
    if status:
        status_text = _safe_str(status.get("status"))
        if status_text:
            return f"Project status: {status_text}"

    if verdict == VERDICT_EMPTY:
        return "No project data yet — run a simulation to get insights."
    if verdict == VERDICT_CRITICAL:
        return "Project needs attention — critical signals detected."
    if verdict == VERDICT_WATCH:
        return "Project has watch-level signals — review the panels below."
    return "Project is healthy — all signals clear."


def build_project_overview(
    project_id: int,
    generated_at: str,
    panels: dict[str, dict[str, Any] | None] | None,
) -> dict[str, Any]:
    """Compose the one-call per-project overview payload.

    Args:
        project_id: owning project primary key (echoed back).
        generated_at: ISO-8601 timestamp for the composed payload.
        panels: mapping of panel key -> digest payload (or ``None`` when a
            digest could not be produced). Unknown keys are ignored so a
            future digest can be added without breaking old payloads.

    Returns:
        A dict matching :class:`ProjectOverviewOut` with subsystem rows,
        an overall verdict/headline/narrative, aggregated key signals, and
        the raw panel payloads echoed back.
    """
    supplied = {
        key: value
        for key, value in (panels or {}).items()
        if key in PANEL_LABELS
    }

    subsystems: list[dict[str, Any]] = []
    for key in PANEL_ORDER:
        panel = supplied.get(key)
        severity = _panel_severity(key, panel)
        verdict = (
            VERDICT_CRITICAL
            if severity == SIGNAL_CRITICAL
            else VERDICT_WATCH
            if severity == SIGNAL_WATCH
            else VERDICT_HEALTHY
        )
        subsystems.append({
            "key": key,
            "label": PANEL_LABELS[key],
            "verdict": verdict,
            "healthy": verdict == VERDICT_HEALTHY,
            "summary": _panel_summary(key, panel),
            "headline": _panel_headline(key, panel),
        })

    overall_verdict, healthy, unhealthy = _overall_verdict(
        supplied,
        subsystems,
    )
    headline = _headline(supplied, subsystems, overall_verdict)

    key_signals: list[dict[str, Any]] = []
    for row in subsystems:
        key_signals.append({
            "label": row["key"],
            "value": row["verdict"],
            "severity": (
                SIGNAL_CRITICAL
                if row["verdict"] == VERDICT_CRITICAL
                else SIGNAL_WATCH
                if row["verdict"] == VERDICT_WATCH
                else SIGNAL_OK
            ),
            "display": row["summary"],
        })

    narrative = " | ".join(
        row["summary"]
        for row in subsystems
        if row["summary"] not in {"No data", "Not available"}
    )
    if not narrative:
        narrative = headline

    return {
        "project_id": project_id,
        "generated_at": generated_at,
        "overall_verdict": overall_verdict,
        "healthy": healthy,
        "headline": headline,
        "narrative": narrative,
        "key_signals": key_signals,
        "unhealthy_components": unhealthy,
        "subsystems": subsystems,
        "panels": supplied,
    }


__all__ = [
    "PANEL_LABELS",
    "PANEL_ORDER",
    "SIGNAL_CRITICAL",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "VERDICT_CRITICAL",
    "VERDICT_EMPTY",
    "VERDICT_HEALTHY",
    "VERDICT_WATCH",
    "build_project_overview",
]
