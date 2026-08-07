"""Tests for the project comparison helper + route."""

from __future__ import annotations

from datetime import datetime, timezone
import sys
import types

import pytest
from pydantic import ValidationError

from app.schemas.project_comparison import ProjectCompareRequest
from app.simulation.project_comparison import (
    build_project_comparison,
    normalise_confidence_score,
)


if "razorpay" not in sys.modules:
    _razorpay_stub = types.ModuleType("razorpay")
    _razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = _razorpay_stub


def _row(
    project_id: int = 1,
    *,
    health_score: int = 70,
    health_verdict: str = "HEALTHY",
    conversion_rate: float | None = 0.04,
    confidence: float | None = 0.6,
    critical: int = 0,
    pending: int = 0,
    weak_links: int = 0,
    brief: bool = True,
) -> dict:
    return {
        "project_id": project_id,
        "title": f"Project {project_id}",
        "status": "ACTIVE",
        "simulation_count": 3,
        "assumption_count": 8,
        "outcome_count": 1,
        "pending_decision_count": pending,
        "critical_finding_count": critical,
        "weak_link_count": weak_links,
        "latest_conversion_rate": conversion_rate,
        "latest_confidence_score": confidence,
        "brief_completed": brief,
        "primary_failure_domain": "pricing",
        "product_type_detected": "saas",
        "project_health_score": health_score,
        "project_health_verdict": health_verdict,
    }


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_compare_request_requires_exactly_two_unique_positive_ids() -> None:
    assert ProjectCompareRequest(project_ids=[3, 7]).project_ids == [3, 7]

    with pytest.raises(ValidationError):
        ProjectCompareRequest(project_ids=[3])
    with pytest.raises(ValidationError):
        ProjectCompareRequest(project_ids=[3, 3])
    with pytest.raises(ValidationError):
        ProjectCompareRequest(project_ids=[0, 3])


# ---------------------------------------------------------------------------
# Pure helper
# ---------------------------------------------------------------------------


def test_build_comparison_returns_dimensions_and_winner() -> None:
    out = build_project_comparison([
        _row(1, health_score=72, conversion_rate=0.04),
        _row(2, health_score=45, conversion_rate=0.03, critical=2),
    ])

    assert out.summary.verdict == "A_LEADS"
    assert out.summary.winner_project_id == 1
    assert out.summary.winner_label == "A"
    assert len(out.projects) == 2
    assert len(out.dimensions) == 10
    assert out.dimensions[0].dimension == "brief_completed"
    assert out.dimensions[-1].dimension == "project_health_score"

    # A has fewer critical findings (0 vs 2), so lower-is-better also favours A.
    critical_row = next(d for d in out.dimensions if d.dimension == "critical_finding_count")
    assert critical_row.winner == "A"
    assert critical_row.display_a == "0"

    conversion_row = next(
        d for d in out.dimensions if d.dimension == "latest_conversion_rate"
    )
    assert conversion_row.winner == "A"
    assert conversion_row.display_a == "4.00%"
    assert "Project A leads on project health (72 vs 45)" in out.summary.narrative


def test_build_comparison_ties_when_health_equal() -> None:
    out = build_project_comparison([
        _row(1, health_score=60, conversion_rate=0.04),
        _row(2, health_score=60, conversion_rate=0.04),
    ])

    assert out.summary.verdict == "TIE"
    assert out.summary.winner_project_id is None
    assert out.summary.winner_label == "TIE"
    assert "Both projects score the same" in out.summary.narrative


def test_build_comparison_uses_conversion_tiebreak_when_health_ties() -> None:
    out = build_project_comparison([
        _row(1, health_score=60, conversion_rate=0.04),
        _row(2, health_score=60, conversion_rate=0.02),
    ])

    assert out.summary.verdict == "A_LEADS"
    assert out.summary.winner_project_id == 1
    assert "favours A" in out.summary.narrative


def test_build_comparison_handles_missing_optional_values() -> None:
    out = build_project_comparison([
        _row(1, conversion_rate=None, confidence=None),
        _row(2, conversion_rate=None, confidence=None),
    ])

    conversion_row = next(
        d for d in out.dimensions if d.dimension == "latest_conversion_rate"
    )
    assert conversion_row.display_a == "—"
    assert conversion_row.winner == "TIE"
    # No conversion sentence because both are None.
    assert "Predicted conversion favours" not in out.summary.narrative


def test_build_comparison_rejects_wrong_row_count() -> None:
    with pytest.raises(ValueError):
        build_project_comparison([_row(1)])
    with pytest.raises(ValueError):
        build_project_comparison([_row(1), _row(2), _row(3)])


def test_normalise_confidence_score_handles_both_scales() -> None:
    assert normalise_confidence_score(None) is None
    assert normalise_confidence_score(0.62) == 0.62
    assert normalise_confidence_score(62) == 0.62
    assert normalise_confidence_score(62.0) == 0.62
    assert normalise_confidence_score("62") == 0.62
    assert normalise_confidence_score("0.4") == 0.4
    assert normalise_confidence_score("not-a-number") is None
    assert normalise_confidence_score(99) == 0.99


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


class _FakeProject:
    def __init__(self, project_id: int) -> None:
        self.id = project_id
        self.title = f"Project {project_id}"
        self.status = "ACTIVE"
        self.brief_completed_at = datetime.now(timezone.utc)


class _FakeSimulation:
    def __init__(self) -> None:
        self.confidence_score = 0.62
        self.results_json = {
            "population_weighted_conversion": 0.04,
            "product_type_detected": "saas",
            "primary_failure_domain": "pricing",
            "domain_findings": [],
        }


class _FakeAssumption:
    def __init__(self) -> None:
        self.id = 1
        self.sensitivity = "HIGH"
        self.specificity_score = 0.9
        self.impact_score = 8.0
        self.is_hidden = False


class _FakeQuery:
    def __init__(self, *, first=None, count=0, all_items=None) -> None:
        self.first_item = first
        self.count_value = count
        self.all_items = all_items if all_items is not None else []

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.first_item

    def count(self):
        return self.count_value

    def all(self):
        return self.all_items


class _FakeSession:
    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Simulation":
            return _FakeQuery(first=_FakeSimulation(), count=2)
        if name == "Assumption":
            return _FakeQuery(count=5, all_items=[_FakeAssumption()])
        if name == "Outcome":
            return _FakeQuery(count=1)
        if name == "Decision":
            return _FakeQuery(count=0)
        return _FakeQuery()


def test_compare_projects_route_builds_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import projects as projects_mod

    monkeypatch.setattr(
        projects_mod,
        "get_owned_project",
        lambda db, user_id, project_id: _FakeProject(project_id),
    )

    out = projects_mod.compare_projects(
        payload=ProjectCompareRequest(project_ids=[1, 2]),
        db=_FakeSession(),
        current_user=type("U", (), {"id": 42})(),
    )

    assert len(out.projects) == 2
    assert len(out.dimensions) == 10
    assert out.summary.winner_label in {"A", "B", "TIE"}
    assert out.projects[0].simulation_count == 2
    assert out.projects[0].outcome_count == 1
    assert out.projects[0].assumption_count == 5
    assert out.projects[0].latest_conversion_rate == 0.04
    assert out.projects[0].latest_confidence_score == 0.62
    assert out.projects[0].brief_completed is True
