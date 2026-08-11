"""Route-level tests for ``GET /projects/{id}/prediction-range-coverage``."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _FakeProject:
    def __init__(self, project_id: int) -> None:
        self.id = project_id


class _FakeOutcome:
    def __init__(
        self,
        *,
        outcome_id: int,
        project_id: int,
        simulation_id: int | None,
        predicted: float,
        actual: float,
        created_at: str,
    ) -> None:
        self.id = outcome_id
        self.project_id = project_id
        self.simulation_id = simulation_id
        self.predicted_conversion_rate = predicted
        self.actual_conversion_rate = actual
        self.created_at = created_at


class _FakeQuery:
    def __init__(self, items: list[Any] | None = None) -> None:
        self.items = items if items is not None else []

    def join(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def filter(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def order_by(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def first(self) -> Any:
        return self.items[0] if self.items else None

    def all(self) -> list[Any]:
        return self.items


class _FakeSession:
    def __init__(
        self,
        *,
        owned_project_ids: list[int] | None = None,
        outcomes: list[_FakeOutcome] | None = None,
    ) -> None:
        self.owned_project_ids = owned_project_ids or [7]
        self.outcomes = outcomes or []

    def query(self, model: Any, *args: Any, **kwargs: Any) -> _FakeQuery:
        if isinstance(model, type) and model.__name__ == "Outcome":
            return _FakeQuery(self.outcomes)
        if getattr(model, "class_", None) is not None:
            class_name = getattr(model.class_, "__name__", "")
            if class_name == "Project":
                return _FakeQuery(
                    [(project_id,) for project_id in self.owned_project_ids]
                )
        if isinstance(model, type) and model.__name__ == "Project":
            return _FakeQuery([_FakeProject(self.owned_project_ids[0])])
        return _FakeQuery()


def _outcomes() -> list[_FakeOutcome]:
    actuals = [0.09, 0.11, 0.09, 0.11, 0.09, 0.11]
    return [
        _FakeOutcome(
            outcome_id=index + 1,
            project_id=7,
            simulation_id=index + 1,
            predicted=0.10,
            actual=actual,
            created_at=f"2026-01-{index + 1:02d}T00:00:00+00:00",
        )
        for index, actual in enumerate(actuals)
    ]


def _call_route(
    *,
    project_id: int = 7,
    current_user_id: int = 42,
    session: _FakeSession | None = None,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    from app.api.v1 import projects as projects_mod

    monkeypatch.setattr(
        projects_mod,
        "get_owned_project",
        lambda db, user_id, pid: _FakeProject(pid),
    )
    return projects_mod.get_prediction_range_coverage(
        project_id=project_id,
        db=session or _FakeSession(outcomes=_outcomes()),
        current_user=type("U", (), {"id": current_user_id})(),
    )


def test_route_returns_coverage_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = _call_route(monkeypatch=monkeypatch)

    assert out.project_id == 7
    assert out.total_project_outcomes == 6
    assert out.evaluated_runs == 3
    assert out.within_range_count == 3
    assert out.coverage_rate == pytest.approx(1.0)
    assert out.verdict == "WELL_CALIBRATED"
    assert len(out.rows) == 6
    assert any(signal.label == "coverage_rate" for signal in out.key_signals)


def test_route_handles_empty_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = _call_route(
        monkeypatch=monkeypatch,
        session=_FakeSession(outcomes=[]),
    )

    assert out.total_project_outcomes == 0
    assert out.evaluated_runs == 0
    assert out.verdict == "INSUFFICIENT_DATA"


def test_route_scopes_history_to_owned_projects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    others = [
        _FakeOutcome(
            outcome_id=index,
            project_id=99,
            simulation_id=index,
            predicted=0.10,
            actual=0.09,
            created_at=f"2026-01-0{index}T00:00:00+00:00",
        )
        for index in range(1, 4)
    ]
    target = _FakeOutcome(
        outcome_id=4,
        project_id=7,
        simulation_id=4,
        predicted=0.10,
        actual=0.11,
        created_at="2026-01-04T00:00:00+00:00",
    )
    # Only one owned project (7), so the other-project row is not loaded.
    out = _call_route(
        monkeypatch=monkeypatch,
        session=_FakeSession(
            owned_project_ids=[7],
            outcomes=[target],
        ),
    )
    assert out.total_project_outcomes == 1
    assert out.evaluated_runs == 0

    # With both projects owned, the earlier row becomes user-pool history.
    out2 = _call_route(
        monkeypatch=monkeypatch,
        session=_FakeSession(
            owned_project_ids=[7, 99],
            outcomes=[*others, target],
        ),
    )
    assert out2.total_project_outcomes == 1
    assert out2.evaluated_runs == 1
    assert out2.rows[0].calibration_source == "user"


def test_route_passes_schema_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.schemas.prediction_range_coverage import (
        PredictionRangeCoverageOut,
    )

    out = _call_route(monkeypatch=monkeypatch)
    validated = PredictionRangeCoverageOut.model_validate(out)
    assert validated.project_id == 7
    assert validated.verdict == "WELL_CALIBRATED"
