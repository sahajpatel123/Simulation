"""Route-level tests for outcome-history pagination and date filters.

Covers the new ``limit`` / ``offset`` / ``has_more`` / ``filtered_total``
fields on ``GET /projects/{id}/outcomes`` plus the optional
``start_date`` / ``end_date`` filters without needing PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest


def _outcome(outcome_id: int, created_at: datetime) -> SimpleNamespace:
    """Build a minimal Outcome-like row with every field the route reads."""
    return SimpleNamespace(
        id=outcome_id,
        project_id=1,
        actual_conversion_rate=0.05,
        actual_mrr=100.0,
        actual_cac=25.0,
        actual_churn_rate=0.03,
        days_since_launch=30,
        actual_dau=None,
        actual_nps=None,
        notes=None,
        predicted_conversion_rate=0.07,
        predicted_mrr=120.0,
        simulation_id=None,
        variance_conversion=-0.02,
        variance_mrr=-20.0,
        variance_cac=0.0,
        variance_churn=0.0,
        calibration_score=75.0,
        created_at=created_at,
    )


class _ProjectQuery:
    """Chainable fake for ``db.query(Project)`` used by ownership check."""

    def filter(self, *args, **kwargs):  # noqa: ARG002
        return self

    def first(self) -> SimpleNamespace:
        return SimpleNamespace(id=1, user_id=42)


class _OutcomeQuery:
    """Chainable fake for ``db.query(Outcome)`` that applies offset/limit."""

    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = list(rows)
        self._offset = 0
        self._limit: int | None = None
        self.filter_count = 0

    def filter(self, *args, **kwargs):  # noqa: ARG002
        self.filter_count += 1
        return self

    def order_by(self, *args, **kwargs):  # noqa: ARG002
        return self

    def count(self) -> int:
        return len(self.rows)

    def with_entities(self, *args, **kwargs):  # noqa: ARG002
        return _AggregateQuery(self.rows)

    def offset(self, value: int) -> "_OutcomeQuery":
        clone = self._clone()
        clone._offset = value
        return clone

    def limit(self, value: int) -> "_OutcomeQuery":
        clone = self._clone()
        clone._limit = value
        return clone

    def all(self) -> list[SimpleNamespace]:
        start = self._offset or 0
        if self._limit is None:
            return self.rows[start:]
        return self.rows[start : start + self._limit]

    def _clone(self) -> "_OutcomeQuery":
        clone = _OutcomeQuery(self.rows)
        clone._offset = self._offset
        clone._limit = self._limit
        clone.filter_count = self.filter_count
        return clone


class _AggregateQuery:
    """Fake for the aggregate ``with_entities(...).one()`` call."""

    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows

    def one(self) -> tuple:
        scores = [
            float(o.calibration_score or 0.0)
            for o in self.rows
        ]
        if not scores:
            return None, None, None
        return sum(scores) / len(scores), max(scores), min(scores)


class _FakeSession:
    def __init__(self, outcome_rows: list[SimpleNamespace]) -> None:
        self.outcome_query = _OutcomeQuery(outcome_rows)

    def query(self, model, *args, **kwargs):  # noqa: ARG002
        if model.__name__ == "Project":
            return _ProjectQuery()
        if model.__name__ == "Outcome":
            return self.outcome_query
        raise AssertionError(f"Unexpected model {model!r}")


def _call_route(
    outcome_rows: list[SimpleNamespace],
    *,
    limit: int | None = None,
    offset: int = 0,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> tuple:
    """Invoke the route function directly with the fake session."""
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import outcomes as out_mod

    db = _FakeSession(outcome_rows)
    result = out_mod.get_outcome_history(
        project_id=1,
        limit=limit,
        offset=offset,
        start_date=start_date,
        end_date=end_date,
        db=db,
        current_user=SimpleNamespace(id=42),
    )
    return result, db.outcome_query


def _rows(count: int) -> list[SimpleNamespace]:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        _outcome(i + 1, base.replace(hour=23 - i))
        for i in range(count)
    ]


def _rows_with_scores(scores: list[float]) -> list[SimpleNamespace]:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        _outcome(i + 1, base.replace(hour=23 - i))
        for i in range(len(scores))
    ]
    for row, score in zip(rows, scores):
        row.calibration_score = score
    return rows


def test_pagination_returns_page_and_has_more() -> None:
    result, _ = _call_route(_rows(5), limit=2)

    assert result.total == 5
    assert result.filtered_total == 5
    assert result.limit == 2
    assert result.offset == 0
    assert result.has_more is True
    assert [r.id for r in result.outcomes] == [1, 2]


def test_pagination_respects_offset() -> None:
    result, _ = _call_route(_rows(5), limit=2, offset=2)

    assert result.total == 5
    assert result.filtered_total == 5
    assert result.has_more is True
    assert [r.id for r in result.outcomes] == [3, 4]


def test_no_limit_returns_all_without_has_more() -> None:
    result, _ = _call_route(_rows(3))

    assert result.total == 3
    assert result.filtered_total == 3
    assert result.limit is None
    assert result.has_more is False
    assert len(result.outcomes) == 3


def test_empty_history_returns_empty_payload() -> None:
    result, _ = _call_route([])

    assert result.total == 0
    assert result.filtered_total == 0
    assert result.has_more is False
    assert result.calibration_trend == "INSUFFICIENT_DATA"


def test_aggregates_cover_full_filtered_set_not_just_page() -> None:
    result, _ = _call_route(_rows_with_scores([60.0, 70.0, 80.0, 90.0]), limit=2)

    # Only the first two rows are returned on the page…
    assert [r.id for r in result.outcomes] == [1, 2]
    # …but the headline calibration numbers come from all four rows.
    assert result.average_calibration_score == 75.0
    assert result.best_calibration_score == 90.0
    assert result.worst_calibration_score == 60.0
    assert result.calibration_trend == "DEGRADING"


def test_date_filters_are_wired() -> None:
    _, query = _call_route(
        _rows(3),
        start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    # project_id filter + start_date + end_date = 3 filter calls.
    assert query.filter_count == 3


def test_naive_datetimes_are_normalized_to_utc() -> None:
    from app.api.v1.outcomes import _as_utc

    assert _as_utc(datetime(2026, 1, 1)) == datetime(
        2026, 1, 1, tzinfo=timezone.utc
    )
    assert _as_utc(None) is None
    aware = datetime(2026, 1, 1, 5, 30, tzinfo=timezone.utc)
    assert _as_utc(aware) == aware
    offset = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
    ist = datetime(2026, 1, 1, 11, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert _as_utc(ist) == offset


def test_pagination_fields_default_in_schema() -> None:
    from app.schemas.outcome import OutcomeHistoryOut

    out = OutcomeHistoryOut(
        project_id=1,
        outcomes=[],
        total=0,
        average_calibration_score=0.0,
        best_calibration_score=0.0,
        worst_calibration_score=0.0,
        calibration_trend="INSUFFICIENT_DATA",
    )

    assert out.filtered_total == 0
    assert out.limit is None
    assert out.offset == 0
    assert out.has_more is False
