"""Route-level tests for ``GET /users/me/prediction-range-coverage``."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

pytest.importorskip("scipy", reason="Route registration requires scipy")

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


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

    def filter(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def order_by(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def all(self) -> list[Any]:
        return self.items


class _FakeSession:
    def __init__(
        self,
        *,
        owned_project_ids: list[int] | None = None,
        outcomes: list[_FakeOutcome] | None = None,
    ) -> None:
        self.owned_project_ids = owned_project_ids or []
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
            return _FakeQuery()
        return _FakeQuery()


def _outcomes() -> list[_FakeOutcome]:
    actuals = [0.09, 0.11, 0.09, 0.11, 0.09, 0.11]
    rows: list[_FakeOutcome] = []
    for index in range(6):
        created = f"2026-01-{index + 1:02d}T00:00:00+00:00"
        rows.append(
            _FakeOutcome(
                outcome_id=index * 2 + 1,
                project_id=7,
                simulation_id=index * 2 + 1,
                predicted=0.10,
                actual=actuals[index],
                created_at=created,
            )
        )
        rows.append(
            _FakeOutcome(
                outcome_id=index * 2 + 2,
                project_id=9,
                simulation_id=index * 2 + 2,
                predicted=0.10,
                actual=actuals[index],
                created_at=created,
            )
        )
    return rows


def _call_route(
    *,
    current_user_id: int = 42,
    session: _FakeSession | None = None,
) -> Any:
    from app.api.v1 import users as users_mod

    return users_mod.get_my_prediction_range_coverage(
        db=session or _FakeSession(
            owned_project_ids=[7, 9],
            outcomes=_outcomes(),
        ),
        current_user=type("U", (), {"id": current_user_id})(),
    )


def test_route_returns_portfolio_coverage_payload() -> None:
    out = _call_route()

    assert out.user_id == 42
    assert out.project_count == 2
    assert out.total_outcomes == 12
    assert out.evaluated_runs == 9
    assert out.within_range_count == 9
    assert out.coverage_rate == pytest.approx(1.0)
    assert out.verdict == "WELL_CALIBRATED"
    assert len(out.projects) == 2
    assert len(out.rows) == 12
    assert any(signal.label == "coverage_rate" for signal in out.key_signals)


def test_route_handles_empty_outcomes() -> None:
    out = _call_route(session=_FakeSession(owned_project_ids=[7]))

    assert out.user_id == 42
    assert out.project_count == 0
    assert out.total_outcomes == 0
    assert out.evaluated_runs == 0
    assert out.verdict == "INSUFFICIENT_DATA"
    assert out.rows == []


def test_route_scopes_query_to_owned_projects() -> None:
    out = _call_route(
        session=_FakeSession(
            owned_project_ids=[7],
            outcomes=[outcome for outcome in _outcomes() if outcome.project_id == 7],
        )
    )

    assert out.project_count == 1
    assert out.total_outcomes == 6
    assert out.evaluated_runs == 3
    assert out.projects[0].project_id == 7


def test_route_is_registered_on_users_router() -> None:
    from app.api.v1 import users as users_mod

    paths = {route.path for route in users_mod.router.routes}
    assert "/users/me/prediction-range-coverage" in paths
