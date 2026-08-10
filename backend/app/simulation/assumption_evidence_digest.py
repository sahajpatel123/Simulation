"""Project-level rollup of logged validation experiments.

The per-assumption evidence scorecard shows a founder what one claim's
experiments proved. This digest answers the portfolio question: *how much of
the project's risk has actually been validated?* It rolls every logged
experiment up into coverage, de-risked / challenged / pending counts,
result and method histograms, and the highest-leverage experiments left to
run.

The digest is deliberately simulation-independent — a founder can track
validation progress before the first simulation finishes, and a corrupt or
missing ``results_json`` can never break the summary.

Legacy rows are normalised before they hit the summary: result casing is
canonicalised (``" pass "`` counts as ``PASS``), known method IDs are
canonicalised to their schema spelling, and unrecognised result values are
surfaced under an ``OTHER`` bucket so ``result_counts`` always reconciles
with ``total_evidence_rows``.

Pure module (no DB, no I/O): the route passes already-loaded assumption and
evidence rows, so the digest is deterministic and easy to test.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any, Mapping

from app.simulation.evidence_scorecard import (
    DECISIVE_RESULTS,
    EVIDENCE_RESULT_FAIL,
    EVIDENCE_RESULT_INCONCLUSIVE,
    EVIDENCE_RESULT_PASS,
    derive_confidence,
)
from app.simulation.validation_experiment_planner import METHOD_SPECS

# Per-assumption status labels surfaced to the founder.
STATUS_DE_RISKED: str = "DE_RISKED"
STATUS_CHALLENGED: str = "CHALLENGED"
STATUS_INCONCLUSIVE: str = "INCONCLUSIVE"
STATUS_PENDING: str = "PENDING"

# Bucket for legacy/unrecognised result values so the histogram stays
# reconciled with total_evidence_rows.
RESULT_OTHER: str = "OTHER"

# Cap for the top-pending / top-challenged sub-lists.
TOP_N: int = 5

DIGEST_MODEL: str = "assumption_evidence_digest_v1"

# Sensitivity ranking used to surface the highest-leverage experiments.
_SENSITIVITY_RANK: dict[str, int] = {
    "CRITICAL": 3,
    "HIGH": 2,
    "MEDIUM": 1,
    "LOW": 0,
}

# Status priority for the full assumption list: challenged first, then
# evidence-gaps, then de-risked claims.
_STATUS_RANK: dict[str, int] = {
    STATUS_CHALLENGED: 0,
    STATUS_PENDING: 1,
    STATUS_INCONCLUSIVE: 2,
    STATUS_DE_RISKED: 3,
}

NEXT_ACTION_NO_ASSUMPTIONS: str = (
    "No visible assumptions to de-risk yet — extract assumptions from the "
    "project description first."
)
NEXT_ACTION_NO_EVIDENCE: str = (
    "No validation experiments logged yet — use the validation-experiment "
    "plan to run your first test."
)
NEXT_ACTION_CHALLENGED: str = (
    "Challenged assumption(s) are the highest risk — rework or replace them "
    "before building."
)
NEXT_ACTION_PENDING: str = (
    "Assumption(s) still need decisive evidence — continue running the "
    "planned validation experiments."
)
NEXT_ACTION_INCONCLUSIVE: str = (
    "Inconclusive experiment(s) need more signal — rerun with a larger "
    "sample or a different method."
)
NEXT_ACTION_ALL_DE_RISKED: str = (
    "All visible assumptions are de-risked — record new evidence as the "
    "product evolves."
)


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


def _row_value(row: Any, name: str, default: Any = None) -> Any:
    """Read a field from an ORM row, SimpleNamespace, or plain dict."""
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def _normalise_result(value: Any) -> str:
    return _safe_text(value).strip().upper()


def _normalise_method(value: Any) -> str:
    """Trim a method and canonicalise known IDs to their schema spelling."""
    method = _safe_text(value).strip()
    upper = method.upper()
    return upper if upper in METHOD_SPECS else method


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


def _evidence_sort_key(row: Any) -> tuple[datetime, int]:
    return (
        _timestamp_key(_row_value(row, "created_at")),
        _safe_int(_row_value(row, "id")),
    )


def _assumption_def(assumption: Any) -> dict[str, Any]:
    """Normalise one assumption row into the digest item fields."""
    return {
        "assumption_id": _safe_int(_row_value(assumption, "id")),
        "assumption_text": _safe_text(_row_value(assumption, "text")),
        "category": _row_value(assumption, "category"),
        "sensitivity": _safe_text(
            _row_value(assumption, "sensitivity"), "MEDIUM"
        ),
    }


def _sensitivity_rank(sensitivity: str) -> int:
    return _SENSITIVITY_RANK.get(
        _safe_text(sensitivity).strip().upper(), 1
    )


def _latest_decisive(
    history: list[Any],
) -> Any | None:
    """Most recent PASS/FAIL in an evidence history (newest first)."""
    for row in history:
        if _normalise_result(_row_value(row, "result")) in DECISIVE_RESULTS:
            return row
    return None


def _assumption_status(
    *,
    history: list[Any],
    decisive: Any | None,
) -> str:
    if decisive is None:
        return STATUS_INCONCLUSIVE if history else STATUS_PENDING
    if _normalise_result(_row_value(decisive, "result")) == EVIDENCE_RESULT_PASS:
        return STATUS_DE_RISKED
    if _normalise_result(_row_value(decisive, "result")) == EVIDENCE_RESULT_FAIL:
        return STATUS_CHALLENGED
    return STATUS_INCONCLUSIVE


def _group_evidence(evidence: list[Any]) -> dict[int, list[Any]]:
    """Group evidence rows by assumption id, each group newest-first."""
    groups: dict[int, list[Any]] = {}
    for row in evidence or []:
        assumption_id = _safe_int(_row_value(row, "assumption_id"))
        if assumption_id <= 0:
            continue
        groups.setdefault(assumption_id, []).append(row)
    for assumption_id in groups:
        groups[assumption_id].sort(
            key=_evidence_sort_key,
            reverse=True,
        )
    return groups


def build_assumption_evidence_digest(
    *,
    assumptions: list[Any],
    evidence: list[Any],
    project_id: int,
) -> dict[str, Any]:
    """Build the project-level validation-evidence digest.

    Args:
        assumptions: every visible ``Assumption`` row for the project (any
            order; the digest sorts its own output).
        evidence: every ``AssumptionEvidence`` row for the project (any
            order; rows are grouped and sorted per assumption).
        project_id: owning project, echoed back for client routing.

    Returns:
        Dict matching :class:`AssumptionEvidenceDigestOut`.
    """
    grouped = _group_evidence(evidence)
    rows: list[dict[str, Any]] = []

    result_counts: dict[str, int] = {
        EVIDENCE_RESULT_PASS: 0,
        EVIDENCE_RESULT_FAIL: 0,
        EVIDENCE_RESULT_INCONCLUSIVE: 0,
    }
    method_counter: Counter[str] = Counter()
    total_evidence_rows = 0

    for assumption in assumptions or []:
        definition = _assumption_def(assumption)
        assumption_id = int(definition["assumption_id"])
        history = grouped.get(assumption_id, [])
        decisive = _latest_decisive(history)
        status = _assumption_status(history=history, decisive=decisive)
        derived = (
            derive_confidence(_row_value(decisive, "result"))
            if decisive is not None
            else None
        )
        rows.append(
            {
                **definition,
                "evidence_count": len(history),
                "latest_result": (
                    _normalise_result(_row_value(history[0], "result"))
                    if history
                    else None
                ),
                "derived_confidence": (
                    derived.value if derived is not None else None
                ),
                "status": status,
            }
        )

        total_evidence_rows += len(history)
        for row in history:
            result = _normalise_result(_row_value(row, "result"))
            if result in result_counts:
                result_counts[result] += 1
            else:
                result_counts[RESULT_OTHER] = result_counts.get(RESULT_OTHER, 0) + 1
            method = _normalise_method(_row_value(row, "method"))
            if method:
                method_counter[method] += 1

    total_assumptions = len(rows)
    de_risked = sum(1 for row in rows if row["status"] == STATUS_DE_RISKED)
    challenged = sum(
        1 for row in rows if row["status"] == STATUS_CHALLENGED
    )
    inconclusive = sum(
        1 for row in rows if row["status"] == STATUS_INCONCLUSIVE
    )
    pending = sum(1 for row in rows if row["status"] == STATUS_PENDING)
    assumptions_with_evidence = sum(
        1 for row in rows if row["evidence_count"] > 0
    )

    rows.sort(
        key=lambda row: (
            -_sensitivity_rank(row["sensitivity"]),
            _STATUS_RANK.get(row["status"], 9),
            row["assumption_id"],
        )
    )

    top_pending = sorted(
        (row for row in rows if row["status"] in {STATUS_PENDING, STATUS_INCONCLUSIVE}),
        key=lambda row: (
            -_sensitivity_rank(row["sensitivity"]),
            row["evidence_count"],
            row["assumption_id"],
        ),
    )[:TOP_N]
    top_challenged = sorted(
        (row for row in rows if row["status"] == STATUS_CHALLENGED),
        key=lambda row: (
            -_sensitivity_rank(row["sensitivity"]),
            -row["evidence_count"],
            row["assumption_id"],
        ),
    )[:TOP_N]

    if total_assumptions == 0:
        next_action = NEXT_ACTION_NO_ASSUMPTIONS
    elif total_evidence_rows == 0:
        next_action = NEXT_ACTION_NO_EVIDENCE
    elif challenged > 0:
        next_action = NEXT_ACTION_CHALLENGED
    elif pending > 0:
        next_action = NEXT_ACTION_PENDING
    elif inconclusive > 0:
        next_action = NEXT_ACTION_INCONCLUSIVE
    else:
        next_action = NEXT_ACTION_ALL_DE_RISKED

    return {
        "project_id": _safe_int(project_id),
        "total_assumptions": total_assumptions,
        "total_evidence_rows": total_evidence_rows,
        "assumptions_with_evidence": assumptions_with_evidence,
        "evidence_coverage_pct": (
            round(assumptions_with_evidence / total_assumptions, 4)
            if total_assumptions > 0
            else None
        ),
        "de_risked_count": de_risked,
        "challenged_count": challenged,
        "inconclusive_count": inconclusive,
        "pending_count": pending,
        "validation_score": (
            round(de_risked / total_assumptions, 4)
            if total_assumptions > 0
            else None
        ),
        "result_counts": result_counts,
        "method_counts": dict(
            sorted(
                method_counter.items(),
                key=lambda pair: (-pair[1], pair[0]),
            )
        ),
        "top_pending": top_pending,
        "top_challenged": top_challenged,
        "assumptions": rows,
        "next_action": next_action,
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "model": DIGEST_MODEL,
            "status_labels": {
                STATUS_DE_RISKED: "latest decisive experiment PASSED",
                STATUS_CHALLENGED: "latest decisive experiment FAILED",
                STATUS_INCONCLUSIVE: "has evidence but no decisive PASS/FAIL",
                STATUS_PENDING: "no logged evidence",
            },
            "decisive_result_policy": (
                "most recent PASS/FAIL wins; INCONCLUSIVE is ignored"
            ),
            "result_counting_policy": (
                "PASS/FAIL/INCONCLUSIVE counted under canonical keys; "
                "unrecognised legacy results aggregate under OTHER"
            ),
        },
    }


__all__ = [
    "STATUS_DE_RISKED",
    "STATUS_CHALLENGED",
    "STATUS_INCONCLUSIVE",
    "STATUS_PENDING",
    "RESULT_OTHER",
    "TOP_N",
    "DIGEST_MODEL",
    "build_assumption_evidence_digest",
]
