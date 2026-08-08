"""Pure helpers for the project comparison endpoint.

The route ``POST /api/v1/projects/compare`` accepts exactly two owned
project IDs and returns a side-by-side view across health, funnel,
assumptions, outcomes, and risk signals. Keeping the composition pure
(no SQL, no I/O) makes the math verifiable in tests.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.schemas.project_comparison import (
    ComparisonProjectRef,
    ProjectComparisonDimension,
    ProjectComparisonOut,
    ProjectComparisonSummary,
)

_DIMENSIONS: tuple[tuple[str, str, bool, str], ...] = (
    ("brief_completed", "Brief completed", True, "bool"),
    ("assumption_count", "Assumptions", True, "int"),
    ("simulation_count", "Simulations run", True, "int"),
    ("latest_conversion_rate", "Latest predicted conversion", True, "pct2"),
    ("latest_confidence_score", "Latest sim confidence", True, "pct1"),
    ("outcome_count", "Outcomes recorded", True, "int"),
    ("critical_finding_count", "Critical findings", False, "int"),
    ("pending_decision_count", "Pending decisions", False, "int"),
    ("weak_link_count", "Weak-link assumptions", False, "int"),
    ("project_health_score", "Project health", True, "int"),
)


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return default


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _display_value(value: Any, kind: str) -> str:
    if value is None:
        return "—"
    if kind == "bool":
        return "yes" if bool(value) else "no"
    if kind == "pct2":
        return f"{float(value) * 100:.2f}%"
    if kind == "pct1":
        return f"{float(value) * 100:.1f}%"
    return str(value)


def _winner_for(a: Any, b: Any, higher_is_better: bool) -> str:
    if a is None and b is None:
        return "TIE"
    if a is None:
        return "B"
    if b is None:
        return "A"
    if a == b:
        return "TIE"
    if a > b:
        return "A" if higher_is_better else "B"
    return "B" if higher_is_better else "A"


def _ref(row: dict[str, Any]) -> ComparisonProjectRef:
    return ComparisonProjectRef(
        project_id=_safe_int(row.get("project_id")),
        title=str(row.get("title") or ""),
        status=str(row.get("status") or "DRAFT"),
        health_score=_safe_int(row.get("project_health_score")),
        health_verdict=str(row.get("project_health_verdict") or "AT_RISK"),
        simulation_count=_safe_int(row.get("simulation_count")),
        latest_conversion_rate=_safe_float(row.get("latest_conversion_rate")),
        latest_confidence_score=_safe_float(
            row.get("latest_confidence_score"),
        ),
        assumption_count=_safe_int(row.get("assumption_count")),
        outcome_count=_safe_int(row.get("outcome_count")),
        pending_decision_count=_safe_int(row.get("pending_decision_count")),
        critical_finding_count=_safe_int(row.get("critical_finding_count")),
        weak_link_count=_safe_int(row.get("weak_link_count")),
        brief_completed=bool(row.get("brief_completed")),
        primary_failure_domain=(
            str(row["primary_failure_domain"])
            if row.get("primary_failure_domain") is not None
            else None
        ),
        product_type_detected=(
            str(row["product_type_detected"])
            if row.get("product_type_detected") is not None
            else None
        ),
    )


def normalise_confidence_score(value: Any) -> float | None:
    """Normalise a confidence value to the 0..1 scale.

    ``Simulation.confidence_score`` is persisted as 0..1, while
    ``results_json.aggregated.confidence_score`` is stored as a 0..100
    integer.  This helper accepts either scale (plus numeric strings)
    and returns a clamped 0..1 float, or ``None`` for missing/unusable
    values.
    """
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score > 1:
        score = score / 100.0
    return max(0.0, min(1.0, score))


def _summary_block(
    a: dict[str, Any],
    b: dict[str, Any],
    dims: list[ProjectComparisonDimension],
) -> ProjectComparisonSummary:
    health_a = _safe_int(a.get("project_health_score"))
    health_b = _safe_int(b.get("project_health_score"))
    cr_a = _safe_float(a.get("latest_conversion_rate"))
    cr_b = _safe_float(b.get("latest_conversion_rate"))

    if health_a > health_b:
        winner_label = "A"
        winner_id = _safe_int(a.get("project_id"))
    elif health_b > health_a:
        winner_label = "B"
        winner_id = _safe_int(b.get("project_id"))
    elif cr_a is not None and cr_b is not None and cr_a != cr_b:
        winner_label = "A" if cr_a > cr_b else "B"
        winner_id = (
            _safe_int(a.get("project_id"))
            if winner_label == "A"
            else _safe_int(b.get("project_id"))
        )
    else:
        winner_label = "TIE"
        winner_id = None

    if winner_label == "A":
        verdict = "A_LEADS"
    elif winner_label == "B":
        verdict = "B_LEADS"
    else:
        verdict = "TIE"

    a_wins = sum(1 for d in dims if d.winner == "A")
    b_wins = sum(1 for d in dims if d.winner == "B")

    sentences: list[str] = []
    if winner_label != "TIE":
        sentences.append(
            f"Project {winner_label} leads on project health "
            f"({health_a} vs {health_b})."
        )
    else:
        sentences.append(
            "Both projects score the same on project health "
            f"({health_a}); compare the dimension rows below."
        )
    if cr_a is not None and cr_b is not None and cr_a != cr_b:
        lead = "A" if cr_a > cr_b else "B"
        sentences.append(
            f"Predicted conversion favours {lead} "
            f"({cr_a * 100:.2f}% vs {cr_b * 100:.2f}%)."
        )
    if a_wins or b_wins:
        sentences.append(
            f"{a_wins} dimension(s) favour A and "
            f"{b_wins} dimension(s) favour B."
        )

    narrative = " ".join(sentences).strip()
    key_signals: list[dict[str, Any]] = [
        {
            "label": "winner",
            "value": winner_label,
            "severity": "ok" if winner_label != "TIE" else "watch",
            "display": (
                f"Overall leader: Project {winner_label}"
                if winner_label != "TIE"
                else "No overall leader"
            ),
        },
        {
            "label": "health_a",
            "value": health_a,
            "severity": "ok" if health_a >= 70 else "watch",
            "display": f"A health: {health_a}",
        },
        {
            "label": "health_b",
            "value": health_b,
            "severity": "ok" if health_b >= 70 else "watch",
            "display": f"B health: {health_b}",
        },
        {
            "label": "dimensions_favour_a",
            "value": a_wins,
            "severity": "ok",
            "display": f"{a_wins} dimension(s) favour A",
        },
        {
            "label": "dimensions_favour_b",
            "value": b_wins,
            "severity": "ok",
            "display": f"{b_wins} dimension(s) favour B",
        },
    ]

    return ProjectComparisonSummary(
        winner_project_id=winner_id,
        winner_label=winner_label,
        verdict=verdict,
        narrative=narrative,
        key_signals=key_signals,
    )


def build_project_comparison(
    project_rows: list[dict[str, Any]],
) -> ProjectComparisonOut:
    """Build a ProjectComparisonOut from exactly two project snapshots.

    Each snapshot should contain at minimum:
        - project_id, title, status
        - simulation_count, assumption_count, outcome_count
        - pending_decision_count, critical_finding_count, weak_link_count
        - latest_conversion_rate, latest_confidence_score
        - project_health_score, project_health_verdict
        - brief_completed
    """
    if len(project_rows) != 2:
        raise ValueError("Exactly two projects are required for comparison")

    a = dict(project_rows[0])
    b = dict(project_rows[1])

    refs = [_ref(a), _ref(b)]
    dims: list[ProjectComparisonDimension] = []
    for key, label, higher_better, kind in _DIMENSIONS:
        va = a.get(key)
        vb = b.get(key)
        dims.append(
            ProjectComparisonDimension(
                dimension=key,
                label=label,
                higher_is_better=higher_better,
                a=va,
                b=vb,
                winner=_winner_for(va, vb, higher_better),
                display_a=_display_value(va, kind),
                display_b=_display_value(vb, kind),
            )
        )

    return ProjectComparisonOut(
        comparison_id=str(uuid.uuid4())[:8],
        projects=refs,
        dimensions=dims,
        summary=_summary_block(a, b, dims),
        generated_at=datetime.now(UTC).isoformat(),
    )


__all__ = ["build_project_comparison", "normalise_confidence_score"]
