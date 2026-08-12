"""Pure helper for the project assumption-validation timeline.

The evidence digest answers "how much of the project's risk has been
validated right now?"; this module answers "when did that happen?" It
replays every logged validation experiment in chronological order and
records, after each event:

* the affected assumption's status (DE_RISKED / CHALLENGED /
  INCONCLUSIVE / PENDING),
* cumulative project counts and the validation score,
* first-occurrence milestones (first evidence, first PASS, first FAIL,
  first inconclusive result).

Status policy matches :mod:`app.simulation.assumption_evidence_digest`:
the most recent decisive PASS/FAIL wins, a trailing INCONCLUSIVE does not
erase an earlier decisive outcome, and unrecognised legacy results count as
non-decisive evidence.

The helper is pure Python (no SQL, no I/O); the route loads assumption and
evidence rows and passes them in, matching the digest's contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping

from app.simulation.assumption_evidence_digest import (
    STATUS_CHALLENGED,
    STATUS_DE_RISKED,
    STATUS_INCONCLUSIVE,
    STATUS_PENDING,
)
from app.simulation.evidence_scorecard import (
    DECISIVE_RESULTS,
    EVIDENCE_RESULT_FAIL,
    EVIDENCE_RESULT_PASS,
    derive_confidence,
)
from app.simulation.validation_experiment_planner import METHOD_SPECS

TIMELINE_MODEL: str = "assumption_validation_timeline_v1"


def _value(row: Any, name: str, default: Any = None) -> Any:
    """Read a field from an ORM row, SimpleNamespace, or plain dict."""
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce to a non-negative int or return ``default``."""
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed > 0 else default


def _safe_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _normalise_result(value: Any) -> str:
    return _safe_text(value).strip().upper()


def _normalise_method(value: Any) -> str:
    """Trim a method and canonicalise known IDs to their schema spelling."""
    method = _safe_text(value).strip()
    upper = method.upper()
    return upper if upper in METHOD_SPECS else method


def _method_label(method: str) -> str:
    spec = METHOD_SPECS.get(method)
    label = spec.get("label") if spec else None
    return _safe_text(label, method)


