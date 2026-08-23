"""
Evidence-quality grader: score how much each logged record deserves trust.

The evidence-verdicts scorecard reports what each record *says* (PASS,
FAIL, on track, killed); this module grades how trustworthy the records
are. Every experiment row gets a deterministic 0..1 quality score:

* **Method reliability** — a concierge MVP or pre-order test observes real
  commitment and outranks surveys; desk research is the weakest signal.
* **Decisiveness** — PASS/FAIL rows are fully decisive; INCONCLUSIVE rows
  carry little weight.
* **Metric presence** — a record without an ``observed_metric`` cannot be
  re-checked, so it is graded down.
* **Recency** — evidence decays from full weight at 30 days to half at 90.

Assumption quality blends the latest row (60% when history exists) with
the mean of older rows; project index is the mean across tested
assumptions. The weakest link names where trust in the validation story
is thinnest.

No I/O — the route layer resolves assumptions and evidence rows and calls
:func:`build_evidence_quality`.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

# Evidential weight per method: observed commitment outranks stated intent.
_METHOD_RELIABILITY: dict[str, float] = {
    "CONCIERGE_MVP": 1.00,
    "PRE_ORDER_WAITLIST": 0.95,
    "PAID_ACQUISITION_TEST": 0.90,
    "PROTOTYPE_USABILITY_TEST": 0.85,
    "LANDING_PAGE_SMOKE_TEST": 0.75,
    "WILLINGNESS_TO_PAY_SURVEY": 0.55,
    "USER_INTERVIEWS": 0.50,
    "COMPETITIVE_DESK_RESEARCH": 0.35,
}
_UNKNOWN_METHOD_RELIABILITY = 0.30

_RESULT_DECISIVENESS = {"PASS": 1.00, "FAIL": 1.00, "INCONCLUSIVE": 0.30}

_FRESH_DAYS = 30
_OLD_DAYS = 90
_OLD_FLOOR = 0.50

_NO_METRIC_PENALTY = 0.60

_HIGH_CUTOFF = 0.70
_MEDIUM_CUTOFF = 0.45


def _label(value: float) -> str:
    if value >= _HIGH_CUTOFF:
        return "HIGH"
    if value >= _MEDIUM_CUTOFF:
        return "MEDIUM"
    return "LOW"


def _reliability(method: str) -> float:
    return _METHOD_RELIABILITY.get(
        str(method or ""), _UNKNOWN_METHOD_RELIABILITY
    )


def _recency_factor(created_at: Any, now: datetime) -> float:
    """1.0 when fresh, linear decay to ``_OLD_FLOOR`` at 90 days."""
    if not hasattr(created_at, "tzinfo") or created_at is None:
        return 1.0  # unknown age — do not punish the row twice
    created = created_at if created_at.tzinfo else created_at.replace(
        tzinfo=UTC
    )
    days = max(0, (now - created).days)
    if days <= _FRESH_DAYS:
        return 1.0
    if days >= _OLD_DAYS:
        return _OLD_FLOOR
    span = _OLD_DAYS - _FRESH_DAYS
    return round(1.0 - (1.0 - _OLD_FLOOR) * (days - _FRESH_DAYS) / span, 4)


def _row_quality(row: Any, now: datetime) -> tuple[float, list[str]]:
    """Quality for one evidence row plus its limiting reasons."""
    method = str(getattr(row, "method", "") or "")
    result = str(getattr(row, "result", "") or "").upper()
    observed = getattr(row, "observed_metric", None)

    reliability = _reliability(method)
    decisiveness = _RESULT_DECISIVENESS.get(result, 0.20)
    metric_factor = 1.0 if observed is not None else _NO_METRIC_PENALTY
    recency = _recency_factor(getattr(row, "created_at", None), now)

    reasons: list[str] = []
    if reliability <= 0.55:
        pretty = method.replace("_", " ").title() or "Unknown method"
        if method in ("WILLINGNESS_TO_PAY_SURVEY", "USER_INTERVIEWS"):
            reasons.append(
                f"{pretty} carries low evidential weight (stated intent, "
                "not observed commitment)"
            )
        else:
            reasons.append(f"{pretty} is indirect evidence")
    if result == "INCONCLUSIVE":
        reasons.append("Latest run was INCONCLUSIVE")
    elif result not in ("PASS", "FAIL"):
        reasons.append(f"Unrecognised result {result!r}")
    if observed is None:
        reasons.append("No observed_metric recorded, so the call cannot "
                       "be re-checked")
    age_days = None
    created_at = getattr(row, "created_at", None)
    if hasattr(created_at, "tzinfo") and created_at is not None:
        created = (
            created_at
            if created_at.tzinfo
            else created_at.replace(tzinfo=UTC)
        )
        age_days = max(0, (now - created).days)
        if recency < 1.0:
            reasons.append(f"Evidence is {age_days}d old")

    quality = round(reliability * decisiveness * metric_factor * recency, 4)
    return quality, reasons


def build_evidence_quality(
    *,
    project_id: int,
    assumptions: list[Any],
    evidence: list[Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Grade every tested assumption's evidence quality; untested assumptions
    are counted but not graded. Returns a dict matching
    ``EvidenceQualityOut``.
    """
    now = now or datetime.now(UTC)

    by_assumption: dict[int, list[tuple[tuple[int, Any], Any]]] = {}
    for row in evidence:
        key = int(getattr(row, "assumption_id", 0) or 0)
        bucket = by_assumption.setdefault(key, [])
        bucket.append(((getattr(row, "id", 0) or 0), row))

    rows_out: list[dict[str, Any]] = []
    labels = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}

    for assumption in assumptions:
        assumption_id = int(getattr(assumption, "id", 0) or 0)
        history = sorted(
            by_assumption.get(assumption_id, []), key=lambda p: p[0]
        )  # oldest first so [-1] is latest
        if not history:
            continue

        graded = [_row_quality(row, now) for _, row in history]
        latest_quality, latest_reasons = graded[-1]
        older = [q for q, _ in graded[:-1]]
        if older:
            quality = round(0.6 * latest_quality + 0.4 * (sum(older) / len(older)), 4)
        else:
            quality = latest_quality
        label = _label(quality)

        latest_row = history[-1][1]
        latest_method = str(getattr(latest_row, "method", "") or "") or None
        created_at = getattr(latest_row, "created_at", None)
        age_days = None
        if hasattr(created_at, "tzinfo") and created_at is not None:
            created = (
                created_at
                if created_at.tzinfo
                else created_at.replace(tzinfo=UTC)
            )
            age_days = max(0, (now - created).days)

        rows_out.append(
            {
                "assumption_id": assumption_id,
                "assumption_text": getattr(assumption, "text", "") or "",
                "category": getattr(assumption, "category", None),
                "evidence_count": len(history),
                "latest_method": latest_method,
                "latest_method_reliability": _reliability(
                    latest_method or ""
                ),
                "latest_result": str(
                    getattr(latest_row, "result", "") or ""
                ).upper()
                or None,
                "latest_age_days": age_days,
                "quality": quality,
                "quality_label": label,
                "reasons": latest_reasons,
            }
        )
        labels[label] += 1

    # Lowest-quality first; ties broken by more evidence, then id.
    rows_out.sort(key=lambda r: (r["quality"], -r["evidence_count"], r["assumption_id"]))

    tested = len(rows_out)
    index = (
        round(sum(r["quality"] for r in rows_out) / tested, 4)
        if tested
        else None
    )

    weakest_link = None
    if rows_out:
        worst = rows_out[0]
        weakest_link = {
            "assumption_id": worst["assumption_id"],
            "assumption_text": worst["assumption_text"],
            "quality": worst["quality"],
            "quality_label": worst["quality_label"],
            "reason": (
                "; ".join(worst["reasons"]) if worst["reasons"] else ""
            ),
        }

    total = int(len(assumptions))
    untested = total - tested
    if tested == 0:
        narrative = (
            "No experiments logged yet — quality grading starts with the "
            "first one."
        )
    else:
        weak = weakest_link["assumption_text"] if weakest_link else ""
        head = f"Project evidence quality is {index:.2f} ({_label(index)})." if index is not None else ""
        tail = (
            f" Thinnest evidence: “{weak}”." if weak else ""
        )
        narrative = f"{head}{tail}"

    return {
        "project_id": project_id,
        "total_assumptions": total,
        "tested_count": tested,
        "untested_count": max(untested, 0),
        "high_count": labels["HIGH"],
        "medium_count": labels["MEDIUM"],
        "low_count": labels["LOW"],
        "evidence_quality_index": index,
        "index_label": _label(index) if index is not None else None,
        "weakest_link": weakest_link,
        "rows": rows_out,
        "narrative": narrative,
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "model": "evidence_quality_v1",
            "method_reliability": dict(_METHOD_RELIABILITY),
            "blend_rule": (
                "latest row 60% + mean of older rows 40% when history "
                "exists; factors: method reliability × decisiveness × "
                "metric presence × recency"
            ),
            "fresh_days": _FRESH_DAYS,
            "old_days": _OLD_DAYS,
        },
    }


__all__ = [
    "build_evidence_quality",
]