def _timestamp_key(value: Any) -> datetime:
    """Coerce a created-at value to an aware UTC datetime for sorting."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        candidate = value.strip()
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return datetime.min.replace(tzinfo=UTC)
        return (
            parsed
            if parsed.tzinfo is not None
            else parsed.replace(tzinfo=UTC)
        )
    return datetime.min.replace(tzinfo=UTC)


def _assumption_def(assumption: Any) -> dict[str, Any]:
    """Normalise one assumption row into timeline summary fields."""
    sensitivity = _safe_text(
        _value(assumption, "sensitivity"), "MEDIUM"
    ).strip().upper()
    return {
        "assumption_id": _safe_int(_value(assumption, "id")),
        "assumption_text": _safe_text(_value(assumption, "text")),
        "category": _value(assumption, "category"),
        "sensitivity": sensitivity or "MEDIUM",
        "is_hidden": bool(_value(assumption, "is_hidden", False)),
    }


def _status_for_decisive(result: str) -> str:
    if result == EVIDENCE_RESULT_PASS:
        return STATUS_DE_RISKED
    if result == EVIDENCE_RESULT_FAIL:
        return STATUS_CHALLENGED
    return STATUS_INCONCLUSIVE


def build_validation_timeline(
    *,
    assumptions: list[Any] | None,
    evidence: list[Any] | None,
    project_id: int,
) -> dict[str, Any]:
    """Build the chronological validation-evidence timeline for a project.

    Args:
        assumptions: visible ``Assumption`` rows for the project (any order;
            the helper filters hidden rows itself).
        evidence: every ``AssumptionEvidence`` row for the project (any
            order; rows are sorted chronologically here).
        project_id: owning project, echoed back for client routing.

    Returns:
        Dict matching :class:`AssumptionValidationTimelineOut`.
    """
    definitions = [
        definition
        for definition in (
            _assumption_def(assumption) for assumption in assumptions or []
        )
        if definition["assumption_id"] > 0 and not definition["is_hidden"]
    ]
    assumptions_by_id = {
        definition["assumption_id"]: definition
        for definition in definitions
    }

    events: list[dict[str, Any]] = []
    for row in evidence or []:
        assumption_id = _safe_int(_value(row, "assumption_id"))
        if assumption_id not in assumptions_by_id:
            continue
        events.append({
            "event_id": _safe_int(_value(row, "id")),
            "assumption_id": assumption_id,
            "method": _normalise_method(_value(row, "method")),
            "result": _normalise_result(_value(row, "result")),
            "observed_metric": _value(row, "observed_metric"),
            "notes": _value(row, "notes"),
            "created_at": _value(row, "created_at"),
        })
    events.sort(
        key=lambda event: (
            _timestamp_key(event["created_at"]),
            event["event_id"],
        )
    )

    total_assumptions = len(definitions)
    statuses: dict[int, str] = {
        definition["assumption_id"]: STATUS_PENDING
        for definition in definitions
    }
    status_counts: dict[str, int] = {
        STATUS_DE_RISKED: 0,
        STATUS_CHALLENGED: 0,
        STATUS_INCONCLUSIVE: 0,
        STATUS_PENDING: total_assumptions,
    }
    evidence_counts: dict[int, int] = {
        definition["assumption_id"]: 0
        for definition in definitions
    }
    has_evidence: set[int] = set()
    # Assumption id -> (status from the latest decisive event, event id).
    decisive_status: dict[int, tuple[str, int]] = {}

    timeline_events: list[dict[str, Any]] = []
    progress: list[dict[str, Any]] = []
    event_status_by_id: dict[int, str] = {}
    assumption_events: dict[int, list[int]] = {
        definition["assumption_id"]: []
        for definition in definitions
    }

    first_de_risked_event_id: int | None = None
    first_challenged_event_id: int | None = None
    first_inconclusive_event_id: int | None = None

    for event in events:
        event_id = int(event["event_id"])
        assumption_id = int(event["assumption_id"])
        result = event["result"]
        definition = assumptions_by_id[assumption_id]

        evidence_counts[assumption_id] += 1
        has_evidence.add(assumption_id)
        assumption_events[assumption_id].append(event_id)

        if result in DECISIVE_RESULTS:
            # Events are chronological, so the latest decisive row always
            # wins; the event id breaks same-timestamp ties in the same
            # order used by the sort.
            decisive_status[assumption_id] = (
                _status_for_decisive(result),
                event_id,
            )
        if assumption_id in decisive_status:
            status_after = decisive_status[assumption_id][0]
        else:
            status_after = (
                STATUS_INCONCLUSIVE
                if evidence_counts[assumption_id] > 0
                else STATUS_PENDING
            )
        previous_status = statuses[assumption_id]
        status_counts[previous_status] -= 1
        statuses[assumption_id] = status_after
        status_counts[status_after] += 1
        event_status_by_id[event_id] = status_after

        derived = derive_confidence(result)
        timeline_events.append({
            "event_id": event_id,
            "assumption_id": assumption_id,
            "assumption_text": definition["assumption_text"],
            "category": definition["category"],
            "sensitivity": definition["sensitivity"],
            "method": event["method"],
            "method_label": _method_label(event["method"]),
            "result": result,
            "observed_metric": event["observed_metric"],
            "notes": event["notes"],
            "created_at": event["created_at"],
            "derived_confidence": (
                derived.value if derived is not None else None
            ),
            "status_after": status_after,
        })

        if first_de_risked_event_id is None and status_after == STATUS_DE_RISKED:
            first_de_risked_event_id = event_id
        if first_challenged_event_id is None and status_after == STATUS_CHALLENGED:
            first_challenged_event_id = event_id
        if (
            first_inconclusive_event_id is None
            and status_after == STATUS_INCONCLUSIVE
        ):
            first_inconclusive_event_id = event_id

        de_risked_count = status_counts[STATUS_DE_RISKED]
        challenged_count = status_counts[STATUS_CHALLENGED]
        inconclusive_count = status_counts[STATUS_INCONCLUSIVE]
        pending_count = status_counts[STATUS_PENDING]
        assumptions_with_evidence = len(has_evidence)
        progress.append({
            "event_id": event_id,
            "created_at": event["created_at"],
            "evidence_rows": len(timeline_events),
            "assumptions_with_evidence": assumptions_with_evidence,
            "de_risked_count": de_risked_count,
            "challenged_count": challenged_count,
            "inconclusive_count": inconclusive_count,
            "pending_count": pending_count,
            "validation_score": (
                round(de_risked_count / total_assumptions, 4)
                if total_assumptions > 0
                else None
            ),
            "evidence_coverage_pct": (
                round(assumptions_with_evidence / total_assumptions, 4)
                if total_assumptions > 0
                else None
            ),
        })

    assumption_rows: list[dict[str, Any]] = []
    for definition in definitions:
        assumption_id = int(definition["assumption_id"])
        history = assumption_events[assumption_id]
        first_de_risked = next(
            (
                event_id
                for event_id in history
                if event_status_by_id.get(event_id) == STATUS_DE_RISKED
            ),
            None,
        )
        first_challenged = next(
            (
                event_id
                for event_id in history
                if event_status_by_id.get(event_id) == STATUS_CHALLENGED
            ),
            None,
        )
        assumption_rows.append({
            "assumption_id": assumption_id,
            "assumption_text": definition["assumption_text"],
            "category": definition["category"],
            "sensitivity": definition["sensitivity"],
            "evidence_count": evidence_counts[assumption_id],
            "status": statuses[assumption_id],
            "first_evidence_event_id": history[0] if history else None,
            "latest_evidence_event_id": history[-1] if history else None,
            "first_de_risked_event_id": first_de_risked,
            "first_challenged_event_id": first_challenged,
        })

    return {
        "project_id": _safe_int(project_id),
        "total_assumptions": total_assumptions,
        "total_evidence_rows": len(timeline_events),
        "events": timeline_events,
        "progress": progress,
        "assumptions": assumption_rows,
        "milestones": {
            "first_evidence_event_id": (
                timeline_events[0]["event_id"] if timeline_events else None
            ),
            "last_evidence_event_id": (
                timeline_events[-1]["event_id"] if timeline_events else None
            ),
            "first_de_risked_event_id": first_de_risked_event_id,
            "first_challenged_event_id": first_challenged_event_id,
            "first_inconclusive_event_id": first_inconclusive_event_id,
        },
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "model": TIMELINE_MODEL,
            "status_labels": {
                STATUS_DE_RISKED: "latest decisive experiment PASSED",
                STATUS_CHALLENGED: "latest decisive experiment FAILED",
                STATUS_INCONCLUSIVE: (
                    "has evidence but no decisive PASS/FAIL"
                ),
                STATUS_PENDING: "no logged evidence",
            },
            "decisive_result_policy": (
                "most recent PASS/FAIL wins; INCONCLUSIVE is ignored"
            ),
            "sort_policy": "created_at ascending, event id ascending",
            "milestone_policy": (
                "first_de_risked/challenged = first event after which the "
                "affected assumption entered that state; first_inconclusive "
                "= first event after which the affected assumption's status "
                "was inconclusive"
            ),
            "orphan_evidence_policy": (
                "evidence for unknown/hidden assumptions is excluded"
            ),
        },
    }


__all__ = [
    "TIMELINE_MODEL",
    "build_validation_timeline",
]
